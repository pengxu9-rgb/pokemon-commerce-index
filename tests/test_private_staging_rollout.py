import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import stage_existing_cloud_run as rollout


IMAGE = rollout.IMAGE_PREFIX + 'a' * 64
OLD = rollout.SERVICE + '-00043-2x6'
NEW = rollout.SERVICE + '-00044-test'


def service():
    return {
        'metadata': {'name': rollout.SERVICE, 'annotations': {
            'run.googleapis.com/ingress': 'all', 'run.googleapis.com/client-name': 'gcloud'}},
        'spec': {'template': {'metadata': {'name': OLD, 'annotations': {'autoscaling.knative.dev/maxScale': '1'},
                                             'labels': {'client.knative.dev/nonce': 'old'}},
                              'spec': {'serviceAccountName': rollout.IDENTITY, 'containerConcurrency': 16,
                                       'timeoutSeconds': 30, 'containers': [{'image': 'old', 'ports': [{'containerPort': 8080}],
                                        'resources': {'limits': {'cpu': '1', 'memory': '512Mi'}}}]}},
                 'traffic': [{'latestRevision': True, 'percent': 100}]},
        'status': {'url': rollout.ORIGIN, 'latestCreatedRevisionName': OLD, 'latestReadyRevisionName': OLD,
                   'conditions': [{'type': 'Ready', 'status': 'True'}],
                   'traffic': [{'revisionName': OLD, 'percent': 100}]}}


POLICY = {'etag': 'known-policy', 'version': 1, 'bindings': [{'role': 'roles/run.invoker', 'members': ['user:operator@example.test']}]}


class PrivateStagingRolloutTests(unittest.TestCase):
    def inspect(self, value=None, policy=None):
        with patch.object(rollout, 'gcloud', side_effect=[value or service(), policy or POLICY]):
            return rollout.inspect()

    def record(self):
        _, baseline = self.inspect()
        return dict(schema='pokemon.private-staging-rollout.v1', project=rollout.PROJECT, region=rollout.REGION,
                    service=rollout.SERVICE, state='staged', image=IMAGE, tag='review-unit', baseline=baseline,
                    operator_asserted_source_sha='b' * 40, expected_catalog_revision='c' * 64,
                    candidate_revision=NEW, candidate_url=rollout.ORIGIN.replace('https://', 'https://review-unit---'))

    def test_private_snapshot_contains_hashes_not_environment(self):
        value = service()
        value['spec']['template']['spec']['containers'][0]['env'] = [{'name': 'EXAMPLE', 'value': 'private-value'}]
        _, observed = self.inspect(value)
        self.assertNotIn('private-value', json.dumps(observed))
        self.assertEqual(observed['traffic'], {OLD: 100})
        self.assertEqual(observed['identity'], rollout.IDENTITY)

    def test_public_policy_and_disabled_invoker_check_fail_closed(self):
        for principal in ['allUsers', 'allAuthenticatedUsers']:
            policy = copy.deepcopy(POLICY)
            policy['bindings'][0]['members'].append(principal)
            with self.assertRaises(rollout.RolloutError):
                self.inspect(policy=policy)
        value = service()
        value['metadata']['annotations']['run.googleapis.com/invoker-iam-disabled'] = 'true'
        with self.assertRaises(rollout.RolloutError):
            self.inspect(value)

    def test_wrong_service_identity_url_or_pending_revision_rejected(self):
        mutations = [lambda x: x['metadata'].update(name='other-service'),
                     lambda x: x['spec']['template']['spec'].update(serviceAccountName='other'),
                     lambda x: x['status'].update(url='https://other.example'),
                     lambda x: x['status'].update(latestCreatedRevisionName=NEW)]
        for mutate in mutations:
            value = service()
            mutate(value)
            with self.assertRaises(rollout.RolloutError):
                self.inspect(value)

    def test_settings_ignore_only_expected_deployment_changes(self):
        before = service()
        after = copy.deepcopy(before)
        after['spec']['template']['metadata']['name'] = NEW
        after['spec']['template']['metadata']['labels']['client.knative.dev/nonce'] = 'new'
        after['spec']['template']['spec']['containers'][0]['image'] = IMAGE
        after['metadata']['annotations']['run.googleapis.com/client-version'] = 'new'
        self.assertEqual(rollout.settings(before), rollout.settings(after))
        for field, value in [('containerConcurrency', 80), ('timeoutSeconds', 300), ('serviceAccountName', 'other')]:
            changed = copy.deepcopy(after)
            changed['spec']['template']['spec'][field] = value
            self.assertNotEqual(rollout.settings(before), rollout.settings(changed))
        changed = copy.deepcopy(after)
        changed['spec']['template']['spec']['containers'][0]['env'] = [{'name': 'ENABLE_MARKET', 'value': 'true'}]
        self.assertNotEqual(rollout.settings(before), rollout.settings(changed))

    def test_unresolved_and_partial_traffic_rejected(self):
        for rows in [[{'latestRevision': True, 'percent': 100}], [{'revisionName': OLD, 'percent': 50}]]:
            value = service()
            value['status']['traffic'] = rows
            with self.assertRaises(rollout.RolloutError):
                rollout.traffic(value)

    def test_failed_inspection_never_invokes_mutation(self):
        args = argparse.Namespace(image=IMAGE, source_sha='b' * 40, catalog_revision='c' * 64, tag='review-unit', receipt='unused')
        with patch.object(rollout, 'inspect', side_effect=rollout.RolloutError('denied')), patch.object(rollout, 'gcloud') as cli:
            with self.assertRaises(rollout.RolloutError):
                rollout.stage(args)
            cli.assert_not_called()

    def test_stage_has_no_iam_setup_or_resource_changes(self):
        base_service, baseline = self.inspect()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            args = argparse.Namespace(image=IMAGE, source_sha='b' * 40, catalog_revision='c' * 64, tag='review-unit', receipt=path)
            with patch.object(rollout, 'inspect', return_value=(base_service, baseline)), patch.object(rollout, 'gcloud', return_value={}) as cli, \
                    patch.object(rollout, 'candidate', return_value=(NEW, self.record()['candidate_url'])), \
                    patch.object(rollout, 'http', return_value=(403, None)):
                rollout.stage(args)
            call = cli.call_args.args
            self.assertIn('--no-traffic', call)
            self.assertIn('--image=' + IMAGE, call)
            self.assertIn('--service-account=' + rollout.IDENTITY, call)
            self.assertFalse(any(part in {'iam', 'create'} or 'concurrency' in part or 'memory' in part or 'unauthenticated' in part for part in call))
            self.assertEqual(rollout.load(path)['state'], 'staged')
            self.assertFalse(rollout.load(path)['source_binding_verified_by_script'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_tag_collision_and_mutable_image_fail_before_deploy(self):
        value, baseline = self.inspect()
        value['status']['traffic'][0]['tag'] = 'review-unit'
        args = argparse.Namespace(image=IMAGE, source_sha='b' * 40, catalog_revision='c' * 64, tag='review-unit', receipt='unused')
        with patch.object(rollout, 'inspect', return_value=(value, baseline)), patch.object(rollout, 'gcloud') as cli:
            with self.assertRaises(rollout.RolloutError):
                rollout.stage(args)
            args.image = IMAGE.split('@')[0] + ':latest'
            with self.assertRaises(rollout.RolloutError):
                rollout.stage(args)
            cli.assert_not_called()

    def test_candidate_must_match_tag_url_digest_and_original_traffic(self):
        record = self.record()
        value = service()
        value['status']['latestCreatedRevisionName'] = NEW
        value['status']['latestReadyRevisionName'] = NEW
        value['status']['traffic'].append({'revisionName': NEW, 'tag': record['tag'], 'url': record['candidate_url']})
        revision = {'status': {'imageDigest': IMAGE, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        with patch.object(rollout, 'inspect', return_value=(value, record['baseline'])), patch.object(rollout, 'gcloud', return_value=revision):
            self.assertEqual(rollout.candidate(record), (NEW, record['candidate_url']))
            revision['status']['imageDigest'] = rollout.IMAGE_PREFIX + 'd' * 64
            with self.assertRaises(rollout.RolloutError):
                rollout.candidate(record)
            revision['status']['imageDigest'] = IMAGE
            value['status']['traffic'][-1]['url'] = 'https://attacker.example'
            with self.assertRaises(rollout.RolloutError):
                rollout.candidate(record)
        changed = copy.deepcopy(record['baseline'])
        changed['traffic'] = {NEW: 100}
        with patch.object(rollout, 'inspect', return_value=(value, changed)), patch.object(rollout, 'gcloud') as cli:
            with self.assertRaises(rollout.RolloutError):
                rollout.candidate(record)
            cli.assert_not_called()

    def test_verify_failure_does_not_mark_verified(self):
        record = self.record()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            rollout.save(path, record, create=True)
            with patch.object(rollout, 'candidate', return_value=(NEW, record['candidate_url'])), \
                    patch.object(rollout, 'smoke', side_effect=rollout.RolloutError('smoke failed')):
                with self.assertRaises(rollout.RolloutError):
                    rollout.verify(argparse.Namespace(receipt=path))
            self.assertEqual(rollout.load(path)['state'], 'staged')

    def test_public_health_denial_required_before_token_acquisition(self):
        record = self.record()
        with patch.object(rollout, 'http', return_value=(200, {'ok': True})), patch.object(rollout, 'command') as run:
            with self.assertRaises(rollout.RolloutError):
                rollout.smoke(record, record['candidate_url'])
            run.assert_not_called()

    def test_promotion_requires_current_verified_candidate_and_operator_gate(self):
        record = self.record()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            rollout.save(path, record, create=True)
            args = argparse.Namespace(receipt=path, accept_reviewed_source_ci_and_full_smokes=True)
            with patch.object(rollout, 'gcloud') as cli:
                with self.assertRaises(rollout.RolloutError):
                    rollout.promote(args)
                record['state'] = 'verified'
                rollout.save(path, record)
                args.accept_reviewed_source_ci_and_full_smokes = False
                with self.assertRaises(rollout.RolloutError):
                    rollout.promote(args)
                cli.assert_not_called()

    def test_rollback_refuses_unrelated_rollout(self):
        record = self.record()
        record['state'] = 'promoted'
        observed = copy.deepcopy(record['baseline'])
        observed['traffic'] = {rollout.SERVICE + '-00045-other': 100}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            rollout.save(path, record, create=True)
            with patch.object(rollout, 'inspect', return_value=(service(), observed)), patch.object(rollout, 'gcloud') as cli:
                with self.assertRaises(rollout.RolloutError):
                    rollout.rollback(argparse.Namespace(receipt=path))
                cli.assert_not_called()

    def test_rollback_restores_concrete_baseline(self):
        record = self.record()
        record['state'] = 'promoted'
        observed = copy.deepcopy(record['baseline'])
        observed['traffic'] = {NEW: 100}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            rollout.save(path, record, create=True)
            with patch.object(rollout, 'inspect', side_effect=[(service(), observed), (service(), record['baseline'])]), \
                    patch.object(rollout, 'gcloud', return_value={}) as cli:
                result = rollout.rollback(argparse.Namespace(receipt=path))
            self.assertIn('--to-revisions=' + OLD + '=100', cli.call_args.args)
            self.assertEqual(result['state'], 'rolled_back')
            self.assertTrue(result['old_revision_authenticated_smokes_still_required'])

    def acceptance(self, directory, record):
        artifact = Path(directory) / 'cloud-checks.json'
        artifact.write_text('{"record":"test evidence fixture"}\n')
        ref = {'evidence_file': artifact.name, 'evidence_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
        report = {'schema': 'pokemon.private-staging-acceptance.v1',
                  'source_sha': record['operator_asserted_source_sha'], 'image': record['image'],
                  'candidate_revision': record['candidate_revision'], 'candidate_url': record['candidate_url'],
                  'catalog_revision': record['expected_catalog_revision'],
                  'checks': {name: {'passed': True, **ref} for name in rollout.REQUIRED_ACCEPTANCE_CHECKS},
                  'source_binding': {'verified': True, 'build_id': 'fixture-build', 'source_context_sha256': 'd' * 64, **ref},
                  'ci': {'head_sha': record['operator_asserted_source_sha'], 'conclusion': 'success',
                         'url': 'https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/123', **ref}}
        path = Path(directory) / 'acceptance.json'
        path.write_text(json.dumps(report))
        return path, report, artifact

    def test_external_acceptance_requires_every_gate_current_binding_and_artifact_integrity(self):
        record = self.record()
        with tempfile.TemporaryDirectory() as temp:
            path, report, artifact = self.acceptance(temp, record)
            self.assertEqual(rollout.validate_acceptance(record, path), hashlib.sha256(path.read_bytes()).hexdigest())
            for mutate in [lambda r: r.update(candidate_revision=OLD),
                           lambda r: r['checks'].pop('separate_selection'),
                           lambda r: r['checks']['blocked_identity_and_source_number_conflicts'].update(passed=False),
                           lambda r: r['ci'].update(head_sha='0' * 40),
                           lambda r: r['source_binding'].update(verified=False),
                           lambda r: r['checks']['evidence_only_comparison'].update(evidence_file='../outside.json')]:
                changed = copy.deepcopy(report)
                mutate(changed)
                path.write_text(json.dumps(changed))
                with self.assertRaises(rollout.RolloutError):
                    rollout.validate_acceptance(record, path)
            path.write_text(json.dumps(report))
            artifact.write_text('changed after acceptance')
            with self.assertRaises(rollout.RolloutError):
                rollout.validate_acceptance(record, path)

    def test_promotion_records_acceptance_and_can_recover_after_post_promotion_smoke_failure(self):
        record = self.record()
        record['state'] = 'verified'
        promoted = copy.deepcopy(record['baseline'])
        promoted['traffic'] = {NEW: 100}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            rollout.save(path, record, create=True)
            acceptance, _, _ = self.acceptance(temp, record)
            args = argparse.Namespace(receipt=path, acceptance_report=acceptance,
                                      accept_reviewed_source_ci_and_full_smokes=True)
            with patch.object(rollout, 'candidate', return_value=(NEW, record['candidate_url'])), \
                    patch.object(rollout, 'smoke', side_effect=[{}, rollout.RolloutError('post-promotion failure')]), \
                    patch.object(rollout, 'inspect', return_value=(service(), promoted)), \
                    patch.object(rollout, 'gcloud', return_value={}) as cli:
                with self.assertRaises(rollout.RolloutError):
                    rollout.promote(args)
            self.assertEqual(rollout.load(path)['state'], 'promoting')
            self.assertEqual(rollout.load(path)['acceptance_report_sha256'], hashlib.sha256(acceptance.read_bytes()).hexdigest())
            self.assertIn('--to-revisions=' + NEW + '=100', cli.call_args.args)

    def test_subprocess_errors_never_echo_secrets(self):
        failure = argparse.Namespace(returncode=1, stdout='secret-token', stderr='secret-environment')
        with patch.object(rollout.subprocess, 'run', return_value=failure):
            with self.assertRaises(rollout.RolloutError) as caught:
                rollout.command(['gcloud', 'auth', 'print-identity-token'])
        self.assertNotIn('secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
