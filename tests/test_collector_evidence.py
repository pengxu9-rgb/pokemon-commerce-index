import copy,json,unittest,tempfile,threading
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from contextlib import closing
from pokemon_index import core,collector_evidence,collector_discovery,collector_inventory,supported_catalog
from scripts.evaluate_collector_sources import catalog_fingerprint
from scripts.review_collector_artwork import parse
from pokemon_index.cli import create_server

class CollectorEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',variant='holo',name='Pikachu',provenance='fixture',rights_reference='fixture'),
                                  dict(language='ja',set_code='FIX',collector_number='002/100',variant='normal',name='Gengar',provenance='fixture',rights_reference='fixture')])
        self.db.execute("INSERT INTO catalog_set_localized(language,set_code,name,release_date,official_card_count,provenance,rights_reference,display_allowed) VALUES ('ja','FIX','Fixture','2023-01-01',100,'fixture','fixture',0)")
        for cid,dex in [('ja:FIX:001/100:holo','25'),('ja:FIX:002/100:normal','94')]:
            self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,'dex_id',dex,'fixture','fixture'))
        self.db.commit();self.cid='ja:FIX:001/100:holo'
    def tearDown(self):self.db.close()
    def row(self,event='first',kind='official_description',status='source_supported'):
        e=dict(kind=kind,source_url='https://www.pokemon-card.com/ex/sv2a/index.html',source_page_sha256='a'*64,
            image_url='https://www.pokemon-card.com/ex/sv2a/assets/images/ar-card-1.png',image_sha256='b'*64,
            official_card_url='https://www.pokemon-card.com/card-search/details.php/card/43958',official_card_page_sha256='c'*64,
            locator='adjacent illustration caption',finding='Gengar appears in the illustrated scene.')
        if kind=='ai_visual':e['review']=dict(model='fixture-model',prompt_version='fixture',identity_match='match',prompt_sha256='d'*64,response_sha256='e'*64)
        return dict(schema='pokemon.collector-evidence.v1',event_id=event,subject_kind='card',subject_id=self.cid,
            claim='depicted_pokemon',value=94,role='cameo',status=status,
            identity_sha256=supported_catalog.digest(collector_evidence.identity(self.db,'card',self.cid)),
            evidence=e,actor='fixture',recorded_at='2026-10-01T00:00:00Z',expected_head=None)
    def test_official_and_ai_tiers_never_promote_copy_or_pair_approvals(self):
        collector_evidence.import_evidence(self.db,[self.row(),self.row('ai','ai_visual','proposed')])
        context=collector_evidence.card_context(self.db,self.cid)
        self.assertEqual(len(context['findings']),2)
        self.assertFalse(context['physical_finish_verified']);self.assertFalse(context['price_comparable'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM card_relationship_assertion').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT display_allowed FROM card WHERE card_id=?',(self.cid,)).fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'remain proposed'):
            collector_evidence.import_evidence(self.db,[self.row('bad','ai_visual','source_supported')])
        fabricated=self.row('copy');fabricated['physical_finish_verified']=True
        with self.assertRaises(ValueError):collector_evidence.import_evidence(self.db,[fabricated])
    def test_batch_validation_is_atomic_and_identity_bound(self):
        invalid=self.row('invalid');invalid['identity_sha256']='0'*64
        with self.assertRaises(ValueError):collector_evidence.import_evidence(self.db,[self.row(),invalid])
        self.assertEqual(collector_evidence.records(self.db),[])
        invalid=self.row();invalid['evidence']['source_url']='https://example.com/source'
        with self.assertRaises(ValueError):collector_evidence.import_evidence(self.db,[invalid])
    def test_append_withdrawal_and_old_replay_do_not_reactivate_a_finding(self):
        first=self.row();collector_evidence.import_evidence(self.db,[first])
        withdrawal=self.row('withdrawn',status='withdrawn');withdrawal['expected_head']='first'
        collector_evidence.import_evidence(self.db,[withdrawal]);self.assertEqual(collector_evidence.records(self.db),[])
        self.assertEqual(collector_evidence.import_evidence(self.db,[first]),0)
        self.assertEqual(collector_evidence.records(self.db),[])
        with self.assertRaisesRegex(ValueError,'stale'):
            collector_evidence.import_evidence(self.db,[self.row('stale')])
        changed=copy.deepcopy(first);changed['actor']='another'
        with self.assertRaisesRegex(ValueError,'collision'):collector_evidence.import_evidence(self.db,[changed])
    def test_identity_mutation_quarantines_prior_evidence(self):
        collector_evidence.import_evidence(self.db,[self.row()])
        self.db.execute('UPDATE card SET name=? WHERE card_id=?',('Changed',self.cid));self.db.commit()
        self.assertEqual(collector_evidence.card_context(self.db,self.cid)['stale_findings'],1)
        self.assertEqual(collector_evidence.artwork_candidates(self.db,[94],['ja']),([],[]))
    def test_release_declaration_is_context_not_per_card_finish_verification(self):
        r=self.row();r.update(subject_kind='release',subject_id='ja:FIX',claim='finish_exists',value='reverse_pokeball',role='release_declaration',
            identity_sha256=supported_catalog.digest(collector_evidence.identity(self.db,'release','ja:FIX')),
            evidence=dict(kind='official_release_text',source_url='https://www.pokemon-card.com/ex/sv2a/index.html',source_page_sha256='a'*64,locator='mirror section',finding='A release-level finish exists.'))
        collector_evidence.import_evidence(self.db,[r]);context=collector_evidence.card_context(self.db,self.cid)
        self.assertEqual(context['findings'][0]['subject_kind'],'release');self.assertFalse(context['physical_finish_verified'])
        self.assertEqual(collector_evidence.artwork_candidates(self.db,[94],['ja']),([],[]))
    def test_official_cameo_cards_and_proposed_leads_are_separate(self):
        collector_evidence.import_evidence(self.db,[self.row('ai','ai_visual','proposed')])
        r=collector_discovery.execute(self.db,'Japanese Gengar cameos in card art')
        self.assertEqual(r['cards'],[]);self.assertEqual(len(r['artwork_review_leads']),1)
        self.assertFalse(r['complete_answer_established'])
        collector_evidence.import_evidence(self.db,[self.row()])
        r=collector_discovery.execute(self.db,'Japanese Gengar cameos in card art')
        self.assertEqual([c['card_id'] for c in r['cards']],[self.cid])
        self.assertTrue(r['coverage']['artwork_cameos_supported'])
        self.assertFalse(r['coverage']['global_printing_completeness_established'])
        self.assertEqual(collector_discovery.execute(self.db,'Japanese Gengar cards')['cards'][0]['card_id'],'ja:FIX:002/100:normal')
    def test_inventory_compares_only_supported_cameo_records(self):
        q='Japanese Gengar cameos in card art'
        collector_evidence.import_evidence(self.db,[self.row('ai','ai_visual','proposed')])
        r=collector_inventory.compare(self.db,dict(question=q,owned_items=[]))
        self.assertEqual(r['status'],'scope_clarification_needed');self.assertEqual(r['missing_catalog_records'],[])
        collector_evidence.import_evidence(self.db,[self.row()])
        r=collector_inventory.compare(self.db,dict(question=q,owned_items=[dict(item_id='a',card_id=self.cid)]))
        self.assertEqual(r['owned_in_scope'][0]['card_id'],self.cid)
        self.assertFalse(r['complete_missing_list_established']);self.assertEqual(r['missing_catalog_records'],[])
    def test_cameo_evidence_honors_release_number_language_and_finish(self):
        collector_evidence.import_evidence(self.db,[self.row(),self.row('ai','ai_visual','proposed')])
        for q in ['English Gengar cameos','Japanese Gengar cameos FIX 002/100',
                  'Japanese Gengar cameos ja:FIX:002/100:normal','Japanese Gengar cameos non-holo']:
            r=collector_discovery.execute(self.db,q)
            self.assertEqual(r['cards'],[],q);self.assertEqual(r.get('artwork_review_leads',[]),[],q)
        good=collector_discovery.execute(self.db,'Japanese Gengar cameos FIX 001/100 holo')
        self.assertEqual(good['cards'][0]['card_id'],self.cid)
    def test_replay_fingerprint_detects_evidence_enrichment(self):
        before=catalog_fingerprint(self.db);collector_evidence.import_evidence(self.db,[self.row()])
        self.assertNotEqual(catalog_fingerprint(self.db),before)
    def test_legacy_snapshot_has_no_implicit_evidence(self):
        self.db.execute('DROP TABLE catalog_collector_evidence')
        self.assertEqual(collector_evidence.records(self.db),[])
        self.assertEqual(collector_discovery.execute(self.db,'Japanese Gengar cameos')['status'],'blocked')
    def test_visual_parser_rejects_duplicate_species_and_incomplete_response(self):
        finding=dict(identity_match='match',read_name='Pikachu',read_number='001/100',uncertainties='',
            depictions=[dict(dex_id=25,name='Pikachu',role='subject',detail='center')]*2)
        response=dict(modelVersion='gemini-3.8-flash',candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(finding))]))])
        with self.assertRaises(ValueError):parse(response)
        response['candidates'][0]['finishReason']='MAX_TOKENS'
        with self.assertRaises(ValueError):parse(response)

    def test_http_evidence_routes_are_internal_and_readonly(self):
        collector_evidence.import_evidence(self.db,[self.row()])
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'catalog.sqlite3'
            with closing(core.connect(path)) as target:self.db.backup(target)
            before=path.read_bytes()
            for enabled in [True,False]:
                with create_server(str(path),'127.0.0.1',0,enabled) as server:
                    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                    try:
                        for route in ['/collector-evidence-status','/catalog-evidence?card_id='+self.cid]:
                            url='http://127.0.0.1:'+str(server.server_address[1])+route
                            if enabled:
                                with urlopen(url,timeout=5) as response:result=json.load(response)
                                self.assertFalse(result.get('physical_finish_verified',False))
                            else:
                                with self.assertRaises(HTTPError) as context:urlopen(url,timeout=5)
                                self.assertEqual(context.exception.code,404);context.exception.close()
                    finally:server.shutdown();thread.join(timeout=5)
            self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
