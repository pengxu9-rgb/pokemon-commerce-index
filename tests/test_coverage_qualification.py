import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core, catalog_locale, coverage_qualification as qualification
from scripts import build_international_release_queue as queue, build_catalog_snapshot
from scripts.audit_international_release_queue import verify_installed


class CoverageQualificationTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(':memory:')
        core.init_db(self.db)
        self.seed = dict(language='ja', set_code='DS', collector_number='001/020', name='ミニリュウ',
            variant='unverified', provenance='ptcg-database:' + 'a'*40 + ':data_jp/DS/1.json:sha256:' + 'b'*64,
            rights_reference='reviewed-metadata-fixture', display_allowed=False, match_eligible=False)
        core.import_cards(self.db, [self.seed])
        core.import_card_references(self.db, [dict(source='ptcg-database', source_jp_id='1', set_code='DS',
            collector_number='001/020', name='ミニリュウ', provenance='fixture-reference', rights_reference='fixture')])
        self.cid = core.card_id('ja', 'DS', '001/020', 'unverified')
        identity = catalog_locale.snapshot(self.db, self.cid)
        self.row = dict(schema=qualification.SCHEMA, identity=identity,
            coordinate_snapshot=qualification.coordinate_snapshot(self.db, identity),
            coordinate_references=qualification.references_snapshot(self.db, identity),
            release_snapshot=None, numbering_scope='provisional:ja:DS', status='held', test_only=False,
            source=dict(provider='ptcg-database', native_id='data_jp/DS/1.json', revision='a'*40, sha256='b'*64,
                language='ja', region='ZZ', rights_reference='reviewed-metadata-fixture',
                rights_status='metadata_internal_reviewed', license_sha256='c'*64,
                inspected_at='2026-10-11T10:37:00Z', retrieved_at=None,
                retrieval_status='historical_snapshot_time_not_recorded'),
            confidence=dict(source_bytes=1.0, product_binding=None, physical_printing=None),
            source_product_declarations=[dict(name='ドラゴンセレクション', product_url=None)],
            cached_official_page=dict(native_id='1', url='https://www.pokemon-card.com/card-search/details.php/card/1',
                sha256='d'*64, retrieved_at='2026-10-02T00:38:43Z', rights_status='cached_evidence_only_no_display_grant',
                name='ミニリュウ', coordinate=dict(set_code='DS', collector_number='001/020'), product_links=[]),
            **{k: False for k in qualification.FLAGS})
        self.sign(self.row)

    def tearDown(self):
        self.db.close()

    @staticmethod
    def sign(row):
        row.pop('candidate_id', None)
        row['hold_reasons'] = qualification.hold_reasons(row)
        row['candidate_id'] = 'coverage-candidate:' + catalog_locale.digest(row)
        return row

    def test_idempotent_hold_does_not_change_catalog_or_trading_tables(self):
        tables = ('card', 'card_reference', 'catalog_set', 'catalog_set_localized', 'catalog_vocabulary',
                  'catalog_source_mapping', 'source_policy', 'listing', 'observation', 'verified_sale')
        before = {t: [tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in tables}
        self.assertEqual(qualification.import_candidates(self.db, [self.row]), dict(inserted=1, unchanged=0, rejected=0))
        self.assertEqual(qualification.import_candidates(self.db, [self.row]), dict(inserted=0, unchanged=1, rejected=0))
        self.assertEqual(before, {t: [tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in tables})
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0], 1)
        self.assertEqual(core.catalog_card_internal(self.db, self.cid)['card']['coverage_qualification'][0]['status'], 'held')
        self.assertEqual(core.catalog_search_internal(self.db, 'ドラゴンセレクション ja')['total'], 0)
        self.assertEqual(core.catalog_search_internal(self.db, 'ミニリュウ ja')['total'], 1)

    def test_later_link_still_cannot_promote_a_held_candidate(self):
        changed = copy.deepcopy(self.row)
        changed['cached_official_page']['product_links'] = [dict(name='ドラゴンセレクション',
            url='https://www.pokemon-card.com/ex/ds/index.html')]
        self.sign(changed)
        self.assertEqual(qualification.import_candidates(self.db, [changed])['inserted'], 1)
        self.assertIn('product_link_requires_separate_release_review', qualification.context(self.db, self.cid)[0]['hold_reasons'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_release_evidence').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT match_eligible FROM card').fetchone()[0], 0)

    def test_permission_and_status_forgery_rejected(self):
        mutations = [{k: True} for k in qualification.FLAGS] + [dict(status='approved'), dict(test_only=True),
            dict(confidence=dict(source_bytes=1.0, product_binding=1.0, physical_printing=1.0))]
        for change in mutations:
            row = self.sign({**self.row, **change})
            self.assertEqual(qualification.import_candidates(self.db, [row])['rejected'], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_coverage_candidate').fetchone()[0], 0)

    def test_stale_source_release_reference_and_sibling_remain_in_history(self):
        qualification.import_candidates(self.db, [self.row])
        self.db.execute("UPDATE card_reference SET provenance='drift'")
        self.assertEqual(qualification.context(self.db, self.cid)[0]['status'], 'stale')
        self.db.execute("UPDATE card_reference SET provenance='fixture-reference'")
        core.import_cards(self.db, [{**self.seed, 'variant': 'holo', 'attributes': {'artwork': 'shared-test-only'}}])
        self.assertEqual(qualification.context(self.db, self.cid)[0]['status'], 'stale')
        sibling = core.card_id('ja', 'DS', '001/020', 'holo')
        self.db.execute('DELETE FROM card_number_context WHERE card_id=?', (sibling,))
        self.db.execute('DELETE FROM card WHERE card_id=?', (sibling,))
        self.assertEqual(qualification.context(self.db, self.cid)[0]['status'], 'held')
        core.import_sets(self.db, [dict(language='ja', set_code='DS', name_ja='別の商品',
            provenance='new-release', rights_reference='fixture')])
        self.assertEqual(qualification.context(self.db, self.cid)[0]['status'], 'stale')
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_coverage_candidate').fetchone()[0], 1)

    def test_provider_collision_wrong_coordinate_and_translated_name_rejected(self):
        cases = []
        for key, value in [('provider', 'tcgdex'), ('native_id', 'data_jp/SC/1.json'), ('language', 'en'), ('region', 'JP')]:
            row = copy.deepcopy(self.row); row['source'][key] = value; cases.append(row)
        for key, value in [('native_id', '2'), ('name', 'Dratini'),
                           ('coordinate', dict(set_code='SC', collector_number='001/020'))]:
            row = copy.deepcopy(self.row); row['cached_official_page'][key] = value; cases.append(row)
        for row in cases:
            self.assertEqual(qualification.import_candidates(self.db, [self.sign(row)])['rejected'], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0], 0)

    def test_test_only_baseline_drift_and_missing_snapshots_fail_closed(self):
        qualification.import_candidates(self.db, [self.row])
        self.db.execute('UPDATE card SET attributes_json=?', (json.dumps(dict(test_only=True)),))
        self.assertEqual(qualification.context(self.db, self.cid)[0]['status'], 'stale')
        self.assertEqual(qualification.import_candidates(self.db, [self.row])['rejected'], 1)
        self.db.execute("UPDATE card SET attributes_json='{}'")
        for field in ('release_snapshot', 'cached_official_page'):
            row = copy.deepcopy(self.row); row.pop(field); row.pop('candidate_id')
            row['candidate_id'] = 'coverage-candidate:' + catalog_locale.digest(row)
            self.assertEqual(qualification.import_candidates(self.db, [row])['rejected'], 1)

    def test_malformed_payloads_quarantine_without_interrupting_next_valid_row(self):
        rows = [None, [], 'malformed']
        for field, value in [('identity', []), ('source', []), ('source_product_declarations', [None]),
                             ('cached_official_page', []), ('coordinate_snapshot', []), ('coordinate_references', {})]:
            row = copy.deepcopy(self.row); row[field] = value
            row.pop('candidate_id'); row['candidate_id'] = 'coverage-candidate:' + catalog_locale.digest(row)
            rows.append(row)
        row = copy.deepcopy(self.row); row['source']['inspected_at'] = []; row.pop('candidate_id')
        row['candidate_id'] = 'coverage-candidate:' + catalog_locale.digest(row); rows.append(row)
        result = qualification.import_candidates(self.db, [*rows, self.row])
        self.assertEqual(result, dict(inserted=1, unchanged=0, rejected=len(rows)))

    def test_cross_language_same_art_promos_and_stamp_variants_do_not_inherit_hold(self):
        qualification.import_candidates(self.db, [self.row])
        others = [{**self.seed, **change} for change in [dict(language='en'), dict(set_code='PROMO'),
            dict(variant='holo'), dict(variant='holo_stamped_promo')]]
        core.import_cards(self.db, others)
        for row in others:
            cid = core.card_id(row['language'], row['set_code'], row['collector_number'], row['variant'])
            self.assertEqual(qualification.context(self.db, cid), [])
        self.assertEqual(self.db.execute('SELECT count(*) FROM card').fetchone()[0], 5)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0], 0)

    def test_old_snapshot_reads_and_internal_search_remain_supported(self):
        self.db.execute('DROP TABLE catalog_coverage_candidate')
        self.assertEqual(qualification.context(self.db, self.cid), [])
        self.assertEqual(qualification.status(self.db)['coverage_candidate_events'], 0)
        self.assertEqual(core.catalog_search_internal(self.db, 'ミニリュウ')['total'], 1)

    def test_internal_cli_and_http_expose_holds_readonly(self):
        from threading import Thread
        from urllib.parse import urlencode
        from urllib.request import urlopen
        from pokemon_index.cli import create_server
        qualification.import_candidates(self.db, [self.row])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'snapshot.sqlite3'
            writer = core.connect(path); self.db.backup(writer); writer.close()
            before = path.read_bytes()
            result = subprocess.check_output(['python3', '-m', 'pokemon_index', '--db', str(path),
                'catalog-card', self.cid], text=True)
            self.assertEqual(json.loads(result)['card']['coverage_qualification'][0]['status'], 'held')
            with create_server(str(path), '127.0.0.1', 0, True) as server:
                thread = Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    url = f'http://127.0.0.1:{server.server_port}/catalog-card?' + urlencode(dict(card_id=self.cid))
                    with urlopen(url) as response:
                        data = json.load(response)
                    self.assertEqual(data['card']['coverage_qualification'][0]['status'], 'held')
                    self.assertEqual(data['observed_priceable_units'], [])
                finally:
                    server.shutdown(); thread.join()
            self.assertEqual(path.read_bytes(), before)

    def test_manifest_rejection_never_leaves_a_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cards = root/'cards.jsonl'; cards.write_text(json.dumps(self.seed)+'\n')
            candidate = root/'held.jsonl'; forged = {**self.row, 'status': 'approved'}
            candidate.write_text(json.dumps(forged)+'\n')
            steps = [dict(operation=op, path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                     for op, path in [('import-cards', cards), ('import-coverage-candidates', candidate)]]
            manifest = root/'manifest.json'; manifest.write_text(json.dumps(dict(schema='pokemon.catalog-build.v1', steps=steps, expected={})))
            output = root/'snapshot.sqlite3'
            with self.assertRaisesRegex(ValueError, 'invalid coverage candidate'):
                build_catalog_snapshot.build(manifest, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob('.catalog-build-*')), [])

    def test_audit_rejects_uninstalled_changed_or_incomplete_after_batch(self):
        with self.assertRaisesRegex(ValueError, 'complete current held batch'):
            verify_installed(self.db, [self.row], [])
        qualification.import_candidates(self.db, [self.row])
        verify_installed(self.db, [self.row], [])
        self.db.execute("UPDATE catalog_identity_quarantine SET reason='forged'")
        with self.assertRaisesRegex(ValueError, 'quarantine payloads/history'):
            verify_installed(self.db, [self.row], [])
        self.db.execute('UPDATE catalog_identity_quarantine SET reason=?', ('; '.join(self.row['hold_reasons']),))
        self.db.execute('DELETE FROM catalog_coverage_candidate')
        with self.assertRaisesRegex(ValueError, 'complete current held batch'):
            verify_installed(self.db, [self.row], [])


class OfflineQueueBuilderTests(unittest.TestCase):
    def test_source_bytes_cache_receipts_and_bounds_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root/'source'; repo.mkdir(); cache = root/'cache'; cache.mkdir()
            license_file = repo/'LICENSE'; license_file.write_text('SYNTHETIC TEST ONLY; NO REAL LICENSE CLAIM')
            sources = []
            for index, code in enumerate(queue.SCOPES):
                path = repo/'data_jp'/code/'1.json'; path.parent.mkdir(parents=True)
                payload = dict(set_name=code, name='テスト', number='001', set_total='020',
                    sources=[dict(name='テスト製品', link=None)])
                path.write_text(json.dumps(payload, ensure_ascii=False)); sources.append(path)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'synthetic test only'], check=True)
            revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            db = core.connect(':memory:'); core.init_db(db)
            try:
                for path in sources:
                    code = path.parent.name; sha = hashlib.sha256(path.read_bytes()).hexdigest()
                    core.import_cards(db, [dict(language='ja', set_code=code, collector_number='001/020', variant='unverified',
                        name='テスト', rights_reference='synthetic test only',
                        provenance=f'ptcg-database:{revision}:{path.relative_to(repo).as_posix()}:sha256:{sha}')])
                with self.assertRaisesRegex(ValueError, '4–65'):
                    queue.select(db, repo, cache, '2026-10-11T10:37:00Z', limit=66, license_path=license_file)
                rows = queue.select(db, repo, cache, '2026-10-11T10:37:00Z', limit=4, license_path=license_file)
                self.assertEqual(len(rows), 4); self.assertTrue(all(r['status']=='held' for r in rows))
                self.assertEqual(qualification.import_candidates(db, rows)['inserted'], 4)
                db.execute('UPDATE card SET attributes_json=?', (json.dumps(dict(test_only=True)),))
                with self.assertRaisesRegex(ValueError, 'test-only baseline'):
                    queue.select(db, repo, cache, '2026-10-11T10:37:00Z', limit=4, license_path=license_file)
                db.execute("UPDATE card SET attributes_json='{}'")
                sources[0].write_text(sources[0].read_text()+' ')
                with self.assertRaisesRegex(ValueError, 'pinned revision/provenance'):
                    queue.select(db, repo, cache, '2026-10-11T10:37:00Z', limit=4, license_path=license_file)
                with self.assertRaisesRegex(ValueError, 'escapes'):
                    queue.checked_source(repo, revision, '../outside', 'a'*64)
                (cache/'card-SMH.html').write_text('SYNTHETIC TEST ONLY')
                (cache/'card-SMH.receipt.json').write_text(json.dumps(dict(sha256='a'*64)))
                identity=rows[0]['identity']
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    queue.cached_page(cache, 'SMH', identity, [])
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
