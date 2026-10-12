"""Verify exact-coordinate offline caption retrieval and preserved evidence."""
import argparse
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from pokemon_index import core, catalog_locale, product_text, coverage_qualification as qualification
from pokemon_index import catalog_question_resolver_v2
from scripts.audit_international_coverage import coverage, facts
from scripts.audit_international_release_queue import table_rows


def verify_installed(db, rows):
    expected = dict(product_text_events=len(rows), product_text_subjects=len({r['card_id'] for r in rows}),
                    current_product_text_events=len(rows), stale_product_text_events=0)
    if product_text.status(db) != expected:
        raise ValueError('audited after snapshot does not contain the complete current caption batch')
    installed = {r['evidence_id']: (r['card_id'], r['record_json']) for r in table_rows(db, 'catalog_product_text')}
    wanted = {r['evidence_id']: (r['card_id'], catalog_locale.encoded(r)) for r in rows}
    if installed != wanted:
        raise ValueError('audited after caption payloads differ from hash-bound evidence')


def run(before_path, after_path, root):
    baseline = json.loads((root/'catalog-build-manifest-source-binding-v1.json').read_text())
    prior = json.loads((root/'catalog-build-manifest-international-qualification-v1.json').read_text())
    manifest = json.loads((root/'catalog-build-manifest-international-product-text-v1.json').read_text())
    assert len(baseline['steps']) == 65 and len(prior['steps']) == 67 and len(manifest['steps']) == 68
    assert manifest['steps'][:65] == baseline['steps'] and manifest['steps'][:67] == prior['steps']
    assert all(manifest['expected'][k] == v for k, v in prior['expected'].items())
    for step in manifest['steps']:
        assert hashlib.sha256((root/step['path']).read_bytes()).hexdigest() == step['sha256']
    rows = [json.loads(line) for line in (root/manifest['steps'][-1]['path']).read_text().splitlines()]
    assert len(rows) == 4 and len({r['card_id'] for r in rows}) == 4
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (before_path, after_path)}
    with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(after_path, readonly=True)) as after:
        assert product_text.status(before)['product_text_events'] == 0
        verify_installed(after, rows)
        tables = [r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        unchanged, timestamp_deltas = {}, {}
        generated_columns = {'card_relationship_assertion': 'asserted_at', 'card_identity_exception': 'applied_at',
                             'card_rarity_correction': 'applied_at', 'card_number_conflict_rule': 'applied_at'}
        for table in tables:
            if table == 'catalog_product_text':
                continue
            old, new = table_rows(before, table), table_rows(after, table)
            if table in generated_columns:
                column = generated_columns[table]
                timestamp_deltas[table] = dict(column=column, changed=sum(a[column] != b[column] for a, b in zip(old, new)))
                old = [{k:v for k,v in r.items() if k != column} for r in old]
                new = [{k:v for k,v in r.items() if k != column} for r in new]
            unchanged[table] = old == new
        assert all(unchanged.values()), 'pre-existing catalogue or evidence table changed'
        assert qualification.status(before) == qualification.status(after) == dict(coverage_candidate_events=65,
            coverage_candidate_subjects=65, coverage_current_held=65, coverage_stale_candidates=0, coverage_admitted_identities=0)
        assert coverage(before) == coverage(after), 'coverage or rights changed'
        assert set(product_text.search_aliases(after)) == {r['card_id'] for r in rows}
        searches = []
        for row in rows:
            held = product_text.candidate(after, row['candidate_id']); identity = held['identity']
            for product in row['products']:
                query = product['name']
                old = core.catalog_search_internal(before, query, language='ja', limit=100)
                new = core.catalog_search_internal(after, query, language='ja', limit=100)
                wrong = core.catalog_search_internal(after, query, language='en', limit=100)
                assert old['total'] == 0 and new['total'] == 1
                assert [c['card_id'] for c in new['cards']] == [row['card_id']] and wrong['total'] == 0
                searches.append(dict(card_id=row['card_id'], query=query, before_total=0, after_total=1,
                    exact_coordinate_only=True, wrong_language_excluded=True, link_kind=product['link_kind']))
            query = f"{identity['name']} {identity['set_code']} {identity['collector_number']}"
            assert [c['card_id'] for c in core.catalog_search_internal(before, query, language='ja', limit=100)['cards']] == [
                c['card_id'] for c in core.catalog_search_internal(after, query, language='ja', limit=100)['cards']]
        locales = [json.loads(line) for line in (root/'catalog/international-coverage-pilot-v1/locales.jsonl').read_text().splitlines()]
        locale_checks = []
        for row in locales:
            language = row['identity']['language']; cid = row['identity']['card_id']
            name = row['name_aliases'][0]['name_en' if language == 'ja' else 'name_ja']
            query = f"{name} {row['identity']['set_code']} {row['identity']['collector_number']}"
            old = core.catalog_search_internal(before, query, language=language, limit=100)
            new = core.catalog_search_internal(after, query, language=language, limit=100)
            assert [c['card_id'] for c in old['cards']] == [c['card_id'] for c in new['cards']] and cid in [c['card_id'] for c in new['cards']]
            old_resolution = catalog_question_resolver_v2.resolve_question(before, facts(row, name))
            new_resolution = catalog_question_resolver_v2.resolve_question(after, facts(row, name))
            assert old_resolution == new_resolution
            locale_checks.append(dict(card_id=cid, retrieval_preserved=True, v2_resolution_preserved=True))
        report = dict(schema='pokemon.product-text-audit.v1', manifest_inputs_before=67, manifest_inputs_after=68,
            preserved_65_source_inputs=True, preserved_67_step_prefix=True, verified_input_hashes=68,
            before=coverage(before), after=coverage(after), before_qualification=qualification.status(before),
            after_qualification=qualification.status(after), before_product_text=product_text.status(before),
            after_product_text=product_text.status(after), by_scope=dict(Counter(product_text.candidate(after, r['candidate_id'])['identity']['set_code'] for r in rows)),
            caption_queries=searches, preserved_localized_queries_and_v2_resolutions=locale_checks,
            unchanged_pre_existing_tables=unchanged, generated_rebuild_timestamp_differences=timestamp_deltas,
            timestamp_scope='Only generated asserted_at/applied_at columns in four named tables excluded across independent rebuilds; incremental append below excludes no historical columns',
            quarantine_records_before=before.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            quarantine_records_after=after.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            new_identities=0, new_provider_mappings=0, new_relationships=0, release_bindings_verified=0,
            scope='Four existing exact Japanese coordinate families gain internal publisher-caption retrieval; all 65 identity holds remain current, with no release date, physical variant, display or commerce approval')
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)/'append.sqlite3'; shutil.copyfile(before_path, scratch)
        with closing(core.connect(scratch)) as db:
            original = {t: table_rows(db, t) for t in tables}
            core.init_db(db)
            report['first_incremental_import'] = product_text.import_evidence(db, rows)
            assert report['first_incremental_import'] == dict(inserted=4, unchanged=0, quarantined=0)
            report['incremental_append_unchanged_pre_existing_tables'] = all(
                table_rows(db, t) == records for t, records in original.items() if t != 'catalog_product_text')
            assert report['incremental_append_unchanged_pre_existing_tables']
            report['idempotent_reimport'] = product_text.import_evidence(db, rows)
            assert report['idempotent_reimport'] == dict(inserted=0, unchanged=4, quarantined=0)
            verify_installed(db, rows)
            assert all(table_rows(db, t) == records for t, records in original.items() if t != 'catalog_product_text')
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == sha for path, sha in hashes.items())
    report['input_database_bytes_unchanged'] = True
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', type=Path, required=True); p.add_argument('--after', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); args = p.parse_args()
    report = run(args.before, args.after, Path.cwd())
    with args.output.open('x') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('verified_input_hashes', 'after_product_text', 'idempotent_reimport')}))


if __name__ == '__main__':
    main()
