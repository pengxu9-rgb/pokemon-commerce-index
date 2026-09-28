import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_workbench import (connect, disagree, export_gold, load_queue,
                                      next_review, status, validate_label)


class ReviewWorkbenchTests(unittest.TestCase):
    def test_specific_finish_requires_photo_review(self):
        base = {"single_card": "yes", "language": "ja", "set_code": "SV2a",
                "number": "185/165", "variant": "holo", "image_seen": False}
        with self.assertRaisesRegex(ValueError, "photo"):
            validate_label(base)
        label = validate_label({**base, "image_seen": True,
                                "evidence_notes": "The holo surface is visible in photo 1."})
        self.assertEqual(label["number"], "185/165")
        self.assertEqual(label["variant"], "holo")

    def test_independent_reviews_and_adjudication_gate_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_path = root / "queue.jsonl"
            queue_path.write_text(json.dumps({
                "item_key": "fixture:a", "source": "fixture", "native_id": "a",
                "title": "Synthetic SV2a 185/165", "url": "https://example.invalid/a",
                "description": "", "image_urls": [],
            }) + "\n")
            queue = load_queue(queue_path)
            with connect(root / "reviews.sqlite3") as db:
                first = validate_label({"single_card": "yes", "language": "ja",
                                        "set_code": "SV2a", "number": "185/165",
                                        "variant": "unknown", "image_seen": False,
                                        "evidence_notes": "The title gives the set and number."})
                second = validate_label({**first, "number": "201/165"})
                self.assertTrue(disagree({"label": first}, {"label": second}))
                db.execute("INSERT INTO review VALUES (?,?,?,?)",
                           ("fixture:a", "reviewer_one", "2026-09-23T00:00:00Z", json.dumps(first)))
                self.assertEqual(next_review(queue, db, "reviewer_one")["item"], None)
                self.assertIsNotNone(next_review(queue, db, "reviewer_two")["item"])
                db.execute("INSERT INTO review VALUES (?,?,?,?)",
                           ("fixture:a", "reviewer_two", "2026-09-23T00:01:00Z", json.dumps(second)))
                self.assertEqual(status(queue, db)["conflicts"], 1)
                result = export_gold(queue, db, root / "pending.jsonl")
                self.assertEqual((result["exported"], result["pending"]), (0, 1))
                db.execute("INSERT INTO adjudication VALUES (?,?,?,?,?)",
                           ("fixture:a", "third_person", "2026-09-23T00:02:00Z",
                            json.dumps(first), "The printed number is 185/165"))
                result = export_gold(queue, db, root / "gold.jsonl")
                self.assertEqual((result["exported"], result["pending"]), (1, 0))
                gold = json.loads((root / "gold.jsonl").read_text())
                self.assertEqual(gold["proposed_number"], "185/165")
                self.assertIsNone(gold["proposed_variant"])
                self.assertTrue(gold["human_reviewed"])
