from pathlib import Path
import sys,copy,json,threading,http.client,unittest
from pokemon_index.commerce_loop import CommerceLoop,CommerceError
from pokemon_index.commerce_service import create_server
from pokemon_index.certificate_evidence import CertificateReader
from tests.test_commerce_loop import Clock,Producer,CARD
from tests.test_psa_strategy import MemoryCAS
from pokemon_index.psa_shared import SharedPSA
from pokemon_index.psa_cert import PSACertClient
from tests.test_psa_cert import PAYLOAD,TOKEN

class Journey(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.producer=Producer(self.clock);self.images=[]
        self.producer.row['listing_photos']=[dict(url='https://static.mercdn.net/item/detail/orig/photos/m1001_1.jpg',role='listing_photo',listing_url=self.producer.row['url'],evidence_ref='offline:retained-photo',observed_at=self.clock())]
        self.reader=CertificateReader(enabled=True,budget=object(),available=lambda:True,fetch=self.fetch,ocr=lambda _:[('00001234',99)],now=self.clock)
        self.loop=CommerceLoop(self.producer,now=self.clock,certificate_reader=self.reader)
        self.offer=self.loop.research('owner',dict(card_id=CARD,query='Pikachu',platforms=['mercari']))['offers'][0]
        self.payload=dict(card_id=CARD,offer_id=self.offer['offer_id'],expected_observed_at=self.offer['observed_at'],expected_price_minor=self.offer['price_minor'],currency=self.offer['currency'])
    def fetch(self,url,**kw):self.images.append(url);return b'offline-photo'
    def test_whole_reading_keeps_grade_price_and_purchase_authority_unchanged(self):
        before=copy.deepcopy(self.loop._offers)
        r=self.loop.read_certificate('owner',self.payload)
        self.assertEqual(r['evidence']['status'],'candidate_found');self.assertEqual(r['offer'],self.offer);self.assertFalse(r['evidence']['psa_queried']);self.assertFalse(r['purchasable']);self.assertFalse(r['order_created']);self.assertEqual(self.loop._offers,before);self.assertEqual(self.loop._selections,{})
    def test_wrong_owner_card_price_and_url_payload_fail_before_photo_read(self):
        for owner,edit in [('other',{}),('owner',{'card_id':'wrong'}),('owner',{'expected_price_minor':1}),('owner',{'photo_url':'https://evil.invalid/photo.jpg'}),('owner',{'priority':'purchase'})]:
            with self.assertRaises(CommerceError):self.loop.read_certificate(owner,self.payload|edit)
        self.assertEqual(self.images,[])
    def test_expired_or_replaced_listing_during_ocr_is_not_published(self):
        original=self.reader.ocr
        def late(data):self.clock.advance(301);return original(data)
        self.reader.ocr=late
        with self.assertRaises(CommerceError):self.loop.read_certificate('owner',self.payload)
    def test_psa_client_is_never_called_by_number_reading(self):
        class Denied:
            def lookup(self,*a,**k):raise AssertionError('no PSA API during image read')
        self.loop.psa_client=Denied();self.loop.read_certificate('owner',self.payload)
    def test_purchase_reserve_is_reachable_only_from_a_fresh_owner_bound_selection(self):
        from datetime import timedelta
        self.producer.row['certificate_number_claim']='00001234'
        self.offer=self.loop.research('owner',dict(card_id=CARD,query='Pikachu',platforms=['mercari']))['offers'][0]
        self.payload=dict(card_id=CARD,offer_id=self.offer['offer_id'],expected_observed_at=self.offer['observed_at'],expected_price_minor=self.offer['price_minor'],currency=self.offer['currency'])
        store=MemoryCAS();co=SharedPSA(store,namespace='offline-account',window_start=self.clock(),window_end=(self.clock.instant+timedelta(hours=1)).isoformat(),limit=2,purchase_reserve=1)
        calls=[]
        def api(*a,**kw):calls.append(a);return {'status':200,'body':copy.deepcopy(PAYLOAD)}
        self.loop.psa_client=PSACertClient(token=TOKEN,allow_live=True,transport=api,coordinator=co,now=self.clock)
        request={'offer_id':self.offer['offer_id'],'certificate_number':'00001234'}
        self.assertEqual(self.loop.psa('owner',request)['verification']['status'],'found')
        self.assertEqual(self.loop.psa('owner',request)['verification']['reason'],'purchase_quota_reserved')
        with self.assertRaises(CommerceError):self.loop.psa('owner',request|{'priority':'purchase'})
        self.loop.select('owner',self.payload)
        self.assertEqual(self.loop.psa('owner',request)['verification']['status'],'found')
        self.assertEqual(len(calls),2);self.assertEqual(store.value['used'],2)
    def test_real_read_only_http_entry_allows_ocr_but_denies_psa_orders_and_selection(self):
        server=create_server(self.loop,token='offline-private-token-at-least-24',port=0,research_only=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(operation,payload,owner='owner'):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('POST','/commerce/'+operation,body=json.dumps(payload),headers={'Authorization':'Bearer offline-private-token-at-least-24','X-Commerce-Owner':owner,'Content-Type':'application/json'})
            r=conn.getresponse();status=r.status;value=json.loads(r.read());conn.close();return status,value
        try:
            status,result=call('read-certificate',self.payload);self.assertEqual(status,200);self.assertEqual(result['evidence']['candidates'][0]['number'],'00001234')
            self.assertEqual(call('read-certificate',self.payload,owner='other')[0],409)
            for op in ['psa','select','handoff','order','payment']:self.assertEqual(call(op,{})[0],403)
        finally:server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
