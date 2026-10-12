'use strict';
// Operator-only benchmark runner. Credentials arrive on stdin, never argv/files.
// The real collector client performs validation, retries, deadlines and cancel.
const {performance} = require('node:perf_hooks');
const {createHash} = require('node:crypto');
const path = require('node:path');

const ERROR_CODES = new Set(['catalog_timeout', 'catalog_cancelled', 'catalog_auth_unavailable',
  'catalog_access_denied', 'catalog_temporarily_unavailable', 'catalog_work_budget_exceeded',
  'catalog_snapshot_changed', 'catalog_transport_error', 'catalog_http_error',
  'catalog_rejected_action', 'invalid_catalog_response', 'response_too_large']);
const RUNTIME_ERRORS = new Set(['catalog_busy', 'catalog_snapshot_changed', 'catalog_work_budget_exceeded']);
const EVENT_FIELDS = ['schema', 'attempt', 'outcome', 'phase', 'duration_ms', 'auth_ms',
  'headers_ms', 'body_ms', 'http_status', 'error_class', 'retryable', 'retry_delay_ms',
  'abort_requested', 'cleanup_state', 'request_id', 'server_timing_ms'];
const round = n => Math.round(n * 1000) / 1000;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const copy = value => JSON.parse(JSON.stringify(value));
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
  return value;
}
const digest = value => createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
function safeEvent(event) {
  if (!event || event.schema !== 'pokemon.collector-attempt.v1') return null;
  const out = {};
  for (const key of EVENT_FIELDS) {
    const value = event[key];
    if (key === 'request_id' && typeof value === 'string' && /^[a-f0-9]{32}$/.test(value)) {out[key] = value; continue;}
    if (key === 'server_timing_ms' && value && typeof value === 'object') {
      out[key] = Object.fromEntries(['receive', 'queue', 'compute'].map(k => [k,
        typeof value[k] === 'number' && Number.isFinite(value[k]) && value[k] >= 0 ? value[k] : null]));
      continue;
    }
    if (value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) out[key] = value;
    else if (typeof value === 'string' && (
      (key === 'schema' && value === 'pokemon.collector-attempt.v1') ||
      (key === 'outcome' && ['accepted', 'catalog_changed', 'error'].includes(value)) ||
      (key === 'phase' && ['auth', 'fetch', 'headers', 'body', 'validate', 'complete'].includes(value)) ||
      (key === 'error_class' && ERROR_CODES.has(value)) ||
      (key === 'cleanup_state' && ['not_needed', 'requested', 'settled', 'failed'].includes(value)))) out[key] = value;
  }
  return out;
}
function observedFetch(rows, changed = () => {}) {
  return async (url, options) => {
    const started = performance.now();
    const row = {attempt: rows.length + 1, http_status: null, runtime_error: null,
      headers_ms: null, body_ms: null, body_bytes: 0, body_complete: false,
      abort_requested: false, cancel_requested: false, cancel_settled: false, error_class: null};
    rows.push(row); changed(row);
    const abort = () => {row.abort_requested = true; row.abort_ms = round(performance.now() - started); changed(row);};
    options.signal?.addEventListener('abort', abort, {once: true});
    let bodyStarted;
    const bodyError = () => {row.error_class = options.signal?.aborted ? 'aborted' : 'body_transport_error';};
    const cancel = async (target, args) => {
      row.cancel_requested = true; changed(row);
      try {const value = await target.cancel(...args); row.cancel_settled = true; row.observed_elapsed_ms = round(performance.now() - started); changed(row); return value;}
      catch (error) {row.cancel_failed = true; row.observed_elapsed_ms = round(performance.now() - started); changed(row); throw error;}
    };
    try {
      const response = await globalThis.fetch(url, options);
      row.headers_ms = round(performance.now() - started); row.http_status = response.status;
      const runtime = response.headers.get('x-collector-error');
      row.runtime_error = RUNTIME_ERRORS.has(runtime) ? runtime : null;
      const requestId = response.headers.get('x-collector-request-id');
      row.request_id = /^[a-f0-9]{32}$/.test(requestId || '') ? requestId : null;
      row.server_timing_ms = {receive: null, queue: null, compute: null};
      for (const field of (response.headers.get('server-timing') || '').split(',')) {
        const match = field.trim().match(/^(receive|queue|compute);dur=(\d+(?:\.\d+)?)$/);
        if (match && Number.isFinite(Number(match[2]))) row.server_timing_ms[match[1]] = Number(match[2]);
      }
      changed(row);
      const body = response.body && {
        cancel: (...args) => cancel(response.body, args),
        getReader: (...args) => {
          bodyStarted = performance.now(); row.body_read_started = true; changed(row);
          const reader = response.body.getReader(...args);
          return {
            read: async (...readArgs) => {
              try {
                const value = await reader.read(...readArgs);
                if (value.done) {
                  row.body_complete = true; row.body_ms = round(performance.now() - bodyStarted);
                  row.observed_elapsed_ms = round(performance.now() - started);
                  options.signal?.removeEventListener('abort', abort); changed(row);
                } else row.body_bytes += value.value?.byteLength || 0;
                return value;
              } catch (error) {bodyError(); row.body_ms = round(performance.now() - bodyStarted); changed(row); throw error;}
            },
            cancel: (...cancelArgs) => cancel(reader, cancelArgs),
            releaseLock: () => reader.releaseLock(),
          };
        },
      };
      // No response body is buffered, replaced, consumed or cancelled by the
      // observer. Only the real caller initiates reads and cleanup operations.
      return new Proxy(response, {get(target, key) {
        if (key === 'body') return body;
        const value = Reflect.get(target, key, target);
        return typeof value === 'function' ? value.bind(target) : value;
      }});
    } catch (error) {
      row.error_class = options.signal?.aborted ? 'aborted' : 'fetch_transport_error';
      row.fetch_elapsed_ms = round(performance.now() - started);
      row.observed_elapsed_ms = row.fetch_elapsed_ms; changed(row);
      options.signal?.removeEventListener('abort', abort);
      throw error;
    }
  };
}
function category(code, status) {
  if (status === 'accepted') return 'completed';
  if (code === 'catalog_timeout') return 'timeout';
  if (code === 'catalog_cancelled') return 'cancelled';
  if (['catalog_temporarily_unavailable', 'catalog_work_budget_exceeded', 'catalog_snapshot_changed',
    'catalog_access_denied', 'catalog_rejected_action', 'catalog_http_error'].includes(code)) return 'explicit_rejection';
  if (code === 'catalog_auth_unavailable') return 'auth_error';
  return 'other_error';
}
async function runBenchmark(input, emit = () => {}) {
  const {createCollectorClient} = require(path.resolve(input.clientPath));
  const variants = input.workload.variants;
  const config = {bursts: [2, 4, 16], sustainedConcurrency: 4, sustainedRequests: 16,
    recoveryDelayMs: 1000, cancellationRecoveryWaitMs: 8500, integrityConcurrency: 4, ...input.scenarios};
  if (!Array.isArray(config.bursts) || config.bursts.some(v => !Number.isInteger(v) || v < 1 || v > 16)
      || config.bursts.length > 4 || !Number.isInteger(config.sustainedConcurrency)
      || config.sustainedConcurrency < 1 || config.sustainedConcurrency > 16
      || !Number.isInteger(config.sustainedRequests) || config.sustainedRequests < 1 || config.sustainedRequests > 64
      || !Number.isInteger(config.recoveryDelayMs) || config.recoveryDelayMs < 0 || config.recoveryDelayMs > 5000
      || !Number.isInteger(config.cancellationRecoveryWaitMs) || config.cancellationRecoveryWaitMs < 0 || config.cancellationRecoveryWaitMs > 8500
      || !Number.isInteger(config.integrityConcurrency) || config.integrityConcurrency < 2 || config.integrityConcurrency > 16)
    throw new Error('invalid_scenarios');
  const mode = input.clientMode || 'current_required';
  if (!['current_required', 'legacy_baseline'].includes(mode)) throw new Error('invalid_mode');
  const plannedRequests = 3 + config.bursts.reduce((a, b) => a + b + 2, 0)
    + config.sustainedRequests + 2 + config.integrityConcurrency + 2 + (mode === 'current_required' ? 3 : 0);
  emit({event: 'run_started', planned_requests: plannedRequests, client_mode: mode, node_version: process.version});
  const cases = []; let requestNumber = 0; let currentCase = null; const references = {};
  async function call(variantName = 'a', cancel = false) {
    const payload = copy(variants[variantName]);
    const session = {schema: 'pokemon.pivota-collector-session.v1', turns: payload.turns.slice(0, -1),
      limit: payload.limit, expected_revision: input.workload.catalog_revision};
    const action = payload.turns.at(-1); const original = digest({session, action});
    const attempts = [], fetchAttempts = [], authObservations = [];
    const requestId = ++requestNumber;
    emit({event: 'request_started', request_id: requestId, case_id: currentCase.case_id,
      variant: variantName, cancellation_requested: cancel, workload_sha256: digest(payload)});
    const client = createCollectorClient({baseUrl: input.baseUrl, allowLoopback: input.allowLoopback,
      fetchImpl: observedFetch(fetchAttempts, attempt => emit({event: 'fetch_attempt', request_id: requestId, attempt: {...attempt}})),
      // Static operator token acquisition is measured, not token minting.
      getIdToken: input.token ? async () => {
        const started = performance.now(); const token = input.token;
        const observation = {duration_ms: round(performance.now() - started), outcome: 'provided'};
        authObservations.push(observation); emit({event: 'auth_observation', request_id: requestId, observation}); return token;
      } : undefined,
      onAttempt: event => {const safe = safeEvent(event); if (safe) {attempts.push(safe); emit({event: 'attempt_completed', request_id: requestId, attempt: safe});}},
    });
    const controller = cancel ? new AbortController() : null;
    const timer = cancel ? setTimeout(() => controller.abort(), 10) : null;
    const started = performance.now();
    const row = {request_id: requestId, variant: variantName, cancellation_requested: cancel,
      workload_sha256: digest(payload), category: null, elapsed_ms: null, error_code: null,
      attempts, fetch_attempts: fetchAttempts, auth_observations: authObservations};
    try {
      const output = await client.advance({session, action, signal: controller?.signal});
      row.status = output.status; row.category = category(null, output.status);
      if (output.status === 'accepted') {
        const result = output.result, coverage = result.discovery?.coverage || {};
        row.semantic_sha256 = digest(output);
        row.catalog_revision = result.catalog_revision;
        row.turn_count = result.turn_count;
        row.exercised_pool_records = coverage.scoped_catalog_records ?? coverage.matched_catalog_records ?? 0;
        row.session_integrity = digest(output.session.turns) === digest(payload.turns)
          && output.session.expected_revision === input.workload.catalog_revision;
        row.gates_closed = ['purchase_ready', 'physical_copy_verified', 'public_display_allowed',
          'ready_for_offer_tracking'].every(key => result[key] === false)
          && result.prices.length === 0 && result.live_offers.length === 0;
      }
    } catch (error) {
      row.error_code = ERROR_CODES.has(error.code) ? error.code : 'unclassified_caller_error';
      row.category = category(row.error_code, null);
    } finally {
      if (timer) clearTimeout(timer);
      row.elapsed_ms = round(performance.now() - started);
      row.input_unchanged = digest({session, action}) === original;
    }
    if (row.category === 'completed' && references[row.variant])
      row.deterministic_match = row.semantic_sha256 === references[row.variant];
    emit({event: 'request_completed', row});
    return row;
  }
  async function record(phase, work, extra = {}) {
    const started = performance.now();
    currentCase = {case_id: cases.length + 1, phase, ...extra};
    emit({event: 'case_started', case: currentCase});
    const results = await work();
    for (const row of results) if (row.category === 'completed' && references[row.variant])
      row.deterministic_match = row.semantic_sha256 === references[row.variant];
    const item = {phase, ...extra, results, wall_ms: round(performance.now() - started)};
    cases.push(item);
    emit({event: 'case_completed', case_id: currentCase.case_id, wall_ms: item.wall_ms});
    return results;
  }
  async function recovery(label) {
    await record('immediate_recovery', async () => [await call()], {after: label, clients: 1});
    await sleep(config.recoveryDelayMs);
    await record('post_burst_recovery', async () => [await call()],
      {after: label, clients: 1, idle_delay_ms: config.recoveryDelayMs});
  }
  const initial = (await record('serial_first_use', async () => [await call()], {clients: 1}))[0];
  if (initial.category === 'completed') references.a = initial.semantic_sha256;
  await record('serial_warm', async () => [await call()], {clients: 1});
  const b = (await record('serial_control_b', async () => [await call('b')], {clients: 1}))[0];
  if (b.category === 'completed') references.b = b.semantic_sha256;
  for (const clients of config.bursts) {
    const label = `burst_${clients}`;
    await record('simultaneous_burst', () => Promise.all(Array.from({length: clients}, () => call())), {label, clients});
    await recovery(label);
  }
  await record('sustained', async () => {
    const results = []; let next = 0;
    await Promise.all(Array.from({length: config.sustainedConcurrency}, async () => {
      while (next++ < config.sustainedRequests) results.push(await call());
    }));
    return results.sort((a, b) => a.request_id - b.request_id);
  }, {clients: config.sustainedConcurrency, scheduled_requests: config.sustainedRequests,
    arrival_model: 'closed_loop_fixed_total_requests_no_inter_request_delay'});
  await recovery('sustained');
  await record('cross_session_integrity', () => Promise.all(Array.from({length: config.integrityConcurrency},
    (_, i) => call(i % 2 ? 'b' : 'a'))), {clients: config.integrityConcurrency});
  for (const variant of ['a', 'b'])
    await record('cross_session_recovery', async () => [await call(variant)], {clients: 1, variant});
  const cancellationSupported = initial.attempts.some(event => event.schema === 'pokemon.collector-attempt.v1');
  if (mode === 'current_required') {
    const cancellationStarted = performance.now();
    await record('external_cancellation', async () => [await call('a', true)], {clients: 1, cancel_after_ms: 10});
    await record('immediate_recovery', async () => [await call()], {after: 'external_cancellation', clients: 1});
    const idle = Math.max(0, config.cancellationRecoveryWaitMs - (performance.now() - cancellationStarted));
    await sleep(idle);
    await record('post_cancel_deadline_recovery', async () => [await call()],
      {clients: 1, after: 'external_cancellation', idle_delay_ms: round(idle),
        minimum_elapsed_from_cancel_start_ms: config.cancellationRecoveryWaitMs});
  }
  return {schema: 'pokemon.collector-node-caller.v1', node_version: process.version,
    client_limits: {attempt_timeout_ms: 10000, maximum_attempts: 2, maximum_response_bytes: 8 * 1024 * 1024,
      policy: 'real_client_defaults_unchanged'},
    client_mode: mode, planned_requests: plannedRequests,
    cancellation_support: mode === 'legacy_baseline' ? 'explicitly_skipped_legacy_baseline' : 'required_and_exercised',
    native_attempt_diagnostics: initial.attempts.length > 0,
    authentication_scope: input.token ? 'operator_supplied_token_provider_only_no_minting' : 'unauthenticated_loopback',
    scenarios: config, cases};
}
if (require.main === module) {
  (async () => {
    let raw = ''; for await (const chunk of process.stdin) {raw += chunk; if (raw.length > 1024 * 1024) throw new Error('input_too_large');}
    const input = JSON.parse(raw); raw = '';
    const result = await runBenchmark(input, event => process.stdout.write(JSON.stringify({schema: 'pokemon.collector-journal.v1', ...event}) + '\n')); delete input.token;
    process.stdout.write(JSON.stringify({schema: 'pokemon.collector-journal.v1', event: 'run_completed',
      node_version: result.node_version, client_mode: result.client_mode,
      native_attempt_diagnostics: result.native_attempt_diagnostics, cancellation_support: result.cancellation_support}) + '\n');
  })().catch(() => {process.stderr.write('collector_caller_benchmark_failed\n'); process.exitCode = 1;});
}
module.exports = {runBenchmark, safeEvent, category, digest};
