'use strict';

// Private catalog orchestration only. The caller authenticates its own users
// and owns session storage; this connector does not mint commerce identities.
const SESSION = 'pokemon.pivota-collector-session.v1';
const STATUSES = new Set(['candidate_clarification_needed', 'followup_clarification_needed',
  'inventory_review_needed', 'evidence_or_scope_needed', 'catalog_target_selected',
  'submitted_scope_covered', 'no_candidates']);
const FALSE_FLAGS = ['conversation_persisted', 'inventory_persisted',
  'ownership_assertions_verified', 'physical_copy_verified', 'ready_for_offer_tracking',
  'purchase_ready', 'complete_collection_established', 'public_display_allowed',
  'preferences_applied_to_market'];
const ACTION_FIELDS = {
  ask: ['type', 'question'], reply: ['type', 'text'], refine: ['type', 'scope'],
  inventory: ['type', 'owned_items'], resolve_owned: ['type', 'item_id', 'card_id'],
  preferences: ['type', 'preferences'], select: ['type', 'card_id'],
  clear_target: ['type'], page: ['type', 'offset'],
  feedback: ['type', 'card_id', 'reaction'], compare: ['type', 'left_card_id', 'right_card_id'],
  choose_comparison: ['type', 'side', 'card_id'],
};

class CollectorCallError extends Error {
  constructor(code, retryable = false) {
    super(code); this.name = 'CollectorCallError'; this.code = code; this.retryable = retryable;
  }
}
function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...keys].sort().join(',');
}
function jsonCopy(value) {
  try { return JSON.parse(JSON.stringify(value)); }
  catch { throw new CollectorCallError('invalid_caller_state'); }
}
function collectingPatch(value) {
  if (value === null) return true;
  const fields = ['mode', 'preferred_dex_ids', 'excluded_dex_ids', 'preferred_illustrators', 'preferred_releases', 'subjective_notes'];
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !fields.includes(k))) return false;
  for (const [key, val] of Object.entries(value)) {
    if (val === null) continue;
    if (key === 'mode') {if (!['discover_next', 'explore'].includes(val)) return false; continue;}
    const dex = key.endsWith('dex_ids');
    if (!Array.isArray(val) || val.length > (dex ? 20 : 10)) return false;
    if (dex && val.some(v => !Number.isInteger(v) || v < 1 || v > 1025)) return false;
    if (key === 'preferred_releases' && val.some(v => !exactKeys(v, ['language', 'set_code']) || !['ja', 'en'].includes(v.language) || typeof v.set_code !== 'string' || !/^[A-Za-z0-9.\-]{1,32}$/.test(v.set_code))) return false;
    if (!dex && key !== 'preferred_releases' && val.some(v => typeof v !== 'string' || !v.trim() || v.length > 160)) return false;
    const keys = val.map(v => typeof v === 'object' ? JSON.stringify([v.language, v.set_code.toUpperCase()]) : v);
    if (new Set(keys).size !== keys.length) return false;
  }
  return !(value.preferred_dex_ids || []).some(v => (value.excluded_dex_ids || []).includes(v));
}
function actionCopy(value) {
  const fields = ACTION_FIELDS[value?.type];
  if (!fields || !exactKeys(value, fields)) throw new CollectorCallError('invalid_action');
  const id = v => typeof v === 'string' && !!v.trim() && v.length <= 160;
  if (value.type === 'preferences') {
    const p = value.preferences;
    if (!p || typeof p !== 'object' || Array.isArray(p) || Object.keys(p).some(k => !['grade_company', 'grade_value', 'budget_minor', 'currency', 'destination', 'collecting'].includes(k)) || ('collecting' in p && !collectingPatch(p.collecting))) throw new CollectorCallError('invalid_action');
  }
  if (value.type === 'feedback' && (!id(value.card_id) || !['like', 'dismiss', 'clear'].includes(value.reaction))) throw new CollectorCallError('invalid_action');
  if (value.type === 'compare' && (!id(value.left_card_id) || !id(value.right_card_id) || value.left_card_id === value.right_card_id)) throw new CollectorCallError('invalid_action');
  if (value.type === 'choose_comparison' && (!id(value.card_id) || !['left', 'right'].includes(value.side))) throw new CollectorCallError('invalid_action');
  return jsonCopy(value);
}
function requestFor(session, action, limit) {
  let request;
  if (session !== null && session !== undefined) {
    if (!exactKeys(session, ['schema', 'turns', 'limit', 'expected_revision'])
        || session.schema !== SESSION || !/^[a-f0-9]{64}$/.test(session.expected_revision)
        || !Array.isArray(session.turns) || !session.turns.length) {
      throw new CollectorCallError('invalid_caller_state');
    }
    request = {turns: session.turns.map(actionCopy), limit: session.limit,
      expected_revision: session.expected_revision};
  } else request = {turns: [], limit};
  if (!Number.isInteger(request.limit) || request.limit < 1 || request.limit > 50)
    throw new CollectorCallError('invalid_page_limit');
  request.turns.push(actionCopy(action));
  if (request.turns[0].type !== 'ask') throw new CollectorCallError('first_action_must_ask');
  if (request.turns.length > 20) throw new CollectorCallError('journey_turn_limit');
  if (Buffer.byteLength(JSON.stringify(request)) > 262144)
    throw new CollectorCallError('request_too_large');
  return request;
}
function validateResult(result, request) {
  const invalid = () => { throw new CollectorCallError('invalid_catalog_response'); };
  const likedIds = new Set();
  for (const action of request.turns) {
    if (action.type === 'ask') likedIds.clear();
    if (action.type === 'feedback') {
      if (action.reaction === 'like') likedIds.add(action.card_id);
      else likedIds.delete(action.card_id);
    }
  }
  if (!result || result.schema !== 'pokemon.collector-journey.v1'
      || !STATUSES.has(result.status) || !/^[a-f0-9]{64}$/.test(result.catalog_revision)
      || result.turn_count !== request.turns.length || !Array.isArray(result.trace)
      || result.trace.length !== request.turns.length
      || (request.expected_revision && result.catalog_revision !== request.expected_revision)
      || !Array.isArray(result.candidate_cards) || result.candidate_cards.length > request.limit
      || !Array.isArray(result.artwork_review_leads)
      || !Array.isArray(result.selection_blockers) || typeof result.selection_allowed !== 'boolean'
      || !result.next_step || !Array.isArray(result.prices) || result.prices.length
      || !Array.isArray(result.live_offers) || result.live_offers.length
      || FALSE_FLAGS.some(k => result[k] !== false)) invalid();
  // New fields are mandatory: the server binds recommendations to the shown page.
  const blocks = result.card_selection_blockers;
  if (!blocks || typeof blocks !== 'object' || Array.isArray(blocks)
      || !exactKeys(blocks, result.candidate_cards.map(c => c.card_id))
      || Object.values(blocks).some(v => !Array.isArray(v) || v.some(x => typeof x !== 'string'))
      || result.candidate_cards.some(c => c.automatic_offer_join_allowed !== false || c.price_comparable !== false)) invalid();
  const recommendation = result.recommendation;
  if (recommendation !== null) {
    if (!exactKeys(recommendation, ['schema', 'ranking_policy', 'preference_evidence', 'candidate_pool_complete', 'coverage_basis', 'global_catalog_completeness_established', 'unapplied_preferences', 'budget_fit', 'grade_availability', 'items', 'coordinate_groups'])
        || recommendation.schema !== 'pokemon.collector-recommendation.v1'
        || recommendation.ranking_policy !== 'explicit_axes_then_liked_axes_then_coordinate_round_robin.v1'
        || recommendation.preference_evidence !== 'user_assertion_only'
        || typeof recommendation.candidate_pool_complete !== 'boolean'
        || recommendation.global_catalog_completeness_established !== false
        || recommendation.coverage_basis !== 'current_catalog_facets_and_reviewed_name_affiliations_only'
        || recommendation.budget_fit !== 'unknown_no_live_price'
        || recommendation.grade_availability !== 'unknown_no_copy_offers'
        || !['collector_recommendations', 'collection_preferences_needed'].includes(result.discovery?.task)
        || !Array.isArray(recommendation.items) || recommendation.items.length !== result.candidate_cards.length
        || !Array.isArray(recommendation.unapplied_preferences) || recommendation.unapplied_preferences.some(v => !exactKeys(v, ['value', 'reason']) || typeof v.value !== 'string' || v.reason !== 'no_source_backed_style_labels')
        || !Array.isArray(recommendation.coordinate_groups)) invalid();
    for (let i = 0; i < recommendation.items.length; i++) {
      const item = recommendation.items[i];
      if (!exactKeys(item, ['card_id', 'rank', 'explicit_match_axes', 'liked_example_match_axes', 'reasons', 'tradeoffs'])
          || item.card_id !== result.candidate_cards[i].card_id
          || item.rank !== (result.discovery?.coverage?.offset || 0) + i + 1
          || !Number.isInteger(item.rank)
          || !Array.isArray(item.explicit_match_axes) || item.explicit_match_axes.some(a => !['character', 'illustrator', 'release'].includes(a))
          || !Array.isArray(item.liked_example_match_axes) || item.liked_example_match_axes.some(a => !['character', 'illustrator'].includes(a))
          || !Array.isArray(item.reasons) || !item.reasons.length
          || !Array.isArray(item.tradeoffs) || item.tradeoffs.some(t => typeof t !== 'string')) invalid();
      for (const reason of item.reasons) {
        if (reason.field === 'character_name_affiliation') {
          const card = result.candidate_cards[i];
          const fields = ['field', 'value', 'basis', 'source_ref', 'target_name', 'base_name_ja',
            'mechanic', 'source_asserted_dex_id', 'anchor_evidence', 'anchor_count',
            'anchor_evidence_sha256', 'derivation', 'affiliated_card_id', 'affiliation_role', 'preference_origin'];
          if (!exactKeys(reason, fields) || reason.basis !== 'source_name_character_affiliation'
              || reason.derivation !== 'exact_pinned_ex_name_to_unanimous_current_name_facets.v1'
              || !Number.isInteger(reason.value) || reason.value < 1 || reason.value > 1025
              || reason.source_asserted_dex_id !== false || reason.mechanic !== 'EX'
              || typeof reason.source_ref !== 'string' || !reason.source_ref
              || typeof reason.target_name !== 'string' || !reason.target_name || reason.target_name.length > 160
              || typeof reason.base_name_ja !== 'string' || !reason.base_name_ja
              || reason.target_name !== reason.base_name_ja + 'ex'
              || typeof reason.affiliated_card_id !== 'string' || !reason.affiliated_card_id.startsWith('ja:')
              || !['candidate', 'liked_example'].includes(reason.affiliation_role)
              || !['explicit_preference', 'liked_example'].includes(reason.preference_origin)
              || (reason.affiliation_role === 'candidate' && (reason.affiliated_card_id !== card.card_id
                || reason.target_name !== card.name || reason.source_ref !== card.provenance))
              || (reason.affiliation_role === 'liked_example' && (reason.preference_origin !== 'liked_example'
                || !likedIds.has(reason.affiliated_card_id)))
              || (reason.affiliated_card_id === card.card_id && (reason.target_name !== card.name
                || reason.source_ref !== card.provenance))
              || (reason.affiliation_role === 'liked_example' && !item.reasons.some(candidate =>
                (candidate.field === 'dex_id' && candidate.value === reason.value
                  && candidate.basis === 'liked_example_catalog_facet')
                || (candidate.field === 'character_name_affiliation' && candidate.value === reason.value
                  && candidate.affiliation_role === 'candidate' && candidate.affiliated_card_id === card.card_id
                  && candidate.preference_origin === 'liked_example')))
              || !(reason.preference_origin === 'explicit_preference' ? item.explicit_match_axes : item.liked_example_match_axes).includes('character')
              || !Number.isInteger(reason.anchor_count) || reason.anchor_count < 1
              || !/^[a-f0-9]{64}$/.test(reason.anchor_evidence_sha256)
              || !Array.isArray(reason.anchor_evidence) || reason.anchor_evidence.length !== 1) invalid();
          for (const anchor of reason.anchor_evidence) {
            if (!exactKeys(anchor, ['card_id', 'name', 'dex_id', 'provenance', 'rights_reference'])
                || typeof anchor.card_id !== 'string' || !anchor.card_id.startsWith('ja:')
                || anchor.card_id === reason.affiliated_card_id || anchor.name !== reason.base_name_ja
                || anchor.dex_id !== reason.value || typeof anchor.provenance !== 'string' || !anchor.provenance
                || typeof anchor.rights_reference !== 'string' || !anchor.rights_reference) invalid();
          }
          continue;
        }
        const fields = reason.field === 'language_set_coordinate' ? ['field', 'value', 'basis', 'source_ref'] : ['field', 'value', 'basis', 'source_ref', 'rights_reference'];
        if (!exactKeys(reason, fields) || !['dex_id', 'illustrator', 'language_set_coordinate'].includes(reason.field)
            || !['catalog_facet', 'liked_example_catalog_facet', 'catalog_coordinate'].includes(reason.basis)
            || typeof reason.source_ref !== 'string' || !reason.source_ref
            || (reason.field === 'dex_id' && (!Number.isInteger(reason.value) || reason.value < 1 || reason.value > 1025))
            || (reason.field === 'illustrator' && typeof reason.value !== 'string')
            || (reason.field === 'language_set_coordinate' && (!exactKeys(reason.value, ['language', 'set_code']) || !['ja', 'en'].includes(reason.value.language) || typeof reason.value.set_code !== 'string'))) invalid();
      }
    }
    for (const group of recommendation.coordinate_groups) {
      if (!exactKeys(group, ['language', 'set_code', 'collector_number', 'shown_card_ids', 'physical_versions_merged'])
          || group.physical_versions_merged !== false || !Array.isArray(group.shown_card_ids)
          || group.shown_card_ids.some(cid => !result.candidate_cards.some(c => c.card_id === cid && c.language === group.language && c.set_code === group.set_code && c.collector_number === group.collector_number))) invalid();
    }
  }
  // These authority fields may not become true anywhere in nested catalog evidence.
  const forbidden = new Set(['purchase_ready', 'transaction_ready', 'automatic_offer_join_allowed',
    'physical_printing_verified', 'physical_copy_verified', 'physical_finish_verified',
    'copy_condition_verified', 'public_display_allowed', 'price_comparable',
    'price_series_merge_allowed', 'numeric_price_gap_available', 'same_physical_printing_established']);
  function checkAuthority(value) {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      if (forbidden.has(key) && child !== false) invalid();
      checkAuthority(child);
    }
  }
  checkAuthority(result);
  const intent = result.target_intent;
  if (result.status === 'catalog_target_selected') {
    if (!intent || intent.contract !== 'pokemon.collector-target-intent.v1'
        || !result.selected_catalog_target
        || intent.card_id !== result.selected_catalog_target.card_id
        || !result.selection_allowed || result.selection_blockers.length
        || result.selected_catalog_target.structural_match_eligible !== true
        || !Array.isArray(blocks[intent.card_id]) || blocks[intent.card_id].length
        || ['transaction_ready', 'automatic_offer_join_allowed',
          'physical_printing_verified', 'public_display_allowed'].some(k => intent[k] !== false)
        || ['priceable_unit_id', 'product_url', 'quote'].some(k => intent[k] !== null)
        || intent.preferences_evidence !== 'user_assertion_only') invalid();
    for (const [key, selectedKey] of [['language', 'language'], ['set_code', 'set_code'],
      ['collector_number', 'collector_number'], ['source_declared_variant', 'variant'],
      ['catalog_provenance', 'provenance']]) {
      if (intent[key] !== result.selected_catalog_target[selectedKey]) invalid();
    }
  } else if (intent !== null) invalid();
  if (result.discovery?.task === 'two_card_comparison') {
    const comparison = result.discovery.comparison;
    if (!comparison || comparison.schema !== 'pokemon.card-comparison.v1'
        || !['catalog_partial', 'scope_confirmation_needed'].includes(comparison.status)
        || result.candidate_cards.length || result.selection_allowed || intent !== null
        || ['same_physical_printing_established', 'physical_finish_verified',
          'copy_condition_verified', 'price_comparable', 'price_series_merge_allowed',
          'numeric_price_gap_available', 'automatic_offer_join_allowed', 'purchase_ready',
          'public_display_allowed', 'complete_answer_established'].some(k => comparison[k] !== false)
        || !Array.isArray(comparison.prices) || comparison.prices.length
        || !Array.isArray(comparison.live_offers) || comparison.live_offers.length
        || comparison.product_url !== null) invalid();
  }
  return result;
}
// These helpers never await cleanup or telemetry supplied by dependencies. A
// cancelled fetch/token provider may ignore AbortSignal; a single independent
// watchdog bounds asynchronous waits, and guards keep late results from advancing
// an expired attempt. JavaScript timers cannot preempt synchronous dependency
// code or a blocked event loop; callbacks must not do blocking CPU work.
function bestEffort(callback, settled = () => {}) {
  try { Promise.resolve(callback()).then(() => settled('settled'), () => settled('failed')); }
  catch { settled('failed'); }
}
function responseDiagnostics(headers) {
  const id = headers.get('x-collector-request-id');
  const timing = {receive: null, queue: null, compute: null};
  const seen = new Set();
  for (const part of (headers.get('server-timing') || '').split(',')) {
    const match = /^(receive|queue|compute);\s*dur=(\d+(?:\.\d+)?)$/.exec(part.trim());
    if (!match) continue;
    const [, key, raw] = match; const value = Number(raw);
    timing[key] = !seen.has(key) && Number.isFinite(value) && value >= 0 ? value : null;
    seen.add(key);
  }
  return {request_id: typeof id === 'string' && /^[a-f0-9]{32}$/.test(id) ? id : null,
    server_timing_ms: Object.freeze(timing)};
}
function throwIfCancelled(signal) {
  if (signal?.aborted) throw new CollectorCallError('catalog_cancelled');
}
function retrySleep(ms, signal) {
  throwIfCancelled(signal);
  if (!ms) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer); signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve();
    };
    const abort = () => finish(new CollectorCallError('catalog_cancelled'));
    const timer = setTimeout(() => finish(), ms);
    signal?.addEventListener('abort', abort, {once: true});
    if (signal?.aborted) abort();
  });
}
async function readBounded(response, maxBytes, guard) {
  const declared = response.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > maxBytes))
    throw new CollectorCallError('response_too_large');
  if (!response.body) throw new CollectorCallError('invalid_catalog_response');
  const reader = response.body.getReader(); const chunks = []; let total = 0;
  guard.setCleanup(() => {
    // Native cancellation may close the stream while its underlying source's
    // cancel promise never settles. Release our reader independently, including
    // when a custom cancel method throws synchronously.
    try { return reader.cancel(); }
    finally { bestEffort(() => reader.releaseLock?.()); }
  });
  while (true) {
    guard.ensureActive();
    const {done, value} = await reader.read();
    guard.ensureActive();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) throw new CollectorCallError('response_too_large');
    chunks.push(Buffer.from(value));
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new CollectorCallError('invalid_catalog_response'); }
}

function createCollectorClient({baseUrl, getIdToken, fetchImpl = globalThis.fetch,
  allowLoopback = false, timeoutMs = 10000, retryDelayMs = 200, maxResponseBytes = 8 * 1024 * 1024,
  onAttempt} = {}) {
  let base; try { base = new URL(baseUrl); } catch { throw new CollectorCallError('invalid_service_url'); }
  const local = allowLoopback && base.protocol === 'http:' && base.hostname === '127.0.0.1';
  if ((!local && base.protocol !== 'https:') || base.username || base.password
      || base.search || base.hash || base.pathname !== '/') throw new CollectorCallError('invalid_service_url');
  if ((!local && typeof getIdToken !== 'function') || typeof fetchImpl !== 'function'
      || (onAttempt !== undefined && typeof onAttempt !== 'function')
      || !Number.isInteger(timeoutMs) || timeoutMs < 50 || timeoutMs > 30000
      || !Number.isInteger(retryDelayMs) || retryDelayMs < 0 || retryDelayMs > 1000
      || !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1024 || maxResponseBytes > 16 * 1024 * 1024)
    throw new CollectorCallError('invalid_client_configuration');
  const audience = base.origin;
  // Only connector-owned error classes can appear in telemetry or error text.
  // Dependency errors (including thrown CollectorCallError objects) are mapped
  // at the auth/fetch boundary instead of exposing provider-controlled details.
  const safeCodes = new Set(['catalog_cancelled', 'catalog_timeout', 'catalog_auth_unavailable',
    'catalog_work_budget_exceeded', 'catalog_snapshot_changed', 'catalog_temporarily_unavailable',
    'catalog_access_denied', 'catalog_http_error', 'invalid_catalog_response',
    'response_too_large', 'catalog_rejected_action', 'catalog_transport_error', 'invalid_caller_state']);
  function sanitizedFailure(error) {
    // Dependencies can throw exported errors with mutable/throwing accessors or
    // proxy prototypes. Snapshot each field once inside the defensive boundary.
    try {
      if (error instanceof CollectorCallError) {
        const code = error.code;
        const retryable = error.retryable === true;
        if (safeCodes.has(code)) return new CollectorCallError(code, retryable);
      }
    } catch {}
    return new CollectorCallError('catalog_transport_error', true);
  }
  async function advance({session = null, action, limit = 5, signal} = {}) {
    if (signal !== undefined && signal !== null && !(signal instanceof AbortSignal))
      throw new CollectorCallError('invalid_cancellation_signal');
    throwIfCancelled(signal);
    const request = requestFor(session, action, limit); const body = JSON.stringify(request);
    for (let attempt = 0; attempt < 2; attempt++) {
      throwIfCancelled(signal);
      let retryWaitMs = retryDelayMs;
      const controller = new AbortController();
      const started = performance.now();
      let phase = getIdToken ? 'auth' : 'fetch'; let phaseStarted = started;
      const timings = {auth: null, fetch: null, body: null};
      let httpStatus = null; let diagnostics = responseDiagnostics(new Headers());
      let stopError; let rejectStopped; let cleanupAction;
      let cleanupState = 'not_needed'; let cleanupRequested = false;
      const stopped = new Promise((_, reject) => { rejectStopped = reject; });
      const setPhase = next => {
        if (Object.hasOwn(timings, phase)) timings[phase] = performance.now() - phaseStarted;
        phase = next; phaseStarted = performance.now();
      };
      const cleanup = () => {
        if (!cleanupAction || cleanupRequested) return;
        cleanupRequested = true; cleanupState = 'requested';
        bestEffort(cleanupAction, state => { cleanupState = state; });
      };
      const stop = error => {
        if (stopError) return;
        stopError = error; rejectStopped(error);
        controller.abort(); cleanup();
      };
      const guard = {
        ensureActive() {
          if (signal?.aborted) stop(new CollectorCallError('catalog_cancelled'));
          if (!stopError && performance.now() - started >= timeoutMs)
            stop(new CollectorCallError('catalog_timeout', true));
          if (stopError) throw stopError;
        },
        setCleanup(callback) {
          cleanupAction = callback;
          // A dependency can synchronously abort while handing us a reader.
          // Adopting that new resource needs its own cleanup even if the prior
          // body-level cancellation was already requested while it was locked.
          cleanupRequested = false;
          if (stopError) cleanup();
        },
      };
      const timer = setTimeout(() => stop(new CollectorCallError('catalog_timeout', true)), timeoutMs);
      const abort = () => stop(new CollectorCallError('catalog_cancelled'));
      signal?.addEventListener('abort', abort, {once: true});
      const execute = async () => {
        try {
          guard.ensureActive();
          const headers = {'Content-Type': 'application/json'};
          if (getIdToken) {
            let token;
            try { token = await getIdToken(audience, {signal: controller.signal}); }
            catch { guard.ensureActive(); throw new CollectorCallError('catalog_auth_unavailable'); }
            guard.ensureActive();
            if (typeof token !== 'string' || !token || /[\r\n]/.test(token))
              throw new CollectorCallError('catalog_auth_unavailable');
            headers.Authorization = 'Bearer ' + token;
            setPhase('fetch');
          }
          let response;
          try {
            response = await fetchImpl(new URL('/collector-journey', base),
              {method: 'POST', headers, body, redirect: 'error', signal: controller.signal});
          } catch { guard.ensureActive(); throw new CollectorCallError('catalog_transport_error', true); }
          // A fetch that ignored cancellation can resolve after this attempt's
          // watchdog. Dispose that late response without consuming its body.
          guard.setCleanup(() => response.body?.cancel());
          guard.ensureActive();
          setPhase('headers');
          httpStatus = Number.isInteger(response.status) && response.status >= 100 && response.status <= 599
            ? response.status : null;
          if (onAttempt) diagnostics = responseDiagnostics(response.headers);
          // These explicit rejections cannot improve by replaying the same
          // expensive transcript immediately. Preserve the caller session.
          const runtimeError = response.headers.get('x-collector-error');
          if ((response.status === 504 && runtimeError === 'catalog_work_budget_exceeded')
              || (response.status === 503 && runtimeError === 'catalog_snapshot_changed'))
            throw new CollectorCallError(runtimeError);
          if ([429, 502, 503, 504].includes(response.status)) {
            const retryAfter = response.headers.get('retry-after');
            if (response.status === 503 && runtimeError === 'catalog_busy'
                && retryAfter !== null && /^\d+$/.test(retryAfter))
              retryWaitMs = Math.max(retryDelayMs, Math.min(1000, Number(retryAfter) * 1000));
            throw new CollectorCallError('catalog_temporarily_unavailable', true);
          }
          if ([401, 403].includes(response.status)) throw new CollectorCallError('catalog_access_denied');
          if (response.status !== 200 && response.status !== 400) throw new CollectorCallError('catalog_http_error');
          if (!(response.headers.get('content-type') || '').toLowerCase().startsWith('application/json'))
            throw new CollectorCallError('invalid_catalog_response');
          setPhase('body');
          const result = await readBounded(response, maxResponseBytes, guard);
          guard.ensureActive();
          setPhase('validate');
          if (response.status === 400) {
            if (request.expected_revision && result?.error ===
                'catalog or journey policy changed; replay without the old revision and reconfirm the target')
              return {schema: 'pokemon.pivota-collector-call.v1', status: 'catalog_changed',
                session: null, result: null, target_intent: null,
                next_step: {field: 'restart_and_reconfirm',
                  prompt: 'The catalog changed. Start the collection question again and reconfirm the target.'}};
            throw new CollectorCallError('catalog_rejected_action');
          }
          validateResult(result, request);
          guard.ensureActive();
          return {schema: 'pokemon.pivota-collector-call.v1', status: 'accepted',
            session: {schema: SESSION, turns: jsonCopy(request.turns), limit: request.limit,
              expected_revision: result.catalog_revision}, result,
            target_intent: result.target_intent, next_step: result.next_step};
        } finally { cleanup(); }
      };
      let call; let failure;
      try {
        call = await Promise.race([execute(), stopped]);
        guard.ensureActive();
        setPhase('complete');
      } catch (error) {
        failure = stopError || sanitizedFailure(error);
        controller.abort(); cleanup();
      } finally {
        clearTimeout(timer); signal?.removeEventListener('abort', abort);
      }
      const retry = !!failure?.retryable && attempt === 0 && !signal?.aborted;
      if (onAttempt) {
        const ended = performance.now();
        const duration = key => {
          const value = key === phase ? ended - phaseStarted : timings[key];
          return value === null ? null : Math.round(value * 1000) / 1000;
        };
        // Deliberately allowlisted values only: no URL, raw headers, token,
        // body, exception message/reason, question, session or target evidence.
        // cleanup_state is its state at emission, not proof of remote teardown.
        const event = Object.freeze({schema: 'pokemon.collector-attempt.v1', attempt: attempt + 1,
          outcome: failure ? 'error' : call.status, phase,
          duration_ms: Math.round((ended - started) * 1000) / 1000,
          auth_ms: duration('auth'), headers_ms: duration('fetch'), body_ms: duration('body'),
          http_status: httpStatus, ...diagnostics, error_class: failure?.code || null,
          retryable: !!failure?.retryable, retry_delay_ms: retry ? retryWaitMs : 0,
          abort_requested: controller.signal.aborted, cleanup_state: cleanupState});
        bestEffort(() => onAttempt(event));
      }
      if (!failure) return call;
      if (!retry) throw failure;
      await retrySleep(retryWaitMs, signal);
    }
  }
  return Object.freeze({advance, start: ({question, limit = 5, signal} = {}) =>
    advance({action: {type: 'ask', question}, limit, signal})});
}

module.exports = {createCollectorClient, CollectorCallError};
