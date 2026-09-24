import sqlite3
import unittest

from pokemon_index import core
from scripts import relationship_coverage


class RelationshipCoverageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        cards = [
            ("ja", "SV2A", "025/165", "ピカチュウ"),
            ("ja", "SV2A", "026/165", "トレーナー"),
            ("en", "SV03.5", "025/165", "Pikachu"),
            ("en", "SV03.5", "026/165", "Trainer"),
        ]
        core.import_cards(self.db, [dict(
            language=language, set_code=set_code, collector_number=number,
            variant="normal", name=name, provenance="tcgdex:fixture",
            rights_reference="fixture", display_allowed=False,
        ) for language, set_code, number, name in cards])
        self.ja = "ja:SV2A:025/165:normal"
        self.trainer = "ja:SV2A:026/165:normal"
        self.en = "en:SV03.5:025/165:normal"
        self.other = "en:SV03.5:026/165:normal"
        core.import_card_facets(self.db, [dict(
            card_id=card_id, facet_type=kind, value=value,
            provenance="fixture", rights_reference="fixture",
        ) for card_id in (self.ja, self.en)
            for kind, value in (("dex_id", "25"), ("illustrator", "Artist"))])

    def tearDown(self):
        self.db.close()

    def _anchor(self, card_id, case):
        card = self.db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
        return {"card_id": card_id, "case": case,
                "identity_sha256": relationship_coverage._identity_hash(card)}

    def _gold(self, anchor, target_id):
        answer = [{"card_id": target_id, "relation_type": "localization_counterpart"}]
        return {"anchor_card_id": anchor["card_id"], "stratum": anchor["case"],
                "identity_sha256": anchor["identity_sha256"],
                "review_status": "adjudicated",
                "reviewers": [{"id": reviewer, "reviewed_at": "2026-09-24T01:00:00Z",
                               "answers": answer} for reviewer in ("person-1", "person-2")],
                "anchor_evidence_ref": f"fixture:{anchor['card_id']}",
                "expected": [{**answer[0], "evidence_ref": f"fixture:{target_id}"}],
                "rationale": "Independent card comparison in fixture",
        }

    def test_blind_sample_is_deterministic_and_excludes_pilot_ids(self):
        first = relationship_coverage.sample(self.db, {self.ja}, per_stratum=1)
        second = relationship_coverage.sample(self.db, {self.ja}, per_stratum=1)
        self.assertEqual(first, second)
        anchors, gold, audit = first
        self.assertNotIn(self.ja, {row["card_id"] for row in anchors})
        self.assertTrue(all(row["review_status"] == "pending" for row in gold))
        self.assertIn("no recall measurement", audit["scope"])

    def test_recall_waits_for_independent_agreement_and_counts_missing_facets(self):
        anchors = [self._anchor(self.ja, "control"), self._anchor(self.trainer, "missing_facet")]
        pending = self._gold(anchors[0], self.en)
        pending["review_status"] = "pending"
        pending["reviewers"] = []
        pending["expected"] = []
        report = relationship_coverage.evaluate(self.db, anchors, [
            pending, {**self._gold(anchors[1], self.other), "review_status": "pending"}])
        self.assertIsNone(report["pair_recall"]["all"]["recall"])
        reviewed = [self._gold(anchors[0], self.en), self._gold(anchors[1], self.other)]
        report = relationship_coverage.evaluate(self.db, anchors, reviewed)
        self.assertEqual(report["pair_recall"]["all"],
                         {"gold_pairs": 2, "retrieved_pairs": 1, "recall": 0.5})
        self.assertEqual(report["misses"][0]["generator_gaps"],
                         ["missing_or_ambiguous_facets"])
        reviewed[0]["reviewers"][1]["answers"] = []
        with self.assertRaisesRegex(ValueError, "two reviewers must agree"):
            relationship_coverage.evaluate(self.db, anchors, reviewed)


if __name__ == "__main__":
    unittest.main()
