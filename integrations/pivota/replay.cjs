'use strict';
// Test/operator runner; JSON stdin may contain a short-lived operator token.
// Only catalog results are written to stdout; never log credentials or HTTP headers.
const {createCollectorClient} = require('./collectorClient.cjs');
async function main() {
  let input = ''; for await (const chunk of process.stdin) input += chunk;
  const {baseUrl, token, journeys, allowLoopback = false} = JSON.parse(input);
  const client = createCollectorClient({baseUrl, allowLoopback,
    getIdToken: token ? async () => token : undefined});
  const rows = [];
  for (const journey of journeys) {
    let session = null;
    for (let i = 0; i < journey.steps.length; i++) {
      try {
        const call = await client.advance({session, action: journey.steps[i].action, limit: journey.limit || 20});
        rows.push({id: journey.id + ':' + (i + 1), call}); session = call.session;
        if (call.status !== 'accepted') break;
      } catch (err) { rows.push({id: journey.id + ':' + (i + 1), error_code: err.code || 'runner_error'}); break; }
    }
  }
  process.stdout.write(JSON.stringify(rows) + '\n');
}
main().catch(() => {process.stderr.write('collector_replay_failed\n'); process.exitCode = 1;});
