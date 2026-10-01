import hashlib
import json
import tempfile
import threading
import unittest
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from pokemon_index import core,collector_inventory
from pokemon_index.cli import create_server


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'catalog.sqlite3'
        with closing(core.connect(self.path)) as db:
            core.init_db(db)
            core.import_cards(db,[dict(language=lang,set_code='FIX',collector_number='001/100',
                variant=v,name='Pikachu',provenance='fixture',rights_reference='fixture',match_eligible=False)
                for lang,v in [('ja','normal'),('ja','holo'),('en','normal')]]+
                [dict(language='ja',set_code='FIX',collector_number='002/100',variant='normal',
                      name='Mew',provenance='fixture',rights_reference='fixture',match_eligible=False)])
            for row in db.execute('SELECT * FROM card').fetchall():
                db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(row['card_id'],'dex_id','151' if row['name']=='Mew' else '25','fixture','fixture'))
            db.commit()
        self.db=core.connect(self.path,readonly=True)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def compare(self,owned,question='Japanese Pikachu cards',**kw):
        return collector_inventory.compare(self.db,dict(question=question,owned_items=owned,**kw))
    def test_exact_owned_duplicates_and_language_are_separate(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=self.compare([dict(item_id='a',card_id='ja:FIX:001/100:normal',quantity=2),
                             dict(item_id='b',card_id='ja:FIX:001/100:normal'),
                             dict(item_id='en',card_id='en:FIX:001/100:normal')])
        self.assertEqual(result['coverage']['asserted_owned_records'],1)
        self.assertEqual(result['owned_in_scope'][0]['quantity'],3)
        self.assertEqual([c['card_id'] for c in result['missing_catalog_records']],['ja:FIX:001/100:holo'])
        self.assertEqual(result['duplicates'][0]['entry_count'],2)
        self.assertEqual(result['outside_scope'][0]['card_id'],'en:FIX:001/100:normal')
        self.assertFalse(result['complete_missing_list_established'])
        self.assertFalse(result['ownership_assertions_verified'])
        self.assertTrue(result['comparison_complete_for_submitted_catalog_scope'])
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_unspecified_version_is_possible_owned_not_a_missing_copy(self):
        result=self.compare([dict(item_id='uncertain',language='ja',set_code='fix',collector_number='1/100')])
        self.assertEqual(result['status'],'inventory_review_needed')
        self.assertEqual(result['coverage']['possible_owned_records'],2)
        self.assertEqual(result['missing_catalog_records'],[])
        self.assertEqual(result['unresolved_items'][0]['status'],'version_evidence_needed')
        self.assertFalse(result['comparison_complete_for_submitted_catalog_scope'])
    def test_one_catalog_candidate_does_not_verify_unspecified_version(self):
        result=self.compare([dict(item_id='uncertain',language='ja',set_code='FIX',collector_number='2/100')],question='Japanese Mew cards')
        self.assertEqual(result['coverage']['asserted_owned_records'],0)
        self.assertEqual(result['coverage']['possible_owned_records'],1)
    def test_unknown_version_cannot_be_assumed_normal(self):
        result=self.compare([dict(item_id='odd',language='ja',set_code='FIX',collector_number='1/100',variant='unknown')])
        self.assertEqual(result['unresolved_items'][0]['status'],'unknown_record')
        self.assertEqual(result['coverage']['possible_owned_records'],2)
    def test_unknown_ids_and_unsupported_languages_are_retained(self):
        result=self.compare([dict(item_id='unknown',card_id='ja:FIX:999/100:holo'),
                             dict(item_id='kr',language='ko',set_code='FIX',collector_number='1/100')])
        self.assertEqual(len(result['unresolved_items']),2)
        self.assertTrue(result['coverage']['unknown_inventory_may_cover_missing_records'])
        self.assertFalse(result['complete_missing_list_established'])
    def test_missing_pages_have_no_duplicate_or_skipped_identity(self):
        a=self.compare([],limit=1);b=self.compare([],limit=1,offset=1)
        self.assertTrue(a['coverage']['has_more']);self.assertFalse(b['coverage']['has_more'])
        self.assertEqual({c['card_id'] for c in a['missing_catalog_records']+b['missing_catalog_records']},
                         {'ja:FIX:001/100:normal','ja:FIX:001/100:holo'})
    def test_market_and_cameo_scopes_cannot_produce_a_missing_list(self):
        for q in ['Cheapest Pikachu card',"Pikachu cameos in other cards' art"]:
            result=self.compare([],question=q)
            self.assertEqual(result['status'],'scope_clarification_needed')
            self.assertEqual(result['missing_catalog_records'],[])
            self.assertEqual(result['prices'],[])
    def test_invalid_items_and_quantities_fail_before_comparison(self):
        requests=[dict(item_id='a',card_id='x',quantity=True),dict(item_id='a',card_id='x',quantity=0),
                  dict(item_id='a',card_id='x',language='ja'),dict(item_id='a',title='Pikachu'),
                  dict(item_id='a',card_id='x',grade='PSA 10')]
        for row in requests:
            with self.subTest(row=row),self.assertRaises(ValueError):self.compare([row])
        with self.assertRaisesRegex(ValueError,'duplicate item_id'):self.compare([dict(item_id='a',card_id='x')]*2)
        with self.assertRaises(ValueError):self.compare([{}]*1001)

    def test_cli_compares_a_readonly_snapshot_and_does_not_create_a_missing_db(self):
        payload=Path(self.temp.name)/'inventory.json'
        payload.write_text(json.dumps(dict(question='Japanese Pikachu cards',owned_items=[])))
        root=Path(__file__).resolve().parents[1]
        command=[sys.executable,'-m','pokemon_index','--db',str(self.path),'collector-inventory',str(payload)]
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=subprocess.run(command,cwd=root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['coverage']['not_in_resolved_inventory'],2)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
        absent=Path(self.temp.name)/'absent.sqlite3';command[4]=str(absent)
        missing=subprocess.run(command,cwd=root,capture_output=True,text=True)
        self.assertNotEqual(missing.returncode,0);self.assertFalse(absent.exists())


class InventoryHTTPTests(unittest.TestCase):
    setUp=InventoryTests.setUp
    tearDown=InventoryTests.tearDown
    def request(self,server,payload,headers=None):
        req=Request('http://127.0.0.1:'+str(server.server_address[1])+'/collector-inventory',
                    data=payload,headers=headers or {'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(req,timeout=10) as r:return r.status,json.load(r)
        except HTTPError as r:
            r.close();return r.code,None
    def run_server(self,enabled,callback):
        with create_server(str(self.path),'127.0.0.1',0,enabled) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:callback(server)
            finally:server.shutdown();thread.join(timeout=5)
    def test_internal_post_works_without_writing_catalog_or_inventory(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        def call(server):
            code,result=self.request(server,json.dumps(dict(question='Japanese Pikachu cards',owned_items=[])).encode())
            self.assertEqual(code,200);self.assertEqual(result['coverage']['not_in_resolved_inventory'],2)
            self.assertFalse(result['inventory_persisted'])
            self.assertEqual(self.request(server,b'not json')[0],400)
            self.assertEqual(self.request(server,b'{}',{'Content-Type':'text/plain'})[0],400)
            self.assertEqual(self.request(server,b'{}',{'Content-Type':'application/json','Content-Length':'300000'})[0],400)
        self.run_server(True,call)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_post_route_is_absent_without_internal_api_flag(self):
        self.run_server(False,lambda server:self.assertEqual(self.request(server,b'{}')[0],404))
