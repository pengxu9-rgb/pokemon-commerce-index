import unittest

from pokemon_index import core
from scripts.evaluate_buyer_questions import evaluate


def gold_row(item_id, kind, card_id=None, language=None):
    label = {"question_type": kind, "card_id": card_id, "target_language": language}
    return {"id": item_id, "question": "Fixture question", "adjudicated": label,
            "reviewers": [{"id": "reviewer-a", "label": dict(label)},
                          {"id": "reviewer-b", "label": dict(label)}]}


class BuyerQuestionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(":memory:")
        core.init_db(self.db)
        core.import_cards(self.db, [dict(
            language="ja", set_code="SV2a", collector_number="025/165",
            variant="normal", name="ピカチュウ", provenance="fixture",
            rights_reference="fixture")])
        self.card_id = "ja:SV2A:025/165:normal"

    def tearDown(self):
        self.db.close()

    def test_counts_correct_route_abstention_and_premature_card(self):
        gold = [gold_row("one", "printing_variants", self.card_id),
                gold_row("two", "condition"), gold_row("three", "unsupported")]
        predictions = [
            {"id": "one", "question_type": "printing_variants", "card_id": self.card_id,
             "target_language": None},
            {"id": "two", "question_type": "condition", "card_id": self.card_id,
             "target_language": None},
            {"id": "three", "question_type": None, "card_id": None,
             "target_language": None},
        ]
        report = evaluate(self.db, gold, predictions)
        self.assertEqual(report["questions"], 3)
        self.assertEqual(report["joint_correct"], 2)
        self.assertEqual(report["premature_card_selections"], 1)
        self.assertEqual(report["abstentions"], 1)
        self.assertEqual(report["invalid_plan_inputs"], 0)

    def test_incomplete_or_nonindependent_gold_fails(self):
        gold = [gold_row("one", "printing_variants", self.card_id)]
        prediction = [{"id": "one", "question_type": "printing_variants",
                       "card_id": self.card_id, "target_language": None}]
        with self.assertRaisesRegex(ValueError, "every frozen gold question"):
            evaluate(self.db, gold, [])
        gold[0]["reviewers"][1]["id"] = "reviewer-a"
        with self.assertRaisesRegex(ValueError, "two distinct agreeing"):
            evaluate(self.db, gold, prediction)


if __name__ == "__main__":
    unittest.main()
