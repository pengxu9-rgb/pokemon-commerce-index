"""Independent boundary checks after the first successful full-catalog run."""
import json
import unittest

from pokemon_index import core, collector_discovery, collector_journey, collector_recommendation, supported_catalog
import test_independent_recommendation_review as fixture
import test_set_browse_diversity as browse_fixture


class FinalCollectorUtilityReview(unittest.TestCase):
    tearDown = fixture.IndependentRecommendationReview.tearDown
    replay = fixture.IndependentRecommendationReview.replay

    def setUp(self):
        fixture.IndependentRecommendationReview.setUp(self)
        for number, name, dex in [(20, 'リザード', 5), (21, 'リザードン', 6),
                                  (22, 'リザードンex', 6), (23, 'ミュウ', 151),
                                  (24, 'ミュウツー', 150)]:
            self.add_character(number, name, dex)
        self.db.commit()

    def add_character(self, number, name, dex):
        row = dict(language='ja', set_code='AAA', collector_number=f'{number:03}/100',
                   variant='normal', name=name, match_eligible=True,
                   provenance='independent:utility', rights_reference='independent:utility')
        core.import_cards(self.db, [row])
        cid = core.card_id('ja', 'AAA', row['collector_number'], 'normal')
        core.import_card_facets(self.db, [dict(card_id=cid, facet_type='dex_id', value=dex,
            provenance=row['provenance'], rights_reference=row['rights_reference'])])
        return cid

    def test_longer_name_only_suppresses_contained_occurrences(self):
        cases = {'Japanese リザードン cards': [6], 'Japanese リザードンex cards': [6],
                 'Japanese ミュウツー cards': [150], 'Japanese ミュウ cards': [151],
                 'Japanese リザード and リザードン cards': [5, 6],
                 'Japanese リザードン and リザード cards': [5, 6],
                 'Japanese ミュウ and ミュウツー cards': [150, 151]}
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(collector_discovery._character_ids(self.db,
                    collector_discovery._norm(question)), expected)

    def test_same_name_conflicting_species_stays_ambiguous(self):
        self.add_character(25, 'リザードン', 5)
        self.assertEqual(collector_discovery._character_ids(self.db, 'リザードン'), [5, 6])
        result = self.replay([dict(type='ask', question='Recommend Japanese リザードン cards')])
        self.assertFalse(result['selection_allowed'])
        self.assertEqual(result['candidate_cards'], [])

    def test_stale_longer_alias_cannot_suppress_current_shorter_evidence(self):
        cid = 'ja:AAA:021/100:normal'
        question = 'Recommend Japanese リザードン cards'
        for column in ['provenance', 'rights_reference']:
            with self.subTest(column=column):
                old = self.db.execute('SELECT '+column+' FROM card WHERE card_id=?', (cid,)).fetchone()[0]
                self.db.execute('UPDATE card SET '+column+'=? WHERE card_id=?', ('changed',cid))
                try:
                    self.assertEqual(collector_discovery._character_ids(self.db, 'リザードン'), [5, 6])
                    result = self.replay([dict(type='ask', question=question)])
                    self.assertFalse(result['selection_allowed'])
                    self.assertEqual(result['candidate_cards'], [])
                finally:
                    self.db.execute('UPDATE card SET '+column+'=? WHERE card_id=?', (old,cid))

    def test_longer_official_alias_dominance_withdraws_with_its_current_reference(self):
        cid = 'ja:AAA:021/100:normal'
        self.db.execute("UPDATE card SET provenance='changed' WHERE card_id=?", (cid,))
        card = self.db.execute('SELECT * FROM card WHERE card_id=?', (cid,)).fetchone()
        reference = dict(source='span-review', native_id='21', name=card['name'],
                         provenance='span:current-reference')
        core.import_card_references(self.db, [dict(source=reference['source'],
            source_jp_id=reference['native_id'], set_code='AAA', collector_number='021/100',
            name=reference['name'], provenance=reference['provenance'], rights_reference='span:reference-rights')])
        record = dict(identity=supported_catalog.identity_snapshot(card), reference=reference,
            official=dict(page_kind='single_number', dex_id=6, illustrators=[], url='span:official-source'))
        self.db.execute('INSERT INTO card_metadata_evidence VALUES (?,?,?,?)',
            ('span:metadata', cid, 1, json.dumps(record)))
        self.assertEqual(collector_discovery._character_ids(self.db, 'リザードン'), [6])
        self.db.execute("UPDATE card_reference SET provenance='stale' WHERE source='span-review'")
        self.assertEqual(collector_discovery._character_ids(self.db, 'リザードン'), [5, 6])

    def test_exact_exclusion_applies_without_becoming_positive_taste(self):
        turns = [dict(type='ask', question='Recommend Japanese cards from AAA, but exclude Mew.')]
        result = self.replay(turns)
        self.assertGreater(len(result['candidate_cards']), 2)
        profile = result['preferences']['collecting']
        self.assertEqual(profile['excluded_dex_ids'], [151])
        self.assertNotIn(151, profile.get('preferred_dex_ids', []))
        self.assertTrue(all(c['set_code'] == 'AAA' and c['language'] == 'ja'
                            for c in result['candidate_cards']))
        for card in result['candidate_cards']:
            self.assertIsNone(self.db.execute("SELECT 1 FROM discovery_card_facet WHERE card_id=? "
                "AND facet_type='dex_id' AND value='151'", (card['card_id'],)).fetchone())
        self.assertFalse(result['purchase_ready'])

    def test_exclusion_reply_and_same_value_reconfirmation_clear_old_authority(self):
        turns = [dict(type='ask', question='Recommend Japanese cards from AAA'),
                 dict(type='reply', text='exclude Mew')]
        result = self.replay(turns)
        self.assertEqual(result['preferences']['collecting']['excluded_dex_ids'], [151])
        self.assertNotIn(fixture.MEW, {c['card_id'] for c in result['candidate_cards']})
        selected = turns+[dict(type='select', card_id=fixture.A)]
        reconfirmed = self.replay(selected+[dict(type='reply', text='exclude Mew')])
        self.assertIsNone(reconfirmed['target_intent'])
        compared = turns+[dict(type='compare', left_card_id=fixture.A, right_card_id=fixture.B)]
        with self.assertRaises(ValueError):
            self.replay(compared+[dict(type='reply', text='exclude Mew'),
                dict(type='choose_comparison', side='left', card_id=fixture.A)])
        former_positive = self.replay([dict(type='ask', question='Recommend Japanese Mew cards'),
            dict(type='select', card_id=fixture.MEW), dict(type='reply', text='exclude Mew'),
            dict(type='refine', scope={'set_code':'AAA'}),
            dict(type='preferences', preferences={'collecting':{'preferred_illustrators':['Yuka Morii']}})])
        self.assertIsNone(former_positive['target_intent'])
        self.assertNotIn(fixture.MEW, {c['card_id'] for c in former_positive['candidate_cards']})
        self.assertNotIn(151, former_positive['preferences']['collecting'].get('preferred_dex_ids', []))

    def test_unsupported_negative_clauses_cannot_silently_apply_one_exclusion(self):
        for tail in ['do not exclude Mew', "don't exclude Mew", 'exclude Missingmon',
                     'exclude Mew and Pikachu', 'exclude Mew artwork cameos',
                     'exclude Mew, except Mew ex', 'not Pikachu, but exclude Mew']:
            with self.subTest(tail=tail):
                turns = [dict(type='ask', question='Recommend Japanese cards from AAA, but '+tail)]
                result = self.replay(turns)
                self.assertFalse(result['selection_allowed'])
                for action in [dict(type='page', offset=0),
                               dict(type='refine', scope={'set_code':'AAA'}),
                               dict(type='inventory', owned_items=[])]:
                    self.assertFalse(self.replay(turns+[action])['selection_allowed'])
                with self.assertRaises(ValueError):
                    self.replay(turns+[dict(type='select', card_id=fixture.A)])

    def test_exclusion_name_cannot_borrow_a_stale_species_assertion(self):
        cid = self.add_character(99, 'Formername', 151)
        question = 'Recommend Japanese cards from AAA, but exclude Formername.'
        self.assertEqual(collector_recommendation.bounded_negative_intent(self.db, question)
                         ['excluded_dex_ids'], [151])
        for column in ['provenance', 'rights_reference']:
            with self.subTest(column=column):
                old = self.db.execute('SELECT '+column+' FROM card WHERE card_id=?', (cid,)).fetchone()[0]
                self.db.execute('UPDATE card SET '+column+'=? WHERE card_id=?', ('changed',cid))
                try:
                    self.assertIsNone(collector_recommendation.bounded_negative_intent(self.db, question))
                    result = self.replay([dict(type='ask', question=question),
                                         dict(type='refine', scope={'language':'ja'})])
                    self.assertFalse(result['selection_allowed'])
                finally:
                    self.db.execute('UPDATE card SET '+column+'=? WHERE card_id=?', (old,cid))

    def test_current_official_alias_can_qualify_but_stale_reference_withdraws_it(self):
        cid = self.add_character(98, 'Officialname', 151)
        self.db.execute('DELETE FROM card_facet WHERE card_id=?', (cid,))
        card = self.db.execute('SELECT * FROM card WHERE card_id=?', (cid,)).fetchone()
        reference = dict(source='utility-review', native_id='98', name=card['name'],
                         provenance='utility:current-reference')
        core.import_card_references(self.db, [dict(source=reference['source'],
            source_jp_id=reference['native_id'], set_code='AAA', collector_number='098/100',
            name=reference['name'], provenance=reference['provenance'], rights_reference='utility:reference-rights')])
        record = dict(identity=supported_catalog.identity_snapshot(card), reference=reference,
            official=dict(page_kind='single_number', dex_id=151, illustrators=[], url='utility:official-source'))
        self.db.execute('INSERT INTO card_metadata_evidence VALUES (?,?,?,?)',
            ('utility:metadata', cid, 1, json.dumps(record)))
        question = 'Recommend Japanese cards from AAA, but exclude Officialname.'
        self.assertEqual(collector_recommendation.bounded_negative_intent(self.db, question)
                         ['excluded_dex_ids'], [151])
        self.db.execute("UPDATE card_reference SET provenance='stale' WHERE source='utility-review'")
        self.assertIsNone(collector_recommendation.bounded_negative_intent(self.db, question))

    def test_unsubmitted_ownership_is_a_durable_evidence_requirement(self):
        ask = dict(type='ask', question="Recommend Japanese Pikachu cards I don't already own.")
        for actions in [[], [dict(type='page', offset=0)],
                        [dict(type='refine', scope={'variant':'normal'})],
                        [dict(type='preferences', preferences={'budget_minor':1000, 'currency':'USD'})]]:
            with self.subTest(actions=actions):
                result = self.replay([ask]+actions)
                self.assertFalse(result['selection_allowed'])
                self.assertIn('owned_inventory_not_supplied', result['selection_blockers'])
                with self.assertRaises(ValueError):
                    self.replay([ask]+actions+[dict(type='select', card_id=fixture.A)])

    def test_asserted_inventory_recovers_and_preserves_other_source_versions(self):
        ask = dict(type='ask', question="Recommend Japanese Pikachu cards I don't already own.")
        owned = dict(type='inventory', owned_items=[dict(item_id='mine', card_id=fixture.A)])
        turns = [ask, owned]
        result = self.replay(turns)
        ids = {c['card_id'] for c in result['candidate_cards']}
        self.assertNotIn(fixture.A, ids)
        self.assertIn('ja:AAA:001/100:holo', ids)
        self.assertIn(fixture.B, ids)
        self.assertTrue(result['selection_allowed'])
        self.assertFalse(result['ownership_assertions_verified'])
        selected = turns+[dict(type='select', card_id=fixture.B)]
        self.assertEqual(self.replay(selected)['target_intent']['card_id'], fixture.B)
        changed = self.replay(selected+[dict(type='inventory', owned_items=[])])
        self.assertIsNone(changed['target_intent'])
        self.assertIn(fixture.A, {c['card_id'] for c in changed['candidate_cards']})
        compared = turns+[dict(type='compare', left_card_id=fixture.B,
                              right_card_id='ja:AAA:001/100:holo')]
        with self.assertRaises(ValueError):
            self.replay(compared+[dict(type='inventory', owned_items=[]),
                dict(type='choose_comparison', side='left', card_id=fixture.B)])

    def test_later_ownership_requirement_clears_target_and_survives_refinement(self):
        turns = [dict(type='ask', question='Recommend Japanese Pikachu cards'),
                 dict(type='select', card_id=fixture.A),
                 dict(type='reply', text="Pikachu cards I don't already own."),
                 dict(type='refine', scope={'set_code':'AAA'})]
        result = self.replay(turns)
        self.assertIsNone(result['target_intent'])
        self.assertFalse(result['selection_allowed'])
        self.assertIn('owned_inventory_not_supplied', result['selection_blockers'])
        with self.assertRaises(ValueError):
            self.replay(turns+[dict(type='select', card_id=fixture.A)])
        recovered = self.replay(turns+[dict(type='inventory', owned_items=[
            dict(item_id='mine', card_id=fixture.A)])])
        self.assertTrue(recovered['selection_allowed'])
        self.assertNotIn(fixture.A, {c['card_id'] for c in recovered['candidate_cards']})
        restarted = self.replay(turns+[dict(type='ask', question='Recommend Japanese Pikachu cards')])
        self.assertNotIn('owned_inventory_not_supplied', restarted['selection_blockers'])

    def test_uncertain_owned_version_does_not_authorize_missing_copy_selection(self):
        turns = [dict(type='ask', question="Recommend Japanese Pikachu cards I don't already own."),
                 dict(type='inventory', owned_items=[dict(item_id='uncertain', language='ja',
                      set_code='AAA', collector_number='001/100')])]
        result = self.replay(turns)
        self.assertFalse(result['selection_allowed'])
        self.assertIn('owned_inventory_resolution', result['selection_blockers'])
        self.assertTrue(all(c['collector_number'] != '001/100' for c in result['candidate_cards']))
        with self.assertRaises(ValueError):
            self.replay(turns+[dict(type='select', card_id=fixture.B)])

    def test_taste_negation_is_not_mistaken_for_ownership(self):
        for question in ["Recommend Japanese Pikachu cards I don't like.",
                         "Recommend Japanese cards I don't already own, but not Pikachu."]:
            result = self.replay([dict(type='ask', question=question),
                                  dict(type='inventory', owned_items=[])])
            self.assertFalse(result['selection_allowed'])


class FinalSetBrowseUtilityReview(unittest.TestCase):
    setUp = browse_fixture.SetBrowseDiversityTests.setUp
    tearDown = browse_fixture.SetBrowseDiversityTests.tearDown

    def test_language_is_part_of_coordinate_and_all_version_records_survive(self):
        question = 'Japanese and English FIX cards'
        result = collector_discovery.execute(self.db, question, limit=100)
        self.assertEqual(result['task'], 'set_cards')
        expected = {r['card_id'] for r in self.db.execute("SELECT card_id FROM card WHERE set_code='FIX'")}
        self.assertEqual({c['card_id'] for c in result['cards']}, expected)
        first = result['cards'][:9]
        self.assertEqual(len({(c['language'], c['set_code'], c['collector_number']) for c in first}), 9)
        self.assertEqual([c for offset, limit in [(0,3),(3,8),(11,1),(12,100)]
            for c in collector_discovery.execute(self.db, question, limit=limit, offset=offset)['cards']],
            result['cards'])
        self.assertFalse(result['coverage']['global_printing_completeness_established'])

    def test_set_browse_comparison_does_not_survive_inventory_or_scope_change(self):
        ask = dict(type='ask', question='Japanese FIX cards')
        compare = dict(type='compare', left_card_id='ja:FIX:001/100:normal',
                       right_card_id='ja:FIX:002/100:normal')
        for action in [dict(type='inventory', owned_items=[]),
                       dict(type='refine', scope={'variant':'normal'})]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                collector_journey.replay(self.db, dict(turns=[ask, compare, action,
                    dict(type='choose_comparison', side='left', card_id='ja:FIX:001/100:normal')]))


if __name__ == '__main__':
    unittest.main()
