import unittest
from pokemon_index import core, collector_journey


class SourceFamilyJourneyTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(':memory:')
        self.addCleanup(self.db.close)
        core.init_db(self.db)
        core.import_cards(self.db, [dict(language='ja', set_code='SV-P',
            collector_number='154/SV-P', variant='official_coordinate_family_only_45644',
            name='ネモ', rarity=None, provenance='official-source:test-fixture',
            rights_reference='https://www.pokemon-card.com/card-search/details.php/card/45644',
            match_eligible=False, display_allowed=False, attributes=dict(family_scope_only=True))])
        self.cid = 'ja:SV-P:154/SV-P:official_coordinate_family_only_45644'

    def test_exact_family_exposes_copy_blocker_without_target_selection(self):
        result = collector_journey.replay(self.db, dict(turns=[dict(type='ask',
            question='Japanese SV-P 154/SV-P')]))
        self.assertFalse(result['selection_allowed'])
        self.assertIn('source_family_copy_evidence', result['selection_blockers'])

    def test_broad_query_cannot_bypass_raw_family_guard(self):
        request = dict(turns=[dict(type='ask', question='Japanese SV-P cards'),
            dict(type='select', card_id=self.cid)])
        with self.assertRaisesRegex(ValueError, 'source-only family'):
            collector_journey.replay(self.db, request)

    def test_removing_mutable_family_attribute_does_not_promote_source_namespace(self):
        self.db.execute("UPDATE card SET attributes_json='{}' WHERE card_id=?", (self.cid,))
        request = dict(turns=[dict(type='ask', question='Japanese SV-P cards'),
            dict(type='select', card_id=self.cid)])
        with self.assertRaisesRegex(ValueError, 'source-only family'):
            collector_journey.replay(self.db, request)


if __name__ == '__main__':
    unittest.main()
