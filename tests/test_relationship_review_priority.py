import sqlite3
import unittest
from pathlib import Path

from scripts.relationship_pilot import read_jsonl
from scripts.relationship_review_priority import prioritize


ROOT = Path(__file__).resolve().parents[1]


class RelationshipPriorityTests(unittest.TestCase):
    def test_high_rarity_counterpart_survives_large_release_gap(self):
        rows = read_jsonl(ROOT / "catalog/concept-review-v6-expanded-relationship-queue.jsonl")
        candidates = [row for row in rows if row["anchor"]["name"] == "なかよしポフィン"
                      and row["candidate"]["card_id"] in {
                          "en:ME01:167/132:holo", "en:SV06:223/167:holo_gold"}]
        self.assertEqual(len(candidates), 2)
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE catalog_set_localized (language TEXT, set_code TEXT, release_date TEXT)")
        db.executemany("INSERT INTO catalog_set_localized VALUES (?,?,?)", [
            ("ja", "SV6", "2024-01-01"), ("en", "ME01", "2024-01-02"),
            ("en", "SV06", "2025-01-01")])
        first, _, audit = prioritize(db, [candidates])
        self.assertEqual(first[0]["candidate"]["card_id"], "en:SV06:223/167:holo_gold")
        self.assertEqual(audit["first_pass_distinctive_rarity_mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
