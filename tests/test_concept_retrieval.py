import sqlite3
import unittest

from pokemon_index import core, tcgdex_source
from scripts import relationship_pilot


class ConceptRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.import_cards(self.db, [
            dict(language=language, set_code=set_code, collector_number=number,
                 variant="normal", name=name, provenance="fixture", rights_reference="fixture",
                 display_allowed=False)
            for language, set_code, number, name in (
                ("ja", "SM10", "093/095", "レスキュータンカ"),
                ("en", "SM2", "130/145", "Rescue Stretcher"),
                ("en", "SM2", "131/145", "Rescue Stretcher"),
                ("en", "SM2", "132/145", "Rescue Stretcher"),
            )
        ])
        self.anchor = "ja:SM10:093/095:normal"
        for card_id, subtype in ((self.anchor, "Item"),
                                 ("en:SM2:130/145:normal", "Item"),
                                 ("en:SM2:131/145:normal", "Supporter"),
                                 ("en:SM2:132/145:normal", "Item")):
            core.import_card_classifications(self.db, [dict(
                card_id=card_id, category="Trainer", subtype=subtype,
                provenance="fixture", rights_reference="fixture")])
        core.import_card_facets(self.db, [dict(
            card_id=card_id, facet_type="illustrator", value=value,
            provenance="fixture", rights_reference="fixture")
            for card_id, value in ((self.anchor, "Artist A"),
                                   ("en:SM2:130/145:normal", "Artist A"),
                                   ("en:SM2:132/145:normal", "Artist B"))])

    def tearDown(self):
        self.db.close()

    def concept(self, revision=1, status="approved"):
        return dict(concept_id="rescue-stretcher", revision=revision, category="Trainer",
                    name_ja="レスキュータンカ", name_en="Rescue Stretcher",
                    source_ja="https://example.invalid/japanese-source",
                    source_en="https://example.invalid/english-source",
                    rights_reference="fixture", reviewer="human-reviewer-1",
                    reviewed_at="2026-09-24T01:00:00Z", status=status)

    def test_source_parser_and_classification_validation(self):
        self.assertEqual(tcgdex_source.parse_card_classification(
            'category: "Trainer", trainerType: "Item"'), ("Trainer", "Item"))
        self.assertEqual(tcgdex_source.parse_card_classification(
            'category: "Energy", energyType: "Special"'), ("Energy", "Special"))
        with self.assertRaisesRegex(ValueError, "invalid trainer subtype"):
            tcgdex_source.parse_card_classification(
                'category: "Pokemon", trainerType: "Item"')
        with self.assertRaisesRegex(ValueError, "invalid card classification"):
            core.import_card_classifications(self.db, [dict(
                card_id=self.anchor, category="Trainer", subtype="Special",
                provenance="fixture", rights_reference="fixture")])

    def test_reviewed_alias_retrieves_only_compatible_trainer_candidate(self):
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.anchor}])
        self.assertEqual(queue, [])
        self.assertEqual(audit["gaps"][0]["reason"], "missing_reviewed_concept_alias")
        self.assertEqual(core.import_bilingual_concepts(self.db, [self.concept()]), 1)
        self.assertEqual(core.import_bilingual_concepts(self.db, [self.concept()]), 0)
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.anchor}])
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["candidate"]["card_id"], "en:SM2:130/145:normal")
        self.assertEqual(queue[0]["shared_facets"]["retrieval_signal"],
                         "reviewed_concept_and_illustrator")
        self.assertEqual(queue[0]["shared_facets"]["concept_source_ja"],
                         self.concept()["source_ja"])
        self.assertTrue(queue[0]["retrieval_only"])
        self.assertEqual(audit["candidate_pairs_by_signal"],
                         {"reviewed_concept_and_illustrator": 1})
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 0)

    def test_alias_withdrawal_and_revision_guards(self):
        core.import_bilingual_concepts(self.db, [self.concept()])
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.anchor}])
        core.import_bilingual_concepts(self.db, [self.concept(revision=2, status="withdrawn")])
        withdrawn_queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.anchor}])
        self.assertEqual(withdrawn_queue, [])
        self.assertEqual(audit["gaps"][0]["reason"], "missing_reviewed_concept_alias")
        queue[0]["review"]["decision"] = "same_artwork"
        with self.assertRaisesRegex(ValueError, "stale concept evidence"):
            relationship_pilot.compile_reviews(queue, self.db)
        with self.assertRaisesRegex(ValueError, "stale or conflicting"):
            core.import_bilingual_concepts(self.db, [self.concept()])
        with self.assertRaisesRegex(ValueError, "reviewed_at"):
            core.import_bilingual_concepts(self.db, [{**self.concept(revision=3),
                                                      "reviewed_at": ""}])

    def test_concept_only_fallback_is_bounded(self):
        core.import_bilingual_concepts(self.db, [self.concept()])
        self.db.execute("DELETE FROM card_facet WHERE facet_type='illustrator'")
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": self.anchor}], max_per_anchor=2)
        self.assertEqual(len(queue), 2)
        self.assertTrue(all(row["shared_facets"]["retrieval_signal"] ==
                            "reviewed_concept_only" for row in queue))
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": self.anchor}], max_per_anchor=1)
        self.assertEqual(queue, [])
        self.assertEqual(audit["gaps"][0]["reason"], "ambiguous_concept_candidates")

    def test_energy_concept_channel_and_ambiguous_alias_abstention(self):
        core.import_cards(self.db, [dict(
            language=language, set_code="E1", collector_number=number,
            variant="normal", name=name, provenance="fixture", rights_reference="fixture",
            display_allowed=False) for language, number, name in (
                ("ja", "001/010", "基本炎エネルギー"),
                ("en", "002/010", "Basic Fire Energy"),
            )])
        ja, en = "ja:E1:001/010:normal", "en:E1:002/010:normal"
        core.import_card_classifications(self.db, [dict(
            card_id=card_id, category="Energy", subtype="Normal",
            provenance="fixture", rights_reference="fixture") for card_id in (ja, en)])
        alias = {**self.concept(), "concept_id": "basic-fire-energy",
                 "category": "Energy", "name_ja": "基本炎エネルギー",
                 "name_en": "Basic Fire Energy"}
        core.import_bilingual_concepts(self.db, [alias])
        queue, _ = relationship_pilot.generate(self.db, [{"card_id": ja}])
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["candidate"]["card_id"], en)
        self.assertEqual(queue[0]["shared_facets"]["retrieval_signal"],
                         "reviewed_concept_only")
        core.import_bilingual_concepts(self.db, [{**alias, "concept_id": "duplicate-alias"}])
        queue, audit = relationship_pilot.generate(self.db, [{"card_id": ja}])
        self.assertEqual(queue, [])
        self.assertEqual(audit["gaps"][0]["reason"], "ambiguous_concept_alias")


if __name__ == "__main__":
    unittest.main()
