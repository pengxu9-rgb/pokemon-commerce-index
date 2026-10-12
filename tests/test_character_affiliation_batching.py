"""Batching must preserve complete effective-facet proofs from 7382318."""
import importlib.util
import json
from pathlib import Path
import unittest

from pokemon_index import collector_character_affiliation as affiliation, core, supported_catalog
import test_character_affiliation_gap_evidence as fixture

_spec = importlib.util.spec_from_file_location("unbatched_7382318",
    Path(__file__).with_name("fixtures") / "collector_character_affiliation_7382318.py")
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)


class CharacterAffiliationBatchingTests(unittest.TestCase):
    def setUp(self):
        self.db, self.receipt = fixture.source_fixture()

    def tearDown(self):
        self.db.close()

    def assert_equivalent(self):
        old = legacy.affiliations(self.db)
        new = affiliation.affiliations(self.db)
        self.assertEqual(new, old)
        # Includes deterministic representative order and full evidence hashes.
        self.assertEqual(supported_catalog.digest(new), supported_catalog.digest(old))
        return new

    def add_metadata(self, cid, dex):
        card = self.db.execute("SELECT * FROM card WHERE card_id=?", (cid,)).fetchone()
        ref = {"source": "synthetic", "native_id": "anchor", "name": card["name"], "provenance": "synthetic:ref"}
        core.import_card_references(self.db, [dict(source=ref["source"], source_jp_id=ref["native_id"],
            set_code=card["set_code"], collector_number=card["collector_number"], name=ref["name"],
            provenance=ref["provenance"], rights_reference="synthetic:ref-rights")])
        row = {"identity": supported_catalog.identity_snapshot(card), "reference": ref,
               "official": {"page_kind": "single_number", "dex_id": dex,
                            "illustrators": [], "url": "synthetic:official-rights"}}
        self.db.execute("INSERT INTO card_metadata_evidence VALUES (?,?,?,?)",
                        ("synthetic:metadata", cid, 1, json.dumps(row, ensure_ascii=False)))

    def test_all_source_qualified_results_and_hashes_match_unbatched_oracle(self):
        self.assertEqual(len(self.assert_equivalent()), 21)

    def test_full_effective_view_is_read_twice_instead_of_per_target_and_name(self):
        def count(fn):
            queries = []
            self.db.set_trace_callback(queries.append)
            try:
                fn(self.db)
            finally:
                self.db.set_trace_callback(None)
            return sum("discovery_card_facet" in query for query in queries)
        self.assertEqual(count(legacy.affiliations), 42)
        self.assertEqual(count(affiliation.affiliations), 2)

    def test_current_metadata_overlay_staleness_and_conflict_preserve_output(self):
        target = "ja:SV4A:332/190:holo"
        anchor = affiliation.affiliations(self.db)[target]["reason"]["anchor_evidence"][0]["card_id"]
        self.add_metadata(anchor, 980)
        self.assertEqual(self.assert_equivalent()[target]["reason"]["anchor_evidence"][0]["provenance"], "synthetic:metadata")
        self.db.execute("UPDATE card_reference SET provenance='stale' WHERE source='synthetic'")
        self.assertNotEqual(self.assert_equivalent()[target]["reason"]["anchor_evidence"][0]["provenance"], "synthetic:metadata")
        self.db.execute("UPDATE card_reference SET provenance='synthetic:ref' WHERE source='synthetic'")
        row = json.loads(self.db.execute("SELECT record_json FROM card_metadata_evidence").fetchone()[0])
        row["official"]["dex_id"] = 194
        self.db.execute("UPDATE card_metadata_evidence SET record_json=?", (json.dumps(row, ensure_ascii=False),))
        self.assertNotIn(target, self.assert_equivalent())

    def test_direct_target_assertions_and_current_anchor_conflicts_are_not_bypassed(self):
        target = self.receipt["targets"][0]
        cid = target["card_id"]
        pin = next(pin for pin in affiliation._bindings() if pin["card_id"] == cid)
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (cid, "dex_id",
            str(target["expected_derived_dex_id"]), pin["source_ref"], pin["target_rights_reference"]))
        self.assertNotIn(cid, self.assert_equivalent())
        self.db.execute("DELETE FROM card_facet WHERE card_id=?", (cid,))
        anchor = affiliation.affiliations(self.db)[cid]["reason"]["anchor_evidence"][0]
        self.db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)", (anchor["card_id"], "dex_id", "1",
            anchor["provenance"], anchor["rights_reference"]))
        self.assertNotIn(cid, self.assert_equivalent())

    def test_empty_qualified_set_never_reads_effective_facets(self):
        self.db.execute("DELETE FROM supported_card")
        queries = []
        self.db.set_trace_callback(queries.append)
        try:
            self.assertEqual(affiliation.affiliations(self.db), {})
        finally:
            self.db.set_trace_callback(None)
        self.assertFalse(any("discovery_card_facet" in query for query in queries))


if __name__ == "__main__":
    unittest.main()
