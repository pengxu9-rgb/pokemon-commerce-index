"""Portable mixed-caller safety tests; synthetic smoke is not capacity evidence."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pokemon_index import core, collector_journey
from pokemon_index.cli import create_server
from scripts import benchmark_collector_caller as bench
from scripts import benchmark_collector_mixed as mixed
from scripts import collector_catalog_evidence as evidence


ROOT = Path(__file__).resolve().parents[1]
MIXED_RUNNER = ROOT / 'integrations/pivota/benchmarkCollectorMixedCaller.cjs'


def normalized(value):
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()
                if key not in {'catalog_revision', 'expected_revision'}}
    return value


class ExplicitExecutionPlanTests(unittest.TestCase):
    def test_invalid_plans_fail_before_launch_or_journal_creation(self):
        invalid = [
            [], {}, 'serial_first_use', 1, [None], [('serial_first_use',)],
            [('serial_first_use', 1, 'unexpected')],
            [('unknown_phase', 1)], [(1, 1)],
            [('serial_first_use', True)], [('serial_first_use', 1.0)],
            [('serial_first_use', '1')], [('serial_first_use', 0)],
            [('serial_first_use', -1)], [('serial_first_use', 129)],
            [('serial_first_use', 65), ('serial_warm', 64)],
            [('serial_warm', 1)] * 65,
        ]
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'must-not-exist.jsonl'
            for execution_plan in invalid:
                with self.subTest(plan=execution_plan), patch.object(bench.subprocess, 'Popen') as launch:
                    with self.assertRaises(ValueError):
                        bench.run_node('http://127.0.0.1:1', {}, repo_root=ROOT,
                            local=True, execution_plan=execution_plan, journal_path=journal)
                    launch.assert_not_called()
                    self.assertFalse(journal.exists())

    def test_default_plan_is_unchanged_without_override(self):
        config, plan = bench.scenario_plan()
        self.assertEqual(config, {'bursts': [2, 4, 16], 'sustainedConcurrency': 4,
            'sustainedRequests': 16, 'recoveryDelayMs': 1000,
            'cancellationRecoveryWaitMs': 8500, 'integrityConcurrency': 4})
        self.assertEqual(plan[:3], [('serial_first_use', 1), ('serial_warm', 1),
            ('serial_control_b', 1)])
        self.assertEqual(sum(count for _, count in plan), 58)
        self.assertEqual(plan[-3:], [('external_cancellation', 1),
            ('immediate_recovery', 1), ('post_cancel_deadline_recovery', 1)])


@unittest.skipUnless(shutil.which('node'), 'Node is required for journal regressions')
class ExplicitRunnerJournalTests(unittest.TestCase):
    def make_runner(self, directory, plan, *, partial=False):
        """Emit protocol-only events; no client/network calls happen in these cases."""
        runner = Path(directory) / 'protocol-fixture.cjs'
        runner.write_text("""'use strict';
const plan = PLAN;
const emit = event => process.stdout.write(JSON.stringify({schema:'pokemon.collector-journal.v1', ...event})+'\\n');
process.stdin.resume();
process.stdin.on('end', () => {
  emit({event:'run_started', planned_requests:plan.reduce((n,c)=>n+c[1],0), client_mode:'current_required', node_version:process.version});
  let request = 0;
  for (let c = 0; c < plan.length; c++) {
    emit({event:'case_started', case:{case_id:c+1,phase:plan[c][0],clients:1,scheduled_requests:plan[c][1]}});
    for (let i=0; i < plan[c][1]; i++) {
      emit({event:'request_started',request_id:++request,case_id:c+1,workload_sha256:'a'.repeat(64)});
      if (PARTIAL && request===2) {process.stderr.write('private-runner-error-canary');setInterval(()=>{},1000);return;}
      emit({event:'fetch_attempt', request_id:request, attempt:{attempt:1,http_status:200,body_complete:true,body_bytes:1,token:'private-token-canary'}});
      emit({event:'attempt_completed', request_id:request, attempt:{schema:'pokemon.collector-attempt.v1',attempt:1,outcome:'accepted',phase:'complete',duration_ms:1}});
      emit({event:'request_completed',row:{request_id:request,category:'completed',elapsed_ms:1,input_unchanged:true,turn_count:20,session_integrity:true,gates_closed:true,deterministic_match:true}});
    }
    emit({event:'case_completed',case_id:c+1,wall_ms:1});
  }
  emit({event:'run_completed',node_version:process.version,client_mode:'current_required',native_attempt_diagnostics:true});
});
""".replace('PLAN', json.dumps(plan)).replace('PARTIAL', 'true' if partial else 'false'))
        return runner

    def test_custom_runner_and_plan_accept_exact_bounds(self):
        plan = [('serial_warm', 2)] * 64
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, plan)
            result = bench.run_node('http://127.0.0.1:1', {}, repo_root=ROOT,
                local=True, runner_path=runner, execution_plan=plan, watchdog_seconds=5)
        self.assertTrue(result['runner_complete'], result)
        self.assertEqual(result['request_accounting'], {'planned_requests': 128,
            'started_requests': 128, 'settled_requests': 128,
            'unsettled_requests': 0, 'not_started_requests': 0})
        self.assertEqual(len(result['cases']), 64)
        self.assertEqual(bench.RUNNER, ROOT / 'integrations/pivota/benchmarkCollectorCaller.cjs')

    def test_failed_pid_observer_cannot_change_completion_or_leak_error(self):
        observed = []
        def broken_observer(pid):
            observed.append(pid)
            raise RuntimeError('private-observer-error-canary')
        with tempfile.TemporaryDirectory() as directory:
            plan = [('serial_first_use', 1)]
            runner = self.make_runner(directory, plan)
            journal = Path(directory) / 'observer.jsonl'
            result = bench.run_node('http://127.0.0.1:1', {}, repo_root=ROOT,
                local=True, runner_path=runner, execution_plan=plan,
                on_process_started=broken_observer, journal_path=journal, watchdog_seconds=3)
            persisted = journal.read_text()
        self.assertTrue(result['runner_complete'], result)
        self.assertEqual(len(observed), 1)
        self.assertIs(type(observed[0]), int)
        self.assertGreater(observed[0], 0)
        self.assertNotIn('private-observer-error-canary', persisted + json.dumps(result))
        self.assertNotIn('private-token-canary', persisted + json.dumps(result))

    def test_pid_observer_is_not_awaited(self):
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        def blocking_observer(pid):
            entered.set()
            release.wait(5)
            returned.set()
        try:
            with tempfile.TemporaryDirectory() as directory:
                plan = [('serial_first_use', 1)]
                runner = self.make_runner(directory, plan)
                result = bench.run_node('http://127.0.0.1:1', {}, repo_root=ROOT,
                    local=True, runner_path=runner, execution_plan=plan,
                    on_process_started=blocking_observer, watchdog_seconds=2)
            self.assertTrue(entered.wait(1), 'PID observer was not invoked')
            self.assertTrue(result['runner_complete'], result)
            self.assertFalse(returned.is_set(), 'Runner waited for the optional observer')
        finally:
            release.set()
        self.assertTrue(returned.wait(1), 'Test observer did not cleanly finish')

    def test_partial_journal_preserves_custom_denominator_and_settled_attempt(self):
        plan = [('serial_first_use', 1), ('simultaneous_burst', 2)]
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, plan, partial=True)
            journal = Path(directory) / 'partial.jsonl'
            result = bench.run_node('http://127.0.0.1:1', {}, repo_root=ROOT,
                local=True, runner_path=runner, execution_plan=plan,
                journal_path=journal, watchdog_seconds=.5)
            raw = journal.read_text()
            events = [json.loads(line) for line in raw.splitlines()]
        self.assertFalse(result['runner_complete'])
        self.assertEqual(result['runner_failure_code'], 'node_watchdog_timeout')
        self.assertEqual(result['request_accounting'], {'planned_requests': 3,
            'started_requests': 2, 'settled_requests': 1,
            'unsettled_requests': 1, 'not_started_requests': 1})
        self.assertEqual(result['cases'][0]['results'][0]['fetch_attempts'][0]['http_status'], 200)
        self.assertEqual(len(result['cases'][0]['results'][0]['attempts']), 1)
        self.assertEqual(result['cases'][1]['results'][0]['category'], 'unsettled')
        self.assertEqual(events[-1]['event'], 'receipt_marker')
        self.assertEqual(events[-1]['completion'], 'partial')
        self.assertEqual(events[-1]['planned_requests'], 3)
        for canary in ('private-runner-error-canary', 'private-token-canary'):
            self.assertNotIn(canary, raw + json.dumps(result))


class MixedWorkloadTests(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / 'tests/fixtures/collector-mixed-workload-v1.json').read_text())

    def test_default_plan_preserves_distinct_sessions_and_exact_denominator(self):
        plan = mixed.plan()
        mixed.validate_plan(plan)
        self.assertEqual(sum(len(case['indices']) for case in plan), 97)
        self.assertEqual([case['indices'][0] for case in plan if case['phase'].startswith('serial_')], list(range(16)))
        self.assertEqual([case['indices'][0] for case in plan if case['phase'] == 'cross_session_recovery'], list(range(16)))
        self.assertEqual(sum(bool(case.get('cancel')) for case in plan), 1)
        for case in plan:
            if case['phase'] == 'simultaneous_burst':
                self.assertEqual(len(case['indices']), case['clients'])
                self.assertEqual(len(set(case['indices'])), case['clients'])
                self.assertEqual(len({index // 4 for index in case['indices']}), min(4, case['clients']))
            if case.get('sustained'):
                lanes = [set(case['indices'][lane::case['clients']]) for lane in range(case['clients'])]
                self.assertEqual(set.union(*lanes), set(range(16)))
                for i, left in enumerate(lanes):
                    for right in lanes[i + 1:]:
                        self.assertFalse(left & right, 'Concurrently active lanes may not coalesce equal payloads')

    def test_frozen_workload_has_verified_payload_digests_and_twenty_turns(self):
        workload = self.fixture()
        original = copy.deepcopy(workload)
        mixed.validate_workload(workload)
        self.assertEqual(workload, original, 'Validation must not rewrite frozen evidence')
        self.assertEqual(workload['catalog_sha256'], '2ee7448b7e42ab9fe7e423a6769b01c18f260b503f3cb6d633802c5b2300549b')
        self.assertEqual(len(workload['sessions']), 16)
        self.assertEqual(len({session['payload_sha256'] for session in workload['sessions']}), 16)
        self.assertEqual(workload['payloads_sha256'], bench.json_hash([session['payload'] for session in workload['sessions']]))
        for session in workload['sessions']:
            self.assertEqual(session['payload_sha256'], bench.json_hash(session['payload']))
            self.assertEqual(len(session['payload']['turns']), 20)
            self.assertTrue(all(session['preflight']['checks'].values()))
        self.assertEqual({session['language'] for session in workload['sessions']}, {'en', 'ja'})
        self.assertEqual(len({session['pattern'] for session in workload['sessions']}), 4)

    def test_malformed_workload_and_changed_payloads_are_rejected(self):
        invalid = [None, [], {}, {'schema': 'other', 'sessions': []}]
        for key, value in [('schema', 'other'), ('catalog_sha256', 'invalid'),
                           ('payloads_sha256', 'f' * 64), ('catalog_evidence', None),
                           ('catalog_evidence', {'schema': 'wrong', 'sha256': 'a' * 64}),
                           ('catalog_evidence', {'schema': evidence.SCHEMA, 'sha256': 'invalid'}),
                           ('sessions', []),
                           ('sessions', self.fixture()['sessions'][:15])]:
            workload = self.fixture()
            workload[key] = value
            invalid.append(workload)
        for field, value in [('payload_sha256', 'f' * 64),
                             ('expected_result_semantic_sha256', 'invalid'),
                             ('index', 99)]:
            workload = self.fixture()
            workload['sessions'][0][field] = value
            invalid.append(workload)
        workload = self.fixture()
        workload['sessions'][0]['payload']['turns'].pop()
        invalid.append(workload)
        workload = self.fixture()
        workload['sessions'][0]['payload']['turns'][0]['question'] += ' changed'
        invalid.append(workload)
        workload = self.fixture()
        workload['sessions'][1]['payload'] = copy.deepcopy(workload['sessions'][0]['payload'])
        workload['sessions'][1]['payload_sha256'] = workload['sessions'][0]['payload_sha256']
        workload['payloads_sha256'] = bench.json_hash([item['payload'] for item in workload['sessions']])
        invalid.append(workload)
        for workload in invalid:
            with self.subTest(workload_type=type(workload).__name__), self.assertRaises(ValueError):
                mixed.validate_workload(workload)

    def test_malformed_mixed_plans_are_rejected(self):
        good = {'phase': 'serial_first_use', 'clients': 1, 'indices': [0]}
        invalid = [None, [], {}, 'plan', [None], [1], [dict(good, phase='unapproved')],
            [dict(good, clients=True)], [dict(good, clients=0)], [dict(good, clients=17)],
            [dict(good, indices=[])], [dict(good, indices=[-1])], [dict(good, indices=[16])],
            [dict(good, indices=[True])], [dict(good, indices=[0.0])],
            [dict(good, delay_ms=-1)], [dict(good, delay_ms=8501)],
            [dict(good, cancel='yes')], [dict(good, sustained='yes')],
            [dict(good)] * 65,
            [{'phase': 'sustained', 'clients': 1, 'indices': [0] * 129, 'sustained': True}],
            [{'phase': 'simultaneous_burst', 'clients': 2, 'indices': [0, 0]}],
            [{'phase': 'sustained', 'clients': 2, 'indices': [0, 1, 1, 0], 'sustained': True}],
        ]
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                mixed.validate_plan(plan)


class CatalogEvidenceIdentityTests(unittest.TestCase):
    def fixture(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for table in evidence.TABLE_NAMES:
            if table == 'card_rarity_correction':
                db.execute('CREATE TABLE card_rarity_correction(id TEXT,value TEXT,applied_at TEXT)')
                db.execute('INSERT INTO card_rarity_correction VALUES(?,?,?)',
                    ('one', 'rarity proof', '2026-01-01T00:00:00Z'))
            elif table == 'card_relationship_assertion':
                db.execute('CREATE TABLE card_relationship_assertion(id TEXT,value TEXT,asserted_by TEXT,review_status TEXT,asserted_at TEXT)')
                db.execute('INSERT INTO card_relationship_assertion VALUES(?,?,?,?,?)',
                    ('one', 'artwork proof', 'ai-artwork-review-v1', 'proposed', '2026-01-01T00:00:00Z'))
            else:
                db.execute('CREATE TABLE ' + table + '(id TEXT,value TEXT)')
                db.execute('INSERT INTO ' + table + ' VALUES(?,?)', ('one', 'proof 日本語'))
        for view in evidence.VIEW_NAMES:
            db.execute('CREATE VIEW ' + view + ' AS SELECT id,value FROM card')
        db.commit()
        return db

    def test_exact_reviewed_scope_has_five_views_and_twenty_tables(self):
        # Reviewed source has twenty, not twenty-two, evidence table names.
        self.assertEqual(evidence.SCHEMA, 'pokemon.collector-catalog-evidence.v2')
        self.assertEqual(evidence.VIEW_NAMES, ('active_card_metadata_evidence',
            'discovery_card_facet', 'base_discovery_card_facet',
            'active_source_correction_evidence', 'effective_card_reference'))
        self.assertEqual(evidence.TABLE_NAMES, ('card', 'card_facet', 'card_classification',
            'catalog_set_localized', 'catalog_vocabulary', 'character_family',
            'character_family_member', 'catalog_collector_evidence', 'supported_card',
            'card_reference', 'card_rarity_correction', 'catalog_release_evidence',
            'card_metadata_evidence', 'coordinate_family_evidence',
            'card_relationship_assertion', 'printing_source_evidence',
            'source_correction_evidence', 'card_number_reading_evidence',
            'source_image_fact_evidence', 'source_mechanic_binding'))

    def test_canonical_evidence_stream_exactly_matches_reviewed_revision(self):
        db = self.fixture()
        db.row_factory = sqlite3.Row
        updates, source_reads = [], []
        real_sha256 = hashlib.sha256
        class RecordingHash:
            def __init__(self, seed):
                self.seed = seed
            def update(self, value):
                updates.append(value)
            def hexdigest(self):
                return '0' * 64
        def source_stub(path):
            source_reads.append(path)
            return b'ignored-runtime-source-bytes'
        with patch.object(collector_journey.hashlib, 'sha256', RecordingHash), \
             patch.object(Path, 'read_bytes', source_stub):
            collector_journey.catalog_revision(db)
        # Production prefixes each source read with its file name. Keep the
        # exact remaining evidence stream, with the explicit stronger v2 schema
        # binding prepended independently of runtime source bytes.
        self.assertGreater(len(source_reads), 0)
        expected = real_sha256(evidence.SCHEMA.encode())
        expected.update(evidence.encoded_schema_record(db))
        for value in updates[2 * len(source_reads):]:
            expected.update(value)
        self.assertEqual(evidence.catalog_evidence_digest(db), expected.hexdigest())

    def test_only_documented_build_bookkeeping_changes_preserve_identity(self):
        db = self.fixture()
        before = evidence.catalog_evidence_digest(db)
        db.execute("UPDATE card_rarity_correction SET applied_at='2026-10-04T10:00:00Z'")
        self.assertEqual(evidence.catalog_evidence_digest(db), before)
        db.execute("UPDATE card_relationship_assertion SET asserted_at='2026-10-04T12:30:00+02:30'")
        self.assertEqual(evidence.catalog_evidence_digest(db), before)
        self.assertRegex(before, '^[a-f0-9]{64}$')

    def test_collation_and_column_type_changes_cannot_collide_with_identical_rows(self):
        results=[]
        for declaration in ('TEXT COLLATE BINARY','TEXT COLLATE NOCASE','BLOB COLLATE BINARY'):
            db=sqlite3.connect(':memory:');self.addCleanup(db.close)
            db.execute('CREATE TABLE card(card_id '+declaration+',value TEXT)')
            db.execute("INSERT INTO card VALUES('Example-ID','identical')")
            results.append((evidence.catalog_evidence_digest(db),
                db.execute("SELECT count(*) FROM card WHERE card_id='example-id'").fetchone()[0]))
        self.assertEqual([row[1] for row in results],[0,1,0])
        self.assertEqual(len({row[0] for row in results}),3)

    def test_indexes_triggers_and_intermediate_views_are_bound(self):
        for statement in (
            'CREATE INDEX semantic_index ON card(value COLLATE NOCASE)',
            'CREATE VIEW intermediate_source_view AS SELECT id,value FROM card',
            "CREATE TRIGGER semantic_trigger AFTER UPDATE ON card BEGIN SELECT 1; END",
        ):
            with self.subTest(statement=statement):
                db=self.fixture();before=evidence.catalog_evidence_digest(db)
                db.execute(statement)
                self.assertNotEqual(evidence.catalog_evidence_digest(db),before)
        db=self.fixture()
        db.execute('CREATE VIEW intermediate_source_view AS SELECT id,value FROM card')
        before=evidence.catalog_evidence_digest(db)
        db.execute('DROP VIEW intermediate_source_view')
        db.execute('CREATE VIEW intermediate_source_view AS SELECT id,value FROM card WHERE 0')
        self.assertNotEqual(evidence.catalog_evidence_digest(db),before)

    def test_encoding_application_id_and_user_version_are_bound(self):
        hashes=[]
        for encoding in ('UTF-8','UTF-16le'):
            db=sqlite3.connect(':memory:');self.addCleanup(db.close)
            db.execute("PRAGMA encoding='"+encoding+"'")
            db.execute('CREATE TABLE card(id TEXT,value TEXT)')
            db.execute("INSERT INTO card VALUES('one','日本語')")
            hashes.append(evidence.catalog_evidence_digest(db))
        self.assertNotEqual(*hashes)
        for pragma in ('application_id','user_version'):
            db=self.fixture();before=evidence.catalog_evidence_digest(db)
            db.execute('PRAGMA '+pragma+'=42')
            self.assertNotEqual(evidence.catalog_evidence_digest(db),before)

    def test_every_evidence_table_and_view_definition_is_bound(self):
        db = self.fixture()
        before = evidence.catalog_evidence_digest(db)
        for table in evidence.TABLE_NAMES:
            with self.subTest(table=table):
                db.execute('SAVEPOINT evidence_change')
                db.execute('UPDATE ' + table + " SET value='genuine changed evidence'")
                self.assertNotEqual(evidence.catalog_evidence_digest(db), before)
                db.execute('ROLLBACK TO evidence_change')
                db.execute('RELEASE evidence_change')
                self.assertEqual(evidence.catalog_evidence_digest(db), before)
        for view in evidence.VIEW_NAMES:
            with self.subTest(view=view):
                db.execute('SAVEPOINT view_change')
                db.execute('DROP VIEW ' + view)
                db.execute('CREATE VIEW ' + view + " AS SELECT id,value FROM card WHERE id <> 'excluded'")
                self.assertNotEqual(evidence.catalog_evidence_digest(db), before)
                db.execute('ROLLBACK TO view_change')
                db.execute('RELEASE view_change')

    def test_other_assertion_timestamps_and_review_content_remain_bound(self):
        db = self.fixture()
        for actor, status in [('human-reviewer', 'proposed'),
                              ('ai-artwork-review-v1', 'approved')]:
            db.execute('UPDATE card_relationship_assertion SET asserted_by=?,review_status=?,asserted_at=?',
                (actor, status, '2026-01-01T00:00:00Z'))
            before = evidence.catalog_evidence_digest(db)
            db.execute("UPDATE card_relationship_assertion SET asserted_at='2026-10-04T00:00:00Z'")
            self.assertNotEqual(evidence.catalog_evidence_digest(db), before)
        db.execute("UPDATE card_relationship_assertion SET asserted_by='ai-artwork-review-v1',review_status='proposed'")
        before = evidence.catalog_evidence_digest(db)
        db.execute("UPDATE card_relationship_assertion SET value='review time or evidence changed'")
        self.assertNotEqual(evidence.catalog_evidence_digest(db), before)

    def test_normalized_timestamp_validity_matches_reviewed_parser(self):
        db = self.fixture()
        values = ['2026-01-01T00:00:00Z', '2026-01-01T00:00:00+00:00',
            '2026-01-01T01:30:00+01:30', '20260101T000000+0000',
            '2026-01-01', '2026-01-01T00:00:00', 'invalid', '', None]
        for value in values:
            with self.subTest(timestamp=value):
                db.execute('UPDATE card_relationship_assertion SET asserted_at=?', (value,))
                try:
                    core.parse_time(value)
                except Exception as error:
                    with self.assertRaises(type(error)):
                        evidence.catalog_evidence_digest(db)
                else:
                    self.assertRegex(evidence.catalog_evidence_digest(db), '^[a-f0-9]{64}$')

    def test_no_source_reads_or_database_writes_or_row_factory_changes(self):
        db = self.fixture()
        before = evidence.catalog_evidence_digest(db)
        original_factory, changes = db.row_factory, db.total_changes
        queries = []
        db.set_trace_callback(queries.append)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('source bytes read')), \
             patch.object(Path, 'read_text', side_effect=AssertionError('source text read')), \
             patch('builtins.open', side_effect=AssertionError('source file opened')):
            self.assertEqual(evidence.catalog_evidence_digest(db), before)
        self.assertEqual(db.total_changes, changes)
        self.assertIs(db.row_factory, original_factory)
        self.assertTrue(all(query.startswith(('SELECT ', 'PRAGMA table_info(')) or query in
            {'PRAGMA main.encoding','PRAGMA main.application_id','PRAGMA main.user_version'} for query in queries))
        db.row_factory = sqlite3.Row
        self.assertEqual(evidence.catalog_evidence_digest(db), before)

    def test_source_only_changes_do_not_affect_evidence_digest(self):
        db = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'collector_journey.py'
            source.write_text('POLICY = "before"\n')
            before = evidence.catalog_evidence_digest(db)
            source.write_text('POLICY = "different runtime only"\n')
            self.assertEqual(evidence.catalog_evidence_digest(db), before)

    def test_row_insertion_order_and_unrelated_state_do_not_change_identity(self):
        db = self.fixture()
        db.execute("INSERT INTO card VALUES('two','second evidence')")
        before = evidence.catalog_evidence_digest(db)
        rows = db.execute('SELECT * FROM card ORDER BY id DESC').fetchall()
        db.execute('DELETE FROM card')
        db.executemany('INSERT INTO card VALUES(?,?)', rows)
        self.assertEqual(evidence.catalog_evidence_digest(db),before)
        db.execute('CREATE TABLE unrelated_conversation(turn TEXT)')
        schema_bound=evidence.catalog_evidence_digest(db)
        self.assertNotEqual(schema_bound,before)
        db.execute("INSERT INTO unrelated_conversation VALUES('private transcript')")
        self.assertEqual(evidence.catalog_evidence_digest(db),schema_bound)


class MixedMemoryEvidenceTests(unittest.TestCase):
    def test_unobserved_node_memory_is_unknown_instead_of_zero(self):
        observer = mixed.MemoryObserver()
        observer.samples = [(12, 0, 12, False)]
        result = observer.report()
        self.assertEqual(result['samples'], 1)
        self.assertEqual(result['node_samples'], 0)
        self.assertEqual(result['sampled_python_rss_max_mib'], 12)
        self.assertIsNone(result['sampled_node_rss_max_mib'])
        self.assertIsNone(result['sampled_combined_rss_max_mib'])

    def test_combined_rss_is_observed_sum_not_sum_of_independent_peaks(self):
        observer = mixed.MemoryObserver()
        observer.samples = [(10, 100, 110, True), (100, 10, 110, True)]
        result = observer.report()
        self.assertEqual(result['sampled_python_rss_max_mib'], 100)
        self.assertEqual(result['sampled_node_rss_max_mib'], 100)
        self.assertEqual(result['sampled_combined_rss_max_mib'], 110)

    def test_child_peak_normalizes_units_and_discloses_unknown_platform(self):
        observer = mixed.MemoryObserver()
        with patch.object(mixed.resource, 'getrusage', return_value=SimpleNamespace(ru_maxrss=1048576)):
            for platform, expected in [('darwin', 1), ('linux', 1024), ('unknown', None)]:
                with self.subTest(platform=platform), patch.object(mixed.sys, 'platform', platform):
                    self.assertEqual(observer.report()['node_children_ru_maxrss_mib'], expected)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the actual mixed caller')
class ActualMixedCallerTests(unittest.TestCase):
    def test_normalizer_preserves_user_state_and_closed_authority(self):
        original = {'catalog_revision': 'old', 'expected_revision': 'old',
            'preferences': {'x': 1}, 'purchase_ready': False,
            'trace': [{'card_id': 'test', 'selected_card_id': None}],
            'resume': {'expected_revision': 'old', 'max_turns': 20}}
        script = "const {normalized}=require(process.argv[1]);process.stdout.write(JSON.stringify(normalized(JSON.parse(process.argv[2]))));"
        result = subprocess.run(['node', '-e', script, str(MIXED_RUNNER), json.dumps(original)],
            capture_output=True, text=True, check=True, timeout=3)
        self.assertEqual(json.loads(result.stdout), normalized(original))

    def test_node_plan_validator_rejects_malformed_and_coalescing_plans(self):
        good = {'phase': 'serial_first_use', 'clients': 1, 'indices': [0]}
        invalid = [None, [], {}, [None], [dict(good, phase='unapproved')],
            [dict(good, clients=True)], [dict(good, clients=0)], [dict(good, clients=17)],
            [dict(good, indices=[])], [dict(good, indices=[-1])], [dict(good, indices=[16])],
            [dict(good, indices=[True])], [dict(good, delay_ms=-1)],
            [dict(good, delay_ms=8501)], [dict(good, delay_ms=None)],
            [dict(good, cancel='yes')], [dict(good, sustained='yes')],
            [dict(good, unknown='ignored?')], [dict(good)] * 65,
            [{'phase': 'sustained', 'clients': 1, 'indices': [0] * 129, 'sustained': True}],
            [{'phase': 'simultaneous_burst', 'clients': 2, 'indices': [0, 0]}],
            [{'phase': 'sustained', 'clients': 2, 'indices': [0, 1, 1, 0], 'sustained': True}]]
        script = """const fs=require('node:fs');const {validatePlan}=require(process.argv[1]);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(plan=>{try{validatePlan(plan);return true;}catch{return false;}})));"""
        result = subprocess.run(['node', '-e', script, str(MIXED_RUNNER)],
            input=json.dumps([mixed.plan(), [good]] + invalid), capture_output=True,
            text=True, check=True, timeout=3)
        accepted = json.loads(result.stdout)
        self.assertEqual(accepted[:2], [True, True])
        for case, value in zip(invalid, accepted[2:]):
            with self.subTest(case=case):
                self.assertFalse(value, 'Node accepted an invalid mixed execution plan')

    def synthetic_workload(self, path):
        with closing(core.connect(path)) as db:
            core.init_db(db)
            for index in range(120):
                card_id = f'en:FX1:{index + 1}/120:normal'
                source = 'synthetic:mixed-caller-smoke'
                db.execute('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (card_id, 'en', 'FX1', f'{index + 1}/120', 'normal', 'Pikachu',
                     None, source, source, 0, 1, '{}'))
                for facet, value in [('illustrator', 'Fixture Artist'), ('dex_id', '25')]:
                    db.execute('INSERT INTO card_facet VALUES(?,?,?,?,?)', (card_id, facet, value, source, source))
            db.commit()
        sessions = []
        with closing(core.connect(path, readonly=True)) as db:
            revision = collector_journey.catalog_revision(db)
            logical_evidence = evidence.catalog_evidence_digest(db)
            for index in range(16):
                axis = {'inventory_question': 'Cards by Fixture Artist',
                    'profile': {'preferred_illustrators': ['Fixture Artist'],
                        'subjective_notes': [f'synthetic smoke session {index}']}}
                payload = bench.make_workload(axis, revision)['variants']['a']
                result = collector_journey.replay(db, copy.deepcopy(payload), revision=revision)
                self.assertEqual(result['turn_count'], 20)
                sessions.append({'index': index, 'name': f'smoke_{index:02d}',
                    'pattern': 'synthetic_twenty_turn_pages', 'language': 'en',
                    'payload': payload, 'payload_sha256': bench.json_hash(payload),
                    'expected_result_semantic_sha256': bench.json_hash(normalized(result))})
        return {'schema': 'pokemon.collector-mixed-workload.v1',
            'catalog_sha256': bench.file_hash(path), 'catalog_revision': revision,
            'catalog_evidence': {'schema': evidence.SCHEMA, 'sha256': logical_evidence},
            'sessions': sessions, 'payloads_sha256': bench.json_hash([item['payload'] for item in sessions])}

    def test_actual_http_run_rejects_changed_or_missing_consumed_workload_file(self):
        # Fresh-process rule is retained; this is a real one-request HTTP smoke.
        script = r"""
import importlib.util,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);path=pathlib.Path(sys.argv[3])
spec=importlib.util.spec_from_file_location('mixed_mutation_probe',root/'scripts/benchmark_collector_mixed.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=module.bench.run_node
raw=path.read_bytes()
def changed(*args,**kwargs):
    if sys.argv[5]=='delete':path.unlink()
    else:path.write_bytes(raw+b'\n')
    return original(*args,**kwargs)
module.bench.run_node=changed
result=module.benchmark(sys.argv[2],repo_root=root,workload_path=path,
    journal_path=sys.argv[4],execution_plan=[{'phase':'serial_first_use','clients':1,'indices':[0]}])
print(json.dumps(result))
"""
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);db=directory/'synthetic.sqlite3'
            workload=self.synthetic_workload(db);raw=json.dumps(workload).encode()
            for mutation in ('append','delete'):
                with self.subTest(mutation=mutation):
                    path=directory/(mutation+'.json');path.write_bytes(raw)
                    journal=directory/(mutation+'.journal.jsonl')
                    result=subprocess.run([sys.executable,'-c',script,str(ROOT),str(db),str(path),str(journal),mutation],
                        capture_output=True,text=True,timeout=25,check=True)
                    report=json.loads(result.stdout)
                    self.assertFalse(report['passed'])
                    self.assertFalse(report['checks']['workload_file_unchanged'])
                    self.assertTrue(report['checks']['runner_complete'])
                    self.assertEqual(report['totals']['completed'],1)
                    self.assertEqual(report['workload_file_sha256'],hashlib.sha256(raw).hexdigest())
                    self.assertEqual(report['workload_file_sha256_after'],
                        hashlib.sha256(raw+b'\n').hexdigest() if mutation=='append' else None)
                    self.assertGreater(journal.stat().st_size,0)

    def test_one_actual_http_case_uses_twenty_turns_and_unmodified_client_defaults(self):
        # An explicit one-call smoke verifies plumbing only, not real-catalog capacity.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.sqlite3'
            workload = self.synthetic_workload(path)
            before = bench.file_hash(path)
            workload_before = copy.deepcopy(workload)
            cases = [{'phase': 'serial_first_use', 'clients': 1, 'indices': [0]}]
            mixed.validate_plan(cases)
            with create_server(str(path), '127.0.0.1', 0, True) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = bench.run_node(f'http://127.0.0.1:{server.server_port}', workload,
                        repo_root=ROOT, local=True, scenarios={'plan': cases},
                        runner_path=MIXED_RUNNER, execution_plan=[('serial_first_use', 1)],
                        watchdog_seconds=8)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
            self.assertEqual(bench.file_hash(path), before)
        self.assertEqual(workload, workload_before)
        self.assertTrue(result['runner_complete'], result)
        self.assertEqual(result['request_accounting'], {'planned_requests': 1,
            'started_requests': 1, 'settled_requests': 1,
            'unsettled_requests': 0, 'not_started_requests': 0})
        self.assertEqual(result['client_limits'], {'attempt_timeout_ms': 10000,
            'maximum_attempts': 2, 'maximum_response_bytes': 8 * 1024 * 1024})
        rows = result['cases'][0]['results']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['category'], 'completed', row)
        self.assertEqual(row['turn_count'], 20)
        for check in ('input_unchanged', 'deterministic_match', 'session_integrity', 'gates_closed'):
            self.assertTrue(row[check], check)
        self.assertTrue(bench.current_diagnostics_complete(rows, 'current_required'))
        self.assertEqual(len(row['attempts']), 1)
        self.assertEqual(row['fetch_attempts'][-1]['http_status'], 200)
        self.assertNotIn('Authorization', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
