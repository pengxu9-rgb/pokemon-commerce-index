"""Verify the offline held batch preserves catalogue and trading boundaries."""
import argparse
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from pokemon_index import core, catalog_locale, coverage_qualification as qualification
from scripts.audit_international_coverage import coverage


def table_rows(db, table):
    return [dict(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]


def verify_installed(db, rows, original_quarantine):
    expected = dict(coverage_candidate_events=len(rows), coverage_candidate_subjects=len({r['identity']['card_id'] for r in rows}),
                    coverage_current_held=len(rows), coverage_stale_candidates=0, coverage_admitted_identities=0)
    if qualification.status(db) != expected:
        raise ValueError('audited after snapshot does not contain the complete current held batch')
    installed = {r['candidate_id']: (r['card_id'], r['record_json']) for r in table_rows(db, 'catalog_coverage_candidate')}
    wanted = {r['candidate_id']: (r['identity']['card_id'], catalog_locale.encoded(r)) for r in rows}
    if installed != wanted:
        raise ValueError('audited after candidate payloads differ from hash-bound queue')
    quarantine = table_rows(db, 'catalog_identity_quarantine')
    wanted_quarantine = original_quarantine + [dict(quarantine_id='catalog-quarantine:' + catalog_locale.digest(r),
        reason='; '.join(r['hold_reasons']), record_json=catalog_locale.encoded(r)) for r in rows]
    if quarantine != wanted_quarantine:
        raise ValueError('audited after quarantine payloads/history differ from held batch')


def run(before_path, after_path, root):
    pilot = json.loads((root/'catalog-build-manifest-international-pilot-v1.json').read_text())
    manifest = json.loads((root/'catalog-build-manifest-international-qualification-v1.json').read_text())
    baseline = json.loads((root/'catalog-build-manifest-source-binding-v1.json').read_text())
    assert len(baseline['steps']) == 65 and len(pilot['steps']) == 66 and len(manifest['steps']) == 67
    assert manifest['steps'][:65] == baseline['steps'] and manifest['steps'][:66] == pilot['steps']
    for step in manifest['steps']:
        assert hashlib.sha256((root/step['path']).read_bytes()).hexdigest() == step['sha256']
    rows = [json.loads(line) for line in (root/manifest['steps'][-1]['path']).read_text().splitlines()]
    assert len(rows) == 65 and len({r['identity']['card_id'] for r in rows}) == 65
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (before_path, after_path)}
    with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(after_path, readonly=True)) as after:
        tables = [r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        unchanged = {}
        generated_columns = {'card_relationship_assertion': 'asserted_at', 'card_identity_exception': 'applied_at',
                             'card_rarity_correction': 'applied_at', 'card_number_conflict_rule': 'applied_at'}
        timestamp_deltas = {}
        for table in tables:
            if table in {'catalog_coverage_candidate', 'catalog_identity_quarantine'}:
                continue
            old, new = table_rows(before, table), table_rows(after, table)
            if table in generated_columns:
                column = generated_columns[table]
                timestamp_deltas[table] = dict(column=column, changed=sum(a[column] != b[column] for a, b in zip(old, new)))
                old = [{k:v for k,v in r.items() if k != column} for r in old]
                new = [{k:v for k,v in r.items() if k != column} for r in new]
            unchanged[table] = old == new
        assert all(unchanged.values()), 'legacy table changed'
        assert all(qualification.current(after, row) for row in rows)
        verify_installed(after, rows, table_rows(before, 'catalog_identity_quarantine'))
        searches = []
        for row in rows:
            c = row['identity']; query = f"{c['name']} {c['set_code']} {c['collector_number']}"
            old = core.catalog_search_internal(before, query, language=c['language'], limit=100)
            new = core.catalog_search_internal(after, query, language=c['language'], limit=100)
            old_ids = [r['card_id'] for r in old['cards']]; new_ids = [r['card_id'] for r in new['cards']]
            wrong = core.catalog_search_internal(after, query, language='en', limit=100)
            assert old_ids == new_ids and c['card_id'] in new_ids and wrong['total'] == 0
            searches.append(dict(card_id=c['card_id'], retrieval_preserved=True, wrong_language_excluded=True))
        report = dict(schema='pokemon.coverage-qualification-audit.v1',
            manifest_inputs_before=66, manifest_inputs_after=67, preserved_65_source_inputs=True,
            preserved_stage1_input=True, verified_input_hashes=67, before=coverage(before), after=coverage(after),
            before_qualification=qualification.status(before), after_qualification=qualification.status(after),
            by_scope=dict(Counter(r['identity']['set_code'] for r in rows)),
            hold_reasons=dict(Counter(reason for r in rows for reason in r['hold_reasons'])),
            cached_exact_card_pages=sum(r['cached_official_page'] is not None for r in rows),
            unchanged_legacy_tables=unchanged,
            generated_rebuild_timestamp_differences=timestamp_deltas,
            timestamp_scope='Only existing generated asserted_at/applied_at columns on four named tables excluded across independent rebuilds; incremental append checks every historical column below',
            quarantine_records_before=before.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            quarantine_records_after=after.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            searches=searches, new_identities=0, release_metadata_admitted=0,
            scope='Held evidence qualification; no retrieval, release, physical-card, display or commerce approval gains')
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == sha for path, sha in hashes.items())
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)/'append.sqlite3'; shutil.copyfile(before_path, scratch)
        with closing(core.connect(scratch)) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            original = {table: table_rows(db, table) for table in tables}
            core.init_db(db)
            first = qualification.import_candidates(db, rows)
            assert first == dict(inserted=65, unchanged=0, rejected=0)
            report['incremental_append_unchanged_legacy_tables'] = all(
                table_rows(db, t) == records for t, records in original.items()
                if t not in {'catalog_coverage_candidate', 'catalog_identity_quarantine'})
            assert report['incremental_append_unchanged_legacy_tables']
            quarantine = table_rows(db, 'catalog_identity_quarantine')
            assert quarantine[:len(original['catalog_identity_quarantine'])] == original['catalog_identity_quarantine']
            assert len(quarantine) == len(original['catalog_identity_quarantine']) + 65
            report['quarantine_history_preserved'] = True
            report['idempotent_reimport'] = qualification.import_candidates(db, rows)
            assert report['idempotent_reimport'] == dict(inserted=0, unchanged=65, rejected=0)
            assert quarantine == table_rows(db, 'catalog_identity_quarantine')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', type=Path, required=True); p.add_argument('--after', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); args = p.parse_args()
    report = run(args.before, args.after, Path.cwd())
    with args.output.open('x') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('verified_input_hashes', 'by_scope', 'after_qualification', 'idempotent_reimport')}))


if __name__ == '__main__':
    main()
