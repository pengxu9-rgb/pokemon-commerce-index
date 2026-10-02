import unittest
from pokemon_index import core,collector_discovery

class ReleaseAliasRoutingTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        releases=[('SI','スタートデッキ100'),('SMP2','名探偵ピカチュウ'),('S1H','シールド'),('CP6','ポケットモンスターカードゲーム 拡張パック 20th Anniversary'),('20TH','Other'),('PMCG1','ポケットモンスターカードゲーム 拡張パック')]
        for code,name in releases:
            core.import_sets(self.db,[dict(language='ja',set_code=code,name_ja=name,provenance='fixture-'+code,rights_reference='fixture')])
            for n,card_name,dex in [('001/100','ピカチュウ',25),('002/100','イーブイ',133)]:
                core.import_cards(self.db,[dict(language='ja',set_code=code,collector_number=n,name=card_name,variant='unverified',provenance='fixture-card',rights_reference='fixture')])
                cid=core.card_id('ja',code,n,'unverified');self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,'dex_id',str(dex),'fixture','fixture'))
        core.import_cards(self.db,[dict(language='en',set_code='TEST',collector_number='001/100',name='Pikachu',variant='unverified',provenance='fixture-card',rights_reference='fixture')])
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(core.card_id('en','TEST','001/100','unverified'),'dex_id','25','fixture','fixture'))
        core.import_cards(self.db,[dict(language='ja',set_code='TEST',collector_number='001/100',name='シールド',variant='unverified',provenance='fixture-card',rights_reference='fixture')])
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(core.card_id('ja','TEST','001/100','unverified'),'dex_id','86','fixture','fixture'));self.db.commit()
    def tearDown(self):self.db.close()
    def test_release_name_overrides_embedded_deck_character_and_nested_codes(self):
        for code,name in [('SI','スタートデッキ100'),('SMP2','名探偵ピカチュウ'),('S1H','シールド'),('CP6','ポケットモンスターカードゲーム 拡張パック 20th Anniversary')]:
            r=collector_discovery.execute(self.db,'Japanese cards from '+name)
            self.assertEqual(r['task'],'set_cards');self.assertEqual({c['set_code'] for c in r['cards']},{code})
    def test_real_gameplay_requests_remain_blocked(self):
        for q in ['How do I play スタートデッキ100?','How to build スタートデッキ100','Japanese cards from スタートデッキ100 for a competitive deck','スタートデッキ100の遊び方','Japanese cards from スタートデッキ100: gameplay rules?']:
            r=collector_discovery.execute(self.db,q);self.assertEqual(r['task'],'gameplay_evidence_needed');self.assertEqual(r['cards'],[])
    def test_release_and_separately_requested_character_remain_joint_constraints(self):
        r=collector_discovery.execute(self.db,'Japanese Pikachu cards from 名探偵ピカチュウ')
        self.assertEqual(r['task'],'character_cards');self.assertEqual(r['dex_ids'],[25]);self.assertEqual({c['set_code'] for c in r['cards']},{'SMP2'});self.assertTrue(all(c['name']=='ピカチュウ' for c in r['cards']))
    def test_broad_ambiguous_title_requires_scope_and_multiple_sets_stay_ambiguous(self):
        r=collector_discovery.execute(self.db,'Japanese cards シールド');self.assertEqual(r['task'],'need_release_scope');self.assertEqual(r['cards'],[])
        r=collector_discovery.execute(self.db,'Japanese cards from シールド and スタートデッキ100');self.assertEqual(r['task'],'need_release_scope')
    def test_numeric_release_name_does_not_consume_number_denominator(self):
        core.import_sets(self.db,[dict(language='en',set_code='EN151',name='151',provenance='fixture-151',rights_reference='fixture')])
        self.assertEqual(collector_discovery._release_codes(self.db,'english cards 001/151',['en']),set())
        self.assertEqual(collector_discovery._release_codes(self.db,'english set 151',['en']),{'EN151'})
    def test_numbered_release_lookup_does_not_inherit_title_species(self):
        r=collector_discovery.execute(self.db,'Japanese cards from 名探偵ピカチュウ 002/100')
        self.assertEqual(r['task'],'exact_coordinates');self.assertEqual(r['cards'][0]['name'],'イーブイ')

if __name__=='__main__':unittest.main()
