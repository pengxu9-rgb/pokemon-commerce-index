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
function actionCopy(value) {
  const fields = ACTION_FIELDS[value?.type];
  if (!fields || !exactKeys(value, fields)) throw new CollectorCallError('invalid_action');
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
  const intent = result.target_intent;
  if (result.status === 'catalog_target_selected') {
    if (!intent || intent.contract !== 'pokemon.collector-target-intent.v1'
        || !result.selected_catalog_target
        || intent.card_id !== result.selected_catalog_target.card_id
        || !result.selection_allowed || result.selection_blockers.length
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
async function readBounded(response, maxBytes) {
  const declared = response.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > maxBytes)) {
    await response.body?.cancel(); throw new CollectorCallError('response_too_large');
  }
  if (!response.body) throw new CollectorCallError('invalid_catalog_response');
  const reader = response.body.getReader(); const chunks = []; let total = 0;
  try {
    while (true) {
      const {done, value} = await reader.read(); if (done) break;
      total += value.byteLength;
      if (total > maxBytes) throw new CollectorCallError('response_too_large');
      chunks.push(Buffer.from(value));
    }
  } finally { await reader.cancel().catch(() => {}); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new CollectorCallError('invalid_catalog_response'); }
}

function createCollectorClient({baseUrl, getIdToken, fetchImpl = globalThis.fetch,
  allowLoopback = false, timeoutMs = 10000, retryDelayMs = 200, maxResponseBytes = 8 * 1024 * 1024} = {}) {
  let base; try { base = new URL(baseUrl); } catch { throw new CollectorCallError('invalid_service_url'); }
  const local = allowLoopback && base.protocol === 'http:' && base.hostname === '127.0.0.1';
  if ((!local && base.protocol !== 'https:') || base.username || base.password
      || base.search || base.hash || base.pathname !== '/') throw new CollectorCallError('invalid_service_url');
  if ((!local && typeof getIdToken !== 'function') || typeof fetchImpl !== 'function'
      || !Number.isInteger(timeoutMs) || timeoutMs < 50 || timeoutMs > 30000
      || !Number.isInteger(retryDelayMs) || retryDelayMs < 0 || retryDelayMs > 1000
      || !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1024 || maxResponseBytes > 16 * 1024 * 1024)
    throw new CollectorCallError('invalid_client_configuration');
  const audience = base.origin;
  async function advance({session = null, action, limit = 20} = {}) {
    const request = requestFor(session, action, limit); const body = JSON.stringify(request);
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const headers = {'Content-Type': 'application/json'};
        if (getIdToken) {
          let token;
          try { token = await Promise.race([getIdToken(audience, {signal: controller.signal}),
            new Promise((_, reject) => controller.signal.addEventListener('abort',
              () => reject(new CollectorCallError('catalog_timeout', true)), {once: true}))]); }
          catch (err) {
            if (err instanceof CollectorCallError) throw err;
            throw new CollectorCallError('catalog_auth_unavailable');
          }
          if (typeof token !== 'string' || !token || /[\r\n]/.test(token))
            throw new CollectorCallError('catalog_auth_unavailable');
          headers.Authorization = 'Bearer ' + token;
        }
        const response = await fetchImpl(new URL('/collector-journey', base),
          {method: 'POST', headers, body, redirect: 'error', signal: controller.signal});
        if ([429, 502, 503, 504].includes(response.status)) {
          await response.body?.cancel(); throw new CollectorCallError('catalog_temporarily_unavailable', true);
        }
        if ([401, 403].includes(response.status)) {
          await response.body?.cancel(); throw new CollectorCallError('catalog_access_denied');
        }
        if (response.status !== 200 && response.status !== 400) {
          await response.body?.cancel(); throw new CollectorCallError('catalog_http_error');
        }
        if (!(response.headers.get('content-type') || '').toLowerCase().startsWith('application/json'))
          throw new CollectorCallError('invalid_catalog_response');
        const result = await readBounded(response, maxResponseBytes);
        if (response.status === 400) {
          if (request.expected_revision && result.error ===
              'catalog or journey policy changed; replay without the old revision and reconfirm the target')
            return {schema: 'pokemon.pivota-collector-call.v1', status: 'catalog_changed',
              session: null, result: null, target_intent: null,
              next_step: {field: 'restart_and_reconfirm',
                prompt: 'The catalog changed. Start the collection question again and reconfirm the target.'}};
          throw new CollectorCallError('catalog_rejected_action');
        }
        validateResult(result, request);
        return {schema: 'pokemon.pivota-collector-call.v1', status: 'accepted',
          session: {schema: SESSION, turns: jsonCopy(request.turns), limit: request.limit,
            expected_revision: result.catalog_revision}, result,
          target_intent: result.target_intent, next_step: result.next_step};
      } catch (error) {
        const safe = error instanceof CollectorCallError ? error :
          new CollectorCallError(controller.signal.aborted ? 'catalog_timeout' : 'catalog_transport_error', true);
        if (!safe.retryable || attempt === 1) throw safe;
      } finally { clearTimeout(timer); }
      if (retryDelayMs) await new Promise(resolve => setTimeout(resolve, retryDelayMs));
    }
  }
  return Object.freeze({advance, start: ({question, limit = 20} = {}) =>
    advance({action: {type: 'ask', question}, limit})});
}

module.exports = {createCollectorClient, CollectorCallError};
