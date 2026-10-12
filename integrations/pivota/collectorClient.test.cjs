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

test('source-scan ranking policy stays metadata-only and rejects unknown policies', async () => {
  const card = {card_id: 'en:FIX:001/100:normal', language: 'en', set_code: 'FIX', collector_number: '001/100', automatic_offer_join_allowed: false, price_comparable: false,
    media_availability: {schema: 'pokemon.catalog-media-availability.v1', status: 'current_source_scan_evidence', evidence_basis: 'number_reading', with_source_scans_eligible: true, live_fetch_verified: false, display_allowed: false, physical_printing_verified: false}};
  const rec = {schema: 'pokemon.collector-recommendation.v1', ranking_policy: 'explicit_axes_then_liked_axes_then_source_scan_tiebreak_then_coordinate_round_robin.v2',
    preference_evidence: 'user_assertion_only', candidate_pool_complete: true, coverage_basis: 'current_source_declared_catalog_and_facets_only', global_catalog_completeness_established: false,
    unapplied_preferences: [], budget_fit: 'unknown_no_live_price', grade_availability: 'unknown_no_copy_offers',
    items: [{card_id: card.card_id, rank: 1, explicit_match_axes: ['character'], liked_example_match_axes: [], reasons: [{field: 'dex_id', value: 35, basis: 'catalog_facet', source_ref: 'synthetic', rights_reference: 'synthetic'}], tradeoffs: ['No live image or market claim']}],
    coordinate_groups: [{language: 'en', set_code: 'FIX', collector_number: '001/100', shown_card_ids: [card.card_id], physical_versions_merged: false}]};
  const call = value => client(async (_, options) => json(result(JSON.parse(options.body), {candidate_cards: [card], card_selection_blockers: {[card.card_id]: []}, recommendation: value, discovery: {task: 'collector_recommendations', coverage: {offset: 0}}}))).start({question: 'Recommend Cleffa cards'});
  assert.equal((await call(rec)).result.recommendation.ranking_policy, rec.ranking_policy);
  assert.equal((await call({...rec, coverage_basis: 'current_catalog_facets_and_reviewed_name_affiliations_only'})).status, 'accepted');
  await assert.rejects(call({...rec, ranking_policy: 'invented_image_approval'}), error => error.code === 'invalid_catalog_response');
  await assert.rejects(call({...rec, coverage_basis: 'invented_review'}), error => error.code === 'invalid_catalog_response');
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
  const sourceOnly = {...recommendation, coverage_basis: 'current_source_declared_catalog_and_facets_only'};
  const sourceOnlyClient = client(async (_, o) => json(result(JSON.parse(o.body), {candidate_cards: [card],
    card_selection_blockers: {[card.card_id]: []}, recommendation: sourceOnly,
    discovery: {task: 'collector_recommendations', coverage: {offset: 0}}})));
  await assert.rejects(sourceOnlyClient.start({question: 'Recommend Mew'}), e => e.code === 'invalid_catalog_response');
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

const never = () => new Promise(() => {});
const tick = () => new Promise(resolve => setImmediate(resolve));

test('the attempt watchdog bounds fetch/body waits even when AbortSignal is ignored', {timeout: 3000}, async () => {
  for (const stalled of ['fetch', 'body']) {
    let calls = 0; let cancellations = 0; const signals = []; const attempts = [];
    const c = client(async (_, options) => {
      calls++; signals.push(options.signal);
      if (stalled === 'fetch') return never();
      return {status: 200, headers: new Headers({'Content-Type': 'application/json'}),
        body: {getReader: () => ({read: never, cancel: () => {cancellations++; return never();}})}};
    }, {timeoutMs: 50, onAttempt: event => attempts.push(event)});
    const began = performance.now();
    await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_timeout' && e.retryable);
    assert.ok(performance.now() - began < 1000, 'attempt deadline waited for an uncooperative dependency');
    assert.equal(calls, 2); assert.ok(signals.every(signal => signal.aborted));
    assert.equal(cancellations, stalled === 'body' ? 2 : 0);
    assert.deepEqual(attempts.map(event => event.phase), [stalled, stalled]);
    assert.ok(attempts.every(event => event.abort_requested && event.error_class === 'catalog_timeout'));
  }
});

test('late token results cannot dispatch fetch after timed-out attempts', {timeout: 1000}, async () => {
  const finishTokens = []; let calls = 0;
  const c = client(async () => {calls++; throw new Error('unexpected late fetch');}, {timeoutMs: 50,
    getIdToken: () => new Promise(resolve => finishTokens.push(resolve))});
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_timeout');
  assert.equal(finishTokens.length, 2);
  finishTokens.forEach(resolve => resolve('late-private-token'));
  await tick();
  assert.equal(calls, 0);
});

test('late fetch responses are discarded and disposed without consuming their bodies', {timeout: 1000}, async () => {
  const finishFetches = []; let reads = 0; let cancelled = 0; const events = [];
  const c = client(() => new Promise(resolve => finishFetches.push(resolve)), {timeoutMs: 50,
    onAttempt: event => events.push(event)});
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_timeout');
  finishFetches.forEach(resolve => resolve({status: 200,
    headers: new Headers({'Content-Type': 'application/json'}), body: {
      cancel() {cancelled++; return never();}, getReader() {reads++; throw new Error('unexpected read');},
    }}));
  await tick();
  assert.equal(finishFetches.length, 2); assert.equal(cancelled, 2); assert.equal(reads, 0);
  assert.equal(events.length, 2);
});

test('stalled or rejected response cleanup cannot change error classes or retry policy', {timeout: 1500}, async () => {
  for (const cancel of [never, () => Promise.reject(new Error('private cleanup')), () => {throw new Error('private cleanup');}]) {
    for (const [status, runtimeError, expected, count] of [
      [503, 'catalog_busy', 'catalog_temporarily_unavailable', 2],
      [504, 'catalog_work_budget_exceeded', 'catalog_work_budget_exceeded', 1],
      [503, 'catalog_snapshot_changed', 'catalog_snapshot_changed', 1],
      [403, '', 'catalog_access_denied', 1], [500, '', 'catalog_http_error', 1],
      [200, '', 'invalid_catalog_response', 1],
    ]) {
      let calls = 0;
      const c = client(async () => {calls++; return {status,
        headers: new Headers({'X-Collector-Error': runtimeError, 'Content-Type': 'text/plain'}), body: {cancel}};
      }, {timeoutMs: 50});
      await assert.rejects(c.start({question: ask.question}), e => e.code === expected);
      assert.equal(calls, count);
    }
  }
  await tick(); // Rejected cleanup promises must be handled rather than escape the test.
});

test('completed, oversized and malformed reads do not wait for reader cancellation', {timeout: 1000}, async () => {
  for (const [body, code] of [[null, null], ['not-json', 'invalid_catalog_response'], ['x'.repeat(2000), 'response_too_large']]) {
    let calls = 0; let cancelled = 0;
    const c = client(async (_, options) => {
      calls++; let sent = false;
      const bytes = Buffer.from(body === null ? JSON.stringify(result(JSON.parse(options.body))) : body);
      return {status: 200, headers: new Headers({'Content-Type': 'application/json'}), body: {getReader: () => ({
        read: async () => sent ? {done: true} : (sent = true, {done: false, value: bytes}),
        cancel: () => {cancelled++; return never();},
      })}};
    }, {timeoutMs: 50, maxResponseBytes: body === null ? 4096 : 1024});
    if (code) await assert.rejects(c.start({question: ask.question}), e => e.code === code);
    else assert.equal((await c.start({question: ask.question})).status, 'accepted');
    assert.equal(calls, 1); assert.equal(cancelled, 1);
  }
});

test('external cancellation stops auth, fetch, body and pre-aborted calls without retry', {timeout: 2000}, async () => {
  for (const phase of ['auth', 'fetch', 'body', 'before']) {
    const controller = new AbortController(); const events = []; let calls = 0; let notifyStarted;
    const began = new Promise(resolve => {notifyStarted = resolve;});
    const c = client(async () => {
      calls++;
      if (phase === 'fetch') {notifyStarted(); return never();}
      return {status: 200, headers: new Headers({'Content-Type': 'application/json'}),
        body: {getReader: () => ({read: () => {notifyStarted(); return never();}, cancel: never})}};
    }, {getIdToken: phase === 'auth' ? () => {notifyStarted(); return never();} : async () => 'private-token',
      timeoutMs: 1000, onAttempt: event => events.push(event)});
    if (phase === 'before') controller.abort(new Error('private cancel reason'));
    const pending = c.start({question: ask.question, signal: controller.signal});
    if (phase !== 'before') {await began; controller.abort(new Error('private cancel reason'));}
    await assert.rejects(pending, e => e.code === 'catalog_cancelled' && !e.retryable && !e.message.includes('private'));
    assert.equal(calls, ['auth', 'before'].includes(phase) ? 0 : 1);
    assert.equal(events.length, phase === 'before' ? 0 : 1);
    assert.ok(events.every(event => event.error_class === 'catalog_cancelled' && !event.retryable));
  }
});

test('external cancellation interrupts the bounded retry wait and preserves the session snapshot', {timeout: 1000}, async () => {
  const controller = new AbortController(); let calls = 0; let notifyAttempt;
  const observed = new Promise(resolve => {notifyAttempt = resolve;});
  const session = {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 5, expected_revision: revision};
  const saved = structuredClone(session);
  const c = client(async () => {calls++; return new Response('{}', {status: 503,
    headers: {'X-Collector-Error': 'catalog_busy', 'Retry-After': '1'}});}, {
    onAttempt: event => notifyAttempt(event),
  });
  const pending = c.advance({session, action: {type: 'clear_target'}, signal: controller.signal});
  assert.equal((await observed).retry_delay_ms, 1000);
  await tick(); controller.abort('private reason');
  await assert.rejects(pending, e => e.code === 'catalog_cancelled');
  assert.equal(calls, 1); assert.deepEqual(session, saved);
});

test('attempt telemetry is opt-in, frozen, allowlisted and cannot alter accepted results', {timeout: 1000}, async () => {
  const events = []; const callbacks = [() => {throw new Error('private telemetry');},
    () => Promise.reject(new Error('private telemetry')), never];
  for (const callback of callbacks) {
    const c = client(async (_, options) => json(result(JSON.parse(options.body))), {
      timeoutMs: 50, onAttempt: event => {events.push(event); return callback(event);},
    });
    assert.equal((await c.start({question: 'private question'})).status, 'accepted');
  }
  const expectedKeys = ['schema', 'attempt', 'outcome', 'phase', 'duration_ms', 'auth_ms', 'headers_ms',
    'body_ms', 'http_status', 'request_id', 'server_timing_ms', 'error_class', 'retryable',
    'retry_delay_ms', 'abort_requested', 'cleanup_state'].sort();
  for (const event of events) {
    assert.deepEqual(Object.keys(event).sort(), expectedKeys);
    assert.ok(Object.isFrozen(event)); assert.ok(Object.isFrozen(event.server_timing_ms));
    assert.equal(event.schema, 'pokemon.collector-attempt.v1'); assert.equal(event.outcome, 'accepted');
    assert.equal(event.phase, 'complete'); assert.equal(event.error_class, null);
    assert.equal(event.http_status, 200); assert.equal(event.request_id, null);
    for (const field of ['duration_ms', 'auth_ms', 'headers_ms', 'body_ms'])
      assert.ok(Number.isFinite(event[field]) && event[field] >= 0, field);
    for (const secret of ['private', 'catalog.example', 'Authorization', 'question', 'session'])
      assert.equal(JSON.stringify(event).includes(secret), false);
  }
  await tick();
  assert.throws(() => client(async () => {}, {onAttempt: true}), e => e.code === 'invalid_client_configuration');
  await assert.rejects(client(async () => {}).start({question: ask.question, signal: {aborted: false}}),
    e => e.code === 'invalid_cancellation_signal');
});

test('attempt telemetry sanitizes dependency exceptions and untrusted service headers', async () => {
  const {CollectorCallError} = require('./collectorClient.cjs');
  for (const dependency of ['auth', 'fetch']) {
    const events = [];
    const hostile = () => {throw new CollectorCallError('https://secret.example/private-token', true);};
    const c = client(dependency === 'fetch' ? hostile : async () => {}, {
      getIdToken: dependency === 'auth' ? hostile : async () => 'private-token',
      onAttempt: event => events.push(event),
    });
    await assert.rejects(c.start({question: ask.question}), e =>
      e.code === (dependency === 'auth' ? 'catalog_auth_unavailable' : 'catalog_transport_error'));
    assert.equal(JSON.stringify(events).includes('secret'), false);
    assert.equal(JSON.stringify(events).includes('private-token'), false);
  }
  const events = [];
  const c = client(async () => new Response('{}', {status: 503, headers: {
    'X-Collector-Error': 'private-token', 'X-Collector-Request-ID': 'private-token',
    'Server-Timing': 'secret;dur=123, compute;dur=Infinity, queue;dur=-1, receive;dur=1.5;desc="private-token"',
  }}), {onAttempt: event => events.push(event)});
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_temporarily_unavailable');
  for (const event of events) {
    assert.equal(event.request_id, null);
    assert.deepEqual(event.server_timing_ms, {receive: null, queue: null, compute: null});
  }
  assert.equal(JSON.stringify(events).includes('private-token'), false);
});

test('server correlation is limited to exact generated IDs and finite fixed-key timings', async () => {
  const events = [];
  const c = client(async (_, options) => new Response(JSON.stringify(result(JSON.parse(options.body))), {
    headers: {'Content-Type': 'application/json', 'X-Collector-Request-ID': '1a'.repeat(16),
      'Server-Timing': 'receive;dur=0.123, queue;dur=0, compute;dur=12.5, unknown;dur=999'},
  }), {onAttempt: event => events.push(event)});
  await c.start({question: ask.question});
  assert.equal(events[0].request_id, '1a'.repeat(16));
  assert.deepEqual(events[0].server_timing_ms, {receive: 0.123, queue: 0, compute: 12.5});
});

async function withHttpService(handler, callback) {
  const http = require('node:http'); const sockets = new Set();
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => handler(req, res, JSON.parse(Buffer.concat(chunks).toString('utf8'))));
  });
  server.on('connection', socket => {sockets.add(socket); socket.on('close', () => sockets.delete(socket));});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try { await callback(`http://127.0.0.1:${server.address().port}`); }
  finally {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  }
}
function sendResult(res, request) {
  res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(result(request)));
}

test('real HTTP stalled headers/body and busy bodies cancel and recover on the bounded retry', {timeout: 5000}, async () => {
  for (const stall of ['headers', 'body', 'busy']) {
    let calls = 0; let firstClosed;
    const closed = new Promise(resolve => {firstClosed = resolve;}); const events = [];
    await withHttpService((req, res, request) => {
      calls++;
      if (calls > 1) {sendResult(res, request); return;}
      res.on('close', firstClosed);
      if (stall === 'headers') return;
      res.writeHead(stall === 'busy' ? 503 : 200, {'Content-Type': 'application/json',
        'X-Collector-Error': 'catalog_busy', 'X-Collector-Request-ID': 'ab'.repeat(16),
        'Server-Timing': 'receive;dur=0.1, queue;dur=0.2, compute;dur=0.3'});
      res.write('{'); // Never finish this body; cancellation must close it.
    }, async baseUrl => {
      const c = createCollectorClient({baseUrl, allowLoopback: true, timeoutMs: 150,
        retryDelayMs: 0, onAttempt: event => events.push(event)});
      assert.equal((await c.start({question: ask.question})).status, 'accepted');
      await closed;
      assert.equal(calls, 2); assert.equal(events.length, 2);
      assert.equal(events[0].error_class, stall === 'busy' ? 'catalog_temporarily_unavailable' : 'catalog_timeout');
      if (stall !== 'headers') {
        assert.equal(events[0].request_id, 'ab'.repeat(16));
        assert.deepEqual(events[0].server_timing_ms, {receive: 0.1, queue: 0.2, compute: 0.3});
      }
      assert.equal(events[1].outcome, 'accepted');
    });
  }
});

test('real HTTP oversized/invalid streams fail closed promptly and the next call recovers', {timeout: 3000}, async () => {
  for (const invalid of ['size', 'type']) {
    let calls = 0; let firstClosed; const closed = new Promise(resolve => {firstClosed = resolve;});
    await withHttpService((req, res, request) => {
      if (++calls > 1) {sendResult(res, request); return;}
      res.on('close', firstClosed);
      res.writeHead(200, {'Content-Type': invalid === 'type' ? 'text/plain' : 'application/json',
        ...(invalid === 'size' ? {'Content-Length': '1000000'} : {})});
      res.write('{');
    }, async baseUrl => {
      const c = createCollectorClient({baseUrl, allowLoopback: true, timeoutMs: 150, retryDelayMs: 0});
      // Default 8 MiB permits this length; use an explicit smaller bounded limit.
      const limited = createCollectorClient({baseUrl, allowLoopback: true, timeoutMs: 150,
        retryDelayMs: 0, maxResponseBytes: 4096});
      await assert.rejects(limited.start({question: ask.question}), e => e.code ===
        (invalid === 'size' ? 'response_too_large' : 'invalid_catalog_response'));
      await closed; assert.equal(calls, 1);
      assert.equal((await c.start({question: ask.question})).status, 'accepted');
      assert.equal(calls, 2);
    });
  }
});

test('real HTTP burst timeouts release connections and preserve deterministic serial recovery', {timeout: 5000}, async () => {
  let stall = true; let active = 0; let calls = 0; let closedCount = 0;
  await withHttpService((req, res, request) => {
    calls++; active++;
    res.on('close', () => {active--; closedCount++;});
    if (!stall) sendResult(res, request);
    else {res.writeHead(200, {'Content-Type': 'application/json'}); res.write('{');}
  }, async baseUrl => {
    const events = [];
    const c = createCollectorClient({baseUrl, allowLoopback: true, timeoutMs: 100, retryDelayMs: 0,
      onAttempt: event => events.push(event)});
    const outcomes = await Promise.allSettled(Array.from({length: 8}, () => c.start({question: ask.question})));
    assert.ok(outcomes.every(outcome => outcome.status === 'rejected' && outcome.reason.code === 'catalog_timeout'));
    assert.equal(events.length, 16); assert.ok(events.every(event => event.attempt <= 2));
    // Wait on actual socket-close events, without assuming they precede the
    // client's rejected promise. Both are asynchronous transport operations.
    const began = performance.now();
    while (active && performance.now() - began < 1000) await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(active, 0); assert.equal(closedCount, calls);
    stall = false;
    const recovered = await c.start({question: ask.question});
    assert.equal(recovered.status, 'accepted');
    assert.deepEqual(recovered.result, result({turns: [ask]}));
    assert.deepEqual(recovered.session.turns, [ask]);
    assert.equal(recovered.target_intent, null);
  });
});

test('body exceptions cannot leak through an exported CollectorCallError with a safe code', async () => {
  const {CollectorCallError} = require('./collectorClient.cjs');
  const error = new CollectorCallError('invalid_catalog_response');
  error.message = 'private session and token'; error.secret = 'private-token';
  await assert.rejects(client(async () => ({status: 200,
    headers: new Headers({'Content-Type': 'application/json'}), body: {getReader: () => ({
      read: async () => {throw error;}, cancel: async () => {},
    })}})).start({question: ask.question}), e => e.code === 'invalid_catalog_response'
      && e.message === 'invalid_catalog_response' && !('secret' in e));
});

test('real HTTP external cancellation aborts one request and a fresh call recovers', {timeout: 2000}, async () => {
  const controller = new AbortController(); let calls = 0; let firstClosed; let ready;
  const closed = new Promise(resolve => {firstClosed = resolve;});
  const received = new Promise(resolve => {ready = resolve;});
  await withHttpService((req, res, request) => {
    if (++calls > 1) {sendResult(res, request); return;}
    res.on('close', firstClosed);
    res.writeHead(200, {'Content-Type': 'application/json'}); res.write('{'); ready();
  }, async baseUrl => {
    const events = [];
    const c = createCollectorClient({baseUrl, allowLoopback: true, timeoutMs: 1000,
      onAttempt: event => events.push(event)});
    const pending = c.start({question: ask.question, signal: controller.signal});
    await received; controller.abort(new Error('private caller cancellation reason'));
    await assert.rejects(pending, e => e.code === 'catalog_cancelled' && !e.retryable);
    await closed;
    assert.equal(calls, 1); assert.equal(events.length, 1);
    assert.equal(events[0].error_class, 'catalog_cancelled');
    assert.equal((await c.start({question: ask.question})).status, 'accepted');
    assert.equal(calls, 2);
  });
});

test('native reader locks release even when underlying cancellation never settles', {timeout: 1000}, async () => {
  const streams = []; let cancellations = 0;
  const c = client(async () => {
    const stream = new ReadableStream({cancel() {cancellations++; return never();}});
    streams.push(stream);
    return new Response(stream, {headers: {'Content-Type': 'application/json'}});
  }, {timeoutMs: 50});
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_timeout');
  await tick();
  assert.equal(cancellations, 2);
  assert.deepEqual(streams.map(stream => stream.locked), [false, false]);
});

test('reader lock release is attempted independently when cancellation throws', async () => {
  let cancellations = 0; let releases = 0;
  const c = client(async () => ({status: 200, headers: new Headers({'Content-Type': 'application/json'}),
    body: {getReader: () => ({read: async () => ({done: true}),
      cancel() {cancellations++; throw new Error('private cleanup error');},
      releaseLock() {releases++; throw new Error('private release error');},
    })}}));
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'invalid_catalog_response');
  assert.equal(cancellations, 1); assert.equal(releases, 1);
});

test('synchronous cancellation during reader adoption still releases the newly owned lock', async () => {
  const controller = new AbortController(); let cancelled = 0;
  const stream = new ReadableStream({cancel() {cancelled++; return never();}});
  const response = new Response(stream, {headers: {'Content-Type': 'application/json'}});
  const c = client(async () => ({status: 200, headers: response.headers, body: {
    cancel: () => response.body.cancel(),
    getReader() {
      const reader = response.body.getReader();
      controller.abort('private reason');
      return reader;
    },
  }}));
  await assert.rejects(c.start({question: ask.question, signal: controller.signal}),
    e => e.code === 'catalog_cancelled');
  await tick(); assert.equal(cancelled, 1); assert.equal(stream.locked, false);
});

test('dependency error accessors are read once and cannot leak through errors or telemetry', async () => {
  const {CollectorCallError} = require('./collectorClient.cjs');
  const events = []; let accesses = 0;
  const error = new CollectorCallError('invalid_catalog_response');
  Object.defineProperty(error, 'code', {get: () => ++accesses === 1
    ? 'invalid_catalog_response' : 'private-token'});
  const c = client(async () => new Response(new ReadableStream({start(controller) {controller.error(error);}}),
    {headers: {'Content-Type': 'application/json'}}), {onAttempt: event => events.push(event)});
  await assert.rejects(c.start({question: ask.question}), e => e.code === 'invalid_catalog_response'
    && e.message === 'invalid_catalog_response');
  assert.equal(accesses, 1); assert.equal(events.length, 1);
  assert.equal(events[0].error_class, 'invalid_catalog_response');
  assert.equal(JSON.stringify(events).includes('private-token'), false);
});

test('throwing error code, retryable and prototype accessors remain bounded and sanitized', async () => {
  const {CollectorCallError} = require('./collectorClient.cjs');
  for (const field of ['code', 'retryable', 'prototype']) {
    let error = new CollectorCallError('invalid_catalog_response');
    if (field === 'prototype') error = new Proxy(error, {
      getPrototypeOf() {throw new Error('private-prototype-token');},
    });
    else Object.defineProperty(error, field, {get() {throw new Error('private-accessor-token');}});
    const events = []; let calls = 0;
    const c = client(async () => {
      calls++;
      return new Response(new ReadableStream({start(controller) {controller.error(error);}}),
        {headers: {'Content-Type': 'application/json'}});
    }, {onAttempt: event => events.push(event)});
    await assert.rejects(c.start({question: ask.question}), e => e.code === 'catalog_transport_error'
      && e.message === 'catalog_transport_error' && e.retryable === true);
    assert.equal(calls, 2); assert.equal(events.length, 2);
    assert.ok(events.every(event => event.error_class === 'catalog_transport_error'));
    assert.equal(JSON.stringify(events).includes('private'), false);
  }
});

test('caller cancellation listeners are removed after success, error and timeout', async () => {
  const {getEventListeners} = require('node:events');
  for (const mode of ['accepted', 'rejected', 'timeout']) {
    const controller = new AbortController();
    const c = client(async (_, options) => {
      if (mode === 'timeout') return never();
      if (mode === 'rejected') return json({}, 403);
      return json(result(JSON.parse(options.body)));
    }, {timeoutMs: 50});
    const pending = c.start({question: ask.question, signal: controller.signal});
    if (mode === 'accepted') await pending;
    else await assert.rejects(pending, e => e.code === (mode === 'timeout' ? 'catalog_timeout' : 'catalog_access_denied'));
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  }
});

test('retry telemetry carries status and actual delay while catalog-change remains a non-error result', async () => {
  const events = []; let calls = 0;
  const c = client(async (_, options) => ++calls === 1 ? json({}, 503) : json(result(JSON.parse(options.body))), {
    retryDelayMs: 10, onAttempt: event => events.push(event),
  });
  await c.start({question: ask.question});
  assert.deepEqual(events.map(event => [event.attempt, event.http_status, event.error_class,
    event.retryable, event.retry_delay_ms]), [
    [1, 503, 'catalog_temporarily_unavailable', true, 10], [2, 200, null, false, 0],
  ]);
  const changed = [];
  const session = {schema: 'pokemon.pivota-collector-session.v1', turns: [ask], limit: 5, expected_revision: revision};
  const changedClient = client(async () => json({error:
    'catalog or journey policy changed; replay without the old revision and reconfirm the target'}, 400), {
    onAttempt: event => changed.push(event),
  });
  assert.equal((await changedClient.advance({session, action: {type: 'clear_target'}})).status, 'catalog_changed');
  assert.equal(changed.length, 1); assert.equal(changed[0].outcome, 'catalog_changed');
  assert.equal(changed[0].error_class, null); assert.equal(changed[0].retry_delay_ms, 0);
});
