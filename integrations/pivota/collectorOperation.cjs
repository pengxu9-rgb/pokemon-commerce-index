'use strict';
const {CollectorCallError} = require('./collectorClient.cjs');

// Proposed internal operation; registration in Pivota's live invoke schema is
// a separate step. The authenticated context must come from Pivota middleware.
function createCollectorOperation({enabled = false, client, authorize} = {}) {
  return async function invoke(context, envelope) {
    if (enabled !== true) throw new CollectorCallError('collector_operation_disabled');
    if (!client || typeof client.advance !== 'function' || typeof authorize !== 'function')
      throw new CollectorCallError('collector_operation_not_configured');
    let allowed; try {allowed = await authorize(context);} catch {allowed = false;}
    if (allowed !== true) throw new CollectorCallError('collector_caller_denied');
    if (!envelope || Object.keys(envelope).sort().join(',') !== 'operation,payload'
        || envelope.operation !== 'collector.explore' || !envelope.payload
        || typeof envelope.payload !== 'object' || Array.isArray(envelope.payload)
        || Object.keys(envelope.payload).some(k => !['session', 'action', 'limit'].includes(k)))
      throw new CollectorCallError('invalid_collector_operation');
    const call = await client.advance(envelope.payload);
    return {...call, visibility: 'internal_catalog_only',
      pivota_content_key: null, commerce_operation_allowed: false};
  };
}
module.exports = {createCollectorOperation};
