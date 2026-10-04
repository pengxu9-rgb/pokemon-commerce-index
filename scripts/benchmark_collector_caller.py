"""Fresh-process actual Python HTTP + production Node caller load receipt.

No deployment, limits, retries, catalog files or caller policy are changed. Use
--repo-root to compare read-only source trees with the same saved workload and
CPU affinity. Overload/rejection is unsuccessful work in every denominator.

Remote mode requires an operator-reviewed immutable revision target receipt and
a rollout receipt, expected source SHA, and a token on stdin or in a named
environment variable. The existing read-only rollout inspector rechecks target,
IAM, settings and traffic immediately before and after calls. It does not mint
tokens, prove source/build provenance, or establish remote Python RSS.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import re
import selectors
import tempfile
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'integrations/pivota/benchmarkCollectorCaller.cjs'
SCHEMA = 'pokemon.collector-caller-concurrency.v1'
CATEGORIES = ('completed', 'explicit_rejection', 'timeout', 'cancelled', 'auth_error', 'other_error', 'unsettled')


def peak_rss_mib():
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == 'darwin': return round(raw / (1024 * 1024), 2)
    if sys.platform.startswith('linux'): return round(raw / 1024, 2)
    return None  # Unknown platform units must not become false memory evidence.


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False).encode()).hexdigest()


def source_receipt(repo_root):
    """Fingerprint executable/catalog-policy source, without git or credentials."""
    root = Path(repo_root).resolve()
    paths = sorted(path for path in (root / 'pokemon_index').rglob('*')
        if path.is_file() and path.suffix in ('.py', '.sql', '.json'))
    paths.append(root / 'integrations/pivota/collectorClient.cjs')
    files = {str(path.relative_to(root)): file_hash(path) for path in paths}
    return {'sha256': json_hash(files), 'files': files}


def make_workload(axis, revision):
    """Exact existing valid 20-turn pages workload; B only changes named input."""
    prefix = [{'type': 'ask', 'question': 'Recommend ' + axis['inventory_question']},
              {'type': 'preferences', 'preferences': {'collecting': axis['profile']}}]
    a = {'turns': prefix + [{'type': 'page', 'offset': i * 5} for i in range(1, 19)], 'limit': 5}
    b = json.loads(json.dumps(a))
    b['turns'][1]['preferences']['collecting']['subjective_notes'] = ['benchmark session b']
    b['turns'][-1]['offset'] = 85
    return {'name': 'recommendation_20_turn_pages', 'catalog_revision': revision,
        'axis': axis, 'variants': {'a': a, 'b': b},
        'variant_b_difference': 'unapplied subjective note and final page offset 85 instead of 90'}


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def summarize(case):
    rows = case['results']
    # Legacy callers without a plan retain the observed-row denominator.
    planned = case.get('planned_requests', len(rows))
    if type(planned) is not int or planned < len(rows):
        raise ValueError('invalid planned request count')
    counts = {category: sum(row['category'] == category for row in rows) for category in CATEGORIES}
    if sum(counts.values()) != len(rows):
        raise ValueError('unknown result category')
    wall = case['wall_ms'] / 1000
    return {**counts, 'all_requests': planned, 'planned_requests': planned,
        'started_requests': len(rows), 'not_started_requests': planned - len(rows),
        'completion_fraction': round(counts['completed'] / planned, 6) if planned else None,
        'completed_per_second': round(counts['completed'] / wall, 6) if wall else None,
        'all_request_latency_ms': {key: percentile([row['elapsed_ms'] for row in rows if row['elapsed_ms'] is not None], q)
            for key, q in [('p50', .5), ('p95', .95), ('maximum', 1)]},
        'completion_latency_ms': {key: percentile([row['elapsed_ms'] for row in rows
            if row['category'] == 'completed'], q) for key, q in [('p50', .5), ('p95', .95), ('maximum', 1)]},
        'http_attempts': sum(len(row['fetch_attempts']) for row in rows),
        'http_attempt_rejections': sum(attempt.get('http_status') not in (None, 200)
            for row in rows for attempt in row['fetch_attempts'])}


def validate_remote_target(base_url, review, *, now=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('remote target must be an HTTPS origin without credentials or query')
    if (review.get('base_url', '').rstrip('/') != base_url.rstrip('/')
            or review.get('target_kind') != 'immutable_revision_url'
            or review.get('authorization_rechecked') is not True
            or not review.get('revision_name') or not review.get('image_digest')):
        raise ValueError('reviewed immutable target and authorization receipt required')
    inspected = datetime.fromisoformat(review['inspected_at_utc'].replace('Z', '+00:00'))
    if inspected.tzinfo is None:
        raise ValueError('target inspection must include timezone')
    age = ((now or datetime.now(timezone.utc)) - inspected).total_seconds()
    if not 0 <= age <= 3600:
        raise ValueError('target must have been reinspected within the last hour')
    # Copy only non-secret, schema-bounded fields into evidence.
    allowed = ['base_url', 'target_kind', 'authorization_rechecked', 'revision_name',
        'image_digest', 'inspected_at_utc', 'catalog_revision', 'catalog_sha256',
        'source_sha256']
    result = {key: review[key] for key in allowed if key in review}
    for key in ('catalog_revision', 'catalog_sha256', 'source_sha256'):
        if key in result and (not isinstance(result[key], str) or len(result[key]) != 64
                or any(c not in '0123456789abcdef' for c in result[key])):
            raise ValueError('invalid reviewed hash')
    for key in ('revision_name', 'image_digest'):
        if not isinstance(result[key], str) or len(result[key]) > 256 or '\n' in result[key]:
            raise ValueError('invalid reviewed identity')
    return result


def inspect_remote_target(base_url, review, rollout_receipt, expected_source_sha):
    """Read-only existing inspector; it cannot deploy or alter traffic/settings."""
    from scripts import stage_existing_cloud_run as stage
    if not rollout_receipt or not expected_source_sha:
        raise ValueError('rollout receipt and independently reviewed source SHA required')
    record = stage.load(rollout_receipt)
    if record['operator_asserted_source_sha'] != expected_source_sha:
        raise ValueError('rollout source identity differs from reviewed source SHA')
    runtime = record['baseline']['runtime']
    limits = runtime.get('resources', {}).get('limits', {})
    if not (str(runtime.get('container_concurrency')) == '16'
            and str(runtime.get('timeout_seconds')) == '30'
            and str(runtime.get('max_instances')) == '1'
            and str(limits.get('cpu')) in ('1', '1000m')
            and limits.get('memory') == '512Mi'):
        raise ValueError('fixed staging runtime must remain 1CPU/512MiB/concurrency16/max1/timeout30')
    name, url = stage.candidate(record)
    if url.rstrip('/') != base_url.rstrip('/') or name != review['revision_name']:
        raise ValueError('freshly inspected candidate identity differs from target')
    if record['image'] != review['image_digest']:
        raise ValueError('freshly inspected image differs from target')
    if record['expected_catalog_revision'] != review.get('catalog_revision'):
        raise ValueError('freshly inspected catalog revision differs from target')
    return {'candidate_revision': name, 'candidate_url': url,
        'image_digest': record['image'], 'operator_asserted_source_sha': expected_source_sha,
        'settings_sha256': record['baseline']['settings_sha256'],
        'iam_sha256': record['baseline']['iam_sha256'], 'traffic': record['baseline']['traffic'],
        'runtime': {'cpu': limits['cpu'], 'memory': limits['memory'],
            'container_concurrency': runtime['container_concurrency'],
            'timeout_seconds': runtime['timeout_seconds'], 'max_instances': runtime['max_instances']},
        'source_build_binding_proven_by_script': False}


def _imports(repo_root):
    root = Path(repo_root).resolve()
    for name, module in tuple(sys.modules.items()):
        if name == 'pokemon_index' or name.startswith('pokemon_index.'):
            location = getattr(module, '__file__', None)
            if location and not Path(location).resolve().is_relative_to(root):
                raise RuntimeError('use a fresh process for each source tree')
    sys.path.insert(0, str(root))
    from pokemon_index import core, collector_journey
    from pokemon_index.cli import create_server
    # Keep axis choice stable across source revisions and save its exact output.
    from scripts.benchmark_collector_runtime import choose_axis
    return core, collector_journey, create_server, choose_axis


JOURNAL_SCHEMA = 'pokemon.collector-journal.v1'
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_JOURNAL_EVENTS = 5000
PHASES = {'serial_first_use', 'serial_warm', 'serial_control_b', 'simultaneous_burst',
    'immediate_recovery', 'post_burst_recovery', 'sustained', 'cross_session_integrity',
    'cross_session_recovery', 'external_cancellation', 'post_cancel_deadline_recovery'}
ERRORS = {'catalog_timeout', 'catalog_cancelled', 'catalog_auth_unavailable', 'catalog_access_denied',
    'catalog_temporarily_unavailable', 'catalog_work_budget_exceeded', 'catalog_snapshot_changed',
    'catalog_transport_error', 'catalog_http_error', 'catalog_rejected_action', 'invalid_catalog_response',
    'response_too_large', 'unclassified_caller_error', 'aborted', 'body_transport_error', 'fetch_transport_error'}
EVENTS = {'run_started', 'case_started', 'request_started', 'fetch_attempt', 'auth_observation',
    'attempt_completed', 'request_completed', 'case_completed', 'run_completed'}
NUMERIC_KEYS = {'planned_requests', 'request_id', 'case_id', 'attempt', 'clients', 'scheduled_requests',
    'idle_delay_ms', 'minimum_elapsed_from_cancel_start_ms', 'cancel_after_ms', 'wall_ms', 'elapsed_ms',
    'turn_count', 'exercised_pool_records', 'duration_ms', 'auth_ms', 'headers_ms', 'body_ms', 'http_status',
    'retry_delay_ms', 'body_bytes', 'abort_ms', 'fetch_elapsed_ms', 'observed_elapsed_ms'}
BOOL_KEYS = {'cancellation_requested', 'input_unchanged', 'gates_closed', 'session_integrity',
    'deterministic_match', 'native_attempt_diagnostics', 'retryable', 'abort_requested', 'cancel_requested',
    'cancel_settled', 'cancel_failed', 'body_complete', 'body_read_started'}
STRING_ENUMS = {'schema': {JOURNAL_SCHEMA, 'pokemon.collector-attempt.v1'}, 'event': EVENTS,
    'client_mode': {'current_required', 'legacy_baseline'}, 'variant': {'a', 'b'},
    'category': set(CATEGORIES), 'status': {'accepted', 'catalog_changed'}, 'error_code': ERRORS,
    'error_class': ERRORS, 'runtime_error': {'catalog_busy', 'catalog_snapshot_changed', 'catalog_work_budget_exceeded'},
    'phase': PHASES | {'auth', 'fetch', 'headers', 'body', 'validate', 'complete'},
    'outcome': {'provided', 'accepted', 'catalog_changed', 'error'},
    'cleanup_state': {'not_needed', 'requested', 'settled', 'failed'},
    'cancellation_support': {'explicitly_skipped_legacy_baseline', 'required_and_exercised'},
    'arrival_model': {'closed_loop_fixed_total_requests_no_inter_request_delay'}}


def sanitize_journal(value):
    """Drop unknown data recursively; never persist arbitrary error text or bodies."""
    if not isinstance(value, dict):
        raise ValueError('invalid journal object')
    out = {}
    for key, item in value.items():
        if key in {'row', 'case', 'observation'} and isinstance(item, dict):
            out[key] = sanitize_journal(item)
        elif key == 'attempt' and isinstance(item, dict):
            out[key] = sanitize_journal(item)
        elif key in {'attempts', 'fetch_attempts', 'auth_observations'} and isinstance(item, list) and len(item) <= 2:
            out[key] = [sanitize_journal(entry) for entry in item]
        elif key == 'server_timing_ms' and isinstance(item, dict):
            out[key] = {name: item.get(name) if type(item.get(name)) in (int, float)
                and math.isfinite(item[name]) and 0 <= item[name] <= 1e9 else None
                for name in ('receive', 'queue', 'compute')}
        elif key in NUMERIC_KEYS and type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 1e9:
            out[key] = item
        elif key in BOOL_KEYS and type(item) is bool:
            out[key] = item
        elif key in STRING_ENUMS and isinstance(item, str) and item in STRING_ENUMS[key]:
            out[key] = item
        elif key in {'workload_sha256', 'semantic_sha256', 'catalog_revision'} and isinstance(item, str) and re.fullmatch('[a-f0-9]{64}', item):
            out[key] = item
        elif key == 'request_id' and isinstance(item, str) and re.fullmatch('[a-f0-9]{32}', item):
            out[key] = item
        elif key in {'label', 'after'} and isinstance(item, str) and (item in {'sustained', 'external_cancellation'} or re.fullmatch(r'burst_([1-9]|1[0-6])', item)):
            out[key] = item
        elif key == 'node_version' and isinstance(item, str) and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', item):
            out[key] = item
        elif item is None and key in NUMERIC_KEYS | BOOL_KEYS | set(STRING_ENUMS):
            out[key] = None
    return out


def scenario_plan(scenarios=None, client_mode='current_required'):
    config = {'bursts': [2, 4, 16], 'sustainedConcurrency': 4, 'sustainedRequests': 16,
        'recoveryDelayMs': 1000, 'cancellationRecoveryWaitMs': 8500, 'integrityConcurrency': 4, **(scenarios or {})}
    plan = [('serial_first_use', 1), ('serial_warm', 1), ('serial_control_b', 1)]
    for clients in config['bursts']:
        plan.extend([('simultaneous_burst', clients), ('immediate_recovery', 1), ('post_burst_recovery', 1)])
    plan.extend([('sustained', config['sustainedRequests']), ('immediate_recovery', 1),
        ('post_burst_recovery', 1), ('cross_session_integrity', config['integrityConcurrency']),
        ('cross_session_recovery', 1), ('cross_session_recovery', 1)])
    if client_mode == 'current_required':
        plan.extend([('external_cancellation', 1), ('immediate_recovery', 1), ('post_cancel_deadline_recovery', 1)])
    return config, plan


def run_node(base_url, workload, *, repo_root, token=None, local=False, scenarios=None,
             client_mode='current_required', journal_path=None, watchdog_seconds=240,
             runner_path=None, execution_plan=None, on_process_started=None):
    if client_mode not in ('current_required', 'legacy_baseline') or not 0 < watchdog_seconds <= 240:
        raise ValueError('invalid benchmark mode or watchdog')
    config, plan = scenario_plan(scenarios, client_mode)
    if execution_plan is not None:
        if (not isinstance(execution_plan, (list, tuple)) or not 1 <= len(execution_plan) <= 64
                or any(not isinstance(item, (list, tuple)) or len(item) != 2
                    or not isinstance(item[0], str) or item[0] not in PHASES
                    or type(item[1]) is not int or not 1 <= item[1] <= 128
                    for item in execution_plan)
                or sum(item[1] for item in execution_plan) > 128):
            raise ValueError('invalid benchmark execution plan')
        plan = [(phase, count) for phase, count in execution_plan]
    runner = Path(runner_path).resolve() if runner_path is not None else RUNNER
    if runner_path is not None and (not runner.is_file() or runner.suffix != '.cjs'):
        raise ValueError('invalid benchmark runner')
    if on_process_started is not None and not callable(on_process_started):
        raise ValueError('invalid process observer')
    planned = sum(count for _, count in plan)
    options = {'baseUrl': base_url, 'allowLoopback': local, 'clientMode': client_mode,
        'clientPath': str(Path(repo_root).resolve() / 'integrations/pivota/collectorClient.cjs'),
        'workload': workload, 'scenarios': config}
    if token:
        options['token'] = token
    environment = {key: value for key, value in os.environ.items()
        if not any(part in key.upper() for part in ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))}
    temporary = tempfile.TemporaryDirectory() if journal_path is None else None
    journal_path = Path(journal_path) if journal_path else Path(temporary.name) / 'caller.journal.jsonl'
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    started, cases, settled = {}, {}, set()
    finished = False; failure = None; native = False; node_version = None
    total_bytes = event_count = 0; beginning = time.monotonic()
    process = None
    with journal_path.open('x', encoding='utf-8') as journal:
        def persist(event):
            nonlocal total_bytes, event_count
            encoded = json.dumps(event, separators=(',', ':')) + '\n'
            size = len(encoded.encode())
            reserved_marker = event.get('event') != 'receipt_marker'
            if (size > MAX_EVENT_BYTES or total_bytes + size > MAX_JOURNAL_BYTES - (2048 if reserved_marker else 0)
                    or event_count >= MAX_JOURNAL_EVENTS - (1 if reserved_marker else 0)):
                raise ValueError('journal limit exceeded')
            journal.write(encoded); journal.flush(); os.fsync(journal.fileno())
            total_bytes += size; event_count += 1
        persist({'schema': JOURNAL_SCHEMA, 'event': 'plan', 'planned_requests': planned,
            'client_mode': client_mode, 'watchdog_seconds': watchdog_seconds})
        def consume(raw):
            nonlocal finished, native, node_version
            event = sanitize_journal(json.loads(raw))
            kind = event.get('event')
            if event.get('schema') != JOURNAL_SCHEMA or kind not in EVENTS:
                raise ValueError('invalid journal event')
            if kind == 'run_started':
                node_version = event.get('node_version')
                if event.get('planned_requests') != planned or event.get('client_mode') != client_mode:
                    raise ValueError('plan mismatch')
            elif kind == 'case_started':
                case = event['case']; number = case['case_id']
                if type(number) is not int or number != len(cases) + 1 or number > len(plan) or case['phase'] != plan[number - 1][0]:
                    raise ValueError('case plan mismatch')
                # The Python execution plan, not runner metadata, owns the denominator.
                cases[number] = {**case, 'planned_requests': plan[number - 1][1],
                    'results': [], 'wall_ms': 0, 'partial': True}
            elif kind == 'request_started':
                number, case_id = event['request_id'], event['case_id']
                if (type(number) is not int or number != len(started) + 1 or number > planned or case_id not in cases
                        or len(cases[case_id]['results']) >= cases[case_id]['planned_requests']):
                    raise ValueError('request plan mismatch')
                row = {**event, 'category': 'unsettled', 'elapsed_ms': None, 'input_unchanged': False,
                    'attempts': [], 'fetch_attempts': [], 'auth_observations': [], 'error_code': None}
                row.pop('event'); row.pop('schema'); started[number] = row; cases[case_id]['results'].append(row)
            elif kind in {'fetch_attempt', 'attempt_completed', 'auth_observation'}:
                row = started[event['request_id']]
                if kind == 'auth_observation':
                    if len(row['auth_observations']) >= 2: raise ValueError('too many auth attempts')
                    row['auth_observations'].append(event['observation'])
                else:
                    attempt = event['attempt']; number = attempt['attempt']
                    field = 'attempts' if kind == 'attempt_completed' else 'fetch_attempts'
                    if type(number) is not int or number not in (1, 2): raise ValueError('invalid attempt')
                    if kind == 'attempt_completed' and any(entry['attempt'] == number for entry in row[field]):
                        raise ValueError('duplicate native attempt')
                    row[field][:] = [entry for entry in row[field] if entry['attempt'] != number] + [attempt]
            elif kind == 'request_completed':
                row = event['row']; number = row['request_id']
                if number not in started or number in settled or row.get('category') not in CATEGORIES:
                    raise ValueError('invalid completed request')
                # Preserve snapshots already journalled if the final row omits them.
                original = started[number]
                original.update({key: value for key, value in row.items() if key not in {'attempts', 'fetch_attempts', 'auth_observations'}})
                settled.add(number)
            elif kind == 'case_completed':
                case = cases[event['case_id']]
                if len(case['results']) != plan[event['case_id'] - 1][1] or any(row['request_id'] not in settled for row in case['results']):
                    raise ValueError('case completion mismatch')
                case.update(wall_ms=event['wall_ms'], partial=False)
            elif kind == 'run_completed':
                if len(settled) != planned or len(cases) != len(plan) or any(case['partial'] for case in cases.values()):
                    raise ValueError('premature completion')
                finished = True; native = event.get('native_attempt_diagnostics') is True
                node_version = event.get('node_version')
            persist(event)
        try:
            process = subprocess.Popen(['node', str(runner)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=environment)
            if on_process_started is not None:
                def notify_process_started(pid):
                    try:
                        on_process_started(pid)
                    except BaseException:
                        pass  # Diagnostics must not affect completion or leak exception text.
                try:
                    threading.Thread(target=notify_process_started, args=(process.pid,), daemon=True).start()
                except Exception:
                    pass
            encoded_input = json.dumps(options).encode()
            if len(encoded_input) > 1024 * 1024: raise ValueError('runner input too large')
            os.set_blocking(process.stdin.fileno(), False)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            input_offset = 0; pending = b''
            try:
                while selector.get_map():
                    remaining = watchdog_seconds - (time.monotonic() - beginning)
                    if remaining <= 0:
                        failure = 'node_watchdog_timeout'; break
                    ready = selector.select(min(remaining, .25))
                    for key, _ in ready:
                        if key.data == 'stdin':
                            try: input_offset += os.write(key.fileobj.fileno(), encoded_input[input_offset:input_offset + MAX_EVENT_BYTES])
                            except BlockingIOError: continue
                            if input_offset == len(encoded_input):
                                selector.unregister(key.fileobj); process.stdin.close()
                            continue
                        data = os.read(key.fileobj.fileno(), MAX_EVENT_BYTES)
                        if not data:
                            selector.unregister(key.fileobj); continue
                        pending += data
                        while b'\n' in pending:
                            line, pending = pending.split(b'\n', 1)
                            if len(line) > MAX_EVENT_BYTES: raise ValueError('event too large')
                            consume(line)
                        if len(pending) > MAX_EVENT_BYTES: raise ValueError('event too large')
                if pending: raise ValueError('truncated event')
            finally:
                selector.close()
            if failure is None:
                code = process.wait(timeout=max(.01, watchdog_seconds - (time.monotonic() - beginning)))
                if code != 0: failure = 'node_process_failed'
                elif not finished: failure = 'node_incomplete_journal'
        except subprocess.TimeoutExpired:
            failure = 'node_watchdog_timeout'
        except Exception:
            failure = 'node_protocol_or_runner_failed'
        finally:
            if process is not None:
                if process.poll() is None: process.kill()
                process.wait(timeout=5)
                if process.stdout: process.stdout.close()
                if process.stdin and not process.stdin.closed: process.stdin.close()
            persist({'schema': JOURNAL_SCHEMA, 'event': 'receipt_marker',
                'completion': 'complete' if finished and failure is None else 'partial',
                'failure_code': failure, 'planned_requests': planned, 'started_requests': len(started),
                'settled_requests': len(settled), 'unsettled_requests': len(started) - len(settled),
                'not_started_requests': planned - len(started)})
    accounting = {'planned_requests': planned, 'started_requests': len(started), 'settled_requests': len(settled),
        'unsettled_requests': len(started) - len(settled), 'not_started_requests': planned - len(started)}
    cancellation_started = any(case['phase'] == 'external_cancellation' and case['results']
        for case in cases.values())
    result = {'schema': 'pokemon.collector-node-caller.v1', 'node_version': node_version,
        'client_mode': client_mode, 'native_attempt_diagnostics': native or any(row['attempts'] for row in started.values()),
        'cancellation_support': ('explicitly_skipped_legacy_baseline' if client_mode == 'legacy_baseline'
            else 'required_and_exercised' if cancellation_started else 'required_but_not_exercised'),
        'client_limits': {'attempt_timeout_ms': 10000, 'maximum_attempts': 2, 'maximum_response_bytes': 8 * 1024 * 1024},
        'runner_complete': finished and failure is None, 'runner_failure_code': failure,
        'request_accounting': accounting, 'scenarios': config, 'cases': list(cases.values()),
        'journal': {'bytes': total_bytes, 'events': event_count, 'sha256': file_hash(journal_path),
            'durable': temporary is None, 'maximum_bytes': MAX_JOURNAL_BYTES,
            'maximum_event_bytes': MAX_EVENT_BYTES, 'maximum_events': MAX_JOURNAL_EVENTS,
            'watchdog_seconds': watchdog_seconds}}
    if temporary is not None: temporary.cleanup()
    return result

def current_diagnostics_complete(rows, client_mode):
    if client_mode == 'legacy_baseline': return True
    required = {'schema', 'attempt', 'outcome', 'phase', 'duration_ms', 'auth_ms', 'headers_ms',
        'body_ms', 'http_status', 'error_class', 'retryable', 'retry_delay_ms', 'abort_requested', 'cleanup_state',
        'request_id', 'server_timing_ms'}
    if not rows: return False
    for row in rows:
        attempts = row.get('attempts', [])
        if not 1 <= len(attempts) <= 2 or [a.get('attempt') for a in attempts] != list(range(1, len(attempts) + 1)):
            return False
        if any(not required.issubset(a) or a['schema'] != 'pokemon.collector-attempt.v1'
               or type(a['duration_ms']) not in (int, float) or a['duration_ms'] < 0 for a in attempts):
            return False
        if len(row.get('fetch_attempts', [])) > len(attempts): return False
        for observed in row.get('fetch_attempts', []):
            matching = next((a for a in attempts if a['attempt'] == observed.get('attempt')), None)
            if matching is None or (observed.get('http_status') is not None
                    and matching['http_status'] != observed['http_status']): return False
        if row.get('category') == 'completed' and attempts[-1]['outcome'] != 'accepted': return False
    return True


def benchmark(path, *, repo_root=ROOT, fixture_label='real_pinned_catalog', scenarios=None,
              base_url=None, target_review=None, token=None, workload=None, rollout_receipt=None, expected_source_sha=None,
              client_mode='current_required', journal_path=None, watchdog_seconds=240):
    path, repo_root = Path(path).resolve(), Path(repo_root).resolve()
    before = file_hash(path)
    source_before = source_receipt(repo_root)
    core, collector_journey, create_server, choose_axis = _imports(repo_root)
    with closing(core.connect(path, readonly=True)) as db:
        count = db.execute('SELECT count(*) FROM card').fetchone()[0]
        revision = collector_journey.catalog_revision(db)
        axis = choose_axis(db)
    if workload is None:
        workload = make_workload(axis, revision)
    if workload.get('catalog_revision') != revision:
        raise ValueError('saved workload revision does not match input catalog and source')
    started = time.monotonic()
    reviewed = None
    remote_before = remote_after = None
    remote_unchanged = None
    if base_url:
        reviewed = validate_remote_target(base_url, target_review or {})
        if not token or '\n' in token or '\r' in token:
            raise ValueError('remote mode requires an operator token via stdin or environment')
        if reviewed.get('catalog_revision') and reviewed['catalog_revision'] != revision:
            raise ValueError('reviewed remote catalog revision differs from workload')
        remote_before = inspect_remote_target(base_url, reviewed, rollout_receipt, expected_source_sha)
        startup = None
        try:
            caller = run_node(base_url, workload, repo_root=repo_root, token=token, scenarios=scenarios, client_mode=client_mode,
                journal_path=journal_path, watchdog_seconds=watchdog_seconds)
        finally:
            try:
                remote_after = inspect_remote_target(base_url, reviewed, rollout_receipt, expected_source_sha)
                remote_unchanged = remote_before == remote_after
            except Exception:
                remote_unchanged = False
    else:
        if token:
            raise ValueError('token is not used for local mode')
        # No overrides: keep server admission, deadline and resource limits fixed.
        with create_server(str(path), '127.0.0.1', 0, True) as server:
            startup = round(time.monotonic() - started, 4)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                caller = run_node(f'http://127.0.0.1:{server.server_port}', workload,
                    repo_root=repo_root, local=True, scenarios=scenarios, client_mode=client_mode,
                    journal_path=journal_path, watchdog_seconds=watchdog_seconds)
            finally:
                server.shutdown()
                thread.join(timeout=10)
    measured_seconds = round(time.monotonic() - started, 4)
    after = file_hash(path)
    source_after = source_receipt(repo_root)
    for case in caller['cases']:
        case['counts'] = summarize(case)
    rows = [row for case in caller['cases'] for row in case['results']]
    completed = [row for row in rows if row['category'] == 'completed']
    recovery = [row for case in caller['cases']
        if case['phase'] in ('immediate_recovery', 'post_burst_recovery')
        and case.get('after') != 'external_cancellation' for row in case['results']]
    serial = [row for case in caller['cases'] if case['phase'].startswith('serial_') for row in case['results']]
    integrity = [row for case in caller['cases'] if case['phase'] == 'cross_session_integrity'
        for row in case['results']]
    isolation_recovery = [row for case in caller['cases'] if case['phase'] == 'cross_session_recovery'
        for row in case['results']]
    cancellation = [row for case in caller['cases'] if case['phase'] == 'external_cancellation'
        for row in case['results']]
    cancellation_recovery = [row for case in caller['cases'] if case['phase'] == 'post_cancel_deadline_recovery'
        for row in case['results']]
    rss = peak_rss_mib()
    checks = {
        'catalog_unchanged': before == after,
        'runner_completed_all_planned_requests': caller.get('runner_complete') is True,
        'required_current_diagnostics_complete': current_diagnostics_complete(rows, client_mode),
        'required_cancellation_exercised': client_mode == 'legacy_baseline' or len(cancellation) == 1,
        'remote_state_unchanged': remote_unchanged,
        'source_unchanged': source_before == source_after,
        'serial_completed': bool(serial) and all(row['category'] == 'completed' for row in serial),
        'recommendation_recovery_completed': bool(recovery) and all(row['category'] == 'completed' for row in recovery),
        'all_completed_requests_valid': bool(completed) and all(
            row['gates_closed'] and row['session_integrity'] and row['turn_count'] == 20
            and 0 < row['exercised_pool_records'] <= 10000
            and row.get('deterministic_match', True) for row in completed),
        'all_inputs_unchanged': all(row['input_unchanged'] for row in rows),
        'cross_session_successes_isolated': bool(integrity) and all(
            row.get('deterministic_match') is True for row in integrity if row['category'] == 'completed'),
        'cross_session_recovery_completed_and_isolated': len(isolation_recovery) == 2 and all(
            row['category'] == 'completed' and row.get('deterministic_match') is True
            for row in isolation_recovery),
        'no_unexpected_timeouts_or_errors': all(row['category'] == 'completed'
            or (row['category'] == 'cancelled' and row['cancellation_requested'])
            or (row['category'] == 'explicit_rejection'
                and row['error_code'] == 'catalog_temporarily_unavailable'
                and row['fetch_attempts'] and all(attempt['http_status'] == 503
                    and attempt['runtime_error'] == 'catalog_busy' for attempt in row['fetch_attempts']))
            for row in rows),
        'request_elapsed_within_21500_ms': all(row['elapsed_ms'] is not None and row['elapsed_ms'] <= 21500 for row in rows),
        'attempt_elapsed_within_10500_ms': all(
            all(attempt.get('duration_ms', 10501) <= 10500 for attempt in row['attempts'])
            and all(attempt.get('observed_elapsed_ms', 10501) <= 10500 for attempt in row['fetch_attempts'])
            for row in rows),
        'at_most_two_attempts': all(len(row['attempts']) <= 2 and len(row['fetch_attempts']) <= 2 for row in rows),
        'post_cancel_deadline_recovery_completed': all(row['category'] == 'completed'
            for row in cancellation_recovery) and len(cancellation_recovery) == len(cancellation),
        'cancelled_calls_do_not_retry': all(row['category'] == 'cancelled'
            and len(row['attempts']) == 1 and len(row['fetch_attempts']) <= 1 for row in cancellation),
        'local_python_peak_rss_within_450_mib': rss is not None and rss <= 450 if not base_url else None,
    }
    accounting = caller.get('request_accounting', {'planned_requests': len(rows), 'started_requests': len(rows),
        'settled_requests': len(rows), 'unsettled_requests': 0, 'not_started_requests': 0})
    all_counts = {name: sum(row['category'] == name for row in rows) for name in CATEGORIES}
    return {'schema': SCHEMA, 'fixture_label': fixture_label,
        'catalog_records': count, 'catalog_sha256': before, 'catalog_revision': revision,
        'catalog_unchanged': before == after,
        'remote_state_unchanged': remote_unchanged, 'source': source_before,
        'source_unchanged': source_before == source_after,
        'harness_sha256': {'python': file_hash(Path(__file__)), 'node': file_hash(RUNNER)},
        'axis': axis, 'workload': workload, 'workload_sha256': json_hash(workload),
        'revision_independent_workload_sha256': json_hash(workload['variants']),
        'startup_seconds': startup, 'measured_seconds': measured_seconds,
        'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'python_version': sys.version.split()[0], 'python_peak_rss_mib': rss if not base_url else None,
        'orchestrator_peak_rss_mib': rss, 'rss_platform': sys.platform, 'reviewed_remote_target': reviewed,
        'remote_inspection_before': remote_before, 'remote_inspection_after': remote_after,
        'catalog_byte_identity_note': 'Input SQLite byte hash is explicit. Equal logical content is not byte identity with another deployed/rebuilt catalog.',
        'limits': {'python_peak_rss_mib': 450, 'server_policy': 'create_server_defaults_unchanged',
            'attempt_timeout_ms': 10000, 'maximum_attempts': 2, 'maximum_retry_delay_ms': 1000,
            'measurement_scheduling_tolerance_ms': 500, 'request_elapsed_ms': 21500,
            'attempt_elapsed_ms': 10500,
            'baseline_attempt_timing_scope': 'fetch start through body read/cancel settlement; auth provider separately observed'},
        'deployment_scope': ('Reviewed remote immutable target; operator token provider only, not token minting; backend Python RSS not measured.'
            if base_url else 'Fresh local Python process and real Node caller over HTTP. CPU affinity is reported; this is not a Cloud Run cgroup, CPU, memory or latency guarantee.'),
        'interpretation': 'Explicit overload and rejections are unsuccessful work, never successful capacity. Recovery uses the full recommendation workload, never health. Passed means the listed safety/recovery checks; inspect every completion fraction.',
        'totals': {**all_counts, **accounting, 'all_requests': accounting['planned_requests'],
            'completion_fraction': round(len(completed) / accounting['planned_requests'], 6) if accounting['planned_requests'] else 0},
        'client_mode': client_mode, 'partial_receipt': not caller.get('runner_complete', False),
        'checks': checks, 'passed': all(value for value in checks.values() if value is not None),
        'caller': caller}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--require-current-client', dest='client_mode', action='store_const', const='current_required', help='Require every native attempt diagnostic and cancellation scenario (default)')
    modes.add_argument('--allow-legacy-client', dest='client_mode', action='store_const', const='legacy_baseline', help='Explicit baseline compatibility; skips native telemetry and cancellation requirements')
    parser.set_defaults(client_mode='current_required')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--fixture-label', choices=['synthetic', 'real_pinned_catalog'], default='real_pinned_catalog')
    parser.add_argument('--workload', type=Path, help='Replay exact workload object from an earlier receipt')
    parser.add_argument('--base-url', help='Reviewed immutable HTTPS revision origin, never a moving production URL')
    parser.add_argument('--rollout-receipt', type=Path, help='Existing private staging rollout receipt, inspected read-only before and after')
    parser.add_argument('--expected-source-sha', help='Independently reviewed 40-hex source SHA; script does not prove build provenance')
    parser.add_argument('--reviewed-target', type=Path, help='Non-secret target/auth inspection receipt, no older than one hour')
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument('--token-stdin', action='store_true')
    credentials.add_argument('--token-env', help='Name of environment variable containing the operator token')
    args = parser.parse_args()
    journal_path = args.output.with_suffix('.journal.jsonl')
    if args.output.exists() or journal_path.exists():
        parser.error('output already exists; use a new receipt path')
    if args.base_url and not (args.reviewed_target and args.rollout_receipt and args.expected_source_sha and (args.token_stdin or args.token_env)):
        parser.error('remote mode requires reviewed target, rollout receipt, expected source SHA and operator token input')
    if not args.base_url and (args.reviewed_target or args.rollout_receipt or args.expected_source_sha or args.token_stdin or args.token_env):
        parser.error('remote options require --base-url')
    try:
        token = sys.stdin.read().strip() if args.token_stdin else os.environ.get(args.token_env) if args.token_env else None
        review = json.loads(args.reviewed_target.read_text()) if args.reviewed_target else None
        workload = json.loads(args.workload.read_text()) if args.workload else None
        report = benchmark(args.db, repo_root=args.repo_root, fixture_label=args.fixture_label,
            base_url=args.base_url, target_review=review, token=token, workload=workload,
            rollout_receipt=args.rollout_receipt, expected_source_sha=args.expected_source_sha,
            client_mode=args.client_mode, journal_path=journal_path)
    except Exception as error:
        # Exceptions can contain URLs/headers. Never serialize their message.
        report = {'schema': SCHEMA, 'passed': False, 'error_type': type(error).__name__,
            'error': 'benchmark setup or runner failed; no credential or response text retained'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'output': str(args.output)}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
