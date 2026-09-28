import json
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core
from scripts.ai_review_triage import audit, listing_sha256, triage
from scripts.blind_listing_eval import prepare, read_jsonl, write_jsonl
from scripts.review_workbench import connect as review_connect
from scripts.review_workbench import export_gold, load_queue, validate_label


class AIReviewTriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        catalog = self.root / "catalog.sqlite3"
        db = core.connect(str(catalog))
        core.init_db(db)
        core.import_cards(db, [{"language": "ja", "set_code": "SV2a",
                                "collector_number": "173/165", "variant": "standard",
                                "name": "ピカチュウ", "provenance": "synthetic fixture",
                                "rights_reference": "synthetic fixture"}])
        db.close()
        manifest = self.root / "catalog-manifest.json"
        manifest.write_text(json.dumps({"expected": {"printings": 1,
                                                     "match_eligible": 1}}))
        frame = self.root / "frame.jsonl"
        rows = []
        for i in range(3):
            images = [f"https://example.invalid/{i}/front"] if i < 2 else []
            hashes = [f"{i + 1:064x}"] if i < 2 else []
            rows.append({"source": "fixture", "native_id": str(i),
                         "title": "ピカチュウ SV2a 173/165",
                         "url": f"https://example.invalid/{i}",
                         "observed_at": "2026-09-28T00:00:00Z",
                         "description": "Synthetic listing", "image_urls": images,
                         "image_sha256": hashes})
        write_jsonl(frame, rows)
        self.sample = self.root / "sample"
        prepare(frame, catalog, manifest, self.sample, 3, 11, "representative",
                "synthetic fixture", "all three synthetic listings")
        self.items = {row["item_key"]: row for row in read_jsonl(
            self.sample / "review_queue.jsonl")}
        self.reviews = self.root / "ai-reviews.jsonl"
        self.triage_dir = self.root / "triage"

    @staticmethod
    def label(variant="standard"):
        return {"single_card": "yes", "language": "ja", "set_code": "SV2A",
                "number": "173/165", "variant": variant, "grade_status": "raw",
                "image_seen": True, "evidence_notes": "Card front and raw holder visible."}

    def ai_row(self, key, family, *, variant="standard", confidence=0.99):
        item = self.items[key]
        return {"item_key": key, "model_family": family,
                "listing_sha256": listing_sha256(item),
                "image_sha256": item["image_sha256"],
                "confidence": {"identity": confidence, "printing": confidence,
                               "grade": confidence},
                "label": self.label(variant)}

    def _reviews(self):
        rows = []
        for i in range(3):
            key = f"fixture:{i}"
            rows.append(self.ai_row(key, "family_a"))
            rows.append(self.ai_row(key, "family_b",
                                    variant="reverse_masterball" if i == 1 else "standard"))
        write_jsonl(self.reviews, rows)

    def test_consensus_escalation_and_blind_human_audit(self):
        self._reviews()
        result = triage(self.sample, self.reviews, self.triage_dir,
                        min_confidence=0.95, audit_size=1, seed=5,
                        media_ai_rights_ref="synthetic fixture")
        self.assertEqual(result["ai_approved_pending_audit"], 1)
        self.assertEqual(result["human_escalation"], 2)
        self.assertEqual(result["human_audit"], 1)
        queue = read_jsonl(self.triage_dir / "human_queue.jsonl")
        self.assertEqual(len(queue), 3)
        self.assertTrue(all("label" not in row and "model_family" not in row
                            for row in queue))

        review_db = self.root / "human.sqlite3"
        with review_connect(review_db) as db:
            label = validate_label(self.label("reverse_masterball"))
            for reviewer in ("human_one", "human_two"):
                db.execute("INSERT INTO review VALUES (?,?,?,?)",
                           ("fixture:0", reviewer, "2026-09-28T01:00:00Z",
                            json.dumps(label)))
            gold = self.root / "gold.jsonl"
            export_gold(load_queue(self.triage_dir / "human_queue.jsonl"), db, gold)
        report = audit(self.sample, self.triage_dir, gold)
        self.assertEqual(report["joint_incorrect"], 1)
        self.assertEqual(report["review_pending"], 0)
        self.assertEqual(report["initial_auto_join_gate"], "insufficient_or_failed")

    def test_stale_photo_and_duplicate_model_are_rejected(self):
        self._reviews()
        rows = read_jsonl(self.reviews)
        rows[0]["image_sha256"] = ["0" * 64]
        write_jsonl(self.reviews, rows)
        with self.assertRaisesRegex(ValueError, "image hashes"):
            triage(self.sample, self.reviews, self.triage_dir,
                   min_confidence=0.95, audit_size=1, seed=5,
                   media_ai_rights_ref="synthetic fixture")
        rows[0]["image_sha256"] = self.items["fixture:0"]["image_sha256"]
        rows[1]["model_family"] = rows[0]["model_family"]
        write_jsonl(self.reviews, rows)
        with self.assertRaisesRegex(ValueError, "duplicate model family"):
            triage(self.sample, self.reviews, self.triage_dir,
                   min_confidence=0.95, audit_size=1, seed=5,
                   media_ai_rights_ref="synthetic fixture")

    def test_low_confidence_escalates_even_when_models_agree(self):
        self._reviews()
        rows = read_jsonl(self.reviews)
        rows[0]["confidence"]["printing"] = 0.75
        write_jsonl(self.reviews, rows)
        result = triage(self.sample, self.reviews, self.triage_dir,
                        min_confidence=0.95, audit_size=0, seed=5,
                        media_ai_rights_ref="synthetic fixture")
        self.assertEqual(result["ai_approved_pending_audit"], 0)
        self.assertEqual(result["human_escalation"], 3)
        self.assertEqual(result["escalation_reasons"]["low_confidence"], 1)


if __name__ == "__main__":
    unittest.main()
