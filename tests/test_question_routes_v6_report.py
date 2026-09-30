import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pokemon_index import core, catalog_question_resolver_v2 as resolver
from pokemon_index import question_routing_v6 as routing
from scripts import vertex_public_question_facts_v6 as extractor
from scripts.evaluate_question_routes_v6 import evaluate
from scripts.public_question_sandbox import sha_file, write_jsonl
from tests import test_public_question_facts_v6 as fixtures


class QuestionRoutesV6ReportTests(unittest.TestCase):
    def fixture(self, root):
        question, answer = fixtures.PublicQuestionFactsV6Tests().answer()
        question['question_sha256'] = 'a' * 64
        facts = {'id': question['id'], 'question_sha256': question['question_sha256'],
                 'model_family': 'google', 'requested_model': extractor.MODEL,
                 'prompt_version': extractor.PROMPT_VERSION,
                 'prompt_sha256': extractor._request(question)[1],
                 'status': 'ok', **answer}
        write_jsonl(root / 'blind_questions.jsonl', [question])
        write_jsonl(root / 'facts.jsonl', [facts])
        write_jsonl(root / 'expectations.jsonl', [{'id': question['id'],
            'allowed_goals': ['seller_saleability'],
            'explicit_sale_formats': ['single', 'evolution_line'],
            'required_actions': ['review_sale_cohort']}])
        catalog = root / 'catalog.sqlite3'
        with closing(core.connect(catalog)) as db:
            core.init_db(db)
        paths = {'blind_sha256': root / 'blind_questions.jsonl',
                 'catalog_snapshot_sha256': catalog,
                 'researcher_expectations_sha256': root / 'expectations.jsonl',
                 'v6_planner_sha256': Path(routing.__file__),
                 'v6_fact_extractor_sha256': Path(extractor.__file__),
                 'catalog_resolver_sha256': Path(resolver.__file__)}
        (root / 'manifest.json').write_text(json.dumps({k: sha_file(v) for k, v in paths.items()}))
        return facts

    def report(self, root):
        return evaluate(root, root / 'catalog.sqlite3', root / 'facts.jsonl',
                        root / 'expectations.jsonl')

    def test_report_checks_evidence_gates_without_mutating_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            before = sha_file(root / 'catalog.sqlite3')
            report = self.report(root)
            self.assertEqual((report['questions'], report['valid'], report['goal_agreement']), (1, 1, 1))
            self.assertEqual(report['market_ready_cases'], 0)
            self.assertEqual(report['formats_agreement'], 1)
            self.assertEqual(sha_file(root / 'catalog.sqlite3'), before)

    def test_failed_extraction_remains_in_the_question_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts = self.fixture(root)
            facts.update(status='error', facts=None)
            write_jsonl(root / 'facts.jsonl', [facts])
            report = self.report(root)
            self.assertEqual((report['questions'], report['valid'], report['errors']), (1, 0, 1))

    def test_changed_expectation_or_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts = self.fixture(root)
            facts['prompt_sha256'] = 'b' * 64
            write_jsonl(root / 'facts.jsonl', [facts])
            with self.assertRaisesRegex(ValueError, 'prompt or model changed'):
                self.report(root)
            (root / 'expectations.jsonl').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'evaluation input changed'):
                self.report(root)
