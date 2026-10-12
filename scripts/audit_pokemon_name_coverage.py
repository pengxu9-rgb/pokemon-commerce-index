"""Verify the offline thousand-record name expansion against immutable snapshots."""
import argparse
import hashlib
import json
import shutil
import tempfile
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path

from pokemon_index import catalog_locale, catalog_question_resolver_v2 as resolver, core
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import coverage, facts
from scripts.build_international_coverage_expansion import translated_query
from scripts.build_pokemon_name_coverage import SETS, JAPANESE_LIMIT, ENGLISH_COUNT

DIRECTORY = 'catalog/international-pokemon-thousand-v1'
PRIOR = 'catalog-build-manifest-international-coverage-hundred-v1.json'
MANIFEST = 'catalog-build-manifest-international-pokemon-thousand-v1.json'
ADDITIONS = dict(bilingual_concept_revision=163, concept_review_event=163,
                 catalog_locale_evidence=1025, catalog_source_mapping=1025)


def signature(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(root):
    original = json.loads((root/'catalog-build-manifest-source-binding-v1.json').read_text())
    prior = json.loads((root/PRIOR).read_text())
    manifest = json.loads((root/MANIFEST).read_text())
    expected = {**prior['expected'], 'bilingual_alias_revisions': 285, 'concept_review_events': 623}
    operations = [('import-concept-review-bundle', DIRECTORY+'/concept-review-bundle.json'),
                  ('import-catalog-locales', DIRECTORY+'/locales.jsonl')]
    if (len(original['steps']) != 65 or len(prior['steps']) != 70 or len(manifest['steps']) != 72
            or original['steps'] != prior['steps'][:65] or manifest['steps'][:70] != prior['steps']
            or manifest['expected'] != expected
            or [(s['operation'], s['path']) for s in manifest['steps'][70:]] != operations):
        raise ValueError('ordered manifest prefix, append scope or expected inventory differs')
    for step in manifest['steps']:
        path = (root/step['path']).resolve()
        if not path.is_relative_to(root.resolve()) or signature(path) != step['sha256']:
            raise ValueError('manifest input hash/path differs')
    rows = [json.loads(line) for line in (root/DIRECTORY/'locales.jsonl').read_text().splitlines()]
    bundle = json.loads((root/DIRECTORY/'concept-review-bundle.json').read_text())
    if (len(bundle['review_events']) != 163 or len(bundle['concept_revisions']) != 163
            or any(c['category'] != 'Pokemon' for c in bundle['concept_revisions'])
            or any(e['review'].get('requires_card_binding') is not True for e in bundle['review_events'])):
        raise ValueError('exact source-bound Pokemon name review scope differs')
    bounded(rows)
    return manifest, bundle, rows


def bounded(rows):
    if (Counter(r['identity']['language'] for r in rows) != {'ja': JAPANESE_LIMIT, 'en': ENGLISH_COUNT}
            or len({r['identity']['card_id'] for r in rows}) != 1025
            or {r['identity']['set_code'] for r in rows if r['identity']['language'] == 'ja'} != set(SETS)):
        raise ValueError('exact thousand-record language/set/ID scope differs')
    for row in rows:
        scope = row.get('character_scope', {})
        if (scope.get('category') != 'Pokemon' or scope.get('full_name') != row['identity']['name']
                or type(scope.get('dex_id')) is not int or not 1 <= scope['dex_id'] <= 151
                or scope.get('form_inheritance_allowed') is not False):
            raise ValueError('literal character name scope differs')


def preserved(before, after):
    if history.tables(before) != history.tables(after):
        raise ValueError('schema inventory differs')
    checks = {}
    for table in history.tables(before):
        old, new = history.records(before, table), history.records(after, table)
        checks[table] = (new[:len(old)] == old and len(new) == len(old)+ADDITIONS[table]
                         if table in ADDITIONS else old == new)
    if not all(checks.values()):
        raise ValueError('historical rows/columns changed: '+','.join(t for t,v in checks.items() if not v))
    return checks


def installed_bundle(db, bundle):
    fields = ('concept_id','revision','category','name_ja','name_en','source_ja','source_en',
              'rights_reference','reviewer','reviewed_at','status','review_event_id')
    for concept in bundle['concept_revisions']:
        found = db.execute('SELECT * FROM bilingual_concept_revision WHERE concept_id=? AND revision=?',
                           (concept['concept_id'], concept['revision'])).fetchone()
        if not found or tuple(found[k] for k in fields) != tuple(concept[k] for k in fields):
            raise ValueError('installed name concept differs')
    for event in bundle['review_events']:
        proposal, review = event['proposal'], event['review']
        expected = (event['event_id'], proposal['proposal_id'], review['review_revision'],
                    proposal['source_snapshot_sha256'], review['decision'], review['reviewer'],
                    review['reviewed_at'], json.dumps(event, ensure_ascii=False, sort_keys=True))
        found = db.execute('SELECT * FROM concept_review_event WHERE event_id=?', (event['event_id'],)).fetchone()
        if not found or tuple(found) != expected:
            raise ValueError('installed name review evidence differs')


def append(before_path, output, root):
    if output.exists():
        raise FileExistsError('incremental snapshot already exists')
    manifest, bundle, rows = inputs(root)
    before_sha = signature(before_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        scratch = Path(directory)/'append.sqlite3'
        shutil.copyfile(before_path, scratch)
        with closing(core.connect(scratch)) as db:
            concepts = core.import_concept_review_bundle(db, bundle)
            locales = catalog_locale.import_evidence(db, rows)
            if concepts != dict(review_events=163, concept_revisions=163) or locales != dict(inserted=1025,unchanged=0,quarantined=0):
                raise ValueError('batch must append distinct name reviews and current bindings')
            installed_bundle(db, bundle); history.installed(db, rows)
        with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(scratch, readonly=True)) as after:
            preserved(before, after)
        if inputs(root) != (manifest, bundle, rows) or signature(before_path) != before_sha:
            raise ValueError('input or prior snapshot drift during append')
        with output.open('xb') as handle:
            handle.write(scratch.read_bytes())
    return dict(concepts=concepts, locales=locales)


def run(before_path, after_path, rebuilt_path, root):
    manifest, bundle, rows = inputs(root)
    paths = (before_path, after_path, rebuilt_path)
    signatures = {str(path): signature(path) for path in paths}
    with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(after_path, readonly=True)) as after, closing(core.connect(rebuilt_path, readonly=True)) as rebuilt:
        preservation = preserved(before, after)
        for db in (after, rebuilt):
            history.installed(db, rows); installed_bundle(db, bundle)
        if history.tables(after) != history.tables(rebuilt):
            raise ValueError('rebuild schema differs')
        rebuilt_checks = {}; timestamps = {}
        for table in history.tables(after):
            left, right = history.records(after, table), history.records(rebuilt, table)
            if table in history.GENERATED_COLUMNS:
                column = history.GENERATED_COLUMNS[table]
                index = [r[1] for r in after.execute('PRAGMA table_info('+table+')')].index(column)
                timestamps[table] = dict(column=column, changed=sum(a[index] != b[index] for a,b in zip(left,right)))
                left = [r[:index]+r[index+1:] for r in left]; right = [r[:index]+r[index+1:] for r in right]
            rebuilt_checks[table] = left == right
        if not all(rebuilt_checks.values()):
            raise ValueError('independent rebuild differs outside four named generated timestamp columns')
        before_counts, after_counts = coverage(before), coverage(after)
        if {k:v for k,v in before_counts.items() if k!='localized_bindings'} != {k:v for k,v in after_counts.items() if k!='localized_bindings'}:
            raise ValueError('coverage changed outside source-bound localization')
        queries = []; search_cache = {}
        for row in rows:
            card, alias = row['identity'], row['name_aliases'][0]
            query = translated_query(card, alias)
            def search(db,q,**kw):
                # Several separate variants share an identical query. Read-only
                # snapshots are hash checked at both ends; each target ID still
                # gets an individual assertion against the actual search result.
                key=(id(db),card['set_code'],q,kw.get('language'))
                if key not in search_cache:
                    search_cache[key]=core.catalog_search_internal(db,q,set_code=card['set_code'],limit=100,**kw)
                return search_cache[key]
            target = lambda result: card['card_id'] in {c['card_id'] for c in result['cards']}
            wide = ''.join(chr(ord(c)+0xfee0) if 0x21<=ord(c)<=0x7e else c for c in query)
            checks = dict(before_missing=not target(search(before,query)), after_found=target(search(after,query)),
                native_found=target(search(after,f"{card['name']} {card['language']} {card['set_code']} {card['collector_number']}")),
                unicode_found=target(search(after,unicodedata.normalize('NFD',wide))),
                wrong_language_excludes_target=not target(search(after,query,language='en' if card['language']=='ja' else 'ja')))
            if not all(checks.values()):
                raise ValueError('retrieval regression: '+card['card_id']+' '+str(checks))
            name = alias['name_en' if card['language']=='ja' else 'name_ja']
            old = resolver.resolve_question(before,facts(row,name))
            new = resolver.resolve_question(after,facts(row,name))
            # The resolver may retain multiple variants or abstain when an unbound
            # stamped sibling is in scope. No artificial unique SKU is required.
            for candidate in new['resolution']['candidate_ids']:
                found = after.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE card_id=?',(candidate,)).fetchone()
                if (not found or found['language']!=card['language'] or found['set_code']!=card['set_code']
                        or found['collector_number']!=card['collector_number'] or found['category']!='Pokemon'
                        or resolver.full_name_key(found['name'])!=resolver.full_name_key(card['name'])
                        or not catalog_locale.has_current_alias(after,candidate,new['name_aliases'])):
                    raise ValueError('resolver crossed an identity/name/binding boundary')
            if new['resolution']['status'] not in {'unique','multiple_candidates','not_attempted'}:
                raise ValueError('unexpected translated resolver miss')
            if new['resolution']['status']=='not_attempted' and new['reason']!='reviewed_name_record_binding_required':
                raise ValueError('unexpected translated resolver hold: '+new['reason'])
            queries.append(dict(card_id=card['card_id'],language=card['language'],query=query,**checks,
                resolver_before=old['resolution'],resolver_after=new['resolution'],resolver_reason=new['reason']))
        unfiltered = []
        for row in rows[::max(1,len(rows)//10)][:10]:
            query = translated_query(row['identity'],row['name_aliases'][0]); cid = row['identity']['card_id']
            if cid not in {c['card_id'] for c in core.catalog_search_internal(after,query,limit=100)['cards']}:
                raise ValueError('unfiltered search lost target')
            unfiltered.append(dict(card_id=cid,query=query,after_found=True))
        report = dict(schema='pokemon.pokemon-name-coverage-audit.v1',before=before_counts,after=after_counts,
            manifest_inputs_before=70,manifest_inputs_after=72,original_manifest_inputs=65,preserved_ordered_prefix=True,
            manifest_sha256=signature(root/MANIFEST),database_sha256=signatures,
            new_name_concepts=163,new_localized_bindings=1025,translated_gaps_closed=len(queries),
            batch_by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
            localized_bindings_by_language={r[0]:r[1] for r in after.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language')},
            historical_tables_preserved=preservation,rebuild_tables_equal=rebuilt_checks,
            rebuild_generated_timestamp_differences=timestamps,
            rebuild_timestamp_scope='Only legacy generated asserted_at/applied_at on four named tables excluded from rebuild comparison. Incremental snapshot preserves every prior column.',
            exact_installed_evidence_and_mapping_bindings=True,queries=queries,unfiltered_queries=unfiltered,
            resolver_status_counts=dict(Counter(q['resolver_after']['status'] for q in queries)),
            resolver_hold_reasons=dict(Counter(q['resolver_reason'] for q in queries if q['resolver_after']['status']=='not_attempted')),
            source_mappings_after=after.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],
            held_candidates_after=after.execute('SELECT count(*) FROM catalog_coverage_candidate').fetchone()[0],
            quarantine_after=after.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            scope='existing-record discovery; no new card identities, counterparts, artwork, prices, physical or commerce approvals')
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)/'reimport.sqlite3'; shutil.copyfile(after_path,scratch)
        with closing(core.connect(scratch)) as db:
            old = {table:history.records(db,table) for table in history.tables(db)}
            concepts = core.import_concept_review_bundle(db,bundle); locales = catalog_locale.import_evidence(db,rows)
            if (concepts!=dict(review_events=0,concept_revisions=0) or locales!=dict(inserted=0,unchanged=1025,quarantined=0)
                    or any(history.records(db,t)!=values for t,values in old.items())):
                raise ValueError('idempotent reimport changed records')
            report['idempotent_reimport'] = dict(concepts=concepts,locales=locales,all_tables_unchanged=True)
        # Reviews alone cannot expand record eligibility across the whole catalogue.
        scratch2 = Path(directory)/'concepts-only.sqlite3'; shutil.copyfile(before_path,scratch2)
        with closing(core.connect(scratch2)) as db:
            core.import_concept_review_bundle(db,bundle)
            binding_holds = 0
            for row in rows:
                card, alias = row['identity'],row['name_aliases'][0]
                name = alias['name_en' if card['language']=='ja' else 'name_ja']
                result = resolver.resolve_question(db,facts(row,name))
                if result['resolution']['status']!='not_attempted' or result['reason']!='reviewed_name_record_binding_required':
                    raise ValueError('name review expanded an unbound record')
                binding_holds += 1
            report['concepts_without_record_bindings_abstain'] = binding_holds
    if inputs(root)!=(manifest,bundle,rows) or any(signature(path)!=signatures[str(path)] for path in paths):
        raise ValueError('audited input/snapshot drift')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a = p.parse_args(); report = run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as handle:
        handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_name_concepts','new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__ == '__main__':
    main()
