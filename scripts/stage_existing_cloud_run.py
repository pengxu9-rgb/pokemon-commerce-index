"""Guarded rollout of an already-built image to the existing PRIVATE staging service.

No credentials, IAM bindings, service accounts, APIs, or repositories are created.
The supplied source SHA is an operator assertion, NOT a build provenance proof.
Read PRIVATE_STAGING_ROLLOUT.md and establish build/source binding before stage.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT = 'pivota-staging'
REGION = 'us-west1'
SERVICE = 'pokemon-commerce-index'
IDENTITY = 'sa-pokemon-commerce-index@pivota-staging.iam.gserviceaccount.com'
ORIGIN = 'https://pokemon-commerce-index-42ogcsuwxq-uw.a.run.app'
IMAGE_PREFIX = 'us-west1-docker.pkg.dev/pivota-staging/cloud-run-source-deploy/pokemon-commerce-index@sha256:'
VOLATILE = {'run.googleapis.com/client-name', 'run.googleapis.com/client-version',
            'run.googleapis.com/operation-id', 'run.googleapis.com/urls',
            'serving.knative.dev/creator', 'serving.knative.dev/lastModifier'}


class RolloutError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RolloutError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def command(args, *, input_text=None, timeout=120):
    # Never forward subprocess output on failure: tokens or service env values can
    # occur there. The operator can separately inspect the original CLI securely.
    try:
        result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                                timeout=timeout, check=False,
                                env={**os.environ, 'CLOUDSDK_CORE_DISABLE_PROMPTS': '1',
                                     'CLOUDSDK_CORE_LOG_HTTP': 'false'})
    except (OSError, subprocess.TimeoutExpired):
        raise RolloutError(f'{args[0]} unavailable or timed out; outcome may be uncertain; inspect before retrying') from None
    require(result.returncode == 0, f'{args[0]} failed; inspect securely before retrying, never auto-create access')
    return result.stdout


def gcloud(*args):
    raw = command(['gcloud', *args, f'--project={PROJECT}', f'--region={REGION}', '--format=json', '--quiet'], timeout=1800)
    try:
        return json.loads(raw)
    except ValueError:
        raise RolloutError('gcloud did not return valid JSON; inspect before retrying') from None


def traffic(service):
    result = {}
    for row in service['status'].get('traffic', []):
        percent = row.get('percent', 0)
        require(type(percent) is int and 0 <= percent <= 100, 'invalid observed traffic')
        if percent:
            revision = row.get('revisionName')
            require(isinstance(revision, str) and revision.startswith(SERVICE + '-'), 'traffic is not resolved to a concrete revision')
            result[revision] = result.get(revision, 0) + percent
    require(sum(result.values()) == 100, 'observed traffic does not sum to 100')
    return result


def settings(service):
    """Hash every revision setting except image and transient deployment metadata.

    Environment/secret references stay in memory only. Unknown differences fail
    closed; do not add blanket exclusions to make a failed rollout pass.
    """
    spec = copy.deepcopy(service['spec'])
    spec.pop('traffic', None)
    template = spec['template']
    meta = template.setdefault('metadata', {})
    meta.pop('name', None)
    for key in VOLATILE:
        meta.get('annotations', {}).pop(key, None)
    meta.get('labels', {}).pop('client.knative.dev/nonce', None)
    for container in template['spec']['containers']:
        container.pop('image', None)
    annotations = {k: v for k, v in service.get('metadata', {}).get('annotations', {}).items() if k not in VOLATILE}
    return {'spec': spec, 'annotations': annotations}


def inspect():
    service = gcloud('run', 'services', 'describe', SERVICE)
    policy = gcloud('run', 'services', 'get-iam-policy', SERVICE)
    require(service.get('metadata', {}).get('name') == SERVICE, 'wrong service')
    require(service.get('status', {}).get('url') == ORIGIN, 'unexpected service URL')
    require(any(c.get('type') == 'Ready' and c.get('status') == 'True'
                for c in service['status'].get('conditions', [])), 'existing service is not Ready')
    require(service['status'].get('latestCreatedRevisionName') == service['status'].get('latestReadyRevisionName'),
            'another rollout is pending or failed; inspect it first')
    spec = service['spec']['template']['spec']
    require(spec.get('serviceAccountName') == IDENTITY, 'unexpected runtime identity; do not change it automatically')
    require(len(spec.get('containers', [])) == 1, 'expected existing single-container service')
    annotations = service.get('metadata', {}).get('annotations', {})
    require(str(annotations.get('run.googleapis.com/invoker-iam-disabled', 'false')).lower() == 'false',
            'Cloud Run invoker IAM check is disabled')
    require(annotations.get('run.googleapis.com/ingress') in {'all', 'internal', 'internal-and-cloud-load-balancing'},
            'cannot establish existing ingress setting')
    bindings = policy.get('bindings', [])
    require(isinstance(bindings, list), 'invalid IAM policy')
    require(not any(m in {'allUsers', 'allAuthenticatedUsers'} for b in bindings for m in b.get('members', [])),
            'service has broad IAM principals; stop instead of changing IAM')
    if 'generation' in service['metadata'] and 'observedGeneration' in service['status']:
        require(str(service['metadata']['generation']) == str(service['status']['observedGeneration']),
                'service status has not observed the current generation')
    runtime = {'container_concurrency': spec.get('containerConcurrency'), 'timeout_seconds': spec.get('timeoutSeconds'),
               'resources': spec['containers'][0].get('resources', {}),
               'min_instances': service['spec']['template'].get('metadata', {}).get('annotations', {}).get('autoscaling.knative.dev/minScale', '0'),
               'max_instances': service['spec']['template'].get('metadata', {}).get('annotations', {}).get('autoscaling.knative.dev/maxScale')}
    # Compare exact IAM content, including etag, audit configs and conditions.
    return service, {'settings_sha256': digest(settings(service)), 'iam_sha256': digest(policy),
                     'traffic': traffic(service), 'url': ORIGIN,
                     'ingress': annotations['run.googleapis.com/ingress'], 'identity': IDENTITY, 'runtime': runtime}


def check_unchanged(baseline, current, expected_traffic):
    for field in ('settings_sha256', 'iam_sha256', 'url', 'ingress', 'identity'):
        require(current[field] == baseline[field], f'{field} changed; no automatic promotion or repair')
    require(current['traffic'] == expected_traffic, 'traffic changed unexpectedly; inspect before acting')


def save(path, record, *, create=False):
    path = Path(path)
    if create:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(record, handle, indent=2)
            handle.write('\n')
    else:
        fd, name = tempfile.mkstemp(prefix='.rollout-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(record, handle, indent=2)
                handle.write('\n')
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def load(path):
    record = json.loads(Path(path).read_text())
    require(record.get('schema') == 'pokemon.private-staging-rollout.v1', 'wrong receipt schema')
    require(record.get('project') == PROJECT and record.get('region') == REGION and record.get('service') == SERVICE,
            'receipt target differs from fixed staging target')
    require(re.fullmatch(re.escape(IMAGE_PREFIX) + r'[a-f0-9]{64}', record.get('image', '')), 'receipt image must be an immutable staging digest')
    require(re.fullmatch(r'[a-f0-9]{40}', record.get('operator_asserted_source_sha', '')), 'invalid asserted source SHA')
    require(re.fullmatch(r'[a-f0-9]{64}', record.get('expected_catalog_revision', '')), 'invalid catalog revision')
    require(re.fullmatch(r'[a-z][a-z0-9-]{0,30}', record.get('tag', '')), 'invalid staging tag')
    return record


def candidate(record):
    service, snapshot = inspect()
    check_unchanged(record['baseline'], snapshot, record['baseline']['traffic'])
    matching = [row for row in service['status'].get('traffic', []) if row.get('tag') == record['tag']]
    require(len(matching) == 1, 'staging tag missing or ambiguous')
    row = matching[0]
    expected_url = ORIGIN.replace('https://', 'https://' + record['tag'] + '---')
    require(row.get('url') == expected_url, 'unexpected tagged URL; no token will be sent')
    name = row.get('revisionName', '')
    require(name == service['status'].get('latestReadyRevisionName'), 'a later revision exists; serialize/reconcile the rollout first')
    require(name.startswith(SERVICE + '-') and name not in record['baseline']['traffic'], 'candidate must be a new revision')
    revision = gcloud('run', 'revisions', 'describe', name)
    require(any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in revision.get('status', {}).get('conditions', [])),
            'candidate revision is not Ready')
    image = revision.get('status', {}).get('imageDigest')
    require(image == record['image'], 'candidate image digest differs from reviewed image')
    return name, row['url']


def stage(args):
    require(re.fullmatch(re.escape(IMAGE_PREFIX) + r'[a-f0-9]{64}', args.image), 'use an immutable image from the existing staging repository')
    require(re.fullmatch(r'[a-f0-9]{40}', args.source_sha), 'use the final full source commit SHA')
    require(re.fullmatch(r'[a-f0-9]{64}', args.catalog_revision), 'use the rebuilt final catalog/runtime revision')
    require(re.fullmatch(r'[a-z][a-z0-9-]{0,30}', args.tag), 'invalid staging tag')
    service, baseline = inspect()
    require(not any(row.get('tag') == args.tag for row in service['status'].get('traffic', [])), 'tag already exists; choose an unused tag')
    # Service-level IAM cannot reveal every inherited project/org grant. Prove
    # anonymous denial before exposing even a zero-traffic tagged revision.
    require(http(ORIGIN + '/health')[0] in {401, 403},
            'canonical service is not rejecting anonymous access; no deployment was attempted')
    record = dict(schema='pokemon.private-staging-rollout.v1', project=PROJECT, region=REGION, service=SERVICE,
                  state='prepared', baseline=baseline, image=args.image, tag=args.tag,
                  operator_asserted_source_sha=args.source_sha, source_binding_verified_by_script=False,
                  expected_catalog_revision=args.catalog_revision)
    save(args.receipt, record, create=True)  # Durable baseline BEFORE the mutating call.
    gcloud('run', 'deploy', SERVICE, f'--image={args.image}', '--no-traffic', f'--tag={args.tag}',
           f"--ingress={baseline['ingress']}", f'--service-account={IDENTITY}')
    name, url = candidate(record)
    record.update(state='staged', candidate_revision=name, candidate_url=url)
    save(args.receipt, record)
    return {'state': 'staged', 'candidate_revision': name, 'candidate_url': url, 'traffic': baseline['traffic']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=30) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            require(len(body) <= 8 * 1024 * 1024, 'HTTP response exceeded limit')
            require(response.headers.get_content_type() == 'application/json', 'expected JSON health response')
            return response.status, json.loads(body)
    except HTTPError as error:
        error.close()
        return error.code, None
    except (OSError, ValueError):
        raise RolloutError('HTTP smoke failed; credentials/response suppressed') from None


NODE_SMOKE = r"""
const fs = require('node:fs');
const {createCollectorClient} = require(process.argv[1]);
const c = JSON.parse(fs.readFileSync(0, 'utf8'));
// Operator token is already acquired for Cloud Run; a service-identity provider
// must use the canonical service origin, never the traffic-tag audience.
const client = createCollectorClient({baseUrl:c.url,getIdToken:async()=>c.token});
(async()=>{
  let call = await client.start({question:'Recommend Japanese Pikachu cards',limit:5});
  if(call.status!=='accepted'||call.result.catalog_revision!==c.revision||
     call.result.discovery.task!=='collector_recommendations'||!call.result.candidate_cards.length)
    throw Error('recommendation smoke failed');
  const first=call.result.candidate_cards[0].card_id;
  call=await client.advance({session:call.session,action:{type:'feedback',card_id:first,reaction:'dismiss'}});
  if(call.status!=='accepted'||call.result.candidate_cards.some(x=>x.card_id===first)||call.target_intent!==null)
    throw Error('dismiss smoke failed');
  call=await client.advance({session:call.session,action:{type:'clear_target'}});
  if(call.status!=='accepted'||call.target_intent!==null) throw Error('target reset smoke failed');
  const stale={...call.session,expected_revision:c.revision==='0'.repeat(64)?'1'.repeat(64):'0'.repeat(64)};
  const changed=await client.advance({session:stale,action:{type:'clear_target'}});
  if(changed.status!=='catalog_changed'||changed.session!==null||changed.result!==null||changed.target_intent!==null)
    throw Error('stale session smoke failed');
  process.stdout.write(JSON.stringify({passed:4,failed:0,catalog_revision:c.revision}));
})().catch(()=>{process.stderr.write('Node caller smoke failed\n');process.exitCode=1;});
"""


def smoke(record, url):
    require(url in {ORIGIN, record['candidate_url']}, 'unexpected smoke URL')
    require(http(url + '/health')[0] in {401, 403}, 'unauthenticated request was not rejected with 401/403')
    token = command(['gcloud', 'auth', 'print-identity-token'], timeout=60).strip()
    require(token and '\n' not in token and '\r' not in token, 'no usable existing identity token')
    require(http(url + '/health', token) == (200, {'ok': True}), 'authenticated health check failed')
    client = Path(__file__).resolve().parents[1] / 'integrations/pivota/collectorClient.cjs'
    result = json.loads(command(['node', '-e', NODE_SMOKE, str(client)], input_text=json.dumps({
        'url': url, 'token': token, 'revision': record['expected_catalog_revision']}), timeout=120))
    require(result.get('passed') == 4 and result.get('failed') == 0, 'Node smoke incomplete')
    return {'anonymous_denied': True, 'authenticated_health': True, 'node_caller': result,
            'deployed_pivota_identity_proven': False, 'full_acceptance_suite_proven': False}


def verify(args):
    record = load(args.receipt)
    require(record['state'] in {'staged', 'verified'}, 'stage must have completed successfully')
    name, url = candidate(record)
    require(name == record['candidate_revision'] and url == record['candidate_url'], 'candidate changed since staging')
    report = smoke(record, url)
    require(candidate(record) == (name, url), 'candidate changed during verification')
    record.update(state='verified', smoke=report)
    save(args.receipt, record)
    return {'state': 'verified', 'candidate_revision': name, **report}


REQUIRED_ACCEPTANCE_CHECKS = {
    'full_python_regression', 'node_unit_tests', 'new_loop_fixture', 'real_catalog_compatibility',
    'preference_set_replace_clear', 'feedback_membership_and_context_invalidation', 'dismiss_and_clear',
    'pagination', 'evidence_only_comparison', 'comparison_choice_exact_focus', 'separate_selection',
    'blocked_identity_and_source_number_conflicts', 'unknown_and_possibly_owned_inventory', 'new_goal_reset',
    'english_japanese_chinese_paths', 'commerce_physical_public_flags_false', 'prices_and_offers_absent',
    'cloud_matches_final_local_replay', 'stale_node_session_compatibility',
    'cold_start_and_parallel_requests', 'memory_latency_and_error_review',
}


def validate_acceptance(record, path):
    """Require independently prepared, artifact-backed acceptance evidence.

    This validates binding/completeness/integrity, not whether an operator told
    the truth. Do not synthesize the report from the small built-in smoke suite.
    """
    path = Path(path).resolve()
    require(path.stat().st_size <= 1024 * 1024, 'acceptance report too large')
    raw = path.read_bytes()
    report = json.loads(raw)
    require(report.get('schema') == 'pokemon.private-staging-acceptance.v1', 'wrong acceptance report schema')
    expected = {'source_sha': record['operator_asserted_source_sha'], 'image': record['image'],
                'candidate_revision': record['candidate_revision'], 'candidate_url': record['candidate_url'],
                'catalog_revision': record['expected_catalog_revision']}
    require(all(report.get(k) == v for k, v in expected.items()), 'acceptance evidence belongs to another source/image/revision')
    checks = report.get('checks', {})
    require(isinstance(checks, dict) and REQUIRED_ACCEPTANCE_CHECKS <= checks.keys(), 'full acceptance checklist is missing')
    cache = {}
    def evidence(entry):
        require(isinstance(entry, dict), 'invalid evidence entry')
        name = entry.get('evidence_file')
        require(isinstance(name, str) and name and not Path(name).is_absolute(), 'evidence must be a local relative artifact')
        artifact = (path.parent / name).resolve()
        require(artifact.is_relative_to(path.parent) and artifact != path, 'evidence must be inside the report directory, not the report itself')
        require(re.fullmatch(r'[a-f0-9]{64}', entry.get('evidence_sha256', '')), 'evidence hash missing')
        if artifact not in cache:
            require(artifact.is_file() and artifact.stat().st_size <= 32 * 1024 * 1024, 'evidence artifact unavailable or too large')
            cache[artifact] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        require(cache[artifact] == entry['evidence_sha256'], 'evidence artifact hash mismatch')
    for name in REQUIRED_ACCEPTANCE_CHECKS:
        require(isinstance(checks[name], dict) and checks[name].get('passed') is True, f'acceptance check failed or missing: {name}')
        evidence(checks[name])
    build = report.get('source_binding', {})
    require(isinstance(build, dict) and build.get('verified') is True
            and isinstance(build.get('build_id'), str) and bool(build['build_id'].strip())
            and re.fullmatch(r'[a-f0-9]{64}', build.get('source_context_sha256', '')), 'reviewed source/build binding missing')
    evidence(build)
    ci = report.get('ci', {})
    require(isinstance(ci, dict) and ci.get('head_sha') == expected['source_sha'] and ci.get('conclusion') == 'success'
            and re.fullmatch(r'https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/[0-9]+', ci.get('url', '')),
            'successful CI evidence is not bound to final source')
    evidence(ci)
    return hashlib.sha256(raw).hexdigest()


def promote(args):
    record = load(args.receipt)
    require(record['state'] == 'verified', 'successful tag verification is required')
    require(args.accept_reviewed_source_ci_and_full_smokes, 'operator must establish source/image binding, final CI and full acceptance suite first')
    acceptance_sha = validate_acceptance(record, args.acceptance_report)
    name, url = candidate(record)
    require((name, url) == (record['candidate_revision'], record['candidate_url']), 'candidate changed')
    smoke(record, url)  # A prior report alone never authorizes stale promotion.
    require(candidate(record) == (name, url), 'candidate changed during smoke; no promotion attempted')
    record['state'] = 'promoting'
    record['acceptance_report_sha256'] = acceptance_sha
    save(args.receipt, record)
    gcloud('run', 'services', 'update-traffic', SERVICE, f'--to-revisions={name}=100')
    _, snapshot = inspect()
    check_unchanged(record['baseline'], snapshot, {name: 100})
    smoke(record, ORIGIN)
    record.update(state='promoted', traffic={name: 100})
    save(args.receipt, record)
    return {'state': 'promoted', 'revision': name, 'traffic': {name: 100}}


def rollback(args):
    record = load(args.receipt)
    require(record['state'] in {'promoting', 'promoted'}, 'no promotion was recorded; inspect uncertain state manually')
    _, snapshot = inspect()
    current = snapshot['traffic']
    require(current in (record['baseline']['traffic'], {record['candidate_revision']: 100}),
            'a later/unrelated rollout owns traffic; refusing rollback')
    check_unchanged(record['baseline'], snapshot, current)
    if current != record['baseline']['traffic']:
        target = ','.join(f'{name}={percent}' for name, percent in sorted(record['baseline']['traffic'].items()))
        gcloud('run', 'services', 'update-traffic', SERVICE, '--to-revisions=' + target)
    _, after = inspect()
    check_unchanged(record['baseline'], after, record['baseline']['traffic'])
    record['state'] = 'rolled_back'
    save(args.receipt, record)
    return {'state': 'rolled_back', 'traffic': after['traffic'], 'old_revision_authenticated_smokes_still_required': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('inspect')
    for action in ('stage', 'verify', 'promote', 'rollback'):
        item = sub.add_parser(action)
        item.add_argument('--receipt', type=Path, required=True)
        if action == 'stage':
            for name in ('image', 'source-sha', 'catalog-revision', 'tag'):
                item.add_argument('--' + name, required=True)
        if action == 'promote':
            item.add_argument('--acceptance-report', type=Path, required=True)
            item.add_argument('--accept-reviewed-source-ci-and-full-smokes', action='store_true')
    args = parser.parse_args()
    try:
        result = inspect()[1] if args.action == 'inspect' else globals()[args.action](args)
        print(json.dumps(result, indent=2))
    except (RolloutError, OSError, ValueError, KeyError) as error:
        if isinstance(error, RolloutError):
            message = str(error)
        else:
            message = 'local receipt/input or cloud response invalid; inspect securely before retrying'
        parser.exit(1, 'Stopped: ' + message + '\n')


if __name__ == '__main__':
    main()
