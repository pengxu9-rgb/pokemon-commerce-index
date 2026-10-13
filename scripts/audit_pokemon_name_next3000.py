"""Audit one exact English metadata append without changing inherited history."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import unicodedata

from pokemon_index import core, catalog_locale, collector_runtime, variant_dimension_hold
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts
from scripts.audit_pokemon_name_eight_followup import snapshot_guard_checks
from scripts.audit_pokemon_name_scale import require_indexes, batch_search_ids
from scripts.build_international_coverage_expansion import RIGHTS

DIRECTORY = 'catalog/international-pokemon-next3000-v1'
PRIOR = 'catalog-build-manifest-international-pokemon-scale-v1.json'
MANIFEST = 'catalog-build-manifest-international-pokemon-next3000-v1.json'
ORIGINAL = 'catalog-build-manifest-source-binding-v1.json'
GENERATED = {'card_identity_exception':'applied_at', 'card_number_conflict_rule':'applied_at',
             'card_rarity_correction':'applied_at', 'card_relationship_assertion':'asserted_at'}


def require(ok, message):
    if not ok: raise ValueError(message)


def signature(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def compiler():
    from scripts import build_pokemon_name_next3000
    return build_pokemon_name_next3000


def schema(db):
    return tuple(tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name'))


def manifest_checks(root, prior, manifest, original):
    require(len(original['steps']) == 65 and len(prior['steps']) == 86
            and prior['steps'][:65] == original['steps'], 'exact original65/prior86 prefix required')
    require(len(manifest['steps']) == 87 and manifest['steps'][:86] == prior['steps']
            and manifest['expected'] == prior['expected']
            and [(s['operation'],s['path']) for s in manifest['steps'][86:]] ==
            [('import-catalog-locales', DIRECTORY+'/locales.jsonl')],
            'single locale append and unchanged ordered86/65 prefix/expected counts required')
    require(manifest.get('schema') == prior.get('schema') == 'pokemon.catalog-build.v1', 'manifest schema differs')
    for step in manifest['steps']:
        relative = PurePosixPath(step['path']); path = root.joinpath(*relative.parts)
        require(not relative.is_absolute() and '..' not in relative.parts and path.is_file()
                and not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
                and signature(path) == step['sha256'], 'manifest path/hash differs')


def row_checks(packet, witnesses, rows, license_sha):
    by_id = {w['identity']['card_id']:w for w in witnesses}
    require(len(rows) == len(witnesses) == len(by_id) == 3000
            and sorted(by_id) == packet['selected_card_ids']
            and {r['identity']['card_id'] for r in rows} == set(by_id)
            and len({r['evidence_id'] for r in rows}) == 3000, 'exact distinct3000 record inventory differs')
    require(license_sha == packet['license_sha256'], 'original metadata license differs')
    times = {r['source']['inspected_at'] for r in rows}
    require(len(times) == 1, 'single actual inspection time required')
    core.parse_time(next(iter(times)))
    groups = set(); releases = set()
    for row in rows:
        card = row['identity']; w = by_id[card['card_id']]; src = w['source']
        require(card['language'] == 'en' and card == w['identity'], 'existing English printing tuple differs')
        alias = w.get('name_alias')
        require(isinstance(alias,dict) and row['name_aliases'] == [alias], 'exact retained current alias required')
        expected = dict(provider='tcgdex', language='en', region='ZZ',
            release_id='tcgdex-product:'+card['set_code'], native_id=src['native_id'],
            source_variant=card['variant'], revision=packet['source_pin'], git_blob=src['git_blob'],
            sha256=src['sha256'], license_git_blob=packet['source_inventory']['LICENSE']['git_blob'],
            license_sha256=packet['license_sha256'], retrieved_at=None,
            retrieval_status='historical_snapshot_time_not_recorded', inspected_at=next(iter(times)),
            physical_distribution_region=None, rights_reference=RIGHTS, rights_status='metadata_internal_reviewed')
        path = PurePosixPath(src['native_id'])
        require(not path.is_absolute() and '..' not in path.parts and path.parts[0] == 'data'
                and path.suffix == '.ts' and not any(p.casefold() in ('pocket','digital') for p in path.parts),
                'existing physical English source path required')
        require(row['source'] == expected and row['release_snapshot'] == w['release_snapshot']
                and row.get('character_scope') == dict(dex_id=w['dex_id'], full_name=card['name'],
                    category='Pokemon', form_inheritance_allowed=False), 'exact source/release/name/Dex scope differs')
        require(row.get('unresolved_conflicts') == [] and row.get('test_only') is False
                and all(row.get(k) is False for k in catalog_locale.FALSE_CLAIMS)
                and row['evidence_id'] == 'catalog-locale:'+catalog_locale.digest({k:v for k,v in row.items() if k!='evidence_id'}),
                'hash or metadata-only permissions differ')
        groups.add(tuple(card[k] for k in ('language','set_code','collector_number'))); releases.add(card['set_code'])
    require(len(groups) == 1503 and len(releases) == 48, 'exact complete-group/release cohort differs')
    return rows


def inputs(root):
    root = Path(root).resolve(); c = compiler()
    packet, witnesses = c.checked_packet((root/DIRECTORY/'basis-qualification.json').read_bytes(),
                                        (root/DIRECTORY/'record-binding-review.json').read_bytes())
    prior = json.loads((root/PRIOR).read_text()); manifest = json.loads((root/MANIFEST).read_text())
    manifest_checks(root,prior,manifest,json.loads((root/ORIGINAL).read_text()))
    rows = [json.loads(line) for line in (root/DIRECTORY/'locales.jsonl').read_text().splitlines()]
    row_checks(packet,witnesses,rows,signature(root/DIRECTORY/'TCGDEX-LICENSE'))
    review = json.loads((root/DIRECTORY/'record-binding-review.json').read_text())
    require(all(core.parse_time(row['source']['inspected_at']) >= core.parse_time(review['review_completed_at'])
                for row in rows), 'compiler inspection cannot predate independent record approval')
    require(all(type(row.get('confidence')) is float and row['confidence'] == 1.0
                and row.get('confidence_scope') == 'checked pinned source tuples and exact independently reviewed full-name translation only'
                for row in rows), 'confidence is limited to checked metadata tuples and exact translated names')
    return manifest,packet,rows


def input_hashes(root):
    root = Path(root).resolve(); manifest = json.loads((root/MANIFEST).read_text())
    paths = {root/MANIFEST,root/PRIOR,root/ORIGINAL}
    paths.update(root/s['path'] for s in manifest['steps'])
    paths.update(root/DIRECTORY/n for n in ('basis-qualification.json','record-binding-review.json','selection.json','TCGDEX-LICENSE'))
    paths.update(root/'scripts'/n for n in ('audit_pokemon_name_next3000.py','build_pokemon_name_next3000.py','rehearse_international_next3000_release.py'))
    active_compiler = compiler()
    code_root = Path(active_compiler.__file__).resolve().parents[1]
    paths.update(root/p.relative_to(code_root) for p in active_compiler.compiler_inputs())
    paths.update(root/'scripts'/n for n in ('audit_pokemon_name_scale.py','rehearse_international_scale_release.py'))
    return {str(p.relative_to(root)):signature(p) for p in sorted(paths)}


def preserved(before, after, n=3000):
    require(history.tables(before) == history.tables(after) and len(history.tables(after)) == 51,
            'exact inherited51 table inventory required')
    require(schema(before) == schema(after), 'entire SQL schema must remain unchanged')
    require_indexes(before); require_indexes(after)
    holds = variant_dimension_hold.rows_for(before)
    require(len(holds) == 44 and variant_dimension_hold.rows_for(after) == holds, 'exact44 inherited holds differ')
    snapshot_guard_checks(before,holds); snapshot_guard_checks(after,holds)
    checks = {}
    for table in history.tables(before):
        old,new = history.records(before,table),history.records(after,table)
        delta = n if table in ('catalog_locale_evidence','catalog_source_mapping') else 0
        checks[table] = new[:len(old)] == old and len(new) == len(old)+delta
    require(all(checks.values()), 'historical rows/columns changed or unexpected append')
    return checks


def rebuild_equal(left, right):
    require(schema(left) == schema(right) and history.tables(left) == history.tables(right), 'rebuilt full SQL schema differs')
    checks = {}; stamps = {}
    for table in history.tables(left):
        a,b = history.records(left,table),history.records(right,table)
        if table in GENERATED:
            names = [r[1] for r in left.execute('PRAGMA table_info('+table+')')]; i = names.index(GENERATED[table])
            for row in a+b:
                require(isinstance(row[i],str) and datetime.fromisoformat(row[i].replace('Z','+00:00')).tzinfo is not None,
                        'known generated time must carry timezone')
            stamps[table] = dict(column=GENERATED[table],changed=sum(x[i]!=y[i] for x,y in zip(a,b)))
            a = [r[:i]+r[i+1:] for r in a]; b = [r[:i]+r[i+1:] for r in b]
        checks[table] = a == b
    require(all(checks.values()), 'independent rebuild differs beyond four named generated times')
    return checks,stamps


def installed(db,packet,rows):
    history.installed(db,rows)
    compiler().current_concepts(db,packet)
    require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            and not db.execute('PRAGMA foreign_key_check').fetchall(), 'integrity or foreign keys differ')
    count = lambda t: db.execute('SELECT count(*) FROM '+t).fetchone()[0]
    require(count('card') == 70006 and count('catalog_locale_evidence') == count('catalog_source_mapping') == 9364
            and count('bilingual_concept_revision') == 718 and count('concept_review_event') == 1056
            and count('catalog_identity_quarantine') == 109 and count('catalog_coverage_candidate') == 65,
            'exact next3000 metadata profile differs')
    require(dict(db.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language')) ==
            dict(en=4333,ja=5031), 'exact9364 language coverage differs')
    require(not db.execute('SELECT count(*) FROM card WHERE display_allowed=1').fetchone()[0]
            and all(count(t) == 0 for t in ('priceable_unit','listing','observation','landed_quote','verified_sale')),
            'display/market state cannot expand')
    for row in rows:
        card = row['identity']; alias = row['name_aliases'][0]
        require(catalog_locale.snapshot(db,card['card_id']) == card, 'installed printing identity drift')
        catalog_locale.approved_alias(db,alias)
        require(not variant_dimension_hold.held(db,card['card_id'])
                and db.execute('SELECT match_eligible FROM card WHERE card_id=?',(card['card_id'],)).fetchone()[0] == 1,
                'held or ineligible identity admitted')
    return dict(bindings=9364,mappings=9364,current_approved_pokemon_names=596,new_name_concepts=0,
                language_counts=dict(en=4333,ja=5031),identity_holds=44,market_rows=0,display_permissions=0)


def queries(db,rows,before=None):
    requests = {}; by_set = {}
    for row in rows:
        card=row['identity']; name=row['name_aliases'][0]['name_ja']; q=f"{name} en {card['set_code']}"
        key=(card['set_code'],q)
        if key not in requests: requests[key]=None; by_set.setdefault(card['set_code'],[]).append(key)
    for code,keys in by_set.items():
        expanded=[]
        for _,q in keys:
            wide=''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in q)
            expanded.extend([(q,code,None),(unicodedata.normalize('NFD',wide),code,None),(q,code,'ja')])
        new=batch_search_ids(db,expanded)
        old=batch_search_ids(before,[(q,code,None) for _,q in keys]) if before is not None else [set()]*len(keys)
        for i,key in enumerate(keys): requests[key]=(new[3*i],new[3*i+1],new[3*i+2],old[i])
    digest=hashlib.sha256(); statuses=Counter()
    @collector_runtime.catalog_request
    def structured_batch(connection,batch):
        for row in batch:
            card=row['identity'];name=row['name_aliases'][0]['name_ja'];q=f"{name} en {card['set_code']}"
            found,unicode,wrong,old=requests[(card['set_code'],q)];cid=card['card_id']
            require(cid in found and cid in unicode and cid not in wrong and (before is None or cid not in old),
                    'translated/Unicode/gap/opposite-language target differs: '+cid)
            answer=resolver.resolve_question(connection,facts(row,name));resolution=answer['resolution']
            require(resolution['status'] in ('unique','multiple_candidates') and cid in resolution['candidate_ids'],
                    'exact numbered/variant structured target lost: '+cid)
            for candidate in resolution['candidate_ids']:
                actual=connection.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE card_id=?',(candidate,)).fetchone()
                require(actual and all(actual[k] == card[k] for k in ('language','set_code','collector_number'))
                        and actual['category']=='Pokemon' and resolver.full_name_key(actual['name'])==resolver.full_name_key(card['name'])
                        and catalog_locale.has_current_alias(connection,candidate,answer['name_aliases']),
                        'structured response crossed exact name/language/coordinate binding')
            statuses[resolution['status']]+=1
            digest.update(catalog_locale.encoded(dict(card_id=cid,found=sorted(found),unicode=sorted(unicode),
                          wrong_language=sorted(wrong),answer=answer)).encode());digest.update(b'\n')
    batches={}
    for row in rows:batches.setdefault(row['identity']['set_code'],[]).append(row)
    for batch in batches.values():structured_batch(db,batch)
    return dict(targets=len(rows),distinct_queries=len(requests),status_counts=dict(statuses),
                semantic_sha256=digest.hexdigest(),unicode_and_opposite_language_checks=True,
                exact_numbered_structured_checks=True,translation_gaps_verified=before is not None)


def abstentions(db,rows):
    @collector_runtime.catalog_request
    def batch(connection,items):
        for row in items:
            answer=resolver.resolve_question(connection,facts(row,row['name_aliases'][0]['name_ja']))
            require(answer['resolution']['status']=='not_attempted' and answer['reason']=='reviewed_name_record_binding_required',
                    'current concept without exact record binding must abstain')
    batches={}
    for row in rows:batches.setdefault(row['identity']['set_code'],[]).append(row)
    for items in batches.values():batch(db,items)
    return len(rows)


def append(before_path,output,root):
    before_path=Path(before_path);output=Path(output);root=Path(root)
    require(signature(before_path)==compiler().BEFORE_SHA,'exact frozen prior snapshot required')
    require(not output.exists(), 'incremental snapshot already exists')
    seal=input_hashes(root);manifest,packet,rows=inputs(root);before_sha=signature(before_path)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        scratch=Path(directory)/'append.sqlite3';shutil.copyfile(before_path,scratch)
        with closing(core.connect(scratch)) as db:
            locales=catalog_locale.import_evidence(db,rows)
            require(locales==dict(inserted=3000,unchanged=0,quarantined=0), 'only3000 distinct locale append permitted')
            installed(db,packet,rows)
        with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(scratch,readonly=True)) as after:
            preserved(before,after)
        require(seal==input_hashes(root) and signature(before_path)==before_sha,'append inputs or prior bytes drifted')
        with scratch.open('rb') as source,output.open('xb') as target:shutil.copyfileobj(source,target)
    return dict(locales=locales,new_concepts=0)


def run(before_path,after_path,rebuilt_path,root):
    require(signature(before_path)==compiler().BEFORE_SHA,'exact frozen prior snapshot required')
    seal=input_hashes(root);manifest,packet,rows=inputs(root)
    paths=(before_path,after_path,rebuilt_path);hashes={str(p):signature(p) for p in paths}
    with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(after_path,readonly=True)) as after,closing(core.connect(rebuilt_path,readonly=True)) as rebuilt:
        preservation=preserved(before,after);checks,stamps=rebuild_equal(after,rebuilt)
        profile=installed(after,packet,rows);installed(rebuilt,packet,rows)
        translated=queries(after,rows,before);missing=abstentions(before,rows)
    with tempfile.TemporaryDirectory() as directory:
        scratch=Path(directory)/'repeat.sqlite3';shutil.copyfile(after_path,scratch)
        with closing(core.connect(scratch)) as db:
            old={t:history.records(db,t) for t in history.tables(db)}
            repeated=catalog_locale.import_evidence(db,rows)
            require(repeated==dict(inserted=0,unchanged=3000,quarantined=0)
                    and all(history.records(db,t)==r for t,r in old.items()), 'idempotent reimport changed any table')
    require(seal==input_hashes(root) and all(signature(p)==hashes[str(p)] for p in paths), 'audited inputs changed')
    return dict(schema='pokemon.pokemon-next3000-audit.v1',profile=profile,
        manifest_inputs_before=86,manifest_inputs_after=87,original65_and_prior86_preserved=True,
        manifest_sha256=signature(Path(root)/MANIFEST),database_sha256=hashes,
        historical_all51_tables_preserved=preservation,full51_rebuild_tables_equal=checks,
        normalized_generated_columns=GENERATED,rebuild_generated_timestamp_differences=stamps,
        sql_schema_unchanged=True,exact44_hold_guards_verified=True,queries=translated,
        concepts_without_record_bindings_abstain=missing,idempotent_reimport=repeated,
        idempotent_all51_tables_unchanged=True,new_identities=0,new_concepts=0,new_permissions=0,
        new_images=0,new_market_rows=0,source_acquisition=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();report=run(args.before,args.after,args.rebuilt,Path.cwd())
    with args.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
