"""Evaluator mechanics only. These tests establish no collector usefulness."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('independent_eval_runner', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def response(card_ids=('ja:TEST:001/010:normal',), target=None, **kwargs):
    cards = []
    for cid in card_ids:
        lang, release, number, variant = cid.split(':')
        cards.append(dict(card_id=cid, language=lang, set_code=release,
                          collector_number=number, variant=variant, provenance='test:source'))
    return dict(candidate_cards=cards, target_intent={'card_id': target} if target else None,
                selected_catalog_target=None, card_selection_blockers={cid: [] for cid in card_ids},
                selection_blockers=[], selection_allowed=bool(cards),
                discovery={'task': 'collector_recommendations'}, **kwargs)


def case(steps=None, checks=None, case_id='TEST'):
    return dict(id=case_id, category='harness_only', question='Harness question', limit=5,
                steps=steps or [{'action': {'type': 'ask', 'question': 'Harness question'}}],
                expected={'automatable_checks': checks or []})


class RunnerTests(unittest.TestCase):
    def test_frozen_integrity_and_all_thirty_cases(self):
        suite, freeze = runner.verify_fixture()
        self.assertEqual(len(suite['cases']), 30)
        self.assertEqual(freeze['files']['questions.json']['sha256'],
                         '2c6013fe0362e0eb9164063e7184ad264ae337c363a15e2eb9b17e4ca0a03ab1')

    def test_frozen_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'metadata').mkdir()
            for name in ('questions.json', 'rubric.json', 'binding-contract.json', 'metadata/freeze.json'):
                shutil.copyfile(runner.HERE / name, root / name)
            with (root / 'questions.json').open('a') as stream:
                stream.write(' ')
            with self.assertRaisesRegex(ValueError, 'frozen fixture changed'):
                runner.verify_fixture(root)

    def test_raw_question_not_rewritten(self):
        step = {'action': {'type': 'ask', 'question': 'Keep THIS raw wording?'}}
        self.assertEqual(runner.resolve_action(step, [], {}), step['action'])

    def test_only_prior_shown_candidate_binding(self):
        step = {'action': {'type': 'feedback', 'card_id': {'$bind': 'x'}, 'reaction': 'like'},
                'bind': {'x': {'from_step': 0, 'candidate_index': 0}}}
        prior = [{'response': response()}]
        self.assertEqual(runner.resolve_action(step, prior, {})['card_id'], 'ja:TEST:001/010:normal')

    def test_missing_candidate_does_not_search_elsewhere(self):
        step = {'action': {'type': 'feedback', 'card_id': {'$bind': 'x'}, 'reaction': 'like'},
                'bind': {'x': {'from_step': 0, 'candidate_index': 0}}}
        with self.assertRaisesRegex(ValueError, 'binding unavailable'):
            runner.resolve_action(step, [{'response': response(())}], {})

    def test_nested_authority_is_checked(self):
        found = runner.authority_violations({'comparison': [{'physical_printing_verified': True}]})
        self.assertEqual(found, ['response.comparison[0].physical_printing_verified'])

    def test_market_values_are_checked(self):
        self.assertTrue(runner.authority_violations({'prices': [50]}))
        self.assertFalse(runner.authority_violations({'prices': [], 'purchase_ready': False}))

    def test_target_without_select_is_safety_failure(self):
        prefix = dict(action={'type': 'choose_comparison'}, response=response(target='a'))
        self.assertIn('step[0].target_created_without_separate_selection',
                      runner.safety_checks(case(), [prefix]))

    def test_separate_select_does_not_claim_purchase(self):
        prefix = dict(action={'type': 'select'}, response=response(target='ja:TEST:001/010:normal'))
        self.assertEqual(runner.safety_checks(case(), [prefix]), [])

    def test_comparison_selection_authority_fails(self):
        value = response(())
        value['discovery']['task'] = 'two_card_comparison'
        value['selection_allowed'] = True
        prefix = dict(action={'type': 'ask'}, response=value)
        self.assertTrue(runner.safety_checks(case(), [prefix]))

    def test_stale_or_held_action_acceptance_is_safety_failure(self):
        for cid in ('ICU-29', 'ICU-30'):
            prefix = dict(action={'type': 'select'}, response=response())
            self.assertIn('stale_or_identity_held_action_was_accepted',
                          runner.safety_checks(case(case_id=cid), [prefix]))

    def test_coordinate_diversity_does_not_merge_versions(self):
        value = response(('ja:TEST:001/010:normal', 'ja:TEST:001/010:holo'))
        req = {'check': 'minimum_coordinates', 'value': 2}
        result = runner.check_constraints(case(checks=[req]), [{'response': value}])
        self.assertFalse(result[0]['mechanical_pass'])
        self.assertEqual(result[0]['observed'], 1)

    def test_empty_response_cannot_pass_minimum_candidate_check(self):
        req = {'check': 'minimum_candidates', 'value': 3}
        result = runner.check_constraints(case(checks=[req]), [{'response': response(())}])
        self.assertFalse(result[0]['mechanical_pass'])

    def test_unknown_check_is_runner_error(self):
        with self.assertRaisesRegex(ValueError, 'does not implement'):
            runner.check_constraints(case(checks=[{'check': 'unimplemented'}]), [])

    def test_expected_value_error_retained(self):
        c = case(steps=[{'action': {'type': 'select', 'card_id': 'held'}, 'expect_error': True}])
        def reject(*args, **kwargs):
            raise ValueError('identity held')
        r = runner.execute_case(c, None, reject, 'revision', {}, 1)
        self.assertEqual(r['execution_status'], 'executed')
        self.assertEqual(r['prefixes'][0]['execution_status'], 'expected_rejection')
        self.assertEqual(r['prefixes'][0]['error'], 'identity held')

    def test_unexpected_api_error_fails_execution(self):
        def reject(*args, **kwargs):
            raise ValueError('unexpected parser failure')
        r = runner.execute_case(case(), None, reject, 'revision', {}, 1)
        self.assertEqual(r['execution_status'], 'execution_error')
        self.assertEqual(runner.execution_exit([r]), 3)

    def test_expected_rejection_does_not_hide_internal_keyerror(self):
        c = case(steps=[{'action': {'type': 'select', 'card_id': 'held'}, 'expect_error': True}])
        def reject(*args, **kwargs):
            raise KeyError('bug')
        r = runner.execute_case(c, None, reject, 'revision', {}, 1)
        self.assertEqual(r['execution_status'], 'execution_error')

    def test_missing_candidate_is_product_path_failure_not_infrastructure(self):
        c = case(steps=[{'action': {'type': 'ask', 'question': 'Harness question'}},
                        {'action': {'type': 'feedback', 'card_id': {'$bind': 'x'}, 'reaction': 'like'},
                         'bind': {'x': {'from_step': 0, 'candidate_index': 0}}}])
        with patch.object(runner, 'candidate_evidence', return_value=[]):
            r = runner.execute_case(c, None, lambda *a, **k: response(()), 'revision', {}, 1)
        self.assertEqual(r['execution_status'], 'product_path_blocked')
        self.assertEqual(runner.execution_exit([r]), 0)

    def test_usefulness_mechanical_failure_does_not_fail_ci(self):
        row = {'execution_status': 'executed', 'safety_violations': [], 'mechanical_constraints_met': False}
        self.assertEqual(runner.execution_exit([row]), 0)
        row['safety_violations'] = ['unsupported_authority']
        self.assertEqual(runner.execution_exit([row]), 2)

    def test_mutation_fails_even_if_constraints_pass(self):
        row = {'execution_status': 'executed', 'safety_violations': [], 'mechanical_constraints_met': True}
        self.assertEqual(runner.execution_exit([row], integrity_ok=False), 3)

    def test_scores_are_never_invented_by_runner(self):
        score = runner.blank_score('ICU-01', 'not_executed')
        for axis in ('relevance', 'evidence_honesty', 'clarification_usefulness', 'completion', 'abstention_quality'):
            self.assertIsNone(score[axis])

    def test_reports_cannot_overwrite_prior_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            runner.save_new(path, {'failed': True})
            with self.assertRaises(FileExistsError):
                runner.save_new(path, {'passed': True})

    def test_preflight_retains_missing_and_hash_mismatched_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'wrong').write_text('wrong')
            data = {'schema': 'pokemon.catalog-build.v1', 'steps': [
                {'path': 'missing', 'sha256': '0'*64}, {'path': 'wrong', 'sha256': '0'*64}]}
            (root / 'manifest.json').write_text(json.dumps(data))
            r = runner.preflight(root / 'manifest.json')
            self.assertEqual(r['counts'], {'missing': 1, 'hash_mismatch': 1})
            self.assertFalse(r['complete'])

    def test_mismatched_build_receipt_is_rejected_before_runtime_access(self):
        with self.assertRaisesRegex(ValueError, 'build receipt'):
            runner.verify_snapshot(None, {'expected': {}, 'steps': []}, {}, Path('/tmp/a'), 'expected')


if __name__ == '__main__':
    unittest.main(verbosity=2)
