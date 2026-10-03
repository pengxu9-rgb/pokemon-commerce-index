"""Independent outcome regressions, chosen before inspecting recommendation code.

This fixture is intentionally separate from the implementation's frozen journeys.
It asserts catalog usefulness and reversible preference lifecycle, not market quality.
"""
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from pokemon_index import core, collector_journey
from pokemon_index.cli import create_server


A = 'ja:AAA:001/100:normal'
B = 'ja:AAA:002/100:normal'
MEW = 'ja:AAA:003/100:normal'
OTHER = 'ja:BBB:005/100:normal'


class IndependentRecommendationReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = core.connect(Path(self.temp.name) / 'catalog.sqlite3')
        core.init_db(self.db)
        cards = [
            ('ja', 'AAA', '001/100', 'normal', 'Pikachu', 25, 'Yuka Morii'),
            ('ja', 'AAA', '001/100', 'holo', 'Pikachu', 25, 'Yuka Morii'),
            ('ja', 'AAA', '002/100', 'normal', 'Pikachu', 25, 'Tomokazu Komiya'),
            ('ja', 'AAA', '003/100', 'normal', 'Mew', 151, 'Yuka Morii'),
            ('en', 'AAA', '003/100', 'normal', 'Mew', 151, 'Yuka Morii'),
            ('ja', 'BBB', '004/100', 'normal', 'Pikachu', 25, 'Tomokazu Komiya'),
            ('ja', 'BBB', '005/100', 'normal', 'Eevee', 133, 'Yuka Morii'),
        ]
        for lang, code, number, variant, name, dex, artist in cards:
            core.import_cards(self.db, [dict(language=lang, set_code=code,
                collector_number=number, variant=variant, name=name, match_eligible=True,
                provenance='independent:synthetic', rights_reference='independent:synthetic')])
            cid = core.card_id(lang, code, number, variant)
            for kind, value in [('dex_id', str(dex)), ('illustrator', artist)]:
                self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                    (cid, kind, value, 'independent:synthetic', 'independent:synthetic'))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def replay(self, turns, limit=50):
        return collector_journey.replay(self.db, dict(turns=turns, limit=limit), revision='a' * 64)

    def start(self):
        return [dict(type='ask', question='Recommend Japanese Pikachu cards')]

    def preference(self, **values):
        return dict(type='preferences', preferences=dict(collecting=values))

    def reaction(self, cid, reaction):
        return dict(type='feedback', card_id=cid, reaction=reaction)

    def ids(self, result):
        return [c['card_id'] for c in result['candidate_cards']]

    def test_next_collection_continues_without_reusing_completed_character(self):
        turns = [dict(type='ask', question='I completed Pikachu. What should I collect next?'),
                 dict(type='reply', text='English')]
        self.assertEqual(self.ids(self.replay(turns)), [])
        result = self.replay(turns + [dict(type='reply', text='Mew')])
        self.assertEqual(self.ids(result), ['en:AAA:003/100:normal'])

    def test_liked_example_expands_pool_using_source_backed_artist(self):
        self.assertNotIn(OTHER, self.ids(self.replay(self.start())))
        result = self.replay(self.start() + [self.reaction(A, 'like')])
        self.assertIn(OTHER, self.ids(result))
        reasons = next(i for i in result['recommendation']['items'] if i['card_id'] == OTHER)['reasons']
        self.assertTrue(any(r['field'] == 'illustrator' and r['basis'] == 'liked_example_catalog_facet' for r in reasons))

    def test_hard_scope_and_exclusion_win_over_liked_example(self):
        turns = self.start() + [self.reaction(A, 'like'),
            self.preference(excluded_dex_ids=[151]),
            dict(type='refine', scope={'set_code': 'AAA', 'variant': 'normal'})]
        result = self.replay(turns)
        self.assertNotIn(MEW, self.ids(result))
        self.assertNotIn(OTHER, self.ids(result))
        self.assertTrue(all(c['set_code'] == 'AAA' and c['variant'] == 'normal' for c in result['candidate_cards']))

    def test_clear_dismissal_still_works_after_scope_change(self):
        turns = self.start() + [self.reaction(A, 'dismiss'),
            dict(type='refine', scope={'variant': 'normal'})]
        self.assertNotIn(A, self.ids(self.replay(turns)))
        self.assertIn(A, self.ids(self.replay(turns + [self.reaction(A, 'clear')])))

    def test_clear_dismissal_still_works_after_preference_change(self):
        turns = self.start() + [self.reaction(A, 'dismiss'),
            self.preference(preferred_illustrators=['Yuka Morii'])]
        self.assertNotIn(A, self.ids(self.replay(turns)))
        self.assertIn(A, self.ids(self.replay(turns + [self.reaction(A, 'clear')])))

    def test_negated_taste_is_never_silently_converted_to_positive(self):
        result = self.replay(self.start() + [dict(type='reply', text='I do not like Mew')])
        self.assertNotIn(151, result['preferences'].get('collecting', {}).get('preferred_dex_ids', []))

    def test_only_release_is_respected_or_explicitly_clarified(self):
        result = self.replay([dict(type='ask', question='Recommend Japanese Pikachu cards only from AAA')])
        violations = [c for c in result['candidate_cards'] if c['set_code'] != 'AAA']
        self.assertFalse(violations and result['selection_allowed'],
                         'An explicit only-from release may not become an unacknowledged soft preference')

    def test_raw_comparison_cannot_be_reused_after_preference_change(self):
        turns = [dict(type='ask', question=f'Compare {A} and {B}'),
                 self.preference(preferred_dex_ids=[151])]
        with self.assertRaises(ValueError):
            self.replay(turns + [dict(type='choose_comparison', side='right', card_id=B)])

    def test_raw_comparison_invalidation_covers_scope_inventory_and_money(self):
        for change in [dict(type='refine', scope={'variant': 'normal'}),
                       dict(type='inventory', owned_items=[]),
                       dict(type='preferences', preferences={'budget_minor': 5000, 'currency': 'USD'})]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.replay([dict(type='ask', question=f'Compare {A} and {B}'), change,
                             dict(type='choose_comparison', side='right', card_id=B)])

    def test_clear_does_not_authorize_arbitrary_or_prior_goal_feedback(self):
        for turns in [self.start(), self.start() + [self.reaction(A, 'dismiss'),
            dict(type='ask', question='Recommend English Mew cards')]]:
            with self.assertRaises(ValueError):
                self.replay(turns + [self.reaction(OTHER if len(turns) == 1 else A, 'clear')])
        changed = self.start() + [self.reaction(A, 'dismiss'),
            dict(type='inventory', owned_items=[dict(item_id='owned', card_id=A)])]
        self.assertNotIn(A, self.ids(self.replay(changed + [self.reaction(A, 'clear')])))

    def test_ambiguous_only_release_cannot_be_bypassed_with_profile(self):
        turns = [dict(type='ask', question='Recommend Japanese Pikachu cards only from AAA or BBB'),
                 self.preference(preferred_dex_ids=[25])]
        result = self.replay(turns)
        self.assertFalse(result['selection_allowed'])
        self.assertTrue(self.replay(turns + [dict(type='refine', scope={'set_code':'AAA'})])['selection_allowed'])

    def test_negated_ask_and_alias_replies_do_not_create_positive_taste(self):
        for text in ['Do not recommend Mew cards', 'I dislike Mew', '我不喜欢梦幻', '夢幻は好きじゃない']:
            with self.subTest(text=text):
                turns = [dict(type='ask', question=text)] if 'recommend' in text else self.start() + [dict(type='reply', text=text)]
                result = self.replay(turns)
                self.assertNotIn(151, result['preferences'].get('collecting', {}).get('preferred_dex_ids', []))
                self.assertFalse(result['selection_allowed'])

    def test_comparison_focus_requires_independent_select(self):
        turns = self.start() + [dict(type='compare', left_card_id=A, right_card_id=B)]
        compared = self.replay(turns)
        self.assertEqual(self.ids(compared), [])
        self.assertIsNone(compared['target_intent'])
        focus = turns + [dict(type='choose_comparison', side='right', card_id=B)]
        self.assertEqual(self.ids(self.replay(focus)), [B])
        self.assertIsNone(self.replay(focus)['target_intent'])
        selected = self.replay(focus + [dict(type='select', card_id=B)])
        self.assertEqual(selected['target_intent']['card_id'], B)
        self.assertFalse(selected['target_intent']['transaction_ready'])

    def test_pagination_is_disjoint_and_new_goal_withdraws_target(self):
        first = self.replay(self.start(), limit=2)
        second = self.replay(self.start() + [dict(type='page', offset=2)], limit=2)
        self.assertFalse(set(self.ids(first)) & set(self.ids(second)))
        selected = self.start() + [dict(type='select', card_id=B),
            dict(type='ask', question='Recommend English Mew cards')]
        result = self.replay(selected)
        self.assertIsNone(result['target_intent'])
        self.assertEqual(self.ids(result), ['en:AAA:003/100:normal'])

    def test_real_http_node_caller_preserves_hold_and_explicit_recovery(self):
        script = r"""
const {createCollectorClient}=require('./integrations/pivota/collectorClient.cjs');
(async()=>{
 const client=createCollectorClient({baseUrl:process.argv[1],allowLoopback:true});
 let call=await client.start({question:'Recommend Japanese Pikachu cards',limit:50});
 call=await client.advance({session:call.session,action:{type:'reply',text:'I do not like Mew'}});
 const held=call.result.selection_allowed;
 let rejected=null;
 try { await client.advance({session:call.session,action:{type:'select',card_id:'ja:AAA:002/100:normal'}}); }
 catch(error) { rejected=error.code; }
 call=await client.advance({session:call.session,action:{type:'preferences',preferences:{collecting:{excluded_dex_ids:[151]}}}});
 call=await client.advance({session:call.session,action:{type:'select',card_id:'ja:AAA:002/100:normal'}});
 console.log(JSON.stringify({held,rejected,target:call.target_intent.card_id,transaction_ready:call.target_intent.transaction_ready}));
})().catch(error=>{console.error(error);process.exit(1)});
"""
        with create_server(str(Path(self.temp.name) / 'catalog.sqlite3'), '127.0.0.1', 0, True) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                result = json.loads(subprocess.check_output(['node', '-e', script,
                    f'http://127.0.0.1:{server.server_address[1]}'], text=True, timeout=15))
            finally:
                server.shutdown()
                worker.join(timeout=5)
        self.assertEqual(result, dict(held=False, rejected='catalog_rejected_action',
                                     target=B, transaction_ready=False))


if __name__ == '__main__':
    unittest.main()
