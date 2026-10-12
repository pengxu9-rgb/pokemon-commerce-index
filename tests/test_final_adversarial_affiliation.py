"""Independent follow-up review of species affiliation and hard exclusions."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest

from pokemon_index import core, collector_journey, collector_recommendation, supported_catalog
from pokemon_index import collector_character_affiliation as affiliation
import test_independent_recommendation_review as fixture


class FinalSpeciesExclusionTests(unittest.TestCase):
    setUp = fixture.IndependentRecommendationReview.setUp
    tearDown = fixture.IndependentRecommendationReview.tearDown
    replay = fixture.IndependentRecommendationReview.replay
    start = fixture.IndependentRecommendationReview.start

    def add_record(self, number, name, category):
        cid = f'ja:AAA:{number}/100:holo'
        provenance = 'independent:source:' + number
        rights = 'synthetic:no-public-display'
        core.import_cards(self.db, [dict(language='ja', set_code='AAA', collector_number=number + '/100',
            variant='holo', name=name, match_eligible=True, provenance=provenance, rights_reference=rights)])
        if category is not None:
            core.import_card_classifications(self.db, [dict(card_id=cid, category=category,
                provenance=provenance, rights_reference=rights)])
        return cid

    def excluded_release(self):
        return self.start() + [dict(type='preferences', preferences={'collecting': {
            'preferred_dex_ids': [], 'preferred_releases': [{'language': 'ja', 'set_code': 'AAA'}],
            'excluded_dex_ids': [151]}})]

    def assert_not_selectable(self, cid, turns):
        result = self.replay(turns)
        if cid in [c['card_id'] for c in result['candidate_cards']]:
            self.assertTrue(result['selection_blockers'] or result['card_selection_blockers'][cid],
                            'Unknown Pokemon membership cannot silently satisfy an exclusion')
        with self.assertRaises(ValueError):
            self.replay(turns + [dict(type='select', card_id=cid)])

    def test_unpinned_pokemon_missing_species_cannot_bypass_exclusion(self):
        cid = self.add_record('007', 'Mew ex', 'Pokemon')
        self.assert_not_selectable(cid, self.excluded_release())

    def test_current_non_pokemon_categories_do_not_need_species_facets(self):
        for number, category in [('008', 'Trainer'), ('009', 'Energy')]:
            cid = self.add_record(number, 'Synthetic ' + category, category)
            result = self.replay(self.excluded_release())
            self.assertIn(cid, [c['card_id'] for c in result['candidate_cards']])
            self.assertEqual(result['card_selection_blockers'][cid], [])
            chosen = self.replay(self.excluded_release() + [dict(type='select', card_id=cid)])
            self.assertEqual(chosen['target_intent']['card_id'], cid)
            self.assertFalse(chosen['purchase_ready'])

    def test_stale_non_pokemon_category_cannot_exempt_unknown_membership(self):
        cid = self.add_record('010', 'Synthetic uncertain category', 'Trainer')
        self.db.execute('UPDATE card_classification SET provenance=? WHERE card_id=?', ('stale:source', cid))
        self.db.commit()
        self.assert_not_selectable(cid, self.excluded_release())

    def test_classification_evidence_changes_invalidate_journey_revision(self):
        before = collector_journey.catalog_revision(self.db)
        source = self.db.execute('SELECT provenance,rights_reference FROM card WHERE card_id=?', (fixture.A,)).fetchone()
        core.import_card_classifications(self.db, [dict(card_id=fixture.A, category='Pokemon',
            provenance=source['provenance'], rights_reference=source['rights_reference'])])
        after = collector_journey.catalog_revision(self.db)
        self.assertNotEqual(before, after)
        with self.assertRaisesRegex(ValueError, 'changed'):
            collector_journey.replay(self.db, dict(turns=self.start(), expected_revision=before))


class FinalSourceAffiliationTests(unittest.TestCase):
    """Use actual six source/support pins, with small explicit synthetic anchors."""
    def setUp(self):
        self.db = core.connect(':memory:')
        core.init_db(self.db)
        # Preserve this original six-target adversarial fixture; the new source
        # batch has its own full 21-target evidence tests, not synthetic anchors.
        original_ids = {f'ja:SV4A:{n}/190:holo' for n in [327, 328, 331, 347, 348, 349]}
        self.bindings = [pin for pin in affiliation._bindings() if pin['card_id'] in original_ids]
        supported = {r['card_id']: r for r in map(json.loads,
            Path('catalog/supported-discovery-v1/supported-cards.jsonl').read_text().splitlines())}
        for pin in self.bindings:
            cid = pin['card_id']; record = supported[cid]; ident = record['identity']; release = record['release']
            core.import_cards(self.db, [dict(ident, match_eligible=True,
                rights_reference=pin['target_rights_reference'])])
            core.import_card_classifications(self.db, [dict(card_id=cid, category='Pokemon',
                provenance=ident['provenance'], rights_reference=pin['target_rights_reference'])])
            self.db.execute('INSERT OR IGNORE INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
                ('ja', 'SV4A', release['name'], release['release_date'], 190,
                 release['source_provenance'], release['official_url'], 0))
            self.db.execute('INSERT OR IGNORE INTO catalog_release_evidence VALUES (?,?,?)',
                ('ja', 'SV4A', json.dumps(release, ensure_ascii=False, sort_keys=True)))
            ref = record['reference']; official = record['official_card']
            core.import_card_references(self.db, [dict(source=ref['source'], source_jp_id=ref['native_id'],
                set_code='SV4A', collector_number=ident['collector_number'], name=ref['name'],
                provenance=ref['provenance'], rights_reference=official['official_url'])])
            self.db.execute('INSERT INTO card_rarity_correction VALUES (?,?,?,?,?,?,?,?,?,?)',
                (cid, ident['name'], ident['rarity'], ident['provenance'], ident['rarity'],
                 ref['provenance'], official['official_url'], official['official_page_sha256'],
                 official['official_rarity_icon'], '2026-10-04T00:00:00+00:00'))
            supported_catalog.import_supported(self.db, [record])
        self.anchor = self.add_anchor('001', 'ミュウ', 151)
        self.add_anchor('002', 'サーナイト', 282)
        self.add_anchor('003', 'リザードン', 6)
        self.db.commit()
        self.mew = 'ja:SV4A:327/190:holo'
        self.other_mew = 'ja:SV4A:347/190:holo'

    def tearDown(self):
        self.db.close()

    def add_anchor(self, number, name, dex, language='ja'):
        cid = core.card_id(language, 'BASE', number + '/100', 'normal')
        source = 'independent:anchor:' + number
        core.import_cards(self.db, [dict(language=language, set_code='BASE', collector_number=number + '/100',
            variant='normal', name=name, match_eligible=True, provenance=source, rights_reference='synthetic:rights')])
        core.import_card_classifications(self.db, [dict(card_id=cid, category='Pokemon',
            provenance=source, rights_reference='synthetic:rights')])
        core.import_card_facets(self.db, [dict(card_id=cid, facet_type='dex_id', value=dex,
            provenance=source, rights_reference='synthetic:rights')])
        return cid

    def test_six_pins_have_current_real_support_and_no_new_target_dex_facts(self):
        before = list(self.db.execute('SELECT * FROM card_facet ORDER BY card_id'))
        actual = affiliation.affiliations(self.db)
        self.assertEqual(set(actual), {b['card_id'] for b in self.bindings})
        for cid, derived in actual.items():
            self.assertEqual(supported_catalog.support_for_card(self.db, cid)['status'], 'supported_for_internal_review')
            self.assertFalse(derived['reason']['source_asserted_dex_id'])
            self.assertEqual(derived['reason']['basis'], 'source_name_character_affiliation')
            self.assertIsNone(self.db.execute("SELECT 1 FROM card_facet WHERE card_id=? AND facet_type='dex_id'", (cid,)).fetchone())
        self.assertEqual(before, list(self.db.execute('SELECT * FROM card_facet ORDER BY card_id')))

    def test_current_reference_drift_withdraws_target_affiliation(self):
        self.db.execute("UPDATE card_reference SET provenance='changed' WHERE set_code='SV4A' AND collector_number='327/190'")
        self.db.commit()
        self.assertNotIn(self.mew, affiliation.affiliations(self.db))
        self.assertIn(self.other_mew, affiliation.affiliations(self.db))

    def test_unpinned_exact_ex_title_is_not_automatically_affiliated(self):
        cid = core.card_id('ja', 'OTHER', '001/100', 'normal')
        core.import_cards(self.db, [dict(language='ja', set_code='OTHER', collector_number='001/100',
            variant='normal', name='ミュウex', match_eligible=True,
            provenance='independent:unreviewed', rights_reference='synthetic:rights')])
        core.import_card_classifications(self.db, [dict(card_id=cid, category='Pokemon',
            provenance='independent:unreviewed', rights_reference='synthetic:rights')])
        self.assertNotIn(cid, affiliation.affiliations(self.db))

    def test_same_language_current_conflicting_anchor_withdraws_both_mew_pins(self):
        self.add_anchor('004', 'ミュウ', 150)
        actual = affiliation.affiliations(self.db)
        self.assertNotIn(self.mew, actual)
        self.assertNotIn(self.other_mew, actual)
        self.assertEqual(len(actual), 4)

    def test_derived_species_participates_in_likes_dismissals_and_hard_exclusions(self):
        def recommend(profile, feedback):
            return collector_recommendation.recommend(self.db, 'Recommend Japanese cards', profile,
                feedback, limit=50, scope={'set_code': 'SV4A'})
        result = recommend({'preferred_dex_ids': [151]}, {})
        self.assertEqual({c['card_id'] for c in result['cards']}, {self.mew, self.other_mew})
        self.assertTrue(all(any(r['field'] == 'character_name_affiliation' for r in item['reasons'])
                            for item in result['recommendation']['items']))
        liked = recommend({}, {self.mew: 'like'})
        self.assertEqual({c['card_id'] for c in liked['cards']}, {self.mew, self.other_mew})
        dismissed = recommend({'preferred_dex_ids': [151]}, {self.mew: 'dismiss'})
        self.assertEqual([c['card_id'] for c in dismissed['cards']], [self.other_mew])
        excluded = recommend({'preferred_releases': [{'language': 'ja', 'set_code': 'SV4A'}],
                              'excluded_dex_ids': [151]}, {self.mew: 'like'})
        self.assertNotIn(self.mew, [c['card_id'] for c in excluded['cards']])
        self.assertNotIn(self.other_mew, [c['card_id'] for c in excluded['cards']])
        self.assertFalse(excluded['scope']['public_display_allowed'])
        self.assertEqual(excluded['scope']['prices'], [])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the actual caller contract')
    def test_actual_http_node_accepts_derived_reasons_and_preserves_exclusions(self):
        from pokemon_index.cli import create_server
        program = r'''
const {createCollectorClient} = require(process.argv[1]);
const cfg = JSON.parse(process.argv[2]);
const client = createCollectorClient({baseUrl:cfg.url,allowLoopback:true,retryDelayMs:0});
(async()=>{
  let call=await client.start({question:'What should I collect next?',limit:50});
  for(const action of [
    {type:'preferences',preferences:{collecting:{preferred_dex_ids:[151]}}},
    {type:'refine',scope:{language:'ja',set_code:'SV4A'}},
    {type:'feedback',card_id:cfg.mew,reaction:'like'}
  ]) call=await client.advance({session:call.session,action});
  const derived=call.result.recommendation.items.flatMap(i=>i.reasons).filter(r=>r.field==='character_name_affiliation');
  if(!derived.length || derived.some(r=>r.source_asserted_dex_id!==false)) throw Error('missing typed derived proof');
  call=await client.advance({session:call.session,action:{type:'feedback',card_id:cfg.mew,reaction:'dismiss'}});
  if(call.result.candidate_cards.some(c=>c.card_id===cfg.mew)) throw Error('dismiss did not remove exact id');
  call=await client.advance({session:call.session,action:{type:'preferences',preferences:{collecting:{
    preferred_dex_ids:[],preferred_releases:[{language:'ja',set_code:'SV4A'}],excluded_dex_ids:[151]}}}});
  if(call.result.candidate_cards.some(c=>[cfg.mew,cfg.other].includes(c.card_id))) throw Error('excluded affiliation escaped');
  if(call.target_intent!==null || call.result.purchase_ready || call.result.public_display_allowed) throw Error('authority changed');
  process.stdout.write(JSON.stringify({status:call.status,derived:derived.length}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'fixture.sqlite3'
            self.db.commit()
            with sqlite3.connect(path) as saved:
                self.db.backup(saved)
            with create_server(str(path), '127.0.0.1', 0, True) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    config = dict(url='http://127.0.0.1:' + str(server.server_address[1]),
                                  mew=self.mew, other=self.other_mew)
                    response = subprocess.check_output(['node', '-e', program,
                        str(Path('integrations/pivota/collectorClient.cjs').resolve()), json.dumps(config)],
                        text=True, timeout=30)
                    self.assertEqual(json.loads(response)['status'], 'accepted')
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the caller contract')
    def test_node_rejects_liked_origin_without_matching_candidate_species_proof(self):
        turns = [dict(type='ask', question='What should I collect next?'),
                 dict(type='preferences', preferences={'collecting': {'preferred_dex_ids': [151]}}),
                 dict(type='refine', scope={'language': 'ja', 'set_code': 'SV4A'}),
                 dict(type='feedback', card_id=self.mew, reaction='like'),
                 dict(type='page', offset=0)]
        result = collector_journey.replay(self.db, dict(turns=turns, limit=50))
        origin = next(reason for item in result['recommendation']['items'] for reason in item['reasons']
                      if reason.get('affiliation_role') == 'liked_example')
        wrong_id = 'ja:SV4A:328/190:holo'
        wrong = collector_journey.replay(self.db, dict(turns=[dict(type='ask', question=wrong_id)]))['candidate_cards'][0]
        self.assertEqual(wrong['card_id'], wrong_id)
        result['candidate_cards'] = [wrong]
        result['card_selection_blockers'] = {wrong_id: []}
        result['recommendation']['items'] = [dict(card_id=wrong_id, rank=1,
            explicit_match_axes=[], liked_example_match_axes=['character'], reasons=[origin],
            tradeoffs=['No candidate-side species proof supplied'])]
        result['recommendation']['coordinate_groups'] = [dict(language='ja', set_code='SV4A',
            collector_number='328/190', shown_card_ids=[wrong_id], physical_versions_merged=False)]
        program = r'''
const {createCollectorClient}=require(process.argv[1]);
const fs=require('node:fs'); const cfg=JSON.parse(fs.readFileSync(0,'utf8'));
const client=createCollectorClient({baseUrl:'https://catalog.example',getIdToken:async()=>'synthetic',
  fetchImpl:async()=>new Response(JSON.stringify(cfg.result),{headers:{'Content-Type':'application/json'}})});
client.advance({session:{schema:'pokemon.pivota-collector-session.v1',turns:cfg.turns.slice(0,-1),
  limit:50,expected_revision:cfg.result.catalog_revision},action:cfg.turns.at(-1)})
  .then(()=>process.stdout.write('accepted')).catch(e=>process.stdout.write(e.code || String(e)));
'''
        response = subprocess.check_output(['node', '-e', program,
            str(Path('integrations/pivota/collectorClient.cjs').resolve())],
            input=json.dumps(dict(result=result, turns=turns)), text=True, timeout=30)
        self.assertEqual(response, 'invalid_catalog_response')


if __name__ == '__main__':
    unittest.main()
