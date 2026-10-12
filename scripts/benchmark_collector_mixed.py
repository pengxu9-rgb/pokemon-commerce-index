"""Bounded distinct-session actual Node/HTTP profile on a read-only catalog.

Run from a fresh process. Overload remains unsuccessful work in every capacity
fraction. A custom small plan is intended for deterministic smoke tests only.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'integrations/pivota/benchmarkCollectorMixedCaller.cjs'
_spec = importlib.util.spec_from_file_location('collector_mixed_reviewed_journal', ROOT / 'scripts/benchmark_collector_caller.py')
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)
SCHEMA = 'pokemon.collector-mixed-capacity.v1'
_evidence_spec = importlib.util.spec_from_file_location('collector_mixed_catalog_evidence', ROOT / 'scripts/collector_catalog_evidence.py')
catalog_evidence = importlib.util.module_from_spec(_evidence_spec)
_evidence_spec.loader.exec_module(catalog_evidence)


def plan():
    rows = [{'phase': 'serial_first_use' if i == 0 else 'serial_control_b', 'clients': 1, 'indices': [i]} for i in range(16)]
    for count in (2, 4, 16):
        indices = {2: [0, 4], 4: [0, 4, 8, 12], 16: list(range(16))}[count]
        rows.append({'phase': 'simultaneous_burst', 'clients': count, 'indices': indices, 'label': f'burst_{count}'})
        rows.extend([
            {'phase': 'immediate_recovery', 'clients': 1, 'indices': [(count + 3) % 16], 'after': f'burst_{count}'},
            {'phase': 'post_burst_recovery', 'clients': 1, 'indices': [(count + 8) % 16], 'after': f'burst_{count}', 'delay_ms': 1000},
        ])
    rows.append({'phase': 'sustained', 'clients': 4, 'indices': list(range(16)) * 2, 'sustained': True})
    rows.extend([
        {'phase': 'immediate_recovery', 'clients': 1, 'indices': [7], 'after': 'sustained'},
        {'phase': 'post_burst_recovery', 'clients': 1, 'indices': [11], 'after': 'sustained', 'delay_ms': 1000},
    ])
    rows.extend({'phase': 'cross_session_recovery', 'clients': 1, 'indices': [i]} for i in range(16))
    rows.extend([
        {'phase': 'external_cancellation', 'clients': 1, 'indices': [0], 'cancel': True},
        {'phase': 'immediate_recovery', 'clients': 1, 'indices': [2], 'after': 'external_cancellation'},
        {'phase': 'post_cancel_deadline_recovery', 'clients': 1, 'indices': [0], 'after': 'external_cancellation', 'delay_ms': 8500},
    ])
    return rows


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_workload(workload):
    if (not isinstance(workload, dict) or workload.get('schema') not in ('pokemon.collector-mixed-workload.v1','pokemon.collector-mixed-workload.v2')
            or not _hash(workload.get('catalog_sha256')) or not _hash(workload.get('payloads_sha256'))
            or not isinstance(workload.get('catalog_evidence'), dict)
            or workload['catalog_evidence'].get('schema') != {'pokemon.collector-mixed-workload.v1':catalog_evidence.SCHEMA,'pokemon.collector-mixed-workload.v2':catalog_evidence.LOCALIZED_SCHEMA}[workload['schema']]
            or not _hash(workload['catalog_evidence'].get('sha256'))
            or not isinstance(workload.get('sessions'), list) or len(workload['sessions']) != 16):
        raise ValueError('invalid mixed workload')
    hashes = []
    for index, item in enumerate(workload['sessions']):
        if not isinstance(item, dict) or type(item.get('index')) is not int or item.get('index') != index or not _hash(item.get('expected_result_semantic_sha256')):
            raise ValueError('invalid mixed reference')
        payload = item.get('payload')
        if (not isinstance(payload, dict) or set(payload) != {'turns', 'limit'}
                or type(payload['limit']) is not int or not 1 <= payload['limit'] <= 50
                or not isinstance(payload['turns'], list) or len(payload['turns']) != 20
                or not all(isinstance(turn, dict) for turn in payload['turns'])
                or payload['turns'][0].get('type') != 'ask'):
            raise ValueError('invalid twenty-turn mixed payload')
        digest = bench.json_hash(payload)
        if item.get('payload_sha256') != digest:
            raise ValueError('mixed payload digest differs')
        hashes.append(digest)
    if len(set(hashes)) != 16 or bench.json_hash([s['payload'] for s in workload['sessions']]) != workload['payloads_sha256']:
        raise ValueError('mixed sessions must have distinct verified payloads')
    return workload


def validate_plan(execution_plan, session_count=16):
    if type(session_count) is not int or not 1 <= session_count <= 16:
        raise ValueError('invalid session count')
    if not isinstance(execution_plan, list) or not 1 <= len(execution_plan) <= 64:
        raise ValueError('invalid mixed plan')
    fields = {'phase', 'clients', 'indices', 'label', 'after', 'delay_ms', 'sustained', 'cancel'}
    labels = {'sustained', 'external_cancellation'} | {f'burst_{i}' for i in range(1, 17)}
    total = 0
    for case in execution_plan:
        if (not isinstance(case, dict) or set(case) - fields or not {'phase', 'clients', 'indices'} <= set(case)
                or not isinstance(case['phase'], str) or case['phase'] not in bench.PHASES or type(case['clients']) is not int or not 1 <= case['clients'] <= 16
                or not isinstance(case['indices'], list) or not case['indices']
                or any(type(i) is not int or not 0 <= i < session_count for i in case['indices'])
                or any(type(case[k]) is not bool for k in ('sustained', 'cancel') if k in case)
                or any(not isinstance(case[k], str) or case[k] not in labels for k in ('label', 'after') if k in case)
                or type(case.get('delay_ms', 0)) is not int or not 0 <= case.get('delay_ms', 0) <= 8500):
            raise ValueError('invalid mixed case')
        total += len(case['indices'])
        if total > 128:
            raise ValueError('mixed plan exceeds request bound')
        if case.get('sustained'):
            if case['clients'] > len(case['indices']) or case.get('cancel'):
                raise ValueError('invalid sustained concurrency')
            lanes = [set(case['indices'][lane::case['clients']]) for lane in range(case['clients'])]
            if any(left & right for i, left in enumerate(lanes) for right in lanes[i + 1:]):
                raise ValueError('sustained lanes would share a concurrent payload')
        elif len(case['indices']) != case['clients'] or len(set(case['indices'])) != len(case['indices']):
            raise ValueError('simultaneous payloads must differ')
        if case.get('cancel') and (case['clients'] != 1 or case['phase'] != 'external_cancellation'):
            raise ValueError('invalid cancellation case')
    return execution_plan


class MemoryObserver:
    """Best-effort Linux samples; diagnostics cannot alter request completion."""
    def __init__(self):
        self.pid = None
        self.samples = []
        self.failures = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def process_started(self, pid):
        self.pid = pid

    def _sample(self):
        while not self.stop.wait(.05):
            try:
                values = []
                for pid in [os.getpid()] + ([self.pid] if self.pid is not None else []):
                    lines = (Path('/proc') / str(pid) / 'status').read_text().splitlines()
                    values.append(int(next(line for line in lines if line.startswith('VmRSS:')).split()[1]) / 1024)
                self.samples.append((values[0], sum(values[1:]), sum(values), len(values) > 1))
            except (OSError, StopIteration, ValueError):
                self.failures += 1

    def report(self):
        raw = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        child_peak = raw / (1024 * 1024) if sys.platform == 'darwin' else raw / 1024 if sys.platform.startswith('linux') else None
        return {
            'python_ru_maxrss_mib': bench.peak_rss_mib(),
            'node_children_ru_maxrss_mib': round(child_peak, 3) if child_peak is not None else None,
            'child_peak_scope': 'launched_child_lifetime_including_process_start_not_a_live_RSS_sample',
            'sample_failures': self.failures, 'node_samples': sum(row[3] for row in self.samples),
            'sample_interval_ms': 50, 'samples': len(self.samples),
            'sampled_python_rss_max_mib': max((row[0] for row in self.samples), default=None),
            'sampled_node_rss_max_mib': max((row[1] for row in self.samples if row[3]), default=None),
            'sampled_combined_rss_max_mib': max((row[2] for row in self.samples if row[3]), default=None),
        }


def benchmark(db, *, repo_root, workload_path, journal_path, execution_plan=None, watchdog_seconds=240):
    root = Path(repo_root).resolve()
    if any(name == 'pokemon_index' or name.startswith('pokemon_index.') for name in sys.modules):
        raise RuntimeError('mixed benchmark requires a fresh process')
    sys.path.insert(0, str(root))
    from pokemon_index import core, collector_journey
    from pokemon_index.cli import create_server
    path = Path(workload_path)
    # Capture and fingerprint exactly the bounded bytes that are consumed.
    # A later edit must never be attributed as the executed frozen fixture.
    with path.open('rb') as source:
        workload_bytes = source.read(1024 * 1024 + 1)
    if len(workload_bytes) > 1024 * 1024:
        raise ValueError('mixed workload exceeds input bound')
    workload_hash = hashlib.sha256(workload_bytes).hexdigest()
    workload = validate_workload(json.loads(workload_bytes.decode('utf-8')))
    cases_plan = validate_plan(plan() if execution_plan is None else execution_plan)
    before = bench.file_hash(db)
    source_before = bench.source_receipt(root)
    with closing(core.connect(db, readonly=True)) as connection:
        logical_catalog = catalog_evidence.catalog_evidence_digest(connection,schema=workload['catalog_evidence']['schema'])
        if logical_catalog != workload['catalog_evidence']['sha256']:
            raise ValueError('logical catalog evidence differs from frozen workload')
        revision = collector_journey.catalog_revision(connection)
    workload['catalog_revision'] = revision
    harness_files = {
        'reviewed_python': ROOT / 'scripts/benchmark_collector_caller.py',
        'reviewed_node_helpers': ROOT / 'integrations/pivota/benchmarkCollectorCaller.cjs',
        'mixed_python': Path(__file__), 'mixed_node': RUNNER,
        'catalog_evidence_digest': ROOT / 'scripts/collector_catalog_evidence.py',
    }
    harness_before = {name: bench.file_hash(file) for name, file in harness_files.items()}
    memory = MemoryObserver()
    memory.thread.start()
    started = time.monotonic()
    try:
        with create_server(str(Path(db).resolve()), '127.0.0.1', 0, True) as server:
            startup = time.monotonic() - started
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                caller = bench.run_node(
                    f'http://127.0.0.1:{server.server_port}', workload,
                    repo_root=root, local=True, scenarios={'plan': cases_plan},
                    journal_path=journal_path, watchdog_seconds=watchdog_seconds,
                    runner_path=RUNNER,
                    execution_plan=[(case['phase'], len(case['indices'])) for case in cases_plan],
                    on_process_started=memory.process_started,
                )
            finally:
                server.shutdown()
                thread.join(timeout=10)
    finally:
        measured = time.monotonic() - started
        memory.stop.set()
        memory.thread.join(timeout=2)
    rows = [row for case in caller['cases'] for row in case['results']]
    completed = [row for row in rows if row['category'] == 'completed']
    accounting = caller['request_accounting']
    for case in caller['cases']:
        case['counts'] = bench.summarize(case)
    counts = bench.summarize({'results': rows, 'wall_ms': measured * 1000})
    counts.update(accounting)
    counts.update(all_requests=accounting['planned_requests'], completion_fraction=len(completed) / accounting['planned_requests'])
    serial = [row for case in caller['cases'] if case['phase'].startswith('serial_') for row in case['results']]
    recovery = [row for case in caller['cases'] if case['phase'] in ('immediate_recovery', 'post_burst_recovery', 'cross_session_recovery') and case.get('after') != 'external_cancellation' for row in case['results']]
    cancellation = [row for case in caller['cases'] if case['phase'] == 'external_cancellation' for row in case['results']]
    deadline_recovery = [row for case in caller['cases'] if case['phase'] == 'post_cancel_deadline_recovery' for row in case['results']]
    memory_result = memory.report()
    try: workload_hash_after = bench.file_hash(path)
    except OSError: workload_hash_after = None
    checks = {
        'runner_complete': caller['runner_complete'],
        'workload_file_unchanged': workload_hash == workload_hash_after,
        'catalog_unchanged': before == bench.file_hash(db),
        'logical_catalog_evidence_matches': logical_catalog == workload['catalog_evidence']['sha256'],
        'source_unchanged': source_before == bench.source_receipt(root),
        'reviewed_harness_unchanged': harness_before == {name: bench.file_hash(file) for name, file in harness_files.items()},
        'memory_samples_available': bool(memory.samples) and any(row[3] for row in memory.samples) if sys.platform.startswith('linux') else None,
        'all_inputs_unchanged': len(rows) == accounting['planned_requests'] and all(row['input_unchanged'] for row in rows),
        'all_completions_semantically_equal_to_frozen_direct_replay': bool(completed) and all(row.get('deterministic_match') for row in completed),
        'all_completions_session_isolated_and_gates_closed': bool(completed) and all(row.get('session_integrity') and row.get('gates_closed') and row.get('turn_count') == 20 for row in completed),
        'all_serial_complete': all(row['category'] == 'completed' for row in serial) if serial else None,
        'all_load_and_isolation_recovery_complete': all(row['category'] == 'completed' for row in recovery) if recovery else None,
        'post_cancel_deadline_recovery_complete': all(row['category'] == 'completed' for row in deadline_recovery) if deadline_recovery else None,
        'native_diagnostics_complete': bench.current_diagnostics_complete(rows, 'current_required'),
        'caller_attempts_at_most_two': all(1 <= len(row['attempts']) <= 2 for row in rows),
        'requests_within_21500ms': all(row.get('elapsed_ms') is not None and row['elapsed_ms'] <= 21500 for row in rows),
        'attempts_within_10500ms': all(attempt['duration_ms'] <= 10500 for row in rows for attempt in row['attempts']),
        'cancellation_settled_without_retry': all(row['category'] == 'cancelled' and len(row['attempts']) == 1 for row in cancellation) if cancellation else None,
        'only_expected_outcomes': all(row['category'] == 'completed' or (row['category'] == 'cancelled' and row['cancellation_requested']) or (row['category'] == 'explicit_rejection' and row['error_code'] == 'catalog_temporarily_unavailable' and row['fetch_attempts'] and all(attempt.get('http_status') == 503 and attempt.get('runtime_error') == 'catalog_busy' for attempt in row['fetch_attempts'])) for row in rows),
        'python_peak_within_450_mib': memory_result['python_ru_maxrss_mib'] <= 450 if memory_result['python_ru_maxrss_mib'] is not None else None,
    }
    return {
        'schema': SCHEMA, 'source': source_before, 'catalog_sha256': before, 'catalog_revision': revision,
        'python_version': sys.version.split()[0], 'sqlite_version': sqlite3.sqlite_version,
        'fixture_original_catalog_sha256': workload['catalog_sha256'],
        'byte_identical_to_frozen_catalog': before == workload['catalog_sha256'],
        'catalog_evidence': {'schema': workload['catalog_evidence']['schema'], 'sha256': logical_catalog},
        'workload_file_sha256': workload_hash, 'workload_file_sha256_after': workload_hash_after,
        'revision_independent_payloads_sha256': workload['payloads_sha256'],
        'harness_sha256': harness_before, 'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'startup_seconds': startup, 'measured_seconds': measured, 'memory': memory_result,
        'limits': {'python_workers': 1, 'python_queue_size': 4, 'python_queue_wait_seconds': .25, 'python_deadline_seconds': 8, 'node_attempt_timeout_ms': 10000, 'maximum_attempts': 2, 'server_and_client_defaults_unchanged': True},
        'plan': cases_plan, 'custom_plan': execution_plan is not None,
        'post_cancel_immediate_categories': [row['category'] for case in caller['cases'] if case['phase'] == 'immediate_recovery' and case.get('after') == 'external_cancellation' for row in case['results']],
        'totals': counts, 'checks': checks, 'passed': all(value for value in checks.values() if value is not None), 'caller': caller,
        'interpretation': 'Distinct valid synthetic twenty-turn sessions through the real Node caller and HTTP server. Concurrent payloads differ. Rejection and timeout are unsuccessful work. Use load-case completion fractions rather than serial/recovery-inclusive totals. Semantic hashes omit only catalog_revision/expected_revision. Workload compatibility strictly binds versioned logical catalog evidence; actual before/after SQLite byte identity is separately enforced. Fresh-process preparation is measured after identity inspection; OS page caches are not flushed. Local RSS/CPU measurements are not a Cloud Run guarantee.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--workload', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cpu', type=int, help='Pin this process and its child to one currently allowed CPU')
    args = parser.parse_args()
    journal = args.output.with_suffix('.journal.jsonl')
    if args.output.exists() or journal.exists():
        parser.error('output already exists; use a new receipt path')
    if args.cpu is not None:
        if not hasattr(os, 'sched_getaffinity') or not hasattr(os, 'sched_setaffinity'):
            parser.error('explicit CPU affinity is unsupported on this platform')
        if args.cpu not in os.sched_getaffinity(0):
            parser.error('requested CPU is not currently allowed')
        os.sched_setaffinity(0, {args.cpu})
    try:
        report = benchmark(args.db, repo_root=args.repo_root, workload_path=args.workload, journal_path=journal)
    except Exception as error:
        report = {'schema': SCHEMA, 'passed': False, 'error_type': type(error).__name__, 'error': 'mixed benchmark setup or runner failed; no response or exception text retained'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as target:
        target.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'output': str(args.output)}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
