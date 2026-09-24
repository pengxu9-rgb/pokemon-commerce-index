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

    def review(self, row, decision="localization_counterpart", revision=1, second=False):
        row["review"].update(
            review_revision=str(revision), decision=decision, reviewer="reviewer-1",
            reviewed_at="2026-09-24T01:00:00Z",
            anchor_evidence_ref="https://example.invalid/ja-card",
            anchor_evidence_kind="official_catalog", anchor_identity_checked="yes",
            candidate_evidence_ref=f"https://example.invalid/{row['candidate']['card_id']}",
            candidate_evidence_kind="official_catalog", candidate_identity_checked="yes",
            artwork_outcome="same", artwork_note="Reviewer compared card-specific artwork",
            finish_outcome="same", finish_note="Both printings have normal finish",
            second_reviewer="reviewer-2" if second else "",
            second_decision=decision if second else "",
            second_reviewed_at="2026-09-24T02:00:00Z" if second else "",
        )

    def test_candidate_queue_does_not_verify_shared_character_and_artist(self):
        queue, audit = relationship_pilot.generate(
            self.db, [{"card_id": self.ja, "case": "same metadata, different art"}])
        self.assertEqual(audit["candidate_pairs"], 2)
        self.assertEqual(queue[0]["candidate"]["card_id"], self.en)
        self.assertEqual(queue[1]["candidate"]["card_id"], self.other)
        self.assertTrue(all(row["retrieval_only"] for row in queue))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 0)

    def test_reverse_anchor_dedup_and_matched_artist_provenance(self):
        queue, audit = relationship_pilot.generate(
            self.db, [{"card_id": self.ja}, {"card_id": self.en}])
        self.assertEqual(audit["duplicate_pairs_skipped"], 1)
        self.assertEqual(len(queue), 2)
        core.import_card_facets(self.db, [dict(
            card_id=self.en, facet_type="illustrator", value="A Different Artist",
            provenance="fixture:wrong-artist", rights_reference="fixture")])
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        matched = next(row for row in queue if row["candidate"]["card_id"] == self.en)
        self.assertEqual(matched["shared_facets"]["candidate_illustrator_provenance"],
                         f"fixture:{self.en}")

    def test_multi_character_uses_complete_signature_not_partial_overlap(self):
        cards = [
            ("ja", "SM10", "110/095", "マルチ"),
            ("en", "SM10", "221/214", "Full pair"),
            ("en", "SM10", "222/214", "Partial pair"),
            ("en", "SM10", "223/214", "Extra character"),
        ]
        core.import_cards(self.db, [dict(language=language, set_code=set_code,
            collector_number=number, variant="holo", name=name,
            provenance="fixture", rights_reference="fixture", display_allowed=False)
            for language, set_code, number, name in cards])
        ja = "ja:SM10:110/095:holo"
        full, partial, extra = (f"en:SM10:{number}:holo" for number in
                                ("221/214", "222/214", "223/214"))
        facets = [
            (ja, "dex_id", "25"), (ja, "dex_id", "644"),
            (full, "dex_id", "25"), (full, "dex_id", "644"),
            (partial, "dex_id", "25"),
            (extra, "dex_id", "25"), (extra, "dex_id", "644"),
            (extra, "dex_id", "999"),
        ] + [(card_id, "illustrator", "Artist") for card_id in (ja, full, partial, extra)]
        core.import_card_facets(self.db, [dict(card_id=card_id, facet_type=kind,
            value=value, provenance="fixture", rights_reference="fixture")
            for card_id, kind, value in facets])
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": ja}])
        self.assertEqual(audit["candidate_pairs"], 1)
        self.assertEqual(queue[0]["candidate"]["card_id"], full)
        self.assertEqual(queue[0]["shared_facets"]["retrieval_signal"],
                         "exact_character_set_and_illustrator")

    def test_character_signature_fallback_is_bounded_when_artist_missing(self):
        cards = [
            ("ja", "SM10", "110/095", "マルチ"),
            ("en", "SM10", "221/214", "Full pair"),
            ("en", "SM10", "222/214", "Full pair variant"),
        ]
        core.import_cards(self.db, [dict(language=language, set_code=set_code,
            collector_number=number, variant="holo", name=name,
            provenance="fixture", rights_reference="fixture", display_allowed=False)
            for language, set_code, number, name in cards])
        ja = "ja:SM10:110/095:holo"
        ends = ["en:SM10:221/214:holo", "en:SM10:222/214:holo"]
        core.import_card_facets(self.db, [dict(card_id=card_id, facet_type="dex_id",
            value=value, provenance="fixture", rights_reference="fixture")
            for card_id in [ja, *ends] for value in ("25", "644")])
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": ja}], max_per_anchor=2)
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue[0]["shared_facets"]["retrieval_signal"],
                         "exact_character_set_only")
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": ja}], max_per_anchor=1)
        self.assertEqual(queue, [])
        self.assertEqual(audit["gaps"][0]["reason"], "ambiguous_character_signature")

    def test_human_review_compilation_requires_two_sided_evidence(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        queue[0]["review"]["decision"] = "localization_counterpart"
        queue[0]["review"]["reviewer"] = "reviewer-1"
        with self.assertRaisesRegex(ValueError, "reviewed_at"):
            relationship_pilot.compile_reviews(queue, self.db)
        self.review(queue[0], second=True)
        queue[1]["review"].update(
            decision="no_relation", reviewer="reviewer-1", reviewed_at="2026-09-24T01:00:00Z",
            anchor_evidence_ref="https://example.invalid/ja-card",
            candidate_evidence_ref="https://example.invalid/promo",
            artwork_note="Different artwork and card design",
        )
        assertions, audit = relationship_pilot.compile_reviews(queue, self.db)
        self.assertEqual(audit["decisions"],
                         {"localization_counterpart": 1, "no_relation": 1})
        self.assertEqual(len(assertions), 1)
        self.assertEqual(assertions[0]["review_status"], "verified")
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 1)
        self.assertEqual(discovery_graph.card_neighborhood(
            self.db, self.ja)["relationships"][0]["other_card_id"], self.en)
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 0)

    def test_match_disabled_card_can_have_reviewed_graph_relation(self):
        self.db.execute("UPDATE card SET match_eligible=0 WHERE card_id=?", (self.other,))
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        self.assertEqual(audit["pairs_with_offer_matching_disabled"], 1)
        target = next(row for row in queue if row["candidate"]["card_id"] == self.other)
        self.review(target, decision="same_artwork", second=True)
        target["review"].update(finish_outcome="different", finish_note="Promo finish differs")
        assertions, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertEqual(len(assertions), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, assertions), 1)
        self.assertEqual(self.db.execute(
            "SELECT match_eligible FROM card WHERE card_id=?", (self.other,)).fetchone()[0], 0)

    def test_re_review_rejects_then_restores_with_new_revision(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        target = queue[0]
        self.review(target, second=True)
        first, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertEqual(discovery_graph.assert_relationships(self.db, first), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, first), 0)
        target["review"].update(review_revision="2", decision="no_relation",
                                artwork_note="Different card design on reinspection")
        rejected, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertEqual([row["review_status"] for row in rejected], ["rejected"])
        self.assertEqual(discovery_graph.assert_relationships(self.db, rejected), 1)
        self.assertEqual(discovery_graph.card_neighborhood(self.db, self.ja)["relationships"], [])
        self.review(target, revision=1, second=True)
        with self.assertRaisesRegex(ValueError, "stale review revision"):
            relationship_pilot.compile_reviews([target], self.db)
        self.review(target, revision=3, second=True)
        restored, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertNotEqual(restored[0]["assertion_id"], first[0]["assertion_id"])
        self.assertEqual(discovery_graph.assert_relationships(self.db, restored), 1)
        self.assertEqual(len(discovery_graph.card_neighborhood(self.db, self.ja)["relationships"]), 1)

    def test_decision_change_retracts_old_type_and_single_review_stays_proposed(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        target = queue[0]
        self.review(target, second=True)
        first, _ = relationship_pilot.compile_reviews([target], self.db)
        discovery_graph.assert_relationships(self.db, first)
        self.review(target, decision="same_artwork", revision=2, second=False)
        changed, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertEqual({(row["relation_type"], row["review_status"]) for row in changed},
                         {("localization_counterpart", "rejected"), ("same_artwork", "proposed")})
        discovery_graph.assert_relationships(self.db, changed)
        self.assertEqual(discovery_graph.card_neighborhood(self.db, self.ja)["relationships"], [])
        self.assertEqual(len(discovery_graph.card_neighborhood(self.db, self.ja, True)["relationships"]), 1)
        self.review(target, decision="same_artwork", revision=3, second=True)
        reviewed, _ = relationship_pilot.compile_reviews([target], self.db)
        discovery_graph.assert_relationships(self.db, reviewed)
        edge = discovery_graph.card_neighborhood(self.db, self.ja)["relationships"][0]
        self.assertEqual(edge["relation_type"], "same_artwork")

    def test_delayed_compiled_review_cannot_override_newer_revision(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        target = queue[0]
        self.review(target, revision=1, second=True)
        old, _ = relationship_pilot.compile_reviews([target], self.db)
        self.review(target, decision="same_artwork", revision=2, second=True)
        newer, _ = relationship_pilot.compile_reviews([target], self.db)
        self.assertEqual(discovery_graph.assert_relationships(self.db, newer), 1)
        with self.assertRaisesRegex(ValueError, "stale pilot"):
            discovery_graph.assert_relationships(self.db, old)
        self.assertEqual(discovery_graph.assert_relationships(self.db, newer), 0)

    def test_competing_review_batches_from_same_head_are_rejected(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        target = queue[0]
        self.review(target, decision="same_artwork", revision=1, second=True)
        first, _ = relationship_pilot.compile_reviews([target], self.db)
        self.review(target, decision="localization_counterpart", revision=2, second=True)
        second, _ = relationship_pilot.compile_reviews([target], self.db)
        discovery_graph.assert_relationships(self.db, first)
        with self.assertRaisesRegex(ValueError, "stale pilot pair head"):
            discovery_graph.assert_relationships(self.db, second)

    def test_competing_same_revision_review_content_is_rejected(self):
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.ja}])
        target = queue[0]
        self.review(target, revision=1, second=True)
        first, _ = relationship_pilot.compile_reviews([target], self.db)
        target["review"]["artwork_note"] = "A distinct review finding"
        changed, _ = relationship_pilot.compile_reviews([target], self.db)
        discovery_graph.assert_relationships(self.db, first)
        with self.assertRaisesRegex(ValueError, "different event"):
            discovery_graph.assert_relationships(self.db, changed)

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
