"""Pinned number leads stay outside the offer-matching and price graph."""

import copy
import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, number_aliases, number_conflicts, number_graph


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class NumberAliasTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.rules = [json.loads(line) for line in (
            CATALOG / "ja-number-denominator-conflict-rules.jsonl").read_text().splitlines()]
        self.row = json.loads((CATALOG / "ja-number-alias-candidates.jsonl").read_text().splitlines()[0])
        core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
            "collector_number": self.row["catalog_number"], "variant": self.row["card_id"].rsplit(":", 1)[-1],
            "name": self.row["catalog_name"], "provenance": self.row["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[0]])

    def tearDown(self):
        self.db.close()

    def test_source_bound_alias_does_not_enable_matching(self):
        self.assertEqual(number_aliases.apply_candidates(self.db, [self.row]), {"candidates": 1})
        self.assertEqual(number_aliases.apply_candidates(self.db, [self.row]), {"candidates": 1})
        context = number_graph.card_number_context(self.db, self.row["card_id"])
        alias = context["source_number_alias_candidate"]
        self.assertEqual(alias["official_number_candidate"], "001/054")
        self.assertEqual(alias["physical_printing_status"], "unverified")
        self.assertEqual(alias["offer_matching_status"], "blocked")
        self.assertEqual(context["match_eligible"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_number_alias_candidate").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "number alias evidence"):
            core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
                "collector_number": self.row["catalog_number"],
                "variant": self.row["card_id"].rsplit(":", 1)[-1],
                "name": "違うカード", "provenance": self.row["source_provenance"],
                "rights_reference": "fixture", "display_allowed": False}])

    def test_rejects_number_or_source_evidence_changes(self):
        for change in ({"official_number_candidate": "002/054"},
                       {"source_provenance": "other"},
                       {"official_source_revision": "f" * 40}):
            row = copy.deepcopy(self.row) | change
            with self.assertRaises(ValueError):
                number_aliases.apply_candidates(self.db, [row])
        row = copy.deepcopy(self.row)
        row["official_records"][0]["name"] = "違うカード"
        with self.assertRaises(ValueError):
            number_aliases.apply_candidates(self.db, [row])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_number_alias_candidate").fetchone()[0], 0)

    def test_multi_record_visual_signal_stays_unassigned(self):
        aliases = [json.loads(line) for line in (
            CATALOG / "ja-number-alias-candidates.jsonl").read_text().splitlines()]
        row = next(row for row in aliases if row["card_id"] == "ja:SV11B:001/174:normal")
        visual = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-visual-crosswalk.jsonl").read_text().splitlines()
                      if '"card_id": "ja:SV11B:001/174:normal"' in line)
        core.import_cards(self.db, [{"language": "ja", "set_code": "SV11B",
            "collector_number": row["catalog_number"], "variant": "normal",
            "name": row["catalog_name"], "provenance": row["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[1]])
        number_aliases.apply_candidates(self.db, [row])
        self.assertEqual(number_aliases.apply_visual_context(self.db, [visual]),
                         {"visual_contexts": 1})
        signal = number_graph.card_number_context(self.db, row["card_id"])[
            "multi_record_visual_signal"]
        self.assertEqual(signal["visual_status"], "ai_exact_artwork_surface_question")
        self.assertEqual(signal["official_record_to_catalog_variant_assignment"],
                         "unestablished")
        self.assertEqual(self.db.execute("SELECT match_eligible FROM card WHERE card_id=?",
                                         (row["card_id"],)).fetchone()[0], 0)
        altered = copy.deepcopy(visual)
        altered["source_jp_ids"] = [1, 2]
        with self.assertRaisesRegex(ValueError, "pinned source records"):
            number_aliases.apply_visual_context(self.db, [altered])
        altered = copy.deepcopy(visual)
        altered["official_record_to_catalog_variant_assignment"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "ambiguous number group"):
            number_aliases.apply_visual_context(self.db, [altered])

    def test_stable_image_recovery_preserves_prior_missing_result(self):
        cid = "ja:SV11B:033/174:normal"
        alias = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-candidates.jsonl").read_text().splitlines()
                     if f'"card_id": "{cid}"' in line)
        visual = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-visual-crosswalk.jsonl").read_text().splitlines()
                      if f'"card_id": "{cid}"' in line)
        recovery = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-visual-recovery.jsonl").read_text().splitlines()
                        if f'"card_id": "{cid}"' in line)
        core.import_cards(self.db, [{"language": "ja", "set_code": "SV11B",
            "collector_number": alias["catalog_number"], "variant": "normal",
            "name": alias["catalog_name"], "provenance": alias["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[1]])
        number_aliases.apply_candidates(self.db, [alias])
        number_aliases.apply_visual_context(self.db, [visual])
        self.assertEqual(number_aliases.apply_visual_recoveries(self.db, [recovery]),
                         {"visual_recoveries": 1})
        context = number_graph.card_number_context(self.db, cid)
        self.assertEqual(context["multi_record_visual_signal"]["visual_status"],
                         "image_unavailable")
        self.assertEqual(context["multi_record_visual_recovery"]["visual_status"],
                         "ai_exact_artwork_surface_question")
        self.assertEqual(context["match_eligible"], 0)
        altered = copy.deepcopy(recovery)
        altered["official_record_to_catalog_variant_assignment"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "source-bound missing-image"):
            number_aliases.apply_visual_recoveries(self.db, [altered])

    def test_scan_candidate_binds_each_hash_to_its_record_without_unlocking_offers(self):
        cid = "ja:SV11B:001/174:reverse_pokeball"
        alias = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-candidates.jsonl").read_text().splitlines()
                     if f'"card_id": "{cid}"' in line)
        visual = next(json.loads(line) for line in (
            CATALOG / "ja-number-alias-visual-crosswalk.jsonl").read_text().splitlines()
                      if f'"card_id": "{cid}"' in line)
        candidate = next(json.loads(line) for line in (
            CATALOG / "ja-sv11b-scan-candidates.jsonl").read_text().splitlines()
                         if f'"card_id": "{cid}"' in line)
        core.import_cards(self.db, [{"language": "ja", "set_code": "SV11B",
            "collector_number": alias["catalog_number"], "variant": "reverse_pokeball",
            "name": alias["catalog_name"], "provenance": alias["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[1]])
        number_aliases.apply_candidates(self.db, [alias])
        number_aliases.apply_visual_context(self.db, [visual])
        self.assertEqual(number_aliases.apply_scan_candidates(self.db, [candidate]),
                         {"scan_candidates": 1})
        context = number_graph.card_number_context(self.db, cid)
        self.assertEqual(context["scan_presentation_candidate"]["candidate_official_scan_id"],
                         48087)
        self.assertEqual(context["match_eligible"], 0)
        altered = copy.deepcopy(candidate)
        altered["official_scans"][1]["source_record_sha256"] = candidate["official_scans"][0]["source_record_sha256"]
        with self.assertRaisesRegex(ValueError, "record ID/hash binding"):
            number_aliases.apply_scan_candidates(self.db, [altered])
        altered = copy.deepcopy(candidate)
        altered["price_series_merge_allowed"] = True
        with self.assertRaisesRegex(ValueError, "cannot establish physical printing"):
            number_aliases.apply_scan_candidates(self.db, [altered])

    def test_secondary_number_lead_does_not_change_offer_status(self):
        row = json.loads((CATALOG / "ja-sm10b-secondary-number-candidates.jsonl")
                         .read_text().splitlines()[0])
        core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
            "collector_number": row["catalog_number"], "variant": "holo",
            "name": row["catalog_name"], "provenance": row["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[0]])
        self.assertEqual(number_aliases.apply_secondary_candidates(self.db, [row]),
                         {"secondary_candidates": 1})
        context = number_graph.card_number_context(self.db, row["card_id"])
        self.assertEqual(context["secondary_number_alias_candidate"]["number_candidate"],
                         "063/054")
        self.assertIsNone(context["source_number_alias_candidate"])
        self.assertEqual(context["match_eligible"], 0)
        altered = copy.deepcopy(row)
        altered["merchant_sources"] = altered["merchant_sources"][:1]
        with self.assertRaisesRegex(ValueError, "two independent merchant"):
            number_aliases.apply_secondary_candidates(self.db, [altered])
        with self.assertRaisesRegex(ValueError, "secondary number evidence"):
            core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
                "collector_number": row["catalog_number"], "variant": "holo",
                "name": "違うカード", "provenance": row["source_provenance"],
                "rights_reference": "fixture", "display_allowed": False}])


if __name__ == "__main__":
    unittest.main()
