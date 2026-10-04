"""Benchmark receipts must preserve failures, exact work and real caller behavior."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pokemon_index import core
from scripts import benchmark_collector_caller as bench


class ReceiptTests(unittest.TestCase):
    def test_rss_units_are_normalized_without_claiming_unknown_platforms(self):
        with patch.object(bench.resource, 'getrusage', return_value=SimpleNamespace(ru_maxrss=1048576)):
            with patch.object(bench.sys, 'platform', 'darwin'):
                self.assertEqual(bench.peak_rss_mib(), 1)
            with patch.object(bench.sys, 'platform', 'linux'):
                self.assertEqual(bench.peak_rss_mib(), 1024)
            with patch.object(bench.sys, 'platform', 'unknown'):
                self.assertIsNone(bench.peak_rss_mib())

    def test_twenty_turn_workload_matches_existing_and_isolates_variants(self):
        axis = {'inventory_question': 'Cards by Fixture Artist', 'profile': {'preferred_illustrators': ['Fixture Artist']}}
        workload = bench.make_workload(axis, 'a' * 64)
        a, b = workload['variants']['a'], workload['variants']['b']
        self.assertEqual(len(a['turns']), 20)
        self.assertEqual(a['turns'][0], {'type': 'ask', 'question': 'Recommend Cards by Fixture Artist'})
        self.assertEqual([v['offset'] for v in a['turns'][2:]], list(range(5, 91, 5)))
        self.assertEqual(a['limit'], 5)
        self.assertEqual(b['turns'][-1]['offset'], 85)
        self.assertNotIn('subjective_notes', axis['profile'])
        self.assertNotEqual(bench.json_hash(a), bench.json_hash(b))

    def test_rejections_and_timeouts_stay_in_denominator(self):
        case = {'wall_ms': 1000, 'results': [
            {'category': 'completed', 'elapsed_ms': 900, 'fetch_attempts': [{'http_status': 200}]},
            {'category': 'explicit_rejection', 'elapsed_ms': 20, 'fetch_attempts': [{'http_status': 503}, {'http_status': 503}]},
            {'category': 'timeout', 'elapsed_ms': 20200, 'fetch_attempts': [{'http_status': None}]}]}
        counts = bench.summarize(case)
        self.assertEqual(counts['all_requests'], 3)
        self.assertEqual(counts['completed'], 1)
        self.assertEqual(counts['completion_fraction'], .333333)
        self.assertEqual(counts['completed_per_second'], 1)
        self.assertEqual(counts['http_attempts'], 4)
        self.assertEqual(counts['http_attempt_rejections'], 2)
        self.assertEqual(counts['all_request_latency_ms']['p95'], 20200)
        self.assertEqual(counts['completion_latency_ms']['p95'], 900)

    def test_remote_requires_current_matching_review(self):
        now = datetime.now(timezone.utc)
        review = {'base_url': 'https://revision.example.test', 'target_kind': 'immutable_revision_url',
            'revision_name': 'reviewed-revision', 'image_digest': 'sha256:' + 'b' * 64,
            'authorization_rechecked': True, 'inspected_at_utc': now.isoformat(), 'token': 'never-retain'}
        saved = bench.validate_remote_target(review['base_url'], review, now=now)
        self.assertNotIn('token', saved)
        for url in ('http://revision.example.test', 'https://user:secret@revision.example.test',
                    'https://revision.example.test?token=secret', 'https://revision.example.test/path'):
            with self.assertRaises(ValueError):
                bench.validate_remote_target(url, review, now=now)
        for patch in ({'authorization_rechecked': False}, {'target_kind': 'production_service'},
                      {'inspected_at_utc': (now - timedelta(hours=2)).isoformat()}):
            with self.assertRaises(ValueError):
                bench.validate_remote_target(review['base_url'], {**review, **patch}, now=now)

    def test_source_receipt_changes_with_client_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pokemon_index').mkdir()
            (root / 'pokemon_index/a.py').write_text('a = 1\n')
            client = root / 'integrations/pivota/collectorClient.cjs'
            client.parent.mkdir(parents=True)
            client.write_text('original')
            before = bench.source_receipt(root)
            client.write_text('changed')
            after = bench.source_receipt(root)
            self.assertNotEqual(before['sha256'], after['sha256'])
            self.assertEqual(set(before['files']), {'pokemon_index/a.py', 'integrations/pivota/collectorClient.cjs'})

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the actual caller benchmark')
    def test_native_diagnostic_sanitizer_drops_sensitive_fields(self):
        script = """const {safeEvent} = require(process.argv[1]);
const event = safeEvent({schema:'pokemon.collector-attempt.v1', attempt:1, outcome:'error', phase:'fetch',
  error_class:'catalog_timeout', duration_ms:10, request_id:'a'.repeat(32),
  server_timing_ms:{receive:1,queue:2,compute:3,token:'secret'},
  token:'secret', authorization:'secret', body:'secret', url:'https://secret.test'});
process.stdout.write(JSON.stringify(event));"""
        result = subprocess.run(['node', '-e', script, str(bench.RUNNER)], text=True, capture_output=True, check=True)
        self.assertNotIn('secret', result.stdout)
        out = json.loads(result.stdout)
        self.assertEqual(out['error_class'], 'catalog_timeout')
        self.assertEqual(out['server_timing_ms'], {'receive': 1, 'queue': 2, 'compute': 3})


class RemoteGuardTests(unittest.TestCase):
    def review(self):
        return {'base_url': 'https://revision.example.test', 'target_kind': 'immutable_revision_url',
            'revision_name': 'reviewed-revision', 'image_digest': 'sha256:' + 'b' * 64,
            'authorization_rechecked': True, 'inspected_at_utc': datetime.now(timezone.utc).isoformat(),
            'catalog_revision': 'a' * 64}

    def record(self):
        return {'operator_asserted_source_sha': 'c' * 40, 'image': 'sha256:' + 'b' * 64,
            'expected_catalog_revision': 'a' * 64,
            'baseline': {'settings_sha256': 'd' * 64, 'iam_sha256': 'e' * 64, 'traffic': {'old': 100},
                'runtime': {'container_concurrency': 16, 'timeout_seconds': 30, 'max_instances': '1',
                    'resources': {'limits': {'cpu': '1000m', 'memory': '512Mi'}}}}}

    def test_fresh_inspector_requires_matching_identity_and_fixed_runtime(self):
        from scripts import stage_existing_cloud_run as stage
        review = self.review()
        record = self.record()
        with patch.object(stage, 'load', return_value=record), patch.object(stage, 'candidate',
                return_value=('reviewed-revision', review['base_url'])) as inspect:
            result = bench.inspect_remote_target(review['base_url'], review, 'receipt.json', 'c' * 40)
            self.assertEqual(result['runtime']['memory'], '512Mi')
            inspect.assert_called_once_with(record)
        record['baseline']['runtime']['resources']['limits']['memory'] = '1Gi'
        with patch.object(stage, 'load', return_value=record), patch.object(stage, 'candidate') as inspect:
            with self.assertRaises(ValueError):
                bench.inspect_remote_target(review['base_url'], review, 'receipt.json', 'c' * 40)
            inspect.assert_not_called()
        record = self.record()
        with patch.object(stage, 'load', return_value=record), patch.object(stage, 'candidate',
                return_value=('different-revision', review['base_url'])):
            with self.assertRaises(ValueError):
                bench.inspect_remote_target(review['base_url'], review, 'receipt.json', 'c' * 40)
        with patch.object(stage, 'load', return_value=record), patch.object(stage, 'candidate') as inspect:
            with self.assertRaises(ValueError):
                bench.inspect_remote_target(review['base_url'], review, 'receipt.json', 'f' * 40)
            inspect.assert_not_called()

    def _benchmark(self, path):
        return bench.benchmark(path, base_url=self.review()['base_url'], target_review=self.review(),
            rollout_receipt='receipt.json', expected_source_sha='c' * 40, token='operator-test-token')

    def test_preflight_conflict_stops_before_token_transmission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.sqlite3'
            with closing(core.connect(path)) as db: core.init_db(db)
            imports = (core, SimpleNamespace(catalog_revision=lambda db: 'a' * 64), None,
                lambda db: {'inventory_question': 'Cards by Fixture Artist', 'profile': {}})
            with patch.object(bench, '_imports', return_value=imports), patch.object(bench,
                    'inspect_remote_target', side_effect=ValueError('changed')), patch.object(bench, 'run_node') as node:
                with self.assertRaises(ValueError): self._benchmark(path)
                node.assert_not_called()

    def test_after_inspection_runs_when_node_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.sqlite3'
            with closing(core.connect(path)) as db: core.init_db(db)
            imports = (core, SimpleNamespace(catalog_revision=lambda db: 'a' * 64), None,
                lambda db: {'inventory_question': 'Cards by Fixture Artist', 'profile': {}})
            with patch.object(bench, '_imports', return_value=imports), patch.object(bench,
                    'inspect_remote_target', return_value={'state': 'fixed'}) as inspect, patch.object(bench,
                    'run_node', side_effect=RuntimeError('runner failed')):
                with self.assertRaises(RuntimeError): self._benchmark(path)
                self.assertEqual(inspect.call_count, 2)

    def test_postflight_conflict_preserves_caller_results_and_fails(self):
        row = {'category': 'completed', 'elapsed_ms': 1, 'fetch_attempts': [], 'attempts': [],
            'input_unchanged': True, 'gates_closed': True, 'session_integrity': True,
            'turn_count': 20, 'exercised_pool_records': 1, 'deterministic_match': True}
        caller = {'cases': [{'phase': phase, 'wall_ms': 1, 'results': [row]}
            for phase in ['serial_first_use', 'immediate_recovery', 'cross_session_integrity']]
            + [{'phase': 'cross_session_recovery', 'wall_ms': 2, 'results': [row, row]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.sqlite3'
            with closing(core.connect(path)) as db: core.init_db(db)
            imports = (core, SimpleNamespace(catalog_revision=lambda db: 'a' * 64), None,
                lambda db: {'inventory_question': 'Cards by Fixture Artist', 'profile': {}})
            with (patch.object(bench, '_imports', return_value=imports), patch.object(bench,
                    'inspect_remote_target', side_effect=[{'state': 'fixed'}, ValueError('changed')]) as inspect,
                    patch.object(bench, 'run_node', return_value=caller)):
                report = self._benchmark(path)
            self.assertEqual(inspect.call_count, 2)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['remote_state_unchanged'])
            self.assertEqual(report['totals']['all_requests'], 5)
            self.assertEqual(report['caller']['cases'][0]['results'][0]['elapsed_ms'], 1)
            self.assertNotIn('operator-test-token', json.dumps(report))


@unittest.skipUnless(shutil.which('node'), 'Node is required for the actual caller benchmark')
class ActualCallerTests(unittest.TestCase):
    def test_small_actual_http_run_keeps_workload_sessions_and_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.sqlite3'
            with closing(core.connect(path)) as db:
                core.init_db(db)
                for index in range(120):
                    cid = f'en:FX1:{index + 1}/120:normal'
                    source = 'synthetic:caller-benchmark-test'
                    db.execute('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid, 'en', 'FX1', f'{index + 1}/120', 'normal', 'Pikachu', None, source, source, 0, 1, '{}'))
                    db.execute('INSERT INTO card_facet VALUES(?,?,?,?,?)', (cid, 'illustrator', 'Fixture Artist', source, source))
                    db.execute('INSERT INTO card_facet VALUES(?,?,?,?,?)', (cid, 'dex_id', '25', source, source))
                db.commit()
            before = bench.file_hash(path)
            report = bench.benchmark(path, fixture_label='synthetic', scenarios={
                'bursts': [2], 'sustainedConcurrency': 2, 'sustainedRequests': 2,
                'recoveryDelayMs': 1, 'cancellationRecoveryWaitMs': 1, 'integrityConcurrency': 2})
            self.assertTrue(report['passed'], report['checks'])
            self.assertEqual(bench.file_hash(path), before)
            self.assertTrue(report['checks']['all_completed_requests_valid'])
            self.assertTrue(report['checks']['all_inputs_unchanged'])
            self.assertTrue(report['checks']['recommendation_recovery_completed'])
            self.assertTrue(report['checks']['cross_session_recovery_completed_and_isolated'])
            self.assertEqual(len(report['workload']['variants']['a']['turns']), 20)
            cases = report['caller']['cases']
            self.assertTrue(any(case['phase'] == 'sustained' for case in cases))
            self.assertTrue(any(case['phase'] == 'immediate_recovery' for case in cases))
            self.assertTrue(any(case['phase'] == 'post_burst_recovery' for case in cases))
            self.assertEqual(report['totals']['all_requests'], sum(len(case['results']) for case in cases))
            for case in cases:
                self.assertEqual(case['counts']['all_requests'], len(case['results']))
                for row in case['results']:
                    self.assertLessEqual(len(row['fetch_attempts']), 2)
                    if row['category'] == 'completed':
                        self.assertEqual(row['fetch_attempts'][-1]['http_status'], 200)
                        self.assertTrue(row['fetch_attempts'][-1]['body_complete'])
                        self.assertGreater(row['fetch_attempts'][-1]['body_bytes'], 0)
                        self.assertTrue(row['session_integrity'])
            self.assertNotIn('Authorization', json.dumps(report))


@unittest.skipUnless(shutil.which('node'), 'Node is required for journal regressions')
class DurableCallerJournalTests(unittest.TestCase):
    scenarios = {'bursts': [2], 'sustainedConcurrency': 2, 'sustainedRequests': 2,
        'recoveryDelayMs': 1, 'cancellationRecoveryWaitMs': 1, 'integrityConcurrency': 2}

    def fixture(self, directory):
        path = Path(directory) / 'catalog.sqlite3'
        with closing(core.connect(path)) as db:
            core.init_db(db)
            for i in range(120):
                cid = f'en:FX1:{i + 1}/120:normal'; source = 'synthetic:journal-test'
                db.execute('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (cid, 'en', 'FX1', f'{i + 1}/120', 'normal', 'Pikachu', None, source, source, 0, 1, '{}'))
                for facet, value in [('illustrator', 'Fixture Artist'), ('dex_id', '25')]:
                    db.execute('INSERT INTO card_facet VALUES(?,?,?,?,?)', (cid, facet, value, source, source))
            db.commit()
        return path

    def runner(self, directory, behavior):
        root = Path(directory)
        client = root / 'wrapped-client.cjs'
        real = str(bench.ROOT / 'integrations/pivota/collectorClient.cjs')
        client.write_text(('const real = require(' + json.dumps(real) + ');' + behavior).replace('\\n', '\n'))
        runner = root / 'runner.cjs'
        runner.write_text("const fs=require('node:fs'); const {runBenchmark}=require(" + json.dumps(str(bench.RUNNER)) + ");\n"
            + "const input=JSON.parse(fs.readFileSync(0,'utf8')); input.clientPath=" + json.dumps(str(client)) + ";\n"
            + "const emit = event => process.stdout.write(JSON.stringify({schema:'pokemon.collector-journal.v1',...event})+'\\n');\n"
            + "runBenchmark(input, emit).then(r=>emit({event:'run_completed',node_version:r.node_version,client_mode:r.client_mode,native_attempt_diagnostics:r.native_attempt_diagnostics,cancellation_support:r.cancellation_support}))"
            + ".catch(()=>{process.stderr.write('private-error-canary');process.exitCode=1;});\n")
        return runner

    def test_missing_native_diagnostics_cannot_pass_current_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory)
            runner = self.runner(directory,
                "exports.createCollectorClient = options => real.createCollectorClient({...options,onAttempt:undefined});\n")
            journal = Path(directory) / 'strict.journal.jsonl'
            with patch.object(bench, 'RUNNER', runner):
                report = bench.benchmark(path, fixture_label='synthetic', scenarios=self.scenarios, journal_path=journal)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks']['required_current_diagnostics_complete'])
            self.assertTrue(report['checks']['required_cancellation_exercised'])
            self.assertEqual(report['totals']['planned_requests'], 18)
            self.assertEqual(report['totals']['settled_requests'], 18)
            self.assertFalse(report['partial_receipt'])
            self.assertIn('receipt_marker', journal.read_text())

    def test_legacy_compatibility_is_explicit_and_skips_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory)
            runner = self.runner(directory,
                "exports.createCollectorClient = options => real.createCollectorClient({...options,onAttempt:undefined});\n")
            with patch.object(bench, 'RUNNER', runner):
                report = bench.benchmark(path, fixture_label='synthetic', scenarios=self.scenarios,
                    client_mode='legacy_baseline')
            self.assertTrue(report['passed'], report['checks'])
            self.assertEqual(report['client_mode'], 'legacy_baseline')
            self.assertEqual(report['caller']['cancellation_support'], 'explicitly_skipped_legacy_baseline')
            self.assertEqual(report['totals']['all_requests'], 15)

    def test_ignored_cancellation_cannot_pass_current_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory)
            runner = self.runner(directory,
                "exports.createCollectorClient = options => { const c=real.createCollectorClient(options);"
                "return {advance: input => c.advance({...input,signal:undefined})}; };\n")
            with patch.object(bench, 'RUNNER', runner):
                report = bench.benchmark(path, fixture_label='synthetic', scenarios=self.scenarios)
            self.assertFalse(report['passed'])
            self.assertTrue(report['checks']['required_current_diagnostics_complete'])
            self.assertFalse(report['checks']['cancelled_calls_do_not_retry'])
            cancellation = next(case for case in report['caller']['cases'] if case['phase'] == 'external_cancellation')
            self.assertEqual(cancellation['results'][0]['category'], 'completed')

    def test_hang_after_real_result_preserves_partial_denominators_and_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory)
            runner = self.runner(directory,
                "let calls=0; exports.createCollectorClient = options => {"
                "const notify=options.onAttempt; const c=real.createCollectorClient({...options,onAttempt:e=>notify?.({...e,token:'private-token-canary',url:'https://private-url-canary.test',payload:'private-payload-canary'})});"
                "return {advance: input => {if(++calls===2){process.stderr.write('private-error-canary');setInterval(()=>{},1000);return new Promise(()=>{});}return c.advance(input);}};};\n")
            journal = Path(directory) / 'partial.journal.jsonl'
            with patch.object(bench, 'RUNNER', runner):
                report = bench.benchmark(path, fixture_label='synthetic', scenarios=self.scenarios,
                    journal_path=journal, watchdog_seconds=1.5)
            self.assertFalse(report['passed']); self.assertTrue(report['partial_receipt'])
            self.assertEqual(report['caller']['cancellation_support'], 'required_but_not_exercised')
            self.assertEqual(report['caller']['runner_failure_code'], 'node_watchdog_timeout')
            self.assertRegex(report['caller']['node_version'], r'^v[0-9]+\.[0-9]+\.[0-9]+$')
            self.assertEqual(report['totals']['planned_requests'], 18)
            self.assertEqual(report['totals']['started_requests'], 2)
            self.assertEqual(report['totals']['settled_requests'], 1)
            self.assertEqual(report['totals']['unsettled_requests'], 1)
            self.assertEqual(report['totals']['not_started_requests'], 16)
            self.assertEqual(report['totals']['completed'], 1)
            first = report['caller']['cases'][0]['results'][0]
            self.assertEqual(first['fetch_attempts'][0]['http_status'], 200)
            self.assertEqual(len(first['attempts']), 1)
            raw = journal.read_text()
            events = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual(events[-1]['completion'], 'partial')
            self.assertTrue(any(e.get('attempt', {}).get('body_read_started') for e in events))
            self.assertTrue(any(e.get('attempt', {}).get('cancel_requested') for e in events))
            for text in [raw, json.dumps(report)]:
                for secret in ['private-token-canary','private-url-canary','private-payload-canary','private-error-canary','Authorization']:
                    self.assertNotIn(secret, text)
            self.assertNotIn('127.0.0.1', raw); self.assertNotIn('turns', raw)

    def test_watchdog_covers_runner_that_never_reads_large_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory) / 'no-input.cjs'
            runner.write_text('setInterval(() => {}, 1000);')
            journal = Path(directory) / 'no-input.journal.jsonl'
            workload = {'private_payload': 'private-input-canary' + 'x' * 262144}
            with patch.object(bench, 'RUNNER', runner):
                result = bench.run_node('http://127.0.0.1:1', workload, repo_root=bench.ROOT,
                    local=True, scenarios=self.scenarios, journal_path=journal, watchdog_seconds=.2)
            self.assertEqual(result['runner_failure_code'], 'node_watchdog_timeout')
            self.assertEqual(result['request_accounting']['started_requests'], 0)
            self.assertEqual(result['request_accounting']['not_started_requests'], 18)
            self.assertNotIn('private-input-canary', journal.read_text())
            self.assertEqual(json.loads(journal.read_text().splitlines()[-1])['completion'], 'partial')

    def test_premature_completion_cannot_omit_required_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory) / 'premature.cjs'
            runner.write_text("process.stdin.resume();process.stdin.on('end',()=>process.stdout.write(JSON.stringify({schema:'pokemon.collector-journal.v1',event:'run_completed'})+'\\n'));")
            with patch.object(bench, 'RUNNER', runner):
                result = bench.run_node('http://127.0.0.1:1', {}, repo_root=bench.ROOT,
                    local=True, scenarios=self.scenarios, watchdog_seconds=1)
            self.assertFalse(result['runner_complete'])
            self.assertEqual(result['request_accounting']['not_started_requests'], 18)
            self.assertEqual(result['runner_failure_code'], 'node_protocol_or_runner_failed')

    def test_journal_overflow_retains_partial_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(directory)
            journal = Path(directory) / 'bounded.journal.jsonl'
            with patch.object(bench, 'MAX_JOURNAL_EVENTS', 8):
                report = bench.benchmark(path, fixture_label='synthetic', scenarios=self.scenarios, journal_path=journal)
            self.assertFalse(report['passed'])
            self.assertTrue(report['partial_receipt'])
            events = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertLessEqual(len(events), 8)
            self.assertEqual(events[-1]['event'], 'receipt_marker')


if __name__ == '__main__':
    unittest.main()
