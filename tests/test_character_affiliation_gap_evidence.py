"""21 source-qualified target pins with real source-derived anchor observations.

This small database is an explicitly partial reconstruction, not the full catalog
or an independent usefulness evaluation. Full catalog currentness is a CI gate.
"""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from pokemon_index import collector_character_affiliation as affiliation
from pokemon_index import core, supported_catalog
from scripts import audit_character_affiliation_gaps as audit


def source_fixture():
    db = core.connect(":memory:")
    core.init_db(db)
    receipt = audit.load_receipt()
    pins = {r["card_id"]: r for r in affiliation._bindings()}
    supported = {r["card_id"]: r for r in map(json.loads,
        (audit.ROOT / "catalog/supported-discovery-v1/supported-cards.jsonl").read_text().splitlines())}
    for target in receipt["targets"]:
        cid = target["card_id"]
        pin = pins[cid]
        record = supported[cid]
        identity = record["identity"]
        release = record["release"]
        core.import_cards(db, [dict(identity, match_eligible=True, rights_reference=pin["target_rights_reference"])])
        core.import_card_classifications(db, [dict(card_id=cid, category="Pokemon",
            provenance=identity["provenance"], rights_reference=pin["target_rights_reference"])])
        db.execute("INSERT OR IGNORE INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)",
            ("ja", "SV4A", release["name"], release["release_date"], 190,
             release["source_provenance"], release["official_url"], 0))
        db.execute("INSERT OR IGNORE INTO catalog_release_evidence VALUES (?,?,?)",
            ("ja", "SV4A", json.dumps(release, ensure_ascii=False, sort_keys=True)))
        ref = record["reference"]
        official = record["official_card"]
        core.import_card_references(db, [dict(source=ref["source"], source_jp_id=ref["native_id"],
            set_code="SV4A", collector_number=identity["collector_number"], name=ref["name"],
            provenance=ref["provenance"], rights_reference=official["official_url"])])
        db.execute("INSERT INTO card_rarity_correction VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, identity["name"], identity["rarity"], identity["provenance"], identity["rarity"],
             ref["provenance"], official["official_url"], official["official_page_sha256"],
             official["official_rarity_icon"], "2026-10-04T01:00:00+00:00"))
        supported_catalog.import_supported(db, [record])
    for source in receipt["anchor_sources"]:
        for card in source["cards"]:
            core.import_cards(db, [card])
            core.import_card_classifications(db, [dict(card_id=card["card_id"], category="Pokemon",
                provenance=source["source_ref"], rights_reference=card["rights_reference"])])
            core.import_card_facets(db, [dict(card_id=card["card_id"], facet_type="dex_id", value=dex,
                provenance=source["source_ref"], rights_reference=card["rights_reference"])
                for dex in source["dex_ids"]])
    db.commit()
    return db, receipt


class CharacterGapEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.receipt = source_fixture()

    def tearDown(self):
        self.db.close()

    def test_review_is_exactly_original_21_gaps_and_90_source_anchors(self):
        self.assertEqual({r["card_id"] for r in self.receipt["targets"]}, audit.GAP_IDS)
        self.assertEqual(len(self.receipt["anchor_sources"]), 90)
        self.assertEqual(sum(len(r["cards"]) for r in self.receipt["anchor_sources"]), 115)
        with gzip.open(audit.ROOT / "catalog/ja-available-explicit-eligibility-v1.jsonl.gz", "rt") as f:
            source_cards = list(map(json.loads, f))
        sources = {r["source_ref"]: r for r in self.receipt["anchor_sources"]}
        names = {r["base_name_ja"] for r in self.receipt["targets"]}
        self.assertEqual({r["provenance"] for r in source_cards if r["name"] in names}, set(sources))
        for source in sources.values():
            self.assertEqual(source["declared_category"], "Pokemon")
            self.assertEqual(len(source["dex_ids"]), 1)
            self.assertTrue(source["source_ref"].endswith(":sha256:" + source["source_sha256"]))
            for card in source["cards"]:
                self.assertIn({k: v for k, v in card.items() if k != "card_id"}, source_cards)
                self.assertEqual(card["name"], source["name_ja"])
        for target in self.receipt["targets"]:
            self.assertEqual(target["target_name"], target["base_name_ja"] + "ex")
            self.assertFalse(target["source_asserted_dex_id"])
            self.assertEqual({sources[ref]["dex_ids"][0] for ref in target["anchor_source_refs"]},
                             {target["expected_derived_dex_id"]})

    def test_all_21_are_derived_with_bounded_current_proof_and_no_target_facet_write(self):
        before = list(self.db.execute("SELECT * FROM card_facet ORDER BY card_id"))
        current = affiliation.affiliations(self.db)
        self.assertEqual(set(current), audit.GAP_IDS)
        for target in self.receipt["targets"]:
            reason = current[target["card_id"]]["reason"]
            self.assertEqual(reason["value"], target["expected_derived_dex_id"])
            self.assertEqual(reason["basis"], "source_name_character_affiliation")
            self.assertFalse(reason["source_asserted_dex_id"])
            self.assertEqual(len(reason["anchor_evidence"]), 1)
            self.assertEqual(reason["anchor_count"], sum(len(s["cards"]) for s in self.receipt["anchor_sources"]
                if s["name_ja"] == target["base_name_ja"]))
        self.assertEqual(before, list(self.db.execute("SELECT * FROM card_facet ORDER BY card_id")))
        self.assertFalse(any(self.db.execute("SELECT 1 FROM card_facet WHERE card_id=?", (cid,)).fetchone()
                             for cid in audit.GAP_IDS))

    def test_actual_action_contract_recommends_all_21_with_typed_proof(self):
        report = audit.audit(self.db, self.receipt)
        self.assertEqual(report["passed"], 21, report["records"])
        self.assertEqual(report["recommended_target_count"], 21)
        self.assertEqual(report["catalog_selection_eligible_count"], 21)
        self.assertEqual(report["unexpected_approval_count"], 0)
        self.assertFalse(report["independent_user_quality_established"])
        self.assertFalse(report["new_stored_target_dex_facts"])

    def test_every_target_rights_drift_withdraws_only_that_pin(self):
        for cid in audit.GAP_IDS:
            self.db.execute("SAVEPOINT drift")
            self.db.execute("UPDATE card SET rights_reference='changed:rights' WHERE card_id=?", (cid,))
            self.assertEqual(set(affiliation.affiliations(self.db)), audit.GAP_IDS - {cid})
            self.db.execute("ROLLBACK TO drift")
            self.db.execute("RELEASE drift")

    def test_regional_base_name_is_preserved_and_conflicting_anchor_withdraws(self):
        cid = "ja:SV4A:332/190:holo"
        target = next(t for t in self.receipt["targets"] if t["card_id"] == cid)
        self.assertEqual(target["base_name_ja"], "パルデア ドオー")
        anchor = affiliation.affiliations(self.db)[cid]["reason"]["anchor_evidence"][0]["card_id"]
        self.db.execute("UPDATE card SET name='ドオー' WHERE card_id=?", (anchor,))
        self.assertNotIn(cid, affiliation.affiliations(self.db))
        self.db.execute("UPDATE card SET name='パルデア ドオー' WHERE card_id=?", (anchor,))
        old = self.db.execute("SELECT * FROM card_facet WHERE card_id=?", (anchor,)).fetchone()
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (anchor, "dex_id", "194", old[3], old[4]))
        self.assertNotIn(cid, affiliation.affiliations(self.db))

    def test_diagnostic_preserves_database_and_refuses_to_replace_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite3"
            with core.connect(path) as disk:
                self.db.backup(disk)
            output = Path(tmp) / "report.json"
            result = audit.run(path, output)
            self.assertEqual(result["failed"], 0)
            self.assertTrue(result["catalog_bytes_unchanged"])
            with self.assertRaisesRegex(ValueError, "overwrite"):
                audit.run(path, output)


if __name__ == "__main__":
    unittest.main()
