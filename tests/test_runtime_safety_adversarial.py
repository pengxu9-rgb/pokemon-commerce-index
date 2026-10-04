"""Independent synthetic resource and caller-transcript regressions."""
import copy,http.client,json,tempfile,threading,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from pokemon_index import core,collector_discovery as discovery,collector_inventory as inventory,collector_journey as journey,collector_recommendation as rec
from pokemon_index.cli import create_server

class RuntimeSafetyAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'synthetic.sqlite3'
        with closing(core.connect(cls.path)) as db:
            core.init_db(db)
            rows=[];facets=[]
            for i in range(1200):
                code='FX'+str(i//100);number=f'{i%100+1:03}/100';cid=f'ja:{code}:{number}:normal';dex=25 if i<1000 else 151
                rows.append((cid,'ja',code,number,'normal','Pikachu' if dex==25 else 'Mew',None,'synthetic','synthetic',0,1,'{}'))
                facets.extend([(cid,'dex_id',str(dex),'synthetic','synthetic'),(cid,'illustrator','Fixture Artist','synthetic','synthetic')])
            db.executemany('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',rows)
            db.executemany('INSERT INTO card_facet VALUES(?,?,?,?,?)',facets);db.commit()
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):self.db=core.connect(self.path,readonly=True)
    def tearDown(self):self.db.close()
    def test_twenty_page_replay_ranks_one_pool_in_bounded_batches(self):
        turns=[dict(type='ask',question='Recommend Japanese Pikachu cards')]+[dict(type='page',offset=i*5) for i in range(1,20)]
        with patch.object(rec,'_facet_batches',wraps=rec._facet_batches) as batches:
            out=journey.replay(self.db,dict(turns=turns,limit=5),revision='a'*64)
        # One full pool and each displayed five-card page. Per-page full ranking
        # used to process the 1,000-row pool twenty times.
        self.assertEqual(sum(len(c.args[1]) for c in batches.call_args_list),1100)
        self.assertEqual(out['turn_count'],20)
        self.assertEqual([x['rank'] for x in out['recommendation']['items']],[96,97,98,99,100])
        self.assertEqual(len({cid for t in out['trace'] for cid in t['displayed_card_ids']}),100)
        self.assertFalse(out['purchase_ready']);self.assertFalse(out['public_display_allowed'])
    def test_cached_pages_match_uncached_and_do_not_mutate_prior_response(self):
        cache={'revision':'a'*64};args=dict(question='Recommend Pikachu cards',profile={'preferred_dex_ids':[25]},feedback={},owned=[])
        first=rec.recommend(self.db,**args,pool_cache=cache);saved=copy.deepcopy(first)
        for offset in [5,95,999]:
            actual=rec.recommend(self.db,**args,offset=offset,pool_cache=cache)
            self.assertEqual(actual,rec.recommend(self.db,**args,offset=offset))
        self.assertEqual(first,saved)
        self.assertEqual(set(cache),{'revision','key','pool','affiliation_key','affiliations'})
        self.assertLessEqual(len(cache['affiliations']),6)
        self.assertNotIn('scope',cache['pool']['inventory'])
    def test_single_pool_invalidates_every_semantic_input(self):
        base=dict(question='Recommend Pikachu cards',profile={'preferred_dex_ids':[25]},feedback={},owned=None,preferences={})
        changes=[dict(profile={'preferred_dex_ids':[151]}),dict(scope={'set_code':'FX1'}),
            dict(feedback={'ja:FX0:001/100:normal':'dismiss'}),
            dict(owned=[dict(item_id='mine',card_id='ja:FX0:001/100:normal')]),
            dict(preferences={'budget_minor':100}),dict(question='Recommend Japanese Pikachu cards')]
        for change in changes:
            cache={'revision':'a'*64};rec.recommend(self.db,**base,pool_cache=cache);old=cache['pool']
            args=dict(base,**change);actual=rec.recommend(self.db,**args,pool_cache=cache)
            self.assertIsNot(cache['pool'],old);self.assertEqual(actual,rec.recommend(self.db,**args))
            self.assertEqual(set(cache),{'revision','key','pool','affiliation_key','affiliations'})
            self.assertLessEqual(len(cache['affiliations']),6)
        cache={'revision':'a'*64};rec.recommend(self.db,**base,pool_cache=cache);old=cache['pool'];cache['revision']='b'*64
        rec.recommend(self.db,**base,pool_cache=cache);self.assertIsNot(cache['pool'],old)
    def test_distinct_replays_do_not_share_ownership_or_feedback(self):
        ask=dict(type='ask',question='Recommend Japanese Pikachu cards')
        first=journey.replay(self.db,dict(turns=[ask]),revision='a'*64)
        cid=first['candidate_cards'][0]['card_id']
        owned=journey.replay(self.db,dict(turns=[ask,dict(type='inventory',owned_items=[dict(item_id='mine',card_id=cid)])]),revision='a'*64)
        self.assertNotIn(cid,[c['card_id'] for c in owned['candidate_cards']])
        self.assertEqual(first,journey.replay(self.db,dict(turns=[ask]),revision='a'*64))
    def test_inventory_projects_scope_once_and_renders_only_bounded_pages(self):
        with patch.object(discovery,'execute',wraps=discovery.execute) as execute,patch.object(discovery,'_card_result',wraps=discovery._card_result) as render:
            out=inventory.compare(self.db,dict(question='Japanese Pikachu cards',owned_items=[],offset=900,limit=5))
        self.assertEqual(execute.call_count,1)
        self.assertLessEqual(render.call_count,105)
        self.assertEqual(out['coverage']['scoped_catalog_records'],1000)
        self.assertEqual(len(out['missing_catalog_records']),5)
        self.assertTrue(out['coverage']['has_more'])
    def test_inventory_capture_respects_hard_pool_cap(self):
        captured=[]
        discovery.execute(self.db,'Japanese Pikachu cards',limit=1,_row_capture=(999,captured))
        self.assertEqual(captured,[])
        with patch.object(inventory,'MAX_SCOPE',999):out=inventory.compare(self.db,dict(question='Japanese Pikachu cards',owned_items=[]))
        self.assertEqual(out['status'],'scope_clarification_needed');self.assertEqual(out['missing_catalog_records'],[])
    def test_artist_inventory_does_not_recheck_every_row_with_a_facet_query(self):
        statements=[];self.db.set_trace_callback(statements.append)
        out=inventory.compare(self.db,dict(question='Cards by Fixture Artist',owned_items=[],limit=5))
        self.assertEqual(out['coverage']['scoped_catalog_records'],1200)
        self.assertFalse(any(q.startswith('SELECT 1 FROM discovery_card_facet WHERE card_id=') and "facet_type='illustrator'" in q for q in statements))
    def test_malformed_forged_stale_or_overlong_transcripts_reject(self):
        ask=dict(type='ask',question='Japanese Pikachu cards')
        for request in [None,[],{},dict(turns=[]),dict(turns=[ask]*21),dict(turns=[ask],target_intent={}),
                        dict(turns=[ask,dict(type='select',card_id='ja:FX9:099/100:normal')],limit=1),
                        dict(turns=[ask],expected_revision='b'*64),dict(turns=[ask,dict(type='page',offset=True)])]:
            with self.subTest(request=request),self.assertRaises(ValueError):journey.replay(self.db,request,revision='a'*64)
    def test_deep_json_returns_generic_http_400_and_server_remains_usable(self):
        with create_server(str(self.path),'127.0.0.1',0,True) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                # Below the transport byte ceiling, but beyond CPython's JSON
                # nesting guard. Previously this dropped the connection and
                # triggered a retryable transport error in the Node caller.
                raw='['*10000+'0'+']'*10000
                client.request('POST','/collector-journey',body=raw,headers={'Content-Type':'application/json'})
                response=client.getresponse()
                self.assertEqual(response.status,400)
                self.assertEqual(json.loads(response.read()),{'error':'JSON nesting exceeds supported depth'})
                client.request('GET','/health');response=client.getresponse()
                self.assertEqual(response.status,200);self.assertEqual(json.loads(response.read()),{'ok':True})
            finally:client.close();server.shutdown();thread.join(timeout=5)

if __name__=='__main__':unittest.main()
