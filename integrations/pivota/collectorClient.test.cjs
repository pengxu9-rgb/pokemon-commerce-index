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
    artwork_review_leads: [], selection_blockers: [], card_selection_blockers: {}, recommendation: null, selection_allowed: false,
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
  const card = {card_id: 'ja:SV2A:025/165:normal', language: 'ja', set_code: 'SV2A', collector_number: '025/165', variant: 'normal', provenance: 'fixture', structural_match_eligible: true, automatic_offer_join_allowed: false, price_comparable: false};
  const target = {contract: 'pokemon.collector-target-intent.v1', card_id: card.card_id, language: 'ja', set_code: 'SV2A', collector_number: '025/165', source_declared_variant: 'normal', catalog_provenance: 'fixture', preferences_evidence: 'user_assertion_only', transaction_ready: false, automatic_offer_join_allowed: false, physical_printing_verified: false, public_display_allowed: false, priceable_unit_id: null, product_url: null, quote: null};
  for (const patch of [{}, {source_declared_variant: 'holo'}, {transaction_ready: true}, {quote: {amount: 1}}]) {
    const c = client(async (_, o) => json(result(JSON.parse(o.body), {status: 'catalog_target_selected', selection_allowed: true, candidate_cards: [card], card_selection_blockers: {[card.card_id]: []}, selected_catalog_target: card, target_intent: {...target, ...patch}})));
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

test('new actions have exact contracts and bounded nested collecting preferences', async () => {
  let calls = 0;
  const c = client(async (_, o) => {calls++; return json(result(JSON.parse(o.body)));});
  for (const action of [
    {type: 'feedback', card_id: 'A', reaction: 'like'},
    {type: 'compare', left_card_id: 'A', right_card_id: 'B'},
    {type: 'choose_comparison', side: 'right', card_id: 'B'},
    {type: 'preferences', preferences: {collecting: {preferred_dex_ids: [25], preferred_releases: [{language: 'ja', set_code: 'FIX'}]}}},
  ]) {
    const session = (await c.start({question: ask.question})).session;
    assert.equal((await c.advance({session, action})).session.turns.at(-1).type, action.type);
  }
  const before = calls;
  for (const collecting of [{preferred_dex_ids: [true]}, {preferred_dex_ids: Array(21).fill(25)},
    {preferred_dex_ids: [25,25]}, {preferred_dex_ids: [25], excluded_dex_ids: [25]},
    {preferred_releases: [{language: 'ja', set_code: 'FIX', purchase_ready: true}]},
    {subjective_notes: ['x'.repeat(161)]}, {mode: 'buy'}, {automatic_offer_join_allowed: true}]) {
    await assert.rejects(c.advance({session: (await c.start({question: ask.question})).session,
      action: {type: 'preferences', preferences: {collecting}}}), e => e.code === 'invalid_action');
  }
  assert.equal(calls - before, 8); // Only the prerequisite asks reached the service.
  await assert.rejects(c.advance({action: {type: 'feedback', card_id: 'A', reaction: 'love'}}), e => e.code === 'invalid_action');
  await assert.rejects(c.advance({action: {type: 'compare', left_card_id: 'A', right_card_id: 'A'}}), e => e.code === 'invalid_action');
});

test('recommendation page is bound to exact IDs, provenance, rank and unknown market fit', async () => {
  const card = {card_id: 'ja:FIX:001/100:normal', language: 'ja', set_code: 'FIX', collector_number: '001/100', structural_match_eligible: true, automatic_offer_join_allowed: false, price_comparable: false};
  const recommendation = {schema: 'pokemon.collector-recommendation.v1',
    ranking_policy: 'explicit_axes_then_liked_axes_then_coordinate_round_robin.v1',
    preference_evidence: 'user_assertion_only', candidate_pool_complete: true,
    coverage_basis: 'current_catalog_facets_and_reviewed_name_affiliations_only', global_catalog_completeness_established: false,
    unapplied_preferences: [{value: 'cute', reason: 'no_source_backed_style_labels'}],
    budget_fit: 'unknown_no_live_price', grade_availability: 'unknown_no_copy_offers',
    items: [{card_id: card.card_id, rank: 1, explicit_match_axes: ['character'], liked_example_match_axes: [],
      reasons: [{field: 'dex_id', value: 25, basis: 'catalog_facet', source_ref: 'synthetic:facet', rights_reference: 'synthetic'}], tradeoffs: ['No market evidence']}],
    coordinate_groups: [{language: 'ja', set_code: 'FIX', collector_number: '001/100', shown_card_ids: [card.card_id], physical_versions_merged: false}]};
  const cases = [() => {}, r => {r.budget_fit = 'within_budget';}, r => {r.items[0].card_id = 'invented';},
    r => {r.items[0].rank = 2;}, r => {r.items[0].purchase_ready = true;},
    r => {r.items[0].reasons[0].value = {purchase_ready: true};}, r => {r.items[0].reasons[0].source_ref = '';},
    r => {r.coordinate_groups[0].physical_versions_merged = true;}];
  for (let i = 0; i < cases.length; i++) {
    const rec = structuredClone(recommendation); cases[i](rec);
    const c = client(async (_, o) => json(result(JSON.parse(o.body), {candidate_cards: [card],
      card_selection_blockers: {[card.card_id]: []}, recommendation: rec,
      discovery: {task: 'collector_recommendations', coverage: {offset: 0}}})));
    if (!i) assert.equal((await c.start({question: 'Recommend Pikachu cards'})).result.recommendation.items.length, 1);
    else await assert.rejects(c.start({question: 'Recommend Pikachu cards'}), e => e.code === 'invalid_catalog_response');
  }
});

test('nested candidate evidence cannot mint physical or commerce approvals', async () => {
  for (const field of ['public_display_allowed', 'price_comparable', 'physical_copy_verified', 'transaction_ready']) {
    const card = {card_id: 'A', automatic_offer_join_allowed: false, price_comparable: false, evidence: {[field]: true}};
    await assert.rejects(client(async (_, o) => json(result(JSON.parse(o.body), {
      candidate_cards: [card], card_selection_blockers: {A: []}}))).start({question: ask.question}),
      e => e.code === 'invalid_catalog_response');
  }
});

test('typed name affiliations require exact current candidate and anchor proof shapes', async () => {
  const pin = require('../../pokemon_index/collector-character-affiliations-v1.json').records[0];
  const card = {...pin.identity, automatic_offer_join_allowed: false, price_comparable: false};
  const proof = {field: 'character_name_affiliation', value: 151, basis: 'source_name_character_affiliation',
    source_ref: card.provenance, target_name: card.name, base_name_ja: 'ミュウ', mechanic: 'EX',
    source_asserted_dex_id: false, anchor_evidence: [{card_id: 'ja:ANCHOR:001/100:normal', name: 'ミュウ',
      dex_id: 151, provenance: 'synthetic:anchor', rights_reference: 'synthetic:rights'}],
    anchor_count: 4, anchor_evidence_sha256: 'b'.repeat(64),
    derivation: 'exact_pinned_ex_name_to_unanimous_current_name_facets.v1',
    affiliated_card_id: card.card_id, affiliation_role: 'candidate', preference_origin: 'explicit_preference'};
  const recommendation = {schema: 'pokemon.collector-recommendation.v1',
    ranking_policy: 'explicit_axes_then_liked_axes_then_coordinate_round_robin.v1',
    preference_evidence: 'user_assertion_only', candidate_pool_complete: true,
    coverage_basis: 'current_catalog_facets_and_reviewed_name_affiliations_only', global_catalog_completeness_established: false,
    unapplied_preferences: [], budget_fit: 'unknown_no_live_price', grade_availability: 'unknown_no_copy_offers',
    items: [{card_id: card.card_id, rank: 1, explicit_match_axes: ['character'], liked_example_match_axes: [],
      reasons: [proof], tradeoffs: ['Derived name affiliation, not a source-provided dexId']}],
    coordinate_groups: [{language: 'ja', set_code: 'SV4A', collector_number: card.collector_number,
      shown_card_ids: [card.card_id], physical_versions_merged: false}]};
  const cases = [() => {}, p => {p.source_asserted_dex_id = true;}, p => {p.basis = 'catalog_facet';},
    p => {p.target_name = 'ミュウツーex';}, p => {p.source_ref = 'other';}, p => {p.affiliated_card_id = 'other';},
    p => {p.anchor_count = 0;}, p => {p.anchor_evidence_sha256 = 'forged';}, p => {p.anchor_evidence = [];},
    p => {p.anchor_evidence[0].dex_id = 150;}, p => {p.anchor_evidence[0].name = 'ミュウツー';},
    p => {p.anchor_evidence[0].rights_reference = '';}, p => {p.anchor_evidence[0].purchase_ready = true;},
    p => {p.affiliation_role = 'liked_example'; p.preference_origin = 'liked_example';}];
  for (let i = 0; i < cases.length; i++) {
    const rec = structuredClone(recommendation); cases[i](rec.items[0].reasons[0]);
    const c = client(async (_, o) => json(result(JSON.parse(o.body), {candidate_cards: [card],
      card_selection_blockers: {[card.card_id]: []}, recommendation: rec,
      discovery: {task: 'collector_recommendations', coverage: {offset: 0}}})));
    if (!i) assert.equal((await c.start({question: 'Recommend Mew'})).result.recommendation.items[0].reasons[0].source_asserted_dex_id, false);
    else await assert.rejects(c.start({question: 'Recommend Mew'}), e => e.code === 'invalid_catalog_response');
  }
  const rec = structuredClone(recommendation);
  rec.items[0].explicit_match_axes = []; rec.items[0].liked_example_match_axes = ['character'];
  rec.items[0].reasons[0].affiliation_role = 'liked_example'; rec.items[0].reasons[0].preference_origin = 'liked_example';
  const c = client(async (_, o) => json(result(JSON.parse(o.body), {candidate_cards: [card],
    card_selection_blockers: {[card.card_id]: []}, recommendation: rec,
    discovery: {task: 'collector_recommendations', coverage: {offset: 0}}})));
  const session = {schema: 'pokemon.pivota-collector-session.v1', turns: [ask,
    {type: 'feedback', card_id: card.card_id, reaction: 'like'}], limit: 5, expected_revision: revision};
  await assert.rejects(c.advance({session, action: {type: 'page', offset: 0}}),
    e => e.code === 'invalid_catalog_response');
  rec.items[0].reasons.push({...structuredClone(proof), preference_origin: 'liked_example'});
  assert.equal((await c.advance({session, action: {type: 'page', offset: 0}})).status, 'accepted');
  await assert.rejects(c.advance({session, action: {type: 'feedback', card_id: card.card_id, reaction: 'clear'}}),
    e => e.code === 'invalid_catalog_response');
});

test('explicit work-budget and changed-snapshot rejections do not repeat expensive transcripts', async () => {
  for (const [status, code] of [[504, 'catalog_work_budget_exceeded'], [503, 'catalog_snapshot_changed']]) {
    let calls = 0;
    const session = {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 5, expected_revision: revision};
    const saved = JSON.stringify(session);
    const c = client(async () => {
      calls++;
      return new Response(JSON.stringify({error: code}), {status,
        headers: {'Content-Type': 'application/json', 'X-Collector-Error': code, 'Retry-After': '1'}});
    });
    await assert.rejects(c.advance({session, action: {type: 'clear_target'}}), e => e.code === code && !e.retryable);
    assert.equal(calls, 1);
    assert.equal(JSON.stringify(session), saved);
  }
});

test('numeric Retry-After is honored but capped at one second without extra attempts', {timeout: 5000}, async () => {
  for (const hint of ['1', '999999999999999999999999999999999999999']) {
    let calls = 0;
    let firstAt;
    let retryAt;
    const c = client(async (_, options) => {
      calls++;
      if (calls === 1) {
        firstAt = performance.now();
        return new Response('{}', {status: 503, headers: {'Retry-After': hint, 'X-Collector-Error': 'catalog_busy'}});
      }
      retryAt = performance.now();
      return json(result(JSON.parse(options.body)));
    });
    assert.equal((await c.start({question: ask.question})).status, 'accepted');
    assert.equal(calls, 2);
    assert.ok(retryAt - firstAt >= 900, 'retry ignored the server backoff hint');
    assert.ok(retryAt - firstAt < 2000, 'retry hint escaped the bounded one-second wait');
  }
});

test('absent, malformed, negative and date hints do not add waits; only exact catalog busy is eligible', async () => {
  const cases = [
    [503, 'catalog_busy', null], [503, 'catalog_busy', 'invalid'],
    [503, 'catalog_busy', '-1'], [503, 'catalog_busy', 'Wed, 01 Jan 2098 00:00:00 GMT'],
    [503, 'unknown', '1'], [502, 'catalog_busy', '1']];
  for (const [status, code, hint] of cases) {
    let calls = 0; let firstAt; let retryAt;
    const c = client(async (_, options) => {
      calls++;
      if (calls === 1) {
        firstAt = performance.now();
        const headers = {'X-Collector-Error': code};
        if (hint !== null) headers['Retry-After'] = hint;
        return new Response('{}', {status, headers});
      }
      retryAt = performance.now();
      return json(result(JSON.parse(options.body)));
    });
    assert.equal((await c.start({question: ask.question})).status, 'accepted');
    assert.equal(calls, 2);
    assert.ok(retryAt - firstAt < 900, 'unsupported hint replaced the configured zero retry delay');
  }
});
