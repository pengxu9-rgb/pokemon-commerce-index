'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createCollectorClient} = require('./collectorClient.cjs');
const revision = 'a'.repeat(64);
const ask = {type: 'ask', question: 'Japanese Pikachu cards'};
function result(request, changes = {}) {
  return {schema: 'pokemon.collector-journey.v1', status: 'candidate_clarification_needed',
    catalog_revision: revision, turn_count: request.turns.length,
    trace: request.turns.map(t => ({action: t.type})), candidate_cards: [],
    artwork_review_leads: [], selection_blockers: [], selection_allowed: false,
    next_step: {field: 'card_id'}, target_intent: null, selected_catalog_target: null,
    prices: [], live_offers: [], conversation_persisted: false, inventory_persisted: false,
    ownership_assertions_verified: false, physical_copy_verified: false,
    ready_for_offer_tracking: false, purchase_ready: false, complete_collection_established: false,
    public_display_allowed: false, preferences_applied_to_market: false, ...changes};
}
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
}
function client(fetchImpl, options = {}) {
  return createCollectorClient({baseUrl: 'https://catalog.example', getIdToken: async () => 'private-test-token',
    fetchImpl, retryDelayMs: 0, ...options});
}
test('authenticated caller replays unchanged prior actions/revision, without ACP/AP2 state', async () => {
  const requests = []; const audiences = [];
  const c = client(async (url, options) => {
    assert.equal(String(url), 'https://catalog.example/collector-journey');
    assert.equal(options.redirect, 'error'); assert.equal(options.headers.Authorization, 'Bearer private-test-token');
    const request = JSON.parse(options.body); requests.push(request); return json(result(request));
  }, {getIdToken: async audience => {audiences.push(audience); return 'private-test-token';}});
  const first = await c.start({question: ask.question}); const saved = structuredClone(first.session);
  const second = await c.advance({session: first.session, action: {type: 'reply', text: 'Japanese'}});
  assert.deepEqual(first.session, saved); assert.deepEqual(requests[1].turns[0], ask);
  assert.equal(requests[1].expected_revision, revision); assert.equal(second.session.turns.length, 2);
  assert.deepEqual(audiences, ['https://catalog.example', 'https://catalog.example']);
  assert.equal(JSON.stringify(second).includes('private-test-token'), false);
  assert.equal('acp_state' in second.session, false); assert.equal('ap2_state' in second.session, false);
});
test('catalog revision change withdraws handoff and requires restart/reconfirmation without silent replay', async () => {
  let calls = 0;
  const c = client(async () => {calls++; return json({error:
    'catalog or journey policy changed; replay without the old revision and reconfirm the target'}, 400);});
  const session = {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 20, expected_revision: revision};
  const original = structuredClone(session);
  const r = await c.advance({session, action: {type: 'reply', text: 'Japanese'}});
  assert.equal(r.status, 'catalog_changed'); assert.equal(r.session, null); assert.equal(r.target_intent, null);
  assert.equal(r.next_step.field, 'restart_and_reconfirm'); assert.equal(calls, 1); assert.deepEqual(session, original);
});
test('transient failures retry at most once and refresh the server identity token', async () => {
  let calls = 0; let tokens = 0;
  const c = client(async (_, options) => {calls++; return calls === 1 ? json({}, 503) : json(result(JSON.parse(options.body)));},
    {getIdToken: async () => 'token-' + ++tokens});
  await c.start({question: ask.question}); assert.equal(calls, 2); assert.equal(tokens, 2);
  calls = 0;
  await assert.rejects(client(async () => {calls++; return json({}, 429);}).start({question: ask.question}),
    e => e.code === 'catalog_temporarily_unavailable' && e.retryable);
  assert.equal(calls, 2);
});
test('action/auth rejections are not retried and service error text cannot leak caller secrets', async () => {
  for (const [status, code] of [[400, 'catalog_rejected_action'], [403, 'catalog_access_denied'], [500, 'catalog_http_error']]) {
    let calls = 0;
    await assert.rejects(client(async () => {calls++; return json({error: 'private-test-token'}, status);}).start({question: ask.question}),
      e => e.code === code && !e.message.includes('private-test-token'));
    assert.equal(calls, 1);
  }
  await assert.rejects(client(async () => {throw new Error('should not fetch');},
    {getIdToken: async () => {throw new Error('private-test-token');}}).start({question: ask.question}),
    e => e.code === 'catalog_auth_unavailable' && !e.message.includes('private-test-token'));
});
test('timeouts cancel fetch and token lookup, with bounded retries', async () => {
  let calls = 0;
  await assert.rejects(client(async (_, options) => {calls++; return new Promise((_, reject) =>
    options.signal.addEventListener('abort', () => reject(new Error('aborted'))));}, {timeoutMs: 50}).start({question: ask.question}),
    e => e.code === 'catalog_timeout');
  assert.equal(calls, 2);
  await assert.rejects(client(async () => {throw new Error('should not fetch');},
    {timeoutMs: 50, getIdToken: async () => new Promise(() => {})}).start({question: ask.question}),
    e => e.code === 'catalog_timeout');
});
test('malformed/oversized/mismatched responses and invented commerce approvals fail closed', async () => {
  for (const changes of [{purchase_ready: true}, {prices: [{price: 10}]}, {public_display_allowed: undefined},
    {status: 'invented'}, {turn_count: 100}, {target_intent: {product_url: 'https://buy.example'}}]) {
    await assert.rejects(client(async (_, o) => json(result(JSON.parse(o.body), changes))).start({question: ask.question}),
      e => e.code === 'invalid_catalog_response');
  }
  await assert.rejects(client(async () => new Response('not-json', {headers: {'Content-Type': 'application/json'}})).start({question: ask.question}),
    e => e.code === 'invalid_catalog_response');
  await assert.rejects(client(async () => json({large: 'x'.repeat(2000)}), {maxResponseBytes: 1024}).start({question: ask.question}),
    e => e.code === 'response_too_large');
  const c = client(async (_, o) => json(result(JSON.parse(o.body), {catalog_revision: 'b'.repeat(64)})));
  await assert.rejects(c.advance({session: {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 20, expected_revision: revision}, action: {type: 'reply', text: 'Japanese'}}),
    e => e.code === 'invalid_catalog_response');
});
test('target handoff requires exact matching catalog coordinates and every commerce gate remains false', async () => {
  const card = {card_id: 'ja:SV2A:025/165:normal', language: 'ja', set_code: 'SV2A', collector_number: '025/165', variant: 'normal', provenance: 'fixture'};
  const target = {contract: 'pokemon.collector-target-intent.v1', card_id: card.card_id, language: 'ja', set_code: 'SV2A', collector_number: '025/165', source_declared_variant: 'normal', catalog_provenance: 'fixture', preferences_evidence: 'user_assertion_only', transaction_ready: false, automatic_offer_join_allowed: false, physical_printing_verified: false, public_display_allowed: false, priceable_unit_id: null, product_url: null, quote: null};
  for (const patch of [{}, {source_declared_variant: 'holo'}, {transaction_ready: true}, {quote: {amount: 1}}]) {
    const c = client(async (_, o) => json(result(JSON.parse(o.body), {status: 'catalog_target_selected', selection_allowed: true, selected_catalog_target: card, target_intent: {...target, ...patch}})));
    if (!Object.keys(patch).length) assert.equal((await c.start({question: ask.question})).target_intent.card_id, card.card_id);
    else await assert.rejects(c.start({question: ask.question}), e => e.code === 'invalid_catalog_response');
  }
});
test('caller cannot inject derived approvals, truncate a 20-action journey, or mutate an in-flight snapshot', async () => {
  let calls = 0;
  const c = client(async (_, o) => {calls++; return json(result(JSON.parse(o.body)));});
  await assert.rejects(c.advance({action: {...ask, purchase_ready: true}}), e => e.code === 'invalid_action');
  await assert.rejects(c.advance({session: {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 20, expected_revision: revision, target_intent: {}}, action: ask}), e => e.code === 'invalid_caller_state');
  await assert.rejects(c.advance({session: {schema: 'pokemon.pivota-collector-session.v1', turns: Array(20).fill(ask), limit: 20, expected_revision: revision}, action: ask}), e => e.code === 'journey_turn_limit');
  await assert.rejects(c.start({question: 'x'.repeat(262144)}), e => e.code === 'request_too_large');
  assert.equal(calls, 0);
  let unblock;
  const paused = client(async (_, o) => json(result(JSON.parse(o.body))),
    {getIdToken: () => new Promise(resolve => {unblock = resolve;})});
  const action = structuredClone(ask); const pending = paused.advance({action});
  action.question = 'altered after dispatch'; unblock('private-test-token');
  assert.equal((await pending).session.turns[0].question, ask.question);
});
test('service URL is trusted setup only, credentials/redirects/cleartext remote calls are rejected', () => {
  for (const baseUrl of ['http://catalog.example', 'https://user:pass@catalog.example', 'https://catalog.example/?token=x', 'https://catalog.example/other'])
    assert.throws(() => client(async () => {}, {baseUrl}), e => e.code === 'invalid_service_url');
  assert.throws(() => createCollectorClient({baseUrl: 'https://catalog.example'}), e => e.code === 'invalid_client_configuration');
  assert.doesNotThrow(() => createCollectorClient({baseUrl: 'http://127.0.0.1:8766', allowLoopback: true}));
});
test('two-card discovery passes partial metadata and rejects nested commerce approvals', async () => {
  const comparison = {schema: 'pokemon.card-comparison.v1', status: 'catalog_partial',
    same_physical_printing_established: false, physical_finish_verified: false,
    copy_condition_verified: false, price_comparable: false, price_series_merge_allowed: false,
    numeric_price_gap_available: false, automatic_offer_join_allowed: false, purchase_ready: false,
    public_display_allowed: false, complete_answer_established: false,
    prices: [], live_offers: [], product_url: null};
  for (const patch of [{}, {price_comparable: true}, {prices: [{amount: 1}]}, {physical_finish_verified: true}]) {
    const c = client(async (_, options) => json(result(JSON.parse(options.body), {
      status: 'evidence_or_scope_needed', selection_blockers: ['supported_catalog_scope_needed'],
      discovery: {task: 'two_card_comparison', comparison: {...comparison, ...patch}},
    })));
    if (!Object.keys(patch).length) {
      const call = await c.start({question: 'Compare Japanese SM1M 18/60 and English SM1 50/149'});
      assert.equal(call.result.discovery.comparison.schema, comparison.schema);
      assert.equal(call.target_intent, null);
    } else await assert.rejects(c.start({question: 'Compare two cards'}),
      error => error.code === 'invalid_catalog_response');
  }
});
