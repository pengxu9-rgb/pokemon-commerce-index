"""Set browsing varies number coordinates without merging source versions."""
import unittest

from pokemon_index import core, collector_discovery, collector_inventory, collector_journey


QUESTION = 'Japanese FIX cards'
VARIANTS = ('normal', 'reverse_masterball', 'reverse_pokeball')


class SetBrowseDiversityTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(':memory:')
        core.init_db(self.db)
        cards = []
        for language, code, numbers in [('ja', 'FIX', range(1, 8)),
                                         ('en', 'FIX', range(1, 3)),
                                         ('ja', 'OTHER', range(1, 3))]:
            self.db.execute('INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
                            (language, code, code + ' set', '2023-06-16', 100,
                             'fixture-release', 'fixture-rights', 0))
            for number in numbers:
                for variant in VARIANTS if number != 7 else ('normal',):
                    cards.append(dict(language=language, set_code=code,
                        collector_number=f'{number:03}/100', variant=variant,
                        name=f'Synthetic {number}', rarity='Common',
                        provenance=f'fixture-source:{language}:{code}:{number}:{variant}',
                        rights_reference='fixture-rights', match_eligible=number != 7))
        # Import order deliberately differs from the stable catalog order.
        core.import_cards(self.db, reversed(cards))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def discovery(self, **kwargs):
        return collector_discovery.execute(self.db, QUESTION, **kwargs)

    def journey(self, turns, **kwargs):
        return collector_journey.replay(self.db, dict(turns=turns, **kwargs))

    @staticmethod
    def ids(cards):
        return [card['card_id'] for card in cards]

    @staticmethod
    def coordinates(cards):
        return [(card['language'], card['set_code'], card['collector_number']) for card in cards]

    def test_first_page_diversifies_coordinates_without_changing_coverage(self):
        result = self.discovery(limit=5)
        self.assertEqual(result['task'], 'set_cards')
        self.assertEqual(self.ids(result['cards']),
                         [f'ja:FIX:{n:03}/100:normal' for n in range(1, 6)])
        self.assertEqual(result['coverage']['matched_catalog_records'], 19)
        self.assertEqual(sum(row['records'] for row in result['variant_summary']), 19)
        self.assertEqual(sum(row['records'] for row in result['rarity_summary']), 19)
        self.assertFalse(result['coverage']['global_printing_completeness_established'])
        self.assertEqual(result['physical_finish_verification'], 'not_established_by_catalog')
        self.assertIn('no physical versions merged', result['ordering'])

    def test_pages_keep_every_exact_version_and_original_card_evidence(self):
        before = self.db.total_changes
        expected = {row['card_id']: collector_discovery._card_result(self.db, row)
                    for row in collector_discovery._rows(self.db,
                        'c.language=? AND c.set_code=?', ('ja', 'FIX'))}
        pages = [self.discovery(limit=5, offset=offset) for offset in range(0, 20, 5)]
        cards = [card for page in pages for card in page['cards']]
        self.assertEqual(len(cards), 19)
        self.assertEqual(len(set(self.ids(cards))), 19)
        self.assertEqual({card['card_id']: card for card in cards}, expected)
        self.assertEqual(len(set(self.coordinates(cards[:7]))), 7)
        self.assertEqual([c['variant'] for c in cards if c['collector_number'] == '001/100'],
                         list(VARIANTS))
        self.assertEqual([p['coverage']['has_more'] for p in pages], [True, True, True, False])
        self.assertEqual(self.db.total_changes, before)

    def test_offsets_page_sizes_repeated_reads_and_private_projection_are_stable(self):
        full = self.discovery(limit=100)
        for offset, limit in [(0, 1), (2, 3), (6, 5), (7, 7), (17, 10), (19, 5), (100, 5)]:
            with self.subTest(offset=offset, limit=limit):
                page = self.discovery(limit=limit, offset=offset)
                self.assertEqual(page, self.discovery(limit=limit, offset=offset))
                self.assertEqual(page['cards'], full['cards'][offset:offset + limit])
        captured = []
        page = self.discovery(limit=1, offset=5, _row_capture=(100, captured))
        self.assertEqual(self.ids(captured), self.ids(full['cards']))
        self.assertEqual(page['cards'], full['cards'][5:6])

    def test_explicit_coordinate_and_source_variant_inspection_remain_unchanged(self):
        for question, expected_task in [('Japanese FIX 001/100', 'exact_coordinates'),
                                        ('ja:FIX:001/100:normal', 'printing_variants')]:
            result = collector_discovery.execute(self.db, question)
            self.assertEqual(result['task'], expected_task)
            self.assertEqual(self.ids(result['cards']),
                             [f'ja:FIX:001/100:{variant}' for variant in VARIANTS])
            self.assertNotIn('round-robin', result['ordering'])
        narrowed = self.discovery(scope=dict(collector_number='001/100',
                                             variant='reverse_masterball'))
        self.assertEqual(self.ids(narrowed['cards']), ['ja:FIX:001/100:reverse_masterball'])
        self.assertEqual(narrowed['task'], 'exact_coordinates')
        variants = self.discovery(scope=dict(variant='reverse_pokeball'), limit=100)
        self.assertEqual(variants['coverage']['matched_catalog_records'], 6)
        self.assertEqual({card['variant'] for card in variants['cards']}, {'reverse_pokeball'})

    def test_set_variant_comparison_keeps_all_declared_variants(self):
        result = collector_discovery.execute(self.db,
            'Japanese FIX cards: does every card have Pokeball and Masterball holo?', limit=100)
        self.assertEqual(result['task'], 'set_cards')
        self.assertEqual(len(result['cards']), 19)
        self.assertEqual({card['variant'] for card in result['cards']}, set(VARIANTS))
        self.assertIn('physical_variant_completeness', result['unfulfilled_constraints'])

    def test_inventory_reorders_remaining_versions_before_paging(self):
        owned = [dict(item_id=str(number), card_id=f'ja:FIX:{number:03}/100:normal')
                 for number in range(3, 8)]
        request = dict(question=QUESTION, owned_items=owned, limit=5)
        first = collector_inventory.compare(self.db, request)
        self.assertEqual(len(set(self.coordinates(first['missing_catalog_records']))), 5)
        self.assertEqual(first['coverage']['scoped_catalog_records'], 19)
        self.assertEqual(first['coverage']['not_in_resolved_inventory'], 14)
        self.assertEqual(first['coverage']['asserted_owned_records'], 5)
        pages = [collector_inventory.compare(self.db, dict(request, offset=offset))
                 for offset in range(0, 15, 5)]
        cards = [card for page in pages for card in page['missing_catalog_records']]
        self.assertEqual(len(cards), len(set(self.ids(cards))))
        self.assertEqual(set(self.ids(cards)), set(self.ids(self.discovery(limit=100)['cards']))
                         - {item['card_id'] for item in owned})
        self.assertEqual(first, collector_inventory.compare(self.db, request))
        empty = collector_inventory.compare(self.db, dict(question=QUESTION, owned_items=[], limit=5))
        self.assertEqual(empty['missing_catalog_records'], self.discovery(limit=5)['cards'])

    def test_uncertain_inventory_stays_unresolved_and_withholds_all_possible_versions(self):
        owned = [dict(item_id='uncertain', language='ja', set_code='FIX', collector_number='001/100')]
        turns = [dict(type='ask', question=QUESTION), dict(type='inventory', owned_items=owned)]
        result = self.journey(turns)
        self.assertEqual(result['inventory']['coverage']['possible_owned_records'], 3)
        self.assertEqual(result['status'], 'inventory_review_needed')
        self.assertFalse(result['selection_allowed'])
        self.assertNotIn('001/100', [c['collector_number'] for c in result['candidate_cards']])
        self.assertEqual(len(set(self.coordinates(result['candidate_cards']))), 5)
        with self.assertRaises(ValueError):
            self.journey(turns + [dict(type='select', card_id='ja:FIX:002/100:normal')])

    def test_held_records_are_not_removed_or_given_selection_authority(self):
        turns = [dict(type='ask', question=QUESTION), dict(type='page', offset=5)]
        result = self.journey(turns)
        held = 'ja:FIX:007/100:normal'
        self.assertIn(held, self.ids(result['candidate_cards']))
        self.assertIn('match_disabled_identity', result['card_selection_blockers'][held])
        for field in ('purchase_ready', 'physical_copy_verified', 'public_display_allowed',
                      'ready_for_offer_tracking'):
            self.assertFalse(result[field])
        with self.assertRaises(ValueError):
            self.journey(turns + [dict(type='select', card_id=held)])

    def test_page_change_clears_selection_and_requires_current_page_identity(self):
        ask = dict(type='ask', question=QUESTION)
        first = 'ja:FIX:001/100:normal'
        selected = self.journey([ask, dict(type='select', card_id=first)])
        self.assertEqual(selected['selected_catalog_target']['card_id'], first)
        paged = self.journey([ask, dict(type='select', card_id=first), dict(type='page', offset=5)])
        self.assertIsNone(paged['selected_catalog_target'])
        self.assertEqual(paged['target_reset_reason'], 'candidate_page_changed')
        with self.assertRaises(ValueError):
            self.journey([ask, dict(type='page', offset=5), dict(type='select', card_id=first)])


if __name__ == '__main__':
    unittest.main()
