'use strict';
const test = require('node:test'); const assert = require('node:assert/strict');
const {createCollectorOperation} = require('./collectorOperation.cjs');
const envelope = {operation: 'collector.explore', payload: {action: {type: 'ask', question: 'Pikachu cards'}}};
test('operation is disabled by default and authorization uses trusted context before any catalog request', async () => {
  let calls = 0; const client = {advance: async () => {calls++; return {status: 'accepted'};}};
  await assert.rejects(createCollectorOperation({client})({}, envelope), e => e.code === 'collector_operation_disabled');
  const invoke = createCollectorOperation({enabled: true, client, authorize: context => context?.internalCollectorPilot === true});
  await assert.rejects(invoke({}, {...envelope, payload: {...envelope.payload, internalCollectorPilot: true}}), e => e.code === 'collector_caller_denied');
  assert.equal(calls, 0);
  const r = await invoke({internalCollectorPilot: true}, envelope);
  assert.equal(calls, 1); assert.equal(r.visibility, 'internal_catalog_only');
  assert.equal(r.pivota_content_key, null); assert.equal(r.commerce_operation_allowed, false);
});
test('checkout fields, caller-provided identities and unregistered operations cannot enter this lane', async () => {
  let calls = 0;
  const invoke = createCollectorOperation({enabled: true, client: {advance: async () => {calls++;}}, authorize: () => true});
  for (const request of [{operation: 'create_order', payload: envelope.payload},
    {...envelope, payload: {...envelope.payload, acp_state: {}}},
    {...envelope, payload: {...envelope.payload, pivota_content_key: 'invented'}},
    {...envelope, caller: {admin: true}}])
    await assert.rejects(invoke({}, request), e => e.code === 'invalid_collector_operation');
  assert.equal(calls, 0);
});
