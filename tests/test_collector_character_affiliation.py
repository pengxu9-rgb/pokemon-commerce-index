"""Bounded derived-name retrieval; no invented source dex facts or permissions."""
import copy
from contextlib import closing
import json
import unittest
from unittest.mock import patch

from pokemon_index import collector_character_affiliation as affiliation, core, supported_catalog


class CharacterAffiliationTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(":memory:")
        core.init_db(self.db)
        self.binding = affiliation._bindings()[0]
        self.cid = self.binding["card_id"]
        identity = self.binding["identity"]
        core.import_cards(self.db, [dict(identity, rights_reference=self.binding["target_rights_reference"],
                                          match_eligible=True)])
        self.db.execute("INSERT INTO card_classification VALUES (?,?,?,?,?)", (
            self.cid, "Pokemon", None, identity["provenance"], self.binding["target_rights_reference"]))
        self.support = {"identity": identity, "scope": "synthetic test support"}
        self.binding = dict(self.binding, supported_record_sha256=supported_catalog.digest(self.support))
        self.anchor = self.add_anchor("001/100", 151)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def add_anchor(self, number, dex, *, name="ミュウ", language="ja"):
        cid = core.card_id(language, "ANCHOR", number, "normal")
        provenance = "synthetic:anchor:" + number
        core.import_cards(self.db, [dict(language=language, set_code="ANCHOR", collector_number=number,
            variant="normal", name=name, provenance=provenance, rights_reference="synthetic:anchor-rights",
            match_eligible=True)])
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)",
                        (cid, "dex_id", str(dex), provenance, "synthetic:anchor-rights"))
        self.db.execute("INSERT INTO card_classification VALUES (?,?,?,?,?)",
                        (cid, "Pokemon", None, provenance, "synthetic:anchor-rights"))
        return cid

    def affiliations(self, *, binding=None, status="supported_for_internal_review", evidence=None):
        with patch.object(affiliation, "_bindings", return_value=[binding or self.binding]), \
             patch.object(supported_catalog, "support_for_card", return_value={
                 "status": status, "evidence": self.support if evidence is None else evidence}):
            return affiliation.affiliations(self.db)

    def test_derived_reason_does_not_mutate_or_claim_target_dex(self):
        before = list(self.db.execute("SELECT * FROM card_facet ORDER BY card_id"))
        out = self.affiliations()[self.cid]
        self.assertEqual(out["dex_id"], 151)
        reason = out["reason"]
        self.assertEqual(reason["basis"], "source_name_character_affiliation")
        self.assertFalse(reason["source_asserted_dex_id"])
        self.assertEqual(reason["target_name"], "ミュウex")
        self.assertEqual(reason["anchor_count"], 1)
        self.assertEqual(reason["anchor_evidence"][0]["card_id"], self.anchor)
        self.assertIsNone(self.db.execute("SELECT 1 FROM card_facet WHERE card_id=?", (self.cid,)).fetchone())
        self.assertEqual(before, list(self.db.execute("SELECT * FROM card_facet ORDER BY card_id")))

    def test_target_identity_source_rights_and_support_drift_fail_closed(self):
        for field, changed in [("name", "ミュウツーex"), ("provenance", "changed-source"),
                               ("rights_reference", "changed-rights")]:
            old = self.db.execute("SELECT " + field + " FROM card WHERE card_id=?", (self.cid,)).fetchone()[0]
            self.db.execute("UPDATE card SET " + field + "=? WHERE card_id=?", (changed, self.cid))
            self.assertEqual(self.affiliations(), {}, field)
            self.db.execute("UPDATE card SET " + field + "=? WHERE card_id=?", (old, self.cid))
        self.assertEqual(self.affiliations(status="stale_support_evidence"), {})
        self.assertEqual(self.affiliations(evidence={"different": "support"}), {})
        self.db.execute("UPDATE card_classification SET category='Trainer' WHERE card_id=?", (self.cid,))
        self.assertEqual(self.affiliations(), {})

    def test_target_source_pin_requires_explicit_ex_and_no_authority(self):
        for field, value in [("declared_suffix", "GX"), ("declared_category", "Trainer"),
                             ("source_asserted_dex_id", True), ("physical_printing_verified", True),
                             ("automatic_offer_join_allowed", True), ("public_display_allowed", True),
                             ("source_sha256", "0" * 64), ("base_name_ja", "ミュ")]:
            self.assertEqual(self.affiliations(binding=dict(self.binding, **{field: value})), {}, field)

    def test_anchor_source_and_rights_drift_or_absence_fail_closed(self):
        for field in ("provenance", "rights_reference"):
            old = self.db.execute("SELECT " + field + " FROM card WHERE card_id=?", (self.anchor,)).fetchone()[0]
            self.db.execute("UPDATE card SET " + field + "='changed' WHERE card_id=?", (self.anchor,))
            self.assertEqual(self.affiliations(), {}, field)
            self.db.execute("UPDATE card SET " + field + "=? WHERE card_id=?", (old, self.anchor))
        self.db.execute("DELETE FROM card_facet WHERE card_id=?", (self.anchor,))
        self.assertEqual(self.affiliations(), {})

    def test_all_anchors_must_agree_before_bounded_evidence_is_returned(self):
        for number in range(2, 8):
            self.add_anchor(f"{number:03}/100", 151)
        reason = self.affiliations()[self.cid]["reason"]
        self.assertEqual(reason["anchor_count"], 7)
        self.assertEqual(len(reason["anchor_evidence"]), 1)
        self.assertEqual(reason["anchor_evidence"][0]["card_id"], self.anchor)
        self.assertEqual(len(reason["anchor_evidence_sha256"]), 64)
        self.add_anchor("099/100", 150)
        self.assertEqual(self.affiliations(), {})

    def test_exact_same_language_base_name_and_single_dex_are_required(self):
        self.db.execute("DELETE FROM card_facet WHERE card_id=?", (self.anchor,))
        self.add_anchor("002/100", 151, name="ミュウツー")
        self.add_anchor("003/100", 151, name="ミュウ", language="en")
        self.assertEqual(self.affiliations(), {})
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (
            self.anchor, "dex_id", "151", "synthetic:anchor:001/100", "synthetic:anchor-rights"))
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (
            self.anchor, "dex_id", "150", "synthetic:anchor:001/100", "synthetic:anchor-rights"))
        self.assertEqual(self.affiliations(), {})

    def test_existing_target_dex_facts_are_never_overwritten_or_reinterpreted(self):
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (
            self.cid, "dex_id", "150", self.binding["source_ref"], self.binding["target_rights_reference"]))
        self.assertEqual(self.affiliations(), {})
        self.assertEqual(self.db.execute("SELECT value FROM card_facet WHERE card_id=?", (self.cid,)).fetchone()[0], "150")

    def test_binding_file_has_only_the_six_inspected_targets(self):
        bindings = affiliation._bindings()
        self.assertEqual({r["card_id"] for r in bindings}, {
            f"ja:SV4A:{number}/190:holo" for number in [327, 328, 331, 347, 348, 349]})
        self.assertTrue(all(r["source_asserted_dex_id"] is False for r in bindings))


if __name__ == "__main__":
    unittest.main()
