"""Disposable87-input rebuild and full3000 native/materialized/loaded proof.

No source acquisition or live service calls. Independent reviewed hashes must
be populated before qualifying a snapshot; historical86 gates stay unchanged.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from scripts import audit_pokemon_name_next3000 as audit
from scripts.rehearse_international_scale_release import logical_snapshot_digest

MANIFEST = audit.MANIFEST
PRIOR = audit.PRIOR
MANIFEST_SHA = '31d1484b579b2d760cc6a2f55dddbeb9cf392c6dfca0cdac3c4878b672dfe7f1'
REVISION = '624eff46195c8c832d517928ae4747adf7ca2d84783803d690105180bcdef8c5'
LOGICAL_SNAPSHOT_SHA = 'd09a072183e6cd31297ee84758839caaff2835459918723762500b1673114d5d'
NATIVE_SEMANTIC_SHA = 'dea1dbe5caf7f3e10ce45b735b20b4bcae1b591b71afa25f2433d9ed3ebeb349'


def pins():
    import re
    audit.require(all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v)
                      for v in (MANIFEST_SHA,REVISION,LOGICAL_SNAPSHOT_SHA,NATIVE_SEMANTIC_SHA)),
                  'independently reviewed next3000 manifest/runtime/logical/semantic pins required')


def fingerprints(root):
    from pokemon_index import collector_journey
    value=audit.input_hashes(root)
    value.update({'pokemon_index/'+n:h for n,h in collector_journey.runtime_source_hashes().items()})
    return value


def verify_snapshot(db,root):
    from pokemon_index import core,collector_journey,collector_runtime,catalog_read_model_artifact
    pins();root=Path(root).resolve();seal=fingerprints(root)
    audit.require(audit.signature(root/MANIFEST)==MANIFEST_SHA,'reviewed87-input manifest differs')
    manifest,packet,rows=audit.inputs(root)
    path=Path(next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'))
    audit.require(path.is_file() and not db.in_transaction,'committed file snapshot required')
    database_sha=audit.signature(path);db.execute('PRAGMA query_only=ON')
    profile=audit.installed(db,packet,rows)
    digest=logical_snapshot_digest(db)
    audit.require(digest==LOGICAL_SNAPSHOT_SHA,'full51 logical snapshot differs from reviewed rebuild')
    revision=collector_journey.catalog_revision(db)
    audit.require(revision==REVISION,'canonical reviewed runtime/data revision differs')
    native=audit.queries(db,rows)
    audit.require(native['targets']==3000 and native['semantic_sha256']==NATIVE_SEMANTIC_SHA,
                  'fresh full3000 native semantic proof differs')
    with closing(core.connect(path,readonly=True)) as model_db:
        model=collector_runtime.CatalogReadModel(model_db)
    with closing(core.connect(path,readonly=True)) as accelerated_db,model.request(accelerated_db):
        accelerated=audit.queries(accelerated_db,rows)
        audit.require(accelerated_db.execute('PRAGMA query_only').fetchone()[0]==1,'materialized main snapshot not query-only')
    audit.require(native==accelerated,'native and materialized full3000 responses differ')
    native_state=catalog_read_model_artifact.model_state(model)
    with tempfile.TemporaryDirectory(prefix='next3000-native-read-model-') as directory:
        artifact_dir=Path(directory)/'read-model'
        with closing(core.connect(path,readonly=True)) as build_db:
            artifact=catalog_read_model_artifact.write(build_db,root/MANIFEST,artifact_dir)
        with closing(core.connect(path,readonly=True)) as load_db:
            loaded,loaded_revision,loaded_receipt=catalog_read_model_artifact.load(
                load_db,artifact_dir,root/MANIFEST,expected_seal_sha256=artifact['seal_sha256'])
        audit.require(loaded_revision==revision and catalog_read_model_artifact.model_state(loaded)==native_state,
                      'entire packaged native model state or revision differs')
        with closing(core.connect(path,readonly=True)) as packaged_db,loaded.request(packaged_db):
            packaged=audit.queries(packaged_db,rows)
            audit.require(packaged_db.execute('PRAGMA query_only').fetchone()[0]==1,'loaded main snapshot not query-only')
        audit.require(packaged==native,'native and loaded full3000 query responses differ')
    audit.require(seal==fingerprints(root) and audit.signature(path)==database_sha
                  and logical_snapshot_digest(db)==digest,'source/input/database drift during native qualification')
    return dict(profile=profile,catalog_revision=revision,manifest_sha256=MANIFEST_SHA,
        database_sha256=database_sha,logical_snapshot_sha256=digest,native_queries=native,
        materialized_queries=accelerated,packaged_native_queries=packaged,
        native_accelerated_equal=True,packaged_native_queries_equal=True,
        packaged_native_state_equal=True,packaged_artifact=artifact,loaded_artifact=loaded_receipt,
        immutable_readonly_snapshot=True,exact_frozen_artifact_bindings=True,
        runtime_source_sha256=collector_journey.runtime_source_hashes(),source_fingerprints=seal)


def rehearse(root):
    from pokemon_index import core
    from scripts.build_catalog_snapshot import build
    pins();root=Path(root).resolve();seal=fingerprints(root);start=time.monotonic()
    audit.require(audit.signature(root/MANIFEST)==MANIFEST_SHA,'reviewed87-input manifest differs')
    manifest,packet,rows=audit.inputs(root)
    with tempfile.TemporaryDirectory(prefix='next3000-release-gate-') as directory:
        directory=Path(directory);before=directory/'prior86.sqlite3'
        incremental=directory/'incremental87.sqlite3';rebuilt=directory/'rebuilt87.sqlite3'
        print('Building fresh pinned86-input prior',flush=True);prior_report=build(root/PRIOR,before)
        before_sha=audit.signature(before);shutil.copyfile(before,incremental)
        with closing(core.connect(incremental)) as db:
            from pokemon_index import catalog_locale
            locales=catalog_locale.import_evidence(db,rows)
            audit.require(locales==dict(inserted=3000,unchanged=0,quarantined=0),'exact3000 single append differs')
        print('Building independent pinned87-input snapshot',flush=True);rebuilt_report=build(root/MANIFEST,rebuilt)
        with closing(core.connect(before,readonly=True)) as old,closing(core.connect(incremental,readonly=True)) as appended,closing(core.connect(rebuilt,readonly=True)) as fresh:
            preservation=audit.preserved(old,appended)
            rebuild_checks,stamps=audit.rebuild_equal(appended,fresh)
            audit.installed(appended,packet,rows);audit.installed(fresh,packet,rows)
            gaps=audit.queries(appended,rows,old)
            abstentions=audit.abstentions(old,rows)
            print('Verifying all3000 installed bindings through native/materialized/loaded runtime',flush=True)
            verified=verify_snapshot(fresh,root)
        repeat=directory/'repeat.sqlite3';shutil.copyfile(rebuilt,repeat)
        with closing(core.connect(repeat)) as db:
            old_rows={t:audit.history.records(db,t) for t in audit.history.tables(db)}
            repeated=catalog_locale.import_evidence(db,rows)
            audit.require(repeated==dict(inserted=0,unchanged=3000,quarantined=0)
                          and all(audit.history.records(db,t)==r for t,r in old_rows.items()),
                          'idempotent reimport changed inherited state')
        audit.require(seal==fingerprints(root) and audit.signature(before)==before_sha,'source/prior inputs changed')
        return dict(schema='pokemon.international-next3000-release-gate.v1',
            fresh_prior_steps=prior_report['steps'],independent_rebuild_steps=rebuilt_report['steps'],
            original65_and_prior86_preserved=True,historical_all51_tables_preserved=preservation,
            independent_full51_logical_rebuild_equal=True,full51_rebuild_tables_equal=rebuild_checks,
            normalized_generated_columns=audit.GENERATED,rebuild_generated_timestamp_differences=stamps,
            fresh_prior_byte_sha256=before_sha,fresh_prior_is_not_frozen_operator_baseline=True,
            translation_gap_queries=gaps,concepts_only_abstentions=abstentions,
            idempotent_reimport=repeated,idempotent_all51_tables_unchanged=True,
            elapsed_seconds=time.monotonic()-start,new_identities=0,new_concepts=0,new_images=0,
            new_prices=0,new_permissions=0,source_acquisition=False,external_requests=False,
            live_ingestion=False,**verified)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--db',type=Path)
    args=parser.parse_args();audit.require(not args.output.exists(),'release report already exists')
    if args.db:
        from pokemon_index import core
        with closing(core.connect(args.db,readonly=True)) as db:
            report=dict(schema='pokemon.international-next3000-snapshot-verification.v1',**verify_snapshot(db,args.root))
    else:report=rehearse(args.root)
    with args.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
