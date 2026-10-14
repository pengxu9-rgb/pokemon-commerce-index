"""Constructor facts reuse complete native evidence without widening trust."""
from collections import Counter
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from pokemon_index import (core, catalog_locale, catalog_media as media,
    source_image_facts, number_evidence, variant_dimension_hold as holds,
    source_corrections, printing_evidence, collector_discovery as discovery,
    collector_runtime as runtime, card_source_context_index as index)
from pokemon_index import catalog_read_model_artifact as artifact
from tests import test_catalog_media as media_fixtures
from tests import test_variant_dimension_hold as hold_fixtures
from tests import test_source_corrections as correction_fixtures


class ConstructorSourceFactReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / 'catalog.sqlite3'
        fixture = media_fixtures.CatalogMediaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        source_image_facts.import_evidence(fixture.db, [fixture.fact()])
        number_evidence.import_evidence(fixture.db, [fixture.row])
        self.scan = fixture.cid
        self.absent = 'en:SVP:037/225:normal'
        hold_fixture = hold_fixtures.VariantDimensionHoldTests()
        hold_fixture.setUp()
        self.addCleanup(hold_fixture.doCleanups)
        self.hold_rows = []
        for ordinal in range(1, 45):
            seed = dict(hold_fixture.seed, collector_number=f'{ordinal:03d}/100')
            core.import_cards(fixture.db, [seed])
            cid = core.card_id(seed['language'], seed['set_code'], seed['collector_number'], seed['variant'])
            row = copy.deepcopy(hold_fixture.row)
            row['identity'] = catalog_locale.snapshot(fixture.db, cid)
            row['event_id'] = holds.event_id(row)
            self.hold_rows.append(row)
        holds.import_evidence(fixture.db, self.hold_rows)
        fixture.db.commit()
        with closing(core.connect(self.path)) as target:
            fixture.db.backup(target)
        self.held_ids = {row['identity']['card_id'] for row in self.hold_rows}

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._work_deadline.get())

    def build(self, path=None):
        with closing(core.connect(path or self.path, readonly=True)) as db, \
                runtime.sqlite_deadline(db, time.monotonic() + 8):
            return runtime.CatalogReadModel(db)

    def models(self, path=None, name='packaged'):
        path = path or self.path
        manifest = self.base / (name + '-manifest.json')
        manifest.write_text('{"synthetic_test_only":true}')
        directory = self.base / name
        with closing(core.connect(path, readonly=True)) as db:
            exported = artifact.write(db, manifest, directory)
        with closing(core.connect(path, readonly=True)) as db:
            loaded, _, _ = artifact.load(db, directory, manifest,
                expected_seal_sha256=exported['seal_sha256'])
        return (self.build(path), loaded)

    def native_cards(self, path=None):
        with closing(core.connect(path or self.path, readonly=True)) as db:
            rows = discovery._rows(db, '1=1', ())
            return rows, {row['card_id']: discovery._card_result(db, row) for row in rows}

    def test_all_historical_subjects_and_all44_holds_validate_once(self):
        evidence_calls, hold_calls = Counter(), Counter()
        original_evidence, original_hold = media.evidence, holds.context
        with closing(core.connect(self.path, readonly=True)) as db:
            complete = media.subjects(db) | self.held_ids
            expected_ids = media.current_ids(db)

        def evidence(db, cid):
            evidence_calls[cid] += 1
            return original_evidence(db, cid)

        def held(db, cid):
            hold_calls[cid] += 1
            return original_hold(db, cid)

        with patch.object(media, 'evidence', evidence), patch.object(holds, 'context', held):
            model = self.build()
        self.assertEqual(len(self.held_ids), 44)
        self.assertEqual({cid: evidence_calls[cid] for cid in complete},
                         {cid: 1 for cid in complete})
        self.assertEqual({cid: hold_calls[cid] for cid in self.held_ids},
                         {cid: 1 for cid in self.held_ids})
        self.assertEqual(model._media_ids, frozenset(expected_ids))
        self.assertTrue(model._card_source_context_index.enabled)
        with closing(core.connect(self.path, readonly=True)) as db:
            for cid in complete:
                self.assertEqual(model._card_source_context_index.lookup(cid), discovery._card_context(db, cid))

    def test_stale_primary_never_falls_through_to_current_secondary(self):
        with closing(core.connect(self.path)) as db:
            db.execute('UPDATE card SET name=? WHERE card_id=?', ('Cleffa updated', self.scan))
            db.commit()
            row = copy.deepcopy(self.fixture.row)
            row['revision'] = 2
            row['endpoint_snapshot'] = number_evidence.snapshot(db, self.scan)
            row['identity_sha256'] = number_evidence.supported_catalog.digest(row['endpoint_snapshot'])
            for review in row['review_groups'][0]['reviews']:
                review['observed_name'] = 'Cleffa updated'
            self.fixture.sign(row)
            number_evidence.import_evidence(db, [row])
            self.assertTrue(number_evidence.context(db, self.scan)['current_endpoint'])
        rows, expected = self.native_cards()
        self.assertEqual(expected[self.scan]['media_availability']['evidence_basis'], 'source_image_facts')
        self.assertEqual(expected[self.scan]['media_availability']['status'], 'stale_source_scan_evidence')
        for model in self.models():
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)
                self.assertNotIn(self.scan, model._media_ids)

    def test_held_number_and_stale_hold_keep_exact_native_contexts(self):
        with closing(core.connect(self.path)) as db:
            db.execute('DELETE FROM source_image_fact_evidence')
            db.commit()
            row = copy.deepcopy(self.fixture.row)
            row['revision'] = 2
            row['status'] = 'reading_hold'
            row['review_groups'][0]['reviews'][0]['observed_number_text'] = None
            self.fixture.sign(row)
            number_evidence.import_evidence(db, [row])
            stale_cid = sorted(self.held_ids)[0]
            db.execute('UPDATE card SET provenance=? WHERE card_id=?', ('changed', stale_cid))
            db.commit()
        rows, expected = self.native_cards()
        self.assertEqual(expected[self.scan]['media_availability']['status'], 'held_source_scan_evidence')
        self.assertEqual(expected[stale_cid]['variant_dimension_hold']['status'], 'stale_hold_source_changed')
        for model in self.models():
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                for row in rows:
                    self.assertEqual(discovery._card_result(db, row), expected[row['card_id']])
                    if row['card_id'] in self.held_ids:
                        card = discovery._card_result(db, row)
                        self.assertEqual(card['media_availability']['status'], 'identity_hold')
                        self.assertIs(card['media_availability']['with_source_scans_eligible'], False)
                        self.assertIs(card['variant_dimension_hold']['physical_size_verified'], False)

    def test_native_standalone_compiler_and_request_copies_stay_independent(self):
        model = self.build()
        with closing(core.connect(self.path, readonly=True)) as db:
            with patch.object(discovery, '_card_context', wraps=discovery._card_context) as native:
                standalone = index.compile_index(db)
                self.assertGreater(native.call_count, 0)
            self.assertEqual(standalone.to_state(), model._card_source_context_index.to_state())
            self.assertIsNone(runtime.snapshot_card_context(db, self.scan))
            self.assertEqual(media.current_ids(db), set(model._media_ids))
        rows, expected = self.native_cards()
        for published in self.models():
            with closing(core.connect(self.path, readonly=True)) as db, published.request(db):
                first = discovery._card_result(db, next(row for row in rows if row['card_id'] in self.held_ids))
                first['variant_dimension_hold']['replacement_relationships'].append('caller poison')
                first['media_availability']['warnings'].append('caller poison')
                self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)
                for cid in ('unknown', 1, True, b'not-text'):
                    self.assertIsNone(runtime.snapshot_card_context(db, cid))
        # Transient validator maps do not become additional persistent model facts.
        self.assertEqual(set(artifact.model_state(model)), set(artifact.model_state(self.build())))

    def test_malformed_hold_and_primary_evidence_errors_are_not_absence(self):
        for kind in ('hold_field', 'hold_json', 'primary_review'):
            path = self.base / (kind + '.sqlite3')
            path.write_bytes(self.path.read_bytes())
            with closing(core.connect(path)) as db:
                if kind.startswith('hold'):
                    row = copy.deepcopy(self.hold_rows[0])
                    if kind == 'hold_field':
                        del row['declared_size']
                    else:
                        row = []
                    db.execute('UPDATE catalog_identity_quarantine SET record_json=? WHERE quarantine_id=?',
                               (json.dumps(row), self.hold_rows[0]['event_id']))
                else:
                    row = self.fixture.fact()
                    row['reviews'][0]['image_sha256'] = 'e' * 64
                    db.execute('UPDATE source_image_fact_evidence SET record_json=?', (json.dumps(row),))
                db.commit()
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError, TypeError, artifact.ArtifactInvalid)):
                self.build(path)

    def test_namespace_mutation_during_native_fact_validation_cannot_publish(self):
        original = media.evidence
        for mutation in ('transaction', 'temp_rollback', 'schema', 'query_only'):
            changed = False

            def evidence(db, cid):
                nonlocal changed
                if not changed:
                    changed = True
                    if mutation == 'transaction':
                        db.execute('BEGIN')
                    else:
                        db.execute('PRAGMA query_only=OFF')
                        db.execute('CREATE TEMP TABLE producer_changed(v)')
                        if mutation == 'temp_rollback':
                            db.execute("INSERT INTO producer_changed VALUES ('rolled back')")
                            db.rollback()
                            db.execute('DROP TABLE producer_changed')
                            db.execute('PRAGMA query_only=ON')
                        elif mutation == 'query_only':
                            db.execute('DROP TABLE producer_changed')
                return original(db, cid)

            with self.subTest(mutation=mutation), patch.object(media, 'evidence', evidence):
                with self.assertRaises((runtime.CatalogSnapshotChanged, runtime.CatalogReadModelUnsupported,
                                        ValueError, artifact.ArtifactInvalid)):
                    self.build()

    def test_path_replacement_during_validation_cannot_publish_borrowed_facts(self):
        original = media.evidence
        replacement = self.base / 'replacement.sqlite3'
        replacement.write_bytes(self.path.read_bytes())
        changed = False

        def evidence(db, cid):
            nonlocal changed
            result = original(db, cid)
            if not changed:
                changed = True
                os.replace(replacement, self.path)
            return result

        with patch.object(media, 'evidence', evidence), self.assertRaises(runtime.CatalogSnapshotChanged):
            self.build()

    def test_real_wal_commit_during_validation_aborts_reuse(self):
        original = media.evidence
        changed = False
        with closing(core.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')

            def evidence(db, cid):
                nonlocal changed
                result = original(db, cid)
                if not changed:
                    changed = True
                    writer.execute('UPDATE card SET name=? WHERE card_id=?', ('changed', self.scan))
                    writer.commit()
                    self.assertGreater(Path(str(self.path) + '-wal').stat().st_size, 0)
                return result

            with patch.object(media, 'evidence', evidence), self.assertRaises(runtime.CatalogSnapshotChanged):
                self.build()

    def test_changed_declared_source_policy_during_validation_aborts_reuse(self):
        policy = self.base / 'synthetic-source-policy.json'
        policy.write_text('{"version":1}')
        original_sources, original_evidence = artifact._source_identities, media.evidence
        changed = False

        def sources():
            # Add one disposable policy to the complete original declared set;
            # retain every actual production identity and its original checker.
            return original_sources() + ((policy, artifact._file_identity(policy)),)

        def evidence(db, cid):
            nonlocal changed
            result = original_evidence(db, cid)
            if not changed:
                changed = True
                policy.write_text('{"version":2}')
            return result

        with patch.object(artifact, '_source_identities', sources), patch.object(media, 'evidence', evidence), \
                self.assertRaises(runtime.CatalogSnapshotChanged):
            self.build()

    def test_transient_bounds_disable_whole_index_and_keep_complete_native_ids(self):
        with closing(core.connect(self.path, readonly=True)) as db:
            expected = media.current_ids(db)
        for cap in ('MAX_HISTORY_ROWS', 'MAX_CONTEXT_BYTES'):
            with self.subTest(cap=cap), patch.object(index, cap, 1):
                model = self.build()
                self.assertFalse(model._card_source_context_index.enabled)
                self.assertEqual(model._card_source_context_index.known_card_ids, frozenset())
                self.assertEqual(model._card_source_context_index.assignments, {})
                self.assertEqual(model._media_ids, frozenset(expected))
        original = media.evidence
        deadline = time.monotonic() + 8

        def evidence(db, cid):
            self.assertEqual(runtime._work_deadline.get(), deadline)
            with patch.object(runtime.time, 'monotonic', return_value=deadline + 1):
                runtime.checkpoint()
            return original(db, cid)

        with closing(core.connect(self.path, readonly=True)) as db, runtime.sqlite_deadline(db, deadline), \
                patch.object(media, 'evidence', evidence), self.assertRaises(runtime.CatalogDeadline):
            runtime.CatalogReadModel(db)

    def correction_path(self, family=False):
        fixture = (correction_fixtures.ReferenceBoundaryCorrectionTests() if family else
                   correction_fixtures.SourceCorrectionTests())
        fixture.setUp()
        self.addCleanup(fixture.db.close)
        source_corrections.import_evidence(fixture.db, [fixture.correction])
        path = self.base / ('family.sqlite3' if family else 'correction.sqlite3')
        fixture.db.commit()
        with closing(core.connect(path)) as target:
            fixture.db.backup(target)
        return fixture, path

    def test_current_stale_and_latest_correction_rendering_matches_native(self):
        fixture, path = self.correction_path()
        second = copy.deepcopy(fixture.correction)
        second['revision'] = 2
        second['recorded_at'] = '2026-10-02T00:02:00Z'
        second['event_id'] = source_corrections.event_id(second)
        with closing(core.connect(path)) as db:
            source_corrections.import_evidence(db, [second])
            self.assertEqual(db.execute('SELECT count(*) FROM source_correction_evidence').fetchone()[0], 2)
        for stale in (False, True):
            if stale:
                with closing(core.connect(path)) as db:
                    db.execute('UPDATE card SET name=? WHERE card_id=?', ('Changed', fixture.cid))
                    db.commit()
            rows, expected = self.native_cards(path)
            findings = expected[fixture.cid]['source_corrections']['findings']
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]['event_id'], second['event_id'])
            self.assertEqual(findings[0]['status'], 'stale_source_correction' if stale else 'source_corrected')
            for model in self.models(path, 'correction-' + str(stale)):
                with closing(core.connect(path, readonly=True)) as db, model.request(db):
                    self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)

    def test_reference_correction_new_card_population_and_no_permissions(self):
        fixture, path = self.correction_path(family=True)
        new_id = fixture.correction['new_card']['card_id']
        rows, expected = self.native_cards(path)
        self.assertIn('source_corrections', expected[new_id])
        self.assertIs(expected[new_id]['structural_match_eligible'], False)
        for model in self.models(path, 'family-model'):
            self.assertIn(new_id, model._card_source_context_index.assignments)
            with closing(core.connect(path, readonly=True)) as db, model.request(db):
                self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)
                self.assertIs(discovery._card_result(db, next(row for row in rows if row['card_id'] == new_id))['price_comparable'], False)

    def test_multiple_correction_kinds_keep_current_and_stale_findings_separate(self):
        fixture, path = self.correction_path()
        parent = copy.deepcopy(fixture.row)
        parent['revision'] = 2
        parent['observations'][0].update(claim='printed_qualifier', value='オーリム博士')
        for reviewer in parent['reviewers']:
            reviewer['observations_sha256'] = source_corrections.supported_catalog.digest(parent['observations'])
        fixture.sign(parent)
        with closing(core.connect(path)) as db:
            printing_evidence.import_evidence(db, [parent])
            qualifier = copy.deepcopy(fixture.correction)
            qualifier.update(kind='printed_qualifier', correction_key='printed_qualifier:ja:FIX:001/100',
                parent_event_id=parent['event_id'],
                parent_record_json=db.execute('SELECT record_json FROM printing_source_evidence WHERE event_id=?',
                                              (parent['event_id'],)).fetchone()[0],
                parent_record_sha256=source_corrections.supported_catalog.digest(parent),
                value='オーリム博士', recorded_at='2026-10-02T00:02:00Z')
            qualifier['event_id'] = source_corrections.event_id(qualifier)
            source_corrections.import_evidence(db, [qualifier])
        rows, expected = self.native_cards(path)
        findings = expected[fixture.cid]['source_corrections']['findings']
        self.assertEqual({finding['kind'] for finding in findings}, {'printed_artist', 'printed_qualifier'})
        self.assertEqual({finding['status'] for finding in findings}, {'source_corrected', 'stale_source_correction'})
        for model in self.models(path, 'multi-correction'):
            with closing(core.connect(path, readonly=True)) as db, model.request(db):
                self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)

    def test_malformed_historical_correction_is_not_partial_absence(self):
        fixture, original_path = self.correction_path()
        for field in ('snapshot', 'new_card'):
            path = self.base / ('bad-correction-' + field + '.sqlite3')
            path.write_bytes(original_path.read_bytes())
            malformed = copy.deepcopy(fixture.correction)
            if field == 'snapshot':
                malformed['snapshot']['cards'] = [{}]
            else:
                malformed['new_card'] = {}
            with closing(core.connect(path)) as db:
                db.execute('UPDATE source_correction_evidence SET record_json=?', (json.dumps(malformed),))
                db.commit()
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError, artifact.ArtifactInvalid)):
                self.build(path)

    def test_unsupported_historical_id_type_falls_back_wholly_to_native(self):
        fixture, path = self.correction_path()
        unsupported = copy.deepcopy(fixture.correction)
        unsupported['snapshot']['cards'] = [{'card_id': 1}]
        with closing(core.connect(path)) as db:
            db.execute('UPDATE source_correction_evidence SET record_json=?', (json.dumps(unsupported),))
            db.commit()
        rows, expected = self.native_cards(path)
        model = self.build(path)
        self.assertFalse(model._card_source_context_index.enabled)
        self.assertEqual(model._card_source_context_index.known_card_ids, frozenset())
        with closing(core.connect(path, readonly=True)) as db, model.request(db):
            self.assertEqual({row['card_id']: discovery._card_result(db, row) for row in rows}, expected)


if __name__ == '__main__':
    unittest.main()
