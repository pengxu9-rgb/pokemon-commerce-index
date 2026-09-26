import csv
import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class RelationshipScaleBatchTests(unittest.TestCase):
    def test_thousand_cross_region_pairs_are_distinct_and_pending(self):
        queue = read_jsonl(CATALOG / "relationship-scale-v1-queue.jsonl")
        audit = json.loads((CATALOG / "relationship-scale-v1-audit.json").read_text())
        source_audit = json.loads((CATALOG / "relationship-scale-v1-source-audit.json").read_text())
        self.assertEqual(len(queue), 1000)
        with (CATALOG / "relationship-scale-v1-review-template.csv").open(
                encoding="utf-8-sig", newline="") as handle:
            review_rows = list(csv.DictReader(handle))
        self.assertEqual(len(review_rows), len(queue))
        self.assertEqual({row["candidate_id"] for row in review_rows},
                         {row["candidate_id"] for row in queue})
        self.assertEqual({row["decision"] for row in review_rows}, {"pending"})
        self.assertEqual(len(queue), audit["selected_pairs"])
        self.assertEqual(len(queue), source_audit["candidate_pairs"])
        self.assertEqual(source_audit["queue_sha256"], hashlib.sha256(
            (CATALOG / "relationship-scale-v1-queue.jsonl").read_bytes()).hexdigest())
        self.assertGreaterEqual(source_audit["unique_pinned_source_files_checked"], 1000)
        self.assertEqual(len({row["candidate_id"] for row in queue}), len(queue))
        self.assertEqual(len({tuple(sorted((row["anchor"]["card_id"],
                                            row["candidate"]["card_id"])))
                              for row in queue}), len(queue))
        self.assertEqual(dict(sorted(Counter(row["selection_reason"] for row in queue).items())),
                         audit["selected_by_stratum"])
        self.assertGreaterEqual(audit["selected_ja_sets"], 50)
        self.assertLessEqual(audit["largest_ja_set_count"], audit["max_pairs_per_ja_set"])
        for row in queue:
            anchor, candidate = row["anchor"], row["candidate"]
            self.assertEqual((anchor["language"], candidate["language"]), ("ja", "en"))
            pair = sorted((anchor["card_id"], candidate["card_id"]))
            expected = hashlib.sha256(("relationship-pilot-v1\0" + "\0".join(pair)).encode()).hexdigest()[:20]
            self.assertEqual(row["candidate_id"], expected)
            self.assertRegex(row["source_snapshot_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(row["retrieval_only"])
            self.assertEqual(row["review"]["decision"], "pending")
            self.assertFalse(anchor["display_allowed"])
            self.assertFalse(candidate["display_allowed"])
            self.assertNotIn("price", row)

    def test_all_variant_groups_remain_unverified_and_include_prior_batch(self):
        queue = read_jsonl(CATALOG / "ja-variant-review-all-queue.jsonl")
        previous = read_jsonl(CATALOG / "ja-sv11b-variant-review-queue.jsonl")
        audit = json.loads((CATALOG / "ja-variant-review-all-audit.json").read_text())
        by_id = {row["card_id"]: row for row in queue}
        self.assertEqual(len(queue), 462)
        self.assertEqual(len(by_id), len(queue))
        self.assertEqual(audit["groups_queued"], len(queue))
        self.assertEqual(audit["sets_queued"], len({row["set_code"] for row in queue}))
        self.assertEqual(sum(audit["records_per_group"].values()), len(queue))
        self.assertEqual(sum(audit["differing_field_patterns"].values()), len(queue))
        for old in previous:
            self.assertEqual(by_id[old["card_id"]], old)
        for row in queue:
            self.assertEqual(row["review_status"], "candidate_only")
            n = len(row["source_jp_ids"])
            self.assertGreaterEqual(n, 2)
            self.assertEqual(n, len(row["official_page_urls"]))
            self.assertEqual(n, len(row["source_record_sha256"]))
            self.assertEqual(len(set(row["official_page_urls"])), n)
            self.assertNotIn("image_urls", row)
            for url in row["official_page_urls"]:
                self.assertRegex(url, r"^https://www\.pokemon-card\.com/card-search/details\.php/card/\d+$")
            for digest in row["source_record_sha256"]:
                self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", digest))


if __name__ == "__main__":
    unittest.main()
