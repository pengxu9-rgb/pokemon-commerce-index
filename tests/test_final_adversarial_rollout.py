"""Independent final deployment guards; all cloud mutations are mocked."""
import argparse
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import stage_existing_cloud_run as rollout
import test_private_staging_rollout as fixture


class FinalAdversarialRolloutTests(unittest.TestCase):
    def test_inherited_public_access_stops_before_any_stage_mutation(self):
        helper = fixture.PrivateStagingRolloutTests()
        current, baseline = helper.inspect()
        record = helper.record()
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(image=fixture.IMAGE, source_sha='b' * 40,
                catalog_revision='c' * 64, tag='review-unit', receipt=Path(temp) / 'receipt.json')
            # Service-level IAM is private, but an inherited broad invoker grant
            # or another access path can still make anonymous requests public.
            with patch.object(rollout, 'inspect', return_value=(current, baseline)), \
                    patch.object(rollout, 'http', return_value=(200, {'ok': True})), \
                    patch.object(rollout, 'candidate', return_value=(fixture.NEW, record['candidate_url'])), \
                    patch.object(rollout, 'gcloud', return_value={}) as cli:
                with self.assertRaises(rollout.RolloutError):
                    rollout.stage(args)
                cli.assert_not_called()

    def test_tag_retarget_during_smoke_stops_before_promotion(self):
        helper = fixture.PrivateStagingRolloutTests()
        record = helper.record()
        record['state'] = 'verified'
        after = copy.deepcopy(record['baseline'])
        after['traffic'] = {fixture.NEW: 100}
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / 'receipt.json'
            rollout.save(receipt, record, create=True)
            acceptance, _, _ = helper.acceptance(temp, record)
            args = argparse.Namespace(receipt=receipt, acceptance_report=acceptance,
                accept_reviewed_source_ci_and_full_smokes=True)
            with patch.object(rollout, 'candidate', side_effect=[
                    (fixture.NEW, record['candidate_url']),
                    (rollout.SERVICE + '-00045-retargeted', record['candidate_url'])]), \
                    patch.object(rollout, 'smoke', return_value={}), \
                    patch.object(rollout, 'inspect', return_value=(fixture.service(), after)), \
                    patch.object(rollout, 'gcloud', return_value={}) as cli:
                with self.assertRaises(rollout.RolloutError):
                    rollout.promote(args)
                cli.assert_not_called()
                self.assertEqual(rollout.load(receipt)['state'], 'verified')


if __name__ == '__main__':
    unittest.main()
