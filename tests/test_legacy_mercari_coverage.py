import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core
from scripts.audit_legacy_mercari_coverage import _candidate_codes, audit


class LegacyCoverageTests(unittest.TestCase):
    def test_set_aliases_and_artwork_shorthand_do_not_invent_a_printing(self):
        codes = {"S6A", "SA", "MA", "M2A", "DPS-B"}
        pattern = re.compile(r"(?<![A-Za-z0-9])(?:DPS-B|S6A|M2A|MA|SA)(?![A-Za-z0-9])", re.I)
        self.assertEqual(_candidate_codes("ブラッキーVMAX SA S6a 095/069", codes, pattern),
                         ({"S6A"}, "exact"))
        self.assertEqual(_candidate_codes("メガリザードン MA メガドリーム 223/193", codes, pattern),
                         ({"M2A"}, "set_name"))
        self.assertEqual(_candidate_codes("メガリザードン MA 223/193", codes, pattern),
                         (set(), "artwork_shorthand"))
        self.assertEqual(_candidate_codes("リザードン DP6 092/092", codes, pattern),
                         ({"DPS-B"}, "legacy_alias"))

    def test_fixture_photo_counts_and_catalog_gap_without_listing_leak(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        core.init_db(db)
        core.import_cards(db, [{"language": "ja", "set_code": "S6a",
                                "collector_number": "048/069", "variant": "standard",
                                "name": "ブラッキーVMAX", "provenance": "fixture",
                                "rights_reference": "fixture", "display_allowed": False}])
        item = {"id": "m123456789", "name": "ブラッキーVMAX S6a 095/069",
                "status": "on_sale", "price": 999999,
                "photos": ["https://example.invalid/one", "https://example.invalid/two"]}
        cassette = {"interactions": [{
            "request": {"url": "https://gateway.invalid/v1/supplysrv/tanosys/mercari/search"},
            "response": {"status_code": 200, "body": json.dumps({"data": [item]})}}]}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "test_cassette.json").write_text(json.dumps(cassette))
            before = audit(db, Path(directory))
            self.assertEqual(before["counts"]["with_two_or_more_photos"], 1)
            self.assertEqual(before["missing_set_number_groups"][0]["collector_number"],
                             "095/069")
            core.import_cards(db, [{"language": "ja", "set_code": "S6a",
                                    "collector_number": "095/069", "variant": "unverified_hr_sa",
                                    "name": "ブラッキーVMAX", "provenance": "fixture",
                                    "rights_reference": "fixture", "display_allowed": False,
                                    "match_eligible": False}])
            after = audit(db, Path(directory))
            self.assertEqual(after["counts"]["catalog_identity_present"], 1)
            self.assertEqual(after["counts"]["catalog_match_eligible_present"], 0)
            self.assertEqual(after["missing_set_number_groups"], [])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM priceable_unit").fetchone()[0], 0)
            serial = json.dumps(after)
            self.assertNotIn("999999", serial)
            self.assertNotIn("m123456789", serial)
            self.assertNotIn("example.invalid/one", serial)
        db.close()


if __name__ == "__main__":
    unittest.main()
