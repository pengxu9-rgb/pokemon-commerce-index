import json
import re
import unittest
from pathlib import Path


class JapaneseVariantQueueTests(unittest.TestCase):
    def test_committed_sv11b_queue_is_internal_and_source_bound(self):
        catalog = Path(__file__).resolve().parents[1] / "catalog"
        queue = [json.loads(line) for line in
                 (catalog / "ja-sv11b-variant-review-queue.jsonl").read_text().splitlines()]
        audit = json.loads((catalog / "ja-sv11b-variant-review-audit.json").read_text())
        self.assertEqual(len(queue), audit["groups_queued"])
        self.assertEqual(len(queue), 80)
        self.assertEqual(len({row["card_id"] for row in queue}), 80)
        for row in queue:
            self.assertEqual(row["review_status"], "candidate_only")
            self.assertEqual(len(row["official_page_urls"]), 2)
            self.assertEqual(row["distinct_source_image_urls"], 2)
            self.assertEqual(len(row["source_record_sha256"]), 2)
            self.assertNotIn("image_url", row)
            for url in row["official_page_urls"]:
                self.assertRegex(url, r"^https://www\.pokemon-card\.com/card-search/details\.php/card/\d+$")
            for digest in row["source_record_sha256"]:
                self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", digest))


if __name__ == "__main__":
    unittest.main()
