"""Multi-record image evidence must never become a physical identity claim."""

import copy
import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, multi_record_scans, number_graph


EVIDENCE = Path(__file__).resolve().parents[1] / "catalog/ja-multi-record-scan-evidence.jsonl"
REVISION = "bc5a2698eb9af858feb0280d579fd5fd0f0273e2"


class MultiRecordScanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)

    def tearDown(self):
        self.db.close()

    def _load(self, card_id):
        row = next(json.loads(line) for line in EVIDENCE.read_text().splitlines()
                   if f'"card_id": "{card_id}"' in line)
        provenance = "|".join(
            f"ptcg-database:{REVISION}:{item['source_path']}:sha256:{item['source_record_sha256']}"
            for item in row["source_records"])
        card = {"language": "ja", "set_code": row["set_code"],
                "collector_number": row["collector_number"],
                "variant": "unverified_multi_record", "name": "fixture",
                "provenance": provenance, "rights_reference": "fixture",
                "display_allowed": False, "match_eligible": True}
        core.import_cards(self.db, [card])
        return row, card

    def test_import_exact_artwork_and_keep_group_blocked(self):
        row, card = self._load("ja:XY:001/171:unverified_multi_record")
        self.assertEqual(multi_record_scans.apply_evidence(self.db, [row]),
                         {"multi_record_scan_groups": 1})
        context = number_graph.card_number_context(self.db, row["card_id"])
        self.assertEqual(context["multi_record_scan_evidence"]["artwork_relation"],
                         "exact_artwork")
        self.assertEqual(context["match_eligible"], 0)
        altered = copy.deepcopy(row)
        altered["source_records"][0]["source_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "catalog source provenance"):
            multi_record_scans.apply_evidence(self.db, [altered])
        altered = copy.deepcopy(row)
        altered["price_series_merge_allowed"] = True
        with self.assertRaisesRegex(ValueError, "blocked group card"):
            multi_record_scans.apply_evidence(self.db, [altered])
        with self.assertRaisesRegex(ValueError, "multi-record scan evidence"):
            core.import_cards(self.db, [card | {"provenance": "changed"}])

    def test_missing_image_remains_unresolved(self):
        row, _ = self._load("ja:HST:001/037:unverified_multi_record")
        multi_record_scans.apply_evidence(self.db, [row])
        context = number_graph.card_number_context(self.db, row["card_id"])
        self.assertEqual(context["multi_record_scan_evidence"]["review_status"],
                         "image_unavailable")
        self.assertEqual(context["multi_record_scan_evidence"]["artwork_relation"],
                         "unresolved")


if __name__ == "__main__":
    unittest.main()
