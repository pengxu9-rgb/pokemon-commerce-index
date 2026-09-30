import sqlite3
import unittest

from pokemon_index import core, discovery_graph, number_graph


class NumberGraphTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.import_cards(self.db, [
            dict(match_eligible=True, language=language, set_code=set_code, collector_number=number,
                 variant=variant, name=name, provenance="fixture",
                 rights_reference="fixture", display_allowed=False)
            for language, set_code, number, variant, name in (
                ("ja", "SV2a", "078/165", "reverse_masterball", "ピカチュウ"),
                ("ja", "SV2a", "078/165", "normal", "ピカチュウ"),
                ("en", "SV03.5", "078/165", "normal", "Pikachu"),
                ("en", "ME01", "078/132", "normal", "Pikachu"),
                ("ja", "M-P", "046/M-P", "normal", "プロモ"),
            )
        ])
        self.masterball = "ja:SV2A:078/165:reverse_masterball"
        self.normal_ja = "ja:SV2A:078/165:normal"
        self.normal_en = "en:SV03.5:078/165:normal"
        self.other_en = "en:ME01:078/132:normal"

    def tearDown(self):
        self.db.close()

    def test_number_scope_and_variant_are_distinct_facts(self):
        same_scope = number_graph.explain_number_pair(self.db, self.masterball,
                                                      self.normal_ja)
        self.assertEqual(same_scope["number_alignment"], "same_number_same_scope")
        self.assertEqual(same_scope["evidence_status"],
                         "same_scope_number_variant_candidates")
        self.assertFalse(same_scope["same_physical_printing_established"])
        self.assertFalse(same_scope["price_series_merge_allowed"])
        cross_region = number_graph.explain_number_pair(self.db, self.masterball,
                                                        self.normal_en)
        self.assertEqual(cross_region["number_alignment"],
                         "same_number_different_scope")
        self.assertEqual(cross_region["evidence_status"],
                         "cross_card_relationship_unestablished")
        self.assertIsNone(cross_region["left"]["finish"])
        self.assertEqual(cross_region["left"]["variant_label"], "reverse_masterball")
        self.assertFalse(cross_region["numeric_price_gap_available"])

    def test_only_evidence_edge_can_suggest_cross_language_artwork(self):
        discovery_graph.assert_relationships(self.db, [dict(
            left_card_id=self.masterball, right_card_id=self.other_en,
            relation_type="same_artwork", review_status="proposed",
            evidence_ref="fixture:source-bound-visual-review",
            rights_reference="fixture", asserted_by="fixture-model")])
        result = number_graph.explain_number_pair(self.db, self.masterball,
                                                  self.other_en)
        self.assertEqual(result["number_alignment"],
                         "same_numerator_different_denominator")
        self.assertEqual(result["evidence_status"], "proposed_relationship_only")
        self.assertEqual(result["relationships"][0]["review_status"], "proposed")
        self.assertFalse(result["price_series_merge_allowed"])
        neighborhood = discovery_graph.card_neighborhood(self.db, self.masterball,
                                                          include_proposed=True)
        self.assertEqual(neighborhood["number_context"]["number_scope_id"], "ja:SV2A")
        self.assertEqual(neighborhood["relationships"][0]["number_alignment"],
                         "same_numerator_different_denominator")
        self.assertFalse(neighborhood["relationships"][0]["price_comparable"])
        unrelated = number_graph.explain_number_pair(self.db, self.normal_ja,
                                                     self.other_en)
        self.assertEqual(unrelated["evidence_status"],
                         "cross_card_relationship_unestablished")

    def test_existing_catalog_backfills_without_changing_card_ids(self):
        self.db.execute("DELETE FROM card_number_context")
        core.init_db(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_number_context").fetchone()[0], 5)
        context = core.catalog_card_internal(self.db, "ja:M-P:046/M-P:normal")
        self.assertEqual(context["number_context"]["number_format"], "mixed_fraction")
        self.assertEqual(context["number_context"]["denominator_key"], "M-P")
        self.assertEqual(context["number_context"]["number_scope_id"], "ja:M-P")
        self.assertEqual(context["card"]["card_id"], "ja:M-P:046/M-P:normal")


if __name__ == "__main__":
    unittest.main()
