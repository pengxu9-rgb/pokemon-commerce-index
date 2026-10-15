"""Validate the exact reviewed scale snapshot through fresh disposable builds.

The immutable-before auditor stays unchanged. This gate compares a copied fresh
83-input build with an independent 86-input rebuild; it never acquires sources.
"""
import argparse, hashlib, json, shutil, tempfile, time, unicodedata
from contextlib import closing
from pathlib import Path

MANIFEST = 'catalog-build-manifest-international-pokemon-scale-v1.json'
PRIOR = 'catalog-build-manifest-international-pokemon-eight-followup-v1.json'
MANIFEST_SHA = '1541fa71a1e0cfaf8d4398fb0b10d188f09f14faaa246a8298f821dc20c5f3ac'
REVISION = 'df253f813fabd36b2fd2badcc8c88a74bc55322c7d965a8970b5d7a45eb4f423'
LOGICAL_SNAPSHOT_SHA = '989693744fbbb5a46aae03a76d3364ecc43437bcd44bb60143ee7c6ffdc1dacf'
DIRECTORY = 'catalog/international-pokemon-scale-v1'


def logical_snapshot_digest(db):
    """Portable full SQL/typed-row hash; only four named build times normalize.

    Self-contained standard-library code so an image checker can copy this
    function without importing build/audit code into the production runtime.
    """
    import hashlib, json, datetime
    generated = {'card_relationship_assertion':'asserted_at', 'card_identity_exception':'applied_at',
                 'card_rarity_correction':'applied_at', 'card_number_conflict_rule':'applied_at'}
    def encode(value):
        if value is None:return ['null']
        if isinstance(value,int):return ['integer',str(value)]
        if isinstance(value,float):return ['float',value.hex()]
        if isinstance(value,bytes):return ['blob',value.hex()]
        if isinstance(value,str):return ['text',value]
        raise ValueError('unsupported SQLite storage value')
    digest=hashlib.sha256()
    def append(value):
        digest.update(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode());digest.update(b'\n')
    append(['encoding',db.execute('PRAGMA main.encoding').fetchone()[0],
            'application_id',db.execute('PRAGMA main.application_id').fetchone()[0],
            'user_version',db.execute('PRAGMA main.user_version').fetchone()[0]])
    schema=[tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name,tbl_name')]
    append(['full_sql_schema',schema])
    for table in sorted(row[1] for row in schema if row[0]=='table'):
        quoted='"'+table.replace('"','""')+'"'
        columns=[tuple(row) for row in db.execute('PRAGMA main.table_info('+quoted+')')]
        append(['table',table,'all_columns',columns]);names=[row[1] for row in columns]
        index=names.index(generated[table]) if table in generated else None
        count=0
        for row in db.execute('SELECT * FROM main.'+quoted+' ORDER BY rowid'):
            values=[encode(value) for value in row]
            if index is not None:
                value=row[index]
                if not isinstance(value,str):raise ValueError('generated build time must be a timezone-bearing timestamp')
                parsed=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None:raise ValueError('generated build time lacks timezone')
                values[index]=['documented_generated_build_time']
            append(values);count+=1
        append(['row_count',count])
    return digest.hexdigest()


def _require(condition,message):
    if not condition:raise ValueError(message)


def _verify_reviewed_logical_snapshot(db):
    digest=logical_snapshot_digest(db)
    _require(digest==LOGICAL_SNAPSHOT_SHA,'full51 logical snapshot differs from independently reviewed release')
    return digest


def _inputs(root):
    from scripts import audit_pokemon_name_scale as audit
    _require(hashlib.sha256((root/MANIFEST).read_bytes()).hexdigest()==MANIFEST_SHA,'exact reviewed 86-input manifest required')
    result=audit.inputs(root)
    _require(result[1]['selection_counts']==dict(ja=2952,en=1000,total=3952,newpairs=400,existing_ja=244,new_ja=2708,existing_en=123,new_en=877),
             'exact reviewed scale profile differs')
    return result


def _input_hashes(root):
    manifest=json.loads((root/MANIFEST).read_text())
    paths={root/MANIFEST,root/PRIOR,root/'catalog-build-manifest-source-binding-v1.json'}
    paths|={root/step['path'] for step in manifest['steps']}
    paths|={root/DIRECTORY/name for name in ('basis-qualification.json','semantic-review.json','TCGDEX-LICENSE','selection.json')}
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def _verify_installed_rows(db,rows):
    from pokemon_index import catalog_locale
    from scripts.audit_international_coverage_expansion import installed
    for row in rows:
        src=row['source'];identity=row['identity']
        _require(src.get('provider')=='tcgdex' and src.get('language')==identity['language'] and src.get('region')=='ZZ'
            and src.get('release_id')=='tcgdex-product:'+identity['set_code'] and src.get('source_variant')==identity['variant'],
            'exact provider/language/region/release/variant namespace differs')
        _require(all(row.get(key) is False for key in catalog_locale.FALSE_CLAIMS),'metadata cannot grant display or trading permissions')
    installed(db,rows)


def _verify_holds(db,holds):
    from scripts.audit_pokemon_name_eight_followup import snapshot_guard_checks
    snapshot_guard_checks(db,holds)


def _profile(db):
    from pokemon_index import variant_dimension_hold
    from scripts import audit_pokemon_name_scale as audit
    from scripts import audit_international_coverage_expansion as history
    audit.require_indexes(db)
    holds=variant_dimension_hold.rows_for(db);_require(len(holds)==44,'exact44 installed identity holds required');_verify_holds(db,holds)
    _require(len(history.tables(db))==51,'full51-table snapshot required')
    count=lambda sql:db.execute(sql).fetchone()[0]
    actual=dict(source_records=count('SELECT count(*) FROM card'),bindings=count('SELECT count(*) FROM catalog_locale_evidence'),
        mappings=count('SELECT count(*) FROM catalog_source_mapping'),concept_revisions=count('SELECT count(*) FROM bilingual_concept_revision'),
        review_events=count('SELECT count(*) FROM concept_review_event'),quarantines=count('SELECT count(*) FROM catalog_identity_quarantine'),
        coverage_holds=count('SELECT count(*) FROM catalog_coverage_candidate'),display=count('SELECT count(*) FROM card WHERE display_allowed=1'),
        approved_pokemon_names=count("WITH latest AS(SELECT *,row_number() OVER(PARTITION BY concept_id ORDER BY revision DESC) rn FROM bilingual_concept_revision) SELECT count(*) FROM latest WHERE rn=1 AND status='approved' AND category='Pokemon'"))
    expected=dict(source_records=70006,bindings=6364,mappings=6364,concept_revisions=718,review_events=1056,
                  quarantines=109,coverage_holds=65,display=0,approved_pokemon_names=596)
    _require(actual==expected,'exact scale cardinalities/rights/holds differ: '+str(actual))
    languages={row[0]:row[1] for row in db.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language')}
    _require(languages=={'ja':5031,'en':1333},'exact6364 language binding profile differs')
    market={table:count('SELECT count(*) FROM '+table) for table in ('priceable_unit','listing','observation','landed_quote','verified_sale')}
    _require(not any(market.values()),'scale snapshot contains market or payment state')
    return dict(**actual,bindings_by_language=languages,market_tables=market,identity_holds=44,exact_lookup_indexes=True,
                exact_hold_guards=True,full51_table_schema=True,integrity_foreign_keys=True)


def _queries(db,rows,*,before=None):
    from pokemon_index import core,catalog_locale,catalog_question_resolver_v2 as resolver,collector_runtime
    from scripts.audit_international_coverage import facts
    from scripts.audit_pokemon_name_scale import batch_search_ids
    requests={};by_set={}
    for row in rows:
        c=row['identity'];alias=row['name_aliases'][0];name=alias['name_en' if c['language']=='ja' else 'name_ja']
        key=(c['language'],c['set_code'],f"{name} {c['language']} {c['set_code']}")
        if key not in requests:requests[key]=None;by_set.setdefault(c['set_code'],[]).append(key)
    for code,keys in by_set.items():
        expanded=[]
        for language,_,q in keys:
            wide=''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in q)
            expanded.extend([(q,code,None),(unicodedata.normalize('NFD',wide),code,None),(q,code,'en' if language=='ja' else 'ja')])
        fresh=batch_search_ids(db,expanded)
        old=batch_search_ids(before,[(q,code,None) for language,_,q in keys]) if before is not None else [set()]*len(keys)
        for i,key in enumerate(keys):requests[key]=(fresh[3*i],fresh[3*i+1],fresh[3*i+2],old[i])
    digest=hashlib.sha256();statuses={}
    @collector_runtime.catalog_request
    def structured_batch(connection,batch):
        for row in batch:
            c=row['identity'];alias=row['name_aliases'][0];name=alias['name_en' if c['language']=='ja' else 'name_ja'];q=f"{name} {c['language']} {c['set_code']}"
            found,unicode_ids,wrong,old=requests[(c['language'],c['set_code'],q)];cid=c['card_id']
            _require(cid in found and cid in unicode_ids and cid not in wrong and (before is None or cid not in old),
                     'translated/Unicode/opposite-language boundary differs: '+cid)
            answer=resolver.resolve_question(connection,facts(row,name));resolution=answer['resolution']
            _require(resolution['status'] in ('unique','multiple_candidates') and cid in resolution['candidate_ids'],'exact structured target lost: '+cid)
            for candidate in resolution['candidate_ids']:
                card=connection.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE card_id=?',(candidate,)).fetchone()
                _require(card and all(card[k]==c[k] for k in ('language','set_code','collector_number')) and card['category']=='Pokemon'
                    and resolver.full_name_key(card['name'])==resolver.full_name_key(c['name'])
                    and catalog_locale.has_current_alias(connection,candidate,answer['name_aliases']),
                    'structured resolver crossed native name/source/language/coordinate binding')
            statuses[resolution['status']]=statuses.get(resolution['status'],0)+1
            digest.update(catalog_locale.encoded(dict(card_id=cid,found=sorted(found),unicode=sorted(unicode_ids),wrong_language=sorted(wrong),answer=answer)).encode());digest.update(b'\n')
    by_code={}
    for row in rows:by_code.setdefault((row['identity']['language'],row['identity']['set_code']),[]).append(row)
    for batch in by_code.values():structured_batch(db,batch)
    return dict(targets=len(rows),distinct_queries=len(requests),status_counts=statuses,semantic_sha256=digest.hexdigest(),
                unicode_and_opposite_language_checks=True,exact_numbered_structured_checks=True)


def verify_snapshot(db,root):
    """Read-only installed-evidence/profile/native API verification, no acquisition.

    The caller supplies the frozen checkout separately from the runtime image.
    """
    from pokemon_index import core,collector_runtime,collector_journey,catalog_read_model_artifact
    from scripts.audit_pokemon_name_eight_followup import installed_bundle
    root=Path(root).resolve();initial=_input_hashes(root);manifest,packet,bundle,rows=_inputs(root)
    policy_before=collector_journey.runtime_source_hashes()
    main=next(row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main')
    _require(main and not db.in_transaction,'committed file snapshot required')
    path=Path(main).resolve();before_sha=hashlib.sha256(path.read_bytes()).hexdigest();db.execute('PRAGMA query_only=ON')
    _verify_installed_rows(db,rows);installed_bundle(db,bundle);profile=_profile(db)
    logical_sha=_verify_reviewed_logical_snapshot(db)
    revision=collector_journey.catalog_revision(db);_require(revision==REVISION,'canonical reviewed runtime/snapshot revision differs')
    native=_queries(db,rows)
    _require(collector_journey.runtime_source_hashes()==policy_before,'runtime policy changed during native proof')
    with closing(core.connect(path,readonly=True)) as model_db:model=collector_runtime.CatalogReadModel(model_db)
    with closing(core.connect(path,readonly=True)) as accelerated_db,model.request(accelerated_db):
        accelerated=_queries(accelerated_db,rows)
        _require(accelerated_db.execute('PRAGMA query_only').fetchone()[0]==1,'accelerated main snapshot is not query-only')
    _require(native==accelerated,'native and accelerated full scale responses differ')
    _require(collector_journey.runtime_source_hashes()==policy_before,'runtime policy changed during accelerated proof')
    with tempfile.TemporaryDirectory(prefix='scale-native-read-model-') as directory:
        artifact_dir=Path(directory)/'read-model'
        with closing(core.connect(path,readonly=True)) as build_db:
            artifact=catalog_read_model_artifact.write(build_db,root/MANIFEST,artifact_dir)
        with closing(core.connect(path,readonly=True)) as load_db:
            loaded,loaded_revision,_loaded_evidence=catalog_read_model_artifact.load(
                load_db,artifact_dir,root/MANIFEST,expected_seal_sha256=artifact['seal_sha256'])
        _require(loaded_revision==revision and catalog_read_model_artifact.model_state(model)==
                 catalog_read_model_artifact.model_state(loaded),'full packaged facts or native revision differ')
        with closing(core.connect(path,readonly=True)) as packaged_db,loaded.request(packaged_db):
            packaged_queries=_queries(packaged_db,rows)
        _require(packaged_queries==native,'native and packaged full scale responses differ')
    _require(collector_journey.runtime_source_hashes()==policy_before,'runtime policy changed during packaged proof')
    _require(initial==_input_hashes(root) and hashlib.sha256(path.read_bytes()).hexdigest()==before_sha,'snapshot/verification artifact bytes changed')
    _require(logical_sha==_verify_reviewed_logical_snapshot(db),'full51 logical snapshot changed during verification')
    return dict(profile=profile,catalog_revision=revision,logical_snapshot_sha256=logical_sha,
        database_sha256=before_sha,manifest_sha256=MANIFEST_SHA,native_queries=native,native_accelerated_equal=True,
        immutable_readonly_snapshot=True,exact_frozen_artifact_bindings=True,
        packaged_native_state_equal=True,packaged_native_queries=packaged_queries,
        packaged_artifact=artifact)


def rehearse(root):
    from pokemon_index import core,catalog_locale,catalog_locale_indexes,catalog_question_resolver_v2 as resolver
    from scripts.build_catalog_snapshot import build
    from scripts import audit_pokemon_name_scale as audit
    from scripts import audit_international_coverage_expansion as history
    from scripts.audit_international_coverage import facts
    root=Path(root).resolve();initial=_input_hashes(root);manifest,packet,bundle,rows=_inputs(root)
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='scale-release-gate-') as directory:
        directory=Path(directory);before=directory/'prior83.sqlite3';incremental=directory/'incremental86.sqlite3';rebuilt=directory/'rebuilt86.sqlite3'
        print('Building fresh pinned83-input prior',flush=True);prior_report=build(root/PRIOR,before)
        shutil.copyfile(before,incremental)
        with closing(core.connect(incremental)) as db:
            catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD])
            concepts=core.import_concept_review_bundle(db,bundle);locales=catalog_locale.import_evidence(db,rows)
            _require(concepts==dict(review_events=400,concept_revisions=400) and locales==dict(inserted=3952,unchanged=0,quarantined=0),'exact copied83 append differs')
        print('Building independent pinned86-input snapshot',flush=True);rebuilt_report=build(root/MANIFEST,rebuilt)
        with closing(core.connect(before,readonly=True)) as old,closing(core.connect(incremental,readonly=True)) as new,closing(core.connect(rebuilt,readonly=True)) as fresh:
            preservation=audit.preserved(old,new,400,3952)
            digest=logical_snapshot_digest(new);_require(digest==logical_snapshot_digest(fresh),'full51 logical rows/schema differ after only documented build-time normalization')
            print('Verifying all3952 installed bindings and native/accelerated Unicode resolution',flush=True)
            verified=verify_snapshot(fresh,root)
            before_sha=hashlib.sha256(before.read_bytes()).hexdigest()
            print('Checking all3952 concepts-only abstentions',flush=True)
        concepts_only=directory/'concepts-only.sqlite3';shutil.copyfile(before,concepts_only)
        with closing(core.connect(concepts_only)) as db:
            catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD]);core.import_concept_review_bundle(db,bundle)
            for row in rows:
                alias=row['name_aliases'][0];name=alias['name_en' if row['identity']['language']=='ja' else 'name_ja']
                answer=resolver.resolve_question(db,facts(row,name))
                _require(answer['resolution']['status']=='not_attempted' and answer['reason']=='reviewed_name_record_binding_required','concept-only review expanded an unbound printing')
        _require(initial==_input_hashes(root) and hashlib.sha256(before.read_bytes()).hexdigest()==before_sha,'gate input/prior bytes drifted')
        return dict(schema='pokemon.international-scale-release-gate.v1',fresh_prior_steps=prior_report['steps'],independent_rebuild_steps=rebuilt_report['steps'],
            original65_and_prior83_preserved=True,fresh_prior_byte_sha256=before_sha,fresh_prior_is_not_frozen_operator_baseline=True,
            unchanged_strict_frozen_baseline_auditor=True,historical_all51_tables_preserved=preservation,independent_full51_logical_rebuild_equal=True,
            normalized_generated_columns=dict(history.GENERATED_COLUMNS),concepts_only_abstentions=3952,**verified,
            elapsed_seconds=time.monotonic()-start,next3000_plan_applied=False,source_acquisition=False,external_requests=False,
            live_ingestion=False,new_images=False,new_prices=False,new_display_or_purchase_permissions=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path.cwd());parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--db',type=Path,help='Verify an existing86 snapshot instead of constructing disposable83/86 builds')
    args=parser.parse_args();_require(not args.output.exists(),'release gate report already exists')
    if args.db:
        from pokemon_index import core
        with closing(core.connect(args.db,readonly=True)) as db:report=dict(schema='pokemon.international-scale-snapshot-verification.v1',**verify_snapshot(db,args.root))
    else:report=rehearse(args.root)
    with args.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('schema','catalog_revision','logical_snapshot_sha256','immutable_readonly_snapshot','native_accelerated_equal')}))


if __name__=='__main__':main()
