import json
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core
from scripts.blind_listing_eval import evaluate, prepare
from scripts.review_workbench import connect as review_connect
from scripts.review_workbench import export_gold, load_queue, validate_label


class BlindListingEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "catalog.sqlite3"
        db = core.connect(str(self.catalog))
        core.init_db(db)
        core.import_cards(db, [{"language": "ja", "set_code": "SV2a",
                                "collector_number": "173/165", "variant": "standard",
                                "name": "ピカチュウ", "provenance": "synthetic fixture",
                                "rights_reference": "synthetic fixture"}])
        db.close()
        self.manifest = self.root / "catalog-manifest.json"
        self.manifest.write_text(json.dumps({"expected": {"printings": 1,
                                                            "match_eligible": 1}}))
        titles = ["ピカチュウ SV2a 173/165", "ピカチュウ SV2a 173/165",
                  "ピカチュウ SV2a 173/165 2枚セット",
                  "PSA10 鑑定品 ピカチュウ SV2a 173/165",
                  "ピカチュウ SV2a 173/165"]
        self.frame = self.root / "frame.jsonl"
        self.frame.write_text("".join(json.dumps({
            "source": "fixture", "native_id": str(i), "title": title,
            "url": f"https://example.invalid/{i}", "observed_at": "2026-09-28T00:00:00Z",
            "description": "Synthetic evidence", "image_urls": [],
            "stratum": "challenge" if i == 1 else "ordinary",
        }, ensure_ascii=False) + "\n" for i, title in enumerate(titles)))
        self.sample = self.root / "sample"
        prepare(self.frame, self.catalog, self.manifest, self.sample, 5, 42,
                "challenge", "synthetic fixture only", "all five synthetic rows")

    def _gold(self, labels):
        queue = load_queue(self.sample / "review_queue.jsonl")
        reviews = self.root / "reviews.sqlite3"
        with review_connect(reviews) as db:
            for item_key, label in labels.items():
                checked = validate_label(label)
                for reviewer in ("alice_one", "bob_two"):
                    db.execute("INSERT INTO review VALUES (?,?,?,?)",
                               (item_key, reviewer, "2026-09-28T01:00:00Z",
                                json.dumps(checked)))
            output = self.root / "gold.jsonl"
            export_gold(queue, db, output)
        return output

    def _labels(self):
        base = {"single_card": "yes", "language": "ja", "set_code": "SV2a",
                "number": "173/165", "variant": "standard", "grade_status": "raw",
                "image_seen": True, "evidence_notes": "The card and lack of slab are visible."}
        return {
            "fixture:0": base,
            "fixture:1": {**base, "variant": "reverse_masterball"},
            "fixture:2": {"single_card": "no", "variant": "unknown",
                          "grade_status": "unknown"},
            "fixture:3": {**base, "grade_status": "graded", "grade_company": "PSA",
                          "grade_value": "9"},
            "fixture:4": {**base, "grade_status": "unknown"},
        }

    def test_blind_evaluation_separates_identity_printing_grade_and_unknown(self):
        report, details = evaluate(self.sample, self._gold(self._labels()))
        self.assertEqual(report["sample_size"], 5)
        self.assertEqual(report["gold_pending"], 0)
        self.assertEqual(report["auto_accepted_all"], 4)
        self.assertEqual(report["metrics"]["identity"]["incorrect"], 0)
        self.assertEqual(report["metrics"]["printing"]["incorrect"], 1)
        self.assertEqual(report["metrics"]["grade"]["incorrect"], 1)
        self.assertEqual(report["metrics"]["grade"]["accepted_unverifiable"], 1)
        self.assertEqual(report["metrics"]["joint"]["incorrect"], 2)
        self.assertFalse(report["population_claim_eligible"])
        self.assertEqual(len(details), 5)

    def test_pending_gold_stays_in_denominator(self):
        gold = self._gold({"fixture:0": self._labels()["fixture:0"]})
        report, _ = evaluate(self.sample, gold)
        self.assertEqual(report["gold_reviewed"], 1)
        self.assertEqual(report["gold_pending"], 4)
        self.assertEqual(report["auto_accepted_all"], 4)

    def test_frozen_queue_and_gold_must_match(self):
        gold = self._gold({"fixture:0": self._labels()["fixture:0"]})
        rows = [json.loads(line) for line in gold.read_text().splitlines()]
        rows[0]["title"] = "modified title"
        gold.write_text(json.dumps(rows[0]) + "\n")
        with self.assertRaisesRegex(ValueError, "frozen review queue"):
            evaluate(self.sample, gold)
        queue = self.sample / "review_queue.jsonl"
        queue.write_text(queue.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "frozen queue"):
            evaluate(self.sample, gold)

    def test_frame_rejects_embedded_prediction(self):
        row = json.loads(self.frame.read_text().splitlines()[0])
        row["card_id"] = "ja:SV2A:173/165:standard"
        bad = self.root / "bad.jsonl"
        bad.write_text(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "must not contain"):
            prepare(bad, self.catalog, self.manifest, self.root / "bad-sample", 1, 1,
                    "representative", "synthetic fixture only", "synthetic row")


if __name__ == "__main__":
    unittest.main()
