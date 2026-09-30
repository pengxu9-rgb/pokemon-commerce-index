import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import vertex_question_batch_v11 as batch
from scripts import evaluate_question_routes_v11 as evaluation
from scripts.public_question_sandbox import sha_file


class SourceBatchTests(unittest.TestCase):
    def fixture(self):
        return ({'id':'new-1','source_url':'https://example.com','question':'Where can I sell cards?',
                 'media_state':'text_only'},
                {'post_locator':'Original question', 'verification_method':'opened_post',
                 'anchor':'sell cards', 'source_context':'An owner explicitly asks where to sell cards.'})

    def test_incomplete_source_calls_are_excluded_and_retained(self):
        question,evidence=self.fixture()
        budgets=[]
        def reply(*args):
            budgets.append(args[-1]['generationConfig']['maxOutputTokens'])
            return {'candidates':[{'finishReason':'MAX_TOKENS'}]}
        with patch.object(batch.audit,'_call_model',side_effect=reply):
            row=batch.source_one(question,evidence,'src','ev','project','global','test-token')
        self.assertEqual(row['status'],'unverifiable')
        self.assertEqual(len(row['attempt_errors']),2)
        self.assertEqual(budgets,[8192,16384])

    def test_unrecognized_source_verdict_cannot_pass_gate(self):
        question,evidence=self.fixture()
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(
            {'status':'trusted','reason':'Sounds plausible'})}]}}]}
        with patch.object(batch.audit,'_call_model',return_value=response):
            row=batch.source_one(question,evidence,'src','ev','project','global','test-token')
        self.assertEqual(row['status'],'unverifiable')
        self.assertEqual(row['attempts'],2)


class FreshEvaluatorTests(unittest.TestCase):
    def test_fresh_role_and_evidence_hashes_are_required_before_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['source_index.jsonl','source_evidence.jsonl']:
                (root/name).write_text('{}\n')
            locked_file=root/'locked-runtime.py';locked_file.write_text('original')
            (root/'collection_lock.json').write_text(json.dumps(
                {'code_sha256':{str(locked_file):sha_file(locked_file)}}))
            manifest={'evaluation_role':'fresh source-post diagnostic for unchanged v7',
                      'evaluator_sha256':sha_file(Path(evaluation.__file__)),
                      'source_index_sha256':sha_file(root/'source_index.jsonl'),
                      'source_evidence_sha256':sha_file(root/'source_evidence.jsonl'),
                      'collection_lock_sha256':sha_file(root/'collection_lock.json')}
            (root/'manifest.json').write_text(json.dumps(manifest))
            with patch.object(evaluation.baseline,'evaluate',return_value={'results':[]}) as replay:
                result=evaluation.evaluate(root,root/'db',root/'facts',root/'labels')
                self.assertEqual(result['schema'],'pokemon.question-v11-fresh-diagnostic.v1')
                replay.assert_called_once()
                (root/'source_index.jsonl').write_text('changed')
                replay.reset_mock()
                with self.assertRaisesRegex(ValueError,'source_index_sha256'):
                    evaluation.evaluate(root,root/'db',root/'facts',root/'labels')
                replay.assert_not_called()
                (root/'source_index.jsonl').write_text('{}\n')
                locked_file.write_text('changed')
                with self.assertRaisesRegex(ValueError,'collection-locked code changed'):
                    evaluation.evaluate(root,root/'db',root/'facts',root/'labels')
