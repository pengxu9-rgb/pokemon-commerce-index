"""Verify frozen thousand-scale metadata bindings and exact inherited history."""
import argparse,hashlib,json,shutil,tempfile,unicodedata
from pathlib import Path
from collections import Counter
from contextlib import closing
from urllib.parse import quote
from pokemon_index import core,catalog_locale,catalog_locale_indexes,variant_dimension_hold,collector_runtime
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_scale as compiler
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import coverage,facts
from scripts.audit_pokemon_name_eight_followup import snapshot_guard_checks,installed_bundle
from scripts.build_international_coverage_expansion import translated_query,ALIAS_FIELDS,RIGHTS
from scripts.build_pokemon_name_coverage import spaced_digest
DIRECTORY='catalog/international-pokemon-scale-v1'
PRIOR='catalog-build-manifest-international-pokemon-eight-followup-v1.json'
MANIFEST='catalog-build-manifest-international-pokemon-scale-v1.json'
signature=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def schema(db):
    return tuple(tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name'))


def require_indexes(db):
    installed={row for row in schema(db) if row[1] in catalog_locale_indexes.SQL}
    expected={('index',name,table,catalog_locale_indexes.SQL[name]) for name,table in catalog_locale_indexes.SPECIFICATIONS}
    if installed!=expected:raise ValueError('both exact bulk lookup indexes are required')


def preserved(before,after,pairs,bindings):
    if history.tables(before)!=history.tables(after):raise ValueError('historical table inventory differs')
    require_indexes(after)
    if catalog_locale_indexes.without_optional_indexes(schema(after))!=schema(before):
        raise ValueError('only the two exact additive lookup indexes may change the schema')
    holds=variant_dimension_hold.rows_for(before)
    if len(holds)!=44:raise ValueError('exact44 identity holds required')
    snapshot_guard_checks(before,holds);snapshot_guard_checks(after,holds)
    changes={'bilingual_concept_revision':pairs,'concept_review_event':pairs,'catalog_locale_evidence':bindings,'catalog_source_mapping':bindings}
    checks={}
    for table in history.tables(before):
        old,new=history.records(before,table),history.records(after,table)
        checks[table]=(new[:len(old)]==old and len(new)==len(old)+changes[table]) if table in changes else old==new
    if not all(checks.values()):raise ValueError('historical rows or columns changed')
    return checks

def approved_bundle_checks(bundle, packet, proposals, inspected_at, semantic_reviewed_at):
    count = len(proposals)
    """Independently bind each imported event to the exact approved source pair."""
    core.parse_time(inspected_at)
    if core.parse_time(semantic_reviewed_at) > core.parse_time(inspected_at):
        raise ValueError('compiler inspection predates actual independent semantic approval')
    events = bundle['review_events']; concepts = bundle['concept_revisions']
    if (len(events) != count or len(concepts) != count
            or len({e['event_id'] for e in events}) != count
            or len({c['concept_id'] for c in concepts}) != count):
        raise ValueError('exact unique bulk event/concept inventory differs')
    by_pair = {(p['name_ja'],p['name_en'],p['dex_id']):p for p in proposals}
    expected_concepts = {}
    for event in events:
        proposal, review = event['proposal'], event['review']
        key = (proposal['name_ja'],proposal['name_en'],proposal['dex_id'])
        if key not in by_pair or type(proposal['dex_id']) is not int:
            raise ValueError('event pair or singleton Dex lacks exact semantic approval')
        pair = by_pair[key]; sources = {}; witnesses = {}
        for language in ('ja','en'):
            witness = pair[language]; source = witness['source']
            sources[language] = 'https://github.com/tcgdex/cards-database/blob/' + source['revision'] + '/' + quote(source['native_id'],safe='/')
            witnesses[language] = dict(identity=witness['identity'],dex_id=pair['dex_id'],category='Pokemon',
                native_id=source['native_id'],revision=source['revision'],git_blob=source['git_blob'],sha256=source['sha256'],
                license_sha256=packet['license_sha256'],rights_reference=RIGHTS,rights_status='metadata_internal_reviewed',
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                physical_distribution_region=None,release_snapshot=witness['release_snapshot'])
        frozen = dict(category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],dex_id=pair['dex_id'],
            source_ja=sources['ja'],source_en=sources['en'],rights_reference=RIGHTS,
            ja_card_id=pair['ja']['identity']['card_id'],en_card_id=pair['en']['identity']['card_id'],retrieval_only=True)
        frozen['proposal_id'] = 'pokemon-name-proposal:' + catalog_locale.digest(frozen)
        snapshot = dict(frozen=frozen,ja_provenance=pair['ja']['identity']['provenance'],en_provenance=pair['en']['identity']['provenance'],
            witnesses=witnesses,scope='exact independently reviewed full-name metadata translation; no printing counterpart',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        expected = {**frozen,'ja_provenance':snapshot['ja_provenance'],'en_provenance':snapshot['en_provenance'],
                    'source_snapshot':snapshot,'source_snapshot_sha256':spaced_digest(snapshot)}
        if proposal != expected:
            raise ValueError('review proposal/source witness differs from the frozen approved pair')
        expected_review = dict(decision='approve',review_revision=1,reviewer='ai-independent:gpt-6.1-sol-high',reviewed_at=inspected_at,
            ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True,
            semantic_review_sha256=compiler.REVIEW_SHA,semantic_reviewed_at=semantic_reviewed_at,
            semantic_review_time_status='recorded_in_independent_approval_packet',
            identity_attestation_scope='existing pinned metadata tuples only; no physical-copy verification',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        if any(review.get(k) != v or isinstance(v,bool) and review.get(k) is not v for k,v in expected_review.items()):
            raise ValueError('review semantic approval, reviewer or no-trading scope differs')
        if event.get('schema') != 'pokemon.concept_review.v1' or event['event_id'] != spaced_digest({k:v for k,v in event.items() if k!='event_id'}):
            raise ValueError('review event hash/schema differs')
        cid = 'pokemon-name:' + catalog_locale.digest(dict(ja=pair['name_ja'],en=pair['name_en'],dex_id=pair['dex_id']))
        expected_concepts[cid] = dict(concept_id=cid,revision=1,category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],
            source_ja=sources['ja'],source_en=sources['en'],rights_reference=RIGHTS,reviewer=expected_review['reviewer'],
            reviewed_at=inspected_at,status='approved',review_event_id=event['event_id'])
    if len(expected_concepts) != count or {c['concept_id']:c for c in concepts} != expected_concepts:
        raise ValueError('concept-to-approved-event identity differs')
    return expected_concepts



def inputs(root):
    prior=json.loads((root/PRIOR).read_text());manifest=json.loads((root/MANIFEST).read_text());original=json.loads((root/'catalog-build-manifest-source-binding-v1.json').read_text())
    raw=(root/DIRECTORY/'basis-qualification.json').read_bytes();review_raw=(root/DIRECTORY/'semantic-review.json').read_bytes()
    packet,proposals,existing,new,english=compiler.checked_packet(raw,review_raw);counts=packet['selection_counts'];n=counts['total'];p=len(proposals)
    operations=[('import-concept-review-bundle',DIRECTORY+'/concept-review-bundle.json'),('import-catalog-locales',DIRECTORY+'/locales.jsonl'),('import-catalog-locale-lookup-indexes',DIRECTORY+'/lookup-indexes.jsonl')]
    expected={**prior['expected'],'bilingual_alias_revisions':318+p,'concept_review_events':656+p}
    if len(prior['steps'])!=83 or len(manifest['steps'])!=86 or prior['steps'][:65]!=original['steps'] or manifest['steps'][:83]!=prior['steps'] or manifest['expected']!=expected or [(x['operation'],x['path']) for x in manifest['steps'][83:]]!=operations:
        raise ValueError('ordered83/original65 prefix, exact three append operations or expected counts differ')
    for step in manifest['steps']:
        path=(root/step['path']).resolve()
        if not path.is_relative_to(root.resolve()) or signature(path)!=step['sha256']:raise ValueError('manifest path/hash differs')
    index_rows=[json.loads(x) for x in (root/DIRECTORY/'lookup-indexes.jsonl').read_text().splitlines()]
    if index_rows!=[catalog_locale_indexes.RECORD]:raise ValueError('exact lookup index input differs')
    bundle=json.loads((root/DIRECTORY/'concept-review-bundle.json').read_text());rows=[json.loads(x) for x in (root/DIRECTORY/'locales.jsonl').read_text().splitlines()]
    witnesses=existing+new+english;by_id={w['identity']['card_id']:w for w in witnesses}
    if len(rows)!=n or len(by_id)!=n or sorted(by_id)!=packet['selected_card_ids'] or {r['identity']['card_id'] for r in rows}!=set(by_id) or len({r['evidence_id'] for r in rows})!=n:
        raise ValueError('exact frozen identity/evidence inventory differs')
    times={r['source']['inspected_at'] for r in rows}
    if len(times)!=1 or signature(root/DIRECTORY/'TCGDEX-LICENSE')!=packet['license_sha256']:raise ValueError('inspection/licence differs')
    inspected_at=next(iter(times));review=json.loads(review_raw);concepts=approved_bundle_checks(bundle,packet,proposals,inspected_at,review['review_completed_at'])
    for row in rows:
        cid=row['identity']['card_id'];w=by_id[cid];card=w['identity'];src=w['source'];lang=card['language']
        expected_source=dict(provider='tcgdex',language=lang,region='ZZ',release_id='tcgdex-product:'+card['set_code'],native_id=src['native_id'],source_variant=card['variant'],revision=packet['source_pin'],git_blob=src['git_blob'],sha256=src['sha256'],license_git_blob=packet['source_inventory']['LICENSE']['git_blob'],license_sha256=packet['license_sha256'],retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,physical_distribution_region=None,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed')
        alias=w.get('name_alias') or next(({k:c[k] for k in ALIAS_FIELDS} for c in concepts.values() if c['name_'+lang]==card['name']),None)
        if row['identity']!=card or row['source']!=expected_source or row['release_snapshot']!=w['release_snapshot'] or row['name_aliases']!=[alias] or row.get('character_scope')!=dict(dex_id=w['dex_id'],full_name=card['name'],category='Pokemon',form_inheritance_allowed=False):
            raise ValueError('exact source/licence/release/name/concept/singletonDex binding differs')
        if row.get('unresolved_conflicts')!=[] or row.get('test_only') is not False or any(row.get(k) is not False for k in catalog_locale.FALSE_CLAIMS) or row['evidence_id']!='catalog-locale:'+catalog_locale.digest({k:v for k,v in row.items() if k!='evidence_id'}):raise ValueError('hash or metadata/trading scope differs')
    return manifest,packet,bundle,rows


def append(before_path,output,root):
    if output.exists():raise FileExistsError('incremental scale snapshot already exists')
    manifest,packet,bundle,rows=inputs(root);before_sha=signature(before_path)
    if before_sha!=compiler.BEFORE_SHA:raise ValueError('exact frozen prior snapshot required')
    pairs=len(bundle['concept_revisions']);n=len(rows);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        temporary=Path(directory)/'scale.sqlite3';shutil.copyfile(before_path,temporary)
        with closing(core.connect(temporary)) as db:
            catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD])
            concepts=core.import_concept_review_bundle(db,bundle);locales=catalog_locale.import_evidence(db,rows)
            if concepts!=dict(review_events=pairs,concept_revisions=pairs) or locales!=dict(inserted=n,unchanged=0,quarantined=0):raise ValueError('scale append must contain distinct exact reviews and bindings')
            installed_bundle(db,bundle);history.installed(db,rows)
        with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(temporary,readonly=True)) as after:preserved(before,after,pairs,n)
        if inputs(root)!=(manifest,packet,bundle,rows) or signature(before_path)!=before_sha:raise ValueError('publication inputs drifted')
        with output.open('xb') as handle:handle.write(temporary.read_bytes())
    return dict(concepts=concepts,locales=locales)


def search_ids(db,query,code,language=None):
    first=core.catalog_search_internal(db,query,set_code=code,language=language,limit=100)
    found={c['card_id'] for c in first['cards']}
    for offset in range(100,first['total'],100):
        found.update(c['card_id'] for c in core.catalog_search_internal(db,query,set_code=code,language=language,limit=100,offset=offset)['cards'])
    return found


@collector_runtime.catalog_request
def batch_search_ids(db,requests):
    return [search_ids(db,q,code,language) for q,code,language in requests]


def run(before_path,after_path,rebuilt_path,root):
    if signature(before_path)!=compiler.BEFORE_SHA:raise ValueError('exact frozen prior snapshot required')
    manifest,packet,bundle,rows=inputs(root);n=len(rows);p=len(bundle['concept_revisions']);paths=(before_path,after_path,rebuilt_path);hashes={str(path):signature(path) for path in paths}
    with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(after_path,readonly=True)) as after,closing(core.connect(rebuilt_path,readonly=True)) as rebuilt:
        history_checks=preserved(before,after,p,n)
        if schema(after)!=schema(rebuilt):raise ValueError('independent rebuilt SQL schema differs')
        snapshot_guard_checks(rebuilt,variant_dimension_hold.rows_for(before));installed_bundle(after,bundle);installed_bundle(rebuilt,bundle);history.installed(after,rows);history.installed(rebuilt,rows)
        rebuild={};timestamps={}
        for table in history.tables(after):
            left,right=history.records(after,table),history.records(rebuilt,table)
            if table in history.GENERATED_COLUMNS:
                cols=[r[1] for r in after.execute('PRAGMA table_info('+table+')')];index=cols.index(history.GENERATED_COLUMNS[table]);timestamps[table]=dict(column=cols[index],changed=sum(a[index]!=b[index] for a,b in zip(left,right)));left=[x[:index]+x[index+1:] for x in left];right=[x[:index]+x[index+1:] for x in right]
            rebuild[table]=left==right
        if not all(rebuild.values()):raise ValueError('independent logical rebuild differs')
        # Cache paginated full-name/language/set queries across complete groups;
        # each printing also receives an exact numbered structured resolution.
        query_cache={};queries=[];by_set={}
        for row in rows:
            card=row['identity'];alias=row['name_aliases'][0];name=alias['name_en' if card['language']=='ja' else 'name_ja'];q=f"{name} {card['language']} {card['set_code']}";key=(card['language'],card['set_code'],q)
            if key not in query_cache:
                query_cache[key]={};by_set.setdefault(card['set_code'],[]).append(key)
        for code,keys in by_set.items():
            requests=[(q,code,None) for lang,code,q in keys];old=batch_search_ids(before,requests)
            expanded=[]
            for language,code,q in keys:
                wide=''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in q)
                expanded.extend([(q,code,None),(unicodedata.normalize('NFD',wide),code,None),(q,code,'en' if language=='ja' else 'ja')])
            fresh=batch_search_ids(after,expanded)
            for index,key in enumerate(keys):query_cache[key]=dict(before=old[index],after=fresh[index*3],unicode=fresh[index*3+1],wrong_language=fresh[index*3+2])
        for row in rows:
            card=row['identity'];alias=row['name_aliases'][0];exact=translated_query(card,alias);name=alias['name_en' if card['language']=='ja' else 'name_ja'];q=f"{name} {card['language']} {card['set_code']}";key=(card['language'],card['set_code'],q)
            results=query_cache[key];cid=card['card_id']
            if cid in results['before'] or cid not in results['after'] or cid not in results['unicode'] or cid in results['wrong_language']:raise ValueError('translated/Unicode/language retrieval boundary differs: '+cid)
            answer=resolver.resolve_question(after,facts(row,alias['name_en' if card['language']=='ja' else 'name_ja']))
            if answer['resolution']['status'] not in {'unique','multiple_candidates'} or cid not in answer['resolution']['candidate_ids']:raise ValueError('structured translated target lost: '+cid)
            for candidate in answer['resolution']['candidate_ids']:
                found=after.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE card_id=?',(candidate,)).fetchone()
                if not found or any(found[k]!=card[k] for k in ('language','set_code','collector_number')) or found['category']!='Pokemon' or resolver.full_name_key(found['name'])!=resolver.full_name_key(card['name']) or not catalog_locale.has_current_alias(after,candidate,answer['name_aliases']):raise ValueError('resolver crossed source/name/language/coordinate binding')
            queries.append(dict(card_id=cid,query=q,exact_numbered_structured_query=exact,translated_before_found=False,translated_after_found=True,unicode_after_found=True,wrong_language_excludes=True,resolver_status=answer['resolution']['status'],candidate_ids=answer['resolution']['candidate_ids']))
        report=dict(schema='pokemon.pokemon-scale-audit.v1',before=coverage(before),after=coverage(after),new_name_concepts=p,new_localized_bindings=n,language_counts=dict(Counter(r['identity']['language'] for r in rows)),by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),localized_bindings_by_language={r[0]:r[1] for r in after.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language')},current_approved_pokemon_names=after.execute("WITH latest AS(SELECT *,row_number() OVER(PARTITION BY concept_id ORDER BY revision DESC)rn FROM bilingual_concept_revision)SELECT count(*) FROM latest WHERE rn=1 AND status='approved' AND category='Pokemon'").fetchone()[0],manifest_inputs_before=83,manifest_inputs_after=86,original65_ordered_prefix_preserved=True,prior83_ordered_prefix_preserved=True,manifest_sha256=signature(root/MANIFEST),database_sha256=hashes,historical_tables_preserved=history_checks,rebuild_tables_equal=rebuild,rebuild_generated_timestamp_differences=timestamps,sql_schema_change='exact two nonunique lookup indexes only; legacy schema and allholddefinitions unchanged',exact44_hold_guards_flags_contexts_verified=True,integrity_foreign_keys_verified=True,queries=queries,distinct_translated_queries=len(query_cache),translated_query_scope='paginated full-name/language/set queries with per-printing target checks;separate exact numbered structured resolution for every target',translated_target_checks=n,resolver_status_counts=dict(Counter(r['resolver_status'] for r in queries)),new_card_identities=0,new_relationships=0,new_images=0,new_market_rows=0,new_permissions=0)
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'repeat.sqlite3';shutil.copyfile(after_path,path)
        with closing(core.connect(path)) as db:
            old={t:history.records(db,t) for t in history.tables(db)};concepts=core.import_concept_review_bundle(db,bundle);locales=catalog_locale.import_evidence(db,rows)
            if concepts!=dict(review_events=0,concept_revisions=0) or locales!=dict(inserted=0,unchanged=n,quarantined=0) or any(history.records(db,t)!=value for t,value in old.items()):raise ValueError('reimport changed history')
            report['idempotent_reimport']=dict(concepts=concepts,locales=locales,all_tables_unchanged=True)
        path2=Path(directory)/'concepts-only.sqlite3';shutil.copyfile(before_path,path2)
        with closing(core.connect(path2)) as db:
            catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD]);core.import_concept_review_bundle(db,bundle)
            for row in rows:
                alias=row['name_aliases'][0];result=resolver.resolve_question(db,facts(row,alias['name_en' if row['identity']['language']=='ja' else 'name_ja']))
                if result['resolution']['status']!='not_attempted' or result['reason']!='reviewed_name_record_binding_required':raise ValueError('review alone expanded an unbound printing')
            report['concepts_without_record_bindings_abstain']=n
    if inputs(root)!=(manifest,packet,bundle,rows) or any(signature(path)!=hashes[str(path)] for path in paths):raise ValueError('audited input bytes drifted')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();report=run(args.before,args.after,args.rebuilt,Path.cwd())
    with args.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_name_concepts','new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__=='__main__':main()
