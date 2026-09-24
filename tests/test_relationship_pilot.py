import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core, discovery_graph
from scripts import relationship_pilot


class RelationshipPilotTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.ja = "ja:SV2A:025/165:normal"
        self.en = "en:SV03.5:025/165:normal"
        self.other = "en:SVP:085/225:normal"
        core.import_cards(self.db, [
            dict(language="ja", set_code="SV2A", collector_number="025/165",
                 variant="normal", name="ピカチュウ", provenance="fixture:ja",
                 rights_reference="fixture", display_allowed=False),
            dict(language="en", set_code="SV03.5", collector_number="025/165",
                 variant="normal", name="Pikachu", provenance="fixture:en",
                 rights_reference="fixture", display_allowed=False),
            dict(language="en", set_code="SVP", collector_number="085/225",
                 variant="normal", name="Pikachu with Grey Felt Hat",
                 provenance="fixture:promo", rights_reference="fixture",
                 display_allowed=False),
        ])
        core.import_card_facets(self.db, [
            dict(card_id=card_id, facet_type=kind, value=value,
                 provenance=f"fixture:{card_id}", rights_reference="fixture")
            for card_id in (self.ja, self.en, self.other)
            for kind, value in (("dex_id", "25"), ("illustrator", "Naoyo Kimura"))
        ])

    def tearDown(self):
        self.db.close()

    def test_candidate_queue_does_not_verify_shared_character_and_artist(self):
        queue, audit = relationship_pilot.generate(
            self.db, [{"card_id": self.ja, "case": "same metadata, different art"}])
        self.assertEqual(audit["candidate_pairs"], 2)
        self.assertEqual(queue[0]["candidate"]["card_id"], self.en)
        self.assertEqual(queue[1]["candidate"]["card_id"], self.other)
        self.assertTrue(all(row["retrieval_only"] for row in queue))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 0)

    def test_human_review_compilation_requires_two_sided_evidence(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        queue[0]["review"]["decision"] = "localization_counterpart"
        queue[0]["review"]["reviewer"] = "reviewer-1"
        with self.assertRaisesRegex(ValueError, "two-sided evidence"):
            relationship_pilot.compile_reviews(queue)
        queue[0]["review"].update(
            reviewer="reviewer-1", anchor_evidence_ref="https://example.invalid/ja-card",
            candidate_evidence_ref="https://example.invalid/en-card",
            artwork_note="Reviewer compared the card illustrations and design",
            finish_note="Both printings are the normal finish",
        )
        queue[1]["review"].update(
            decision="no_relation", reviewer="reviewer-1",
            anchor_evidence_ref="https://example.invalid/ja-card",
            candidate_evidence_ref="https://example.invalid/promo",
            artwork_note="Different artwork and card design",
        )
        assertions, audit = relationship_pilot.compile_reviews(queue)
        self.assertEqual(audit["decisions"],
                         {"localization_counterpart": 1, "no_relation": 1})
        self.assertEqual(len(assertions), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 1)
        self.assertEqual(discovery_graph.card_neighborhood(
            self.db, self.ja)["relationships"][0]["other_card_id"], self.en)
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 0)

    def test_match_disabled_card_can_have_reviewed_graph_relation(self):
        self.db.execute("UPDATE card SET match_eligible=0 WHERE card_id=?", (self.other,))
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        self.assertEqual(audit["pairs_with_offer_matching_disabled"], 1)
        target = next(row for row in queue if row["candidate"]["card_id"] == self.other)
        target["review"].update(
            decision="same_artwork", reviewer="reviewer-1",
            anchor_evidence_ref="https://example.invalid/ja-card",
            candidate_evidence_ref="https://example.invalid/en-card",
            artwork_note="Reviewer compared art", finish_note="Finish differs",
        )
        assertions, _ = relationship_pilot.compile_reviews([target])
        self.assertEqual(len(assertions), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 1)
        self.assertEqual(self.db.execute(
            "SELECT match_eligible FROM card WHERE card_id=?", (self.other,)).fetchone()[0], 0)

    def test_review_sheet_preserves_candidate_identifiers(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            relationship_pilot.write_review_sheet(path, queue)
            self.assertEqual(len(relationship_pilot.apply_review_sheet(queue, path)), 2)
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["candidate_card_id"] = self.other
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=relationship_pilot.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "identities changed"):
                relationship_pilot.apply_review_sheet(queue, path)


if __name__ == "__main__":
    unittest.main()
