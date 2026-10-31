"""No external network: quota/cache races and retained-photo OCR boundaries."""
from pathlib import Path
import copy,json,sys,threading,time,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from pokemon_index.psa_shared import SharedPSA,StoreUnavailable
from pokemon_index.psa_cert import PSACertClient
from pokemon_index.psa_gcs import GCSStore,configure
from pokemon_index.certificate_evidence import CertificateReader,dimensions,fetch_photo,tesseract
from pokemon_index.commerce_loop import CommerceLoop,CommerceError
from tests.test_psa_cert import Clock,PAYLOAD,TOKEN,CERT

class MemoryCAS:
    def __init__(self):self.value=None;self.generation=0;self.lock=threading.Lock();self.fail=False
    def read(self):
        with self.lock:
            if self.fail:raise StoreUnavailable()
            return (str(self.generation),copy.deepcopy(self.value)) if self.value else None
    def write(self,generation,value):
        with self.lock:
            if self.fail:raise StoreUnavailable()
            if generation!=str(self.generation):return False
            self.value=copy.deepcopy(value);self.generation+=1;return True

class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.store=MemoryCAS();self.calls=[]
        for name in ['socket.create_connection','socket.socket.connect','socket.getaddrinfo']:
            p=patch(name,side_effect=AssertionError('offline tests only'));p.start();self.addCleanup(p.stop)
    def coordinator(self,**kw):
        config=dict(namespace='offline-account',window_start=self.clock(),window_end=(self.clock.instant+timedelta(days=1)).isoformat(),limit=8,purchase_reserve=2,cache_seconds=30,cache_approval='offline-approved-policy')
        config.update(kw);return SharedPSA(self.store,**config)
    def transport(self,url,**kw):
        self.calls.append(url);value=copy.deepcopy(PAYLOAD);value['PSACert']['CertNumber']=url.rsplit('/',1)[1]
        return dict(status=200,body=value)
    def client(self,coordinator=None,transport=None):return PSACertClient(token=TOKEN,allow_live=True,transport=transport or self.transport,now=self.clock,coordinator=coordinator or self.coordinator())
    def test_real_transport_requires_shared_quota_and_disabled_config_reads_nothing(self):
        self.assertIsNone(configure({'PSA_SHARED_BUCKET':'unapproved'},enabled=False))
        client=PSACertClient(token=TOKEN,allow_live=True)
        self.assertEqual(client.lookup(CERT)['reason'],'shared_store_unconfigured');self.assertFalse(client.configured())
    def test_cache_is_shared_between_clients_but_offer_comparisons_are_not(self):
        a=self.client().lookup(CERT,expected={'grade':'10'});self.assertEqual(a['comparison']['status'],'matched')
        b=self.client().lookup(CERT,expected={'grade':'9'});self.assertTrue(b['cached']);self.assertEqual(b['status'],'mismatch')
        c=self.client().lookup(CERT);self.assertEqual(c['comparison']['status'],'not_compared');self.assertEqual(len(self.calls),1)
        cached=next(iter(self.store.value['cache'].values()))['value'];self.assertEqual(cached['comparison']['status'],'not_compared');self.assertNotIn(TOKEN,json.dumps(self.store.value))
    def test_local_rate_denial_does_not_spend_global_allowance_but_cache_still_works(self):
        co=self.coordinator();client=PSACertClient(token=TOKEN,allow_live=True,transport=self.transport,now=self.clock,coordinator=co,max_requests=1)
        client.lookup(CERT);self.assertEqual(self.store.value['used'],1)
        self.assertEqual(client.lookup('11111111')['reason'],'lookup_rate_limited')
        self.assertEqual(self.store.value['used'],1);self.assertEqual(len(self.calls),1)
        self.assertTrue(client.lookup(CERT)['cached']);self.assertEqual(self.store.value['used'],1)
    def test_unapproved_persistent_caching_is_off_and_does_not_fall_back_to_local_cache(self):
        c=self.client(self.coordinator(cache_seconds=0,cache_approval=None));c.lookup(CERT);c.lookup(CERT)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.store.value['cache'],{})
        with self.assertRaises(ValueError):self.coordinator(cache_approval=None)
    def test_cache_expiration_is_not_extended_by_new_clients(self):
        coordinator=self.coordinator();a=self.client(coordinator).lookup(CERT)
        self.assertEqual(datetime.fromisoformat(a['expires_at'])-self.clock.instant,timedelta(seconds=30))
        self.clock.advance(31);b=self.client(coordinator).lookup(CERT);self.assertFalse(b['cached']);self.assertEqual(len(self.calls),2)
    def test_shortlist_cannot_spend_purchase_reserve_and_failures_still_count(self):
        co=self.coordinator(limit=4,purchase_reserve=2,cache_seconds=0)
        def denied(url,**kw):self.calls.append(url);return {'status':429,'body':b''}
        for n in range(2):self.assertEqual(self.client(co,denied).lookup(str(12345678+n))['reason'],'provider_rate_limited')
        self.assertEqual(self.client(co).lookup(CERT)['reason'],'purchase_quota_reserved')
        self.client(co).lookup('11111111',priority='purchase');self.client(co).lookup('22222222',priority='purchase')
        self.assertEqual(self.client(co).lookup('33333333',priority='purchase')['reason'],'quota_exhausted');self.assertEqual(len(self.calls),4)
    def test_same_certificate_concurrency_dispatches_once(self):
        entered=threading.Event();release=threading.Event();co=self.coordinator();responses=[]
        def slow(*a,**k):entered.set();release.wait(2);return self.transport(*a,**k)
        thread=threading.Thread(target=lambda:responses.append(self.client(co,slow).lookup(CERT)));thread.start();self.assertTrue(entered.wait(1))
        busy=self.client(co).lookup(CERT);self.assertEqual(busy['reason'],'lookup_busy');release.set();thread.join(2)
        self.assertEqual(len(self.calls),1);self.assertTrue(self.client(co).lookup(CERT)['cached'])
    def test_concurrent_clients_share_account_limit(self):
        co=self.coordinator(limit=5,purchase_reserve=2,cache_seconds=0);results=[];barrier=threading.Barrier(20)
        def run(n):barrier.wait();results.append(self.client(co).lookup(str(12345000+n)))
        threads=[threading.Thread(target=run,args=(n,)) for n in range(20)]
        for t in threads:t.start()
        for t in threads:t.join(3)
        self.assertEqual(len(self.calls),3);self.assertEqual(self.store.value['used'],3)
    def test_store_failure_never_uses_a_process_local_cached_record(self):
        client=self.client();client.lookup(CERT);self.store.fail=True
        r=client.lookup(CERT);self.assertEqual(r['reason'],'shared_store_unavailable');self.assertIsNone(r['record']);self.assertEqual(len(self.calls),1)
    def test_active_window_cannot_be_reset_by_a_different_replica_configuration(self):
        self.client().lookup(CERT)
        self.assertEqual(self.client(self.coordinator(limit=9)).lookup('11111111')['reason'],'shared_store_unavailable');self.assertEqual(self.store.value['used'],1)
    def test_clock_rollback_and_expired_windows_do_not_reset_quota(self):
        co=self.coordinator();self.client(co).lookup(CERT);self.clock.advance(-1)
        self.assertEqual(self.client(co).lookup(CERT)['reason'],'quota_window_closed')
        self.clock.advance(86402);self.assertEqual(self.client(co).lookup(CERT)['reason'],'quota_window_closed');self.assertEqual(self.store.value['used'],1)
    def test_stale_inflight_result_is_not_cached_and_credit_is_not_refunded(self):
        co=self.coordinator()
        def slow(*a,**kw):value=self.transport(*a,**kw);self.clock.advance(91);return value
        self.assertEqual(self.client(co,slow).lookup(CERT)['reason'],'shared_store_unavailable');self.assertEqual(self.store.value['used'],1);self.assertEqual(self.store.value['cache'],{})
    def test_corrupted_shared_record_does_not_gain_a_badge_or_leak_a_token(self):
        co=self.coordinator();self.client(co).lookup(CERT);key=next(iter(self.store.value['cache']))
        self.store.value['cache'][key]['value']['record']['subject']=TOKEN
        r=self.client(co).lookup(CERT);self.assertIsNone(r['record']);self.assertNotIn(TOKEN,json.dumps(r));self.assertEqual(len(self.calls),1)
    def test_gcs_uses_generation_preconditions_and_never_retries_unknown_writes(self):
        calls=[]
        def io(url,**kw):
            calls.append((url,kw));return (200,{'generation':'7','size':'10'}) if 'fields=generation,size' in url else (200,{'schema':'offline'}) if 'alt=media' in url else (412,None)
        store=GCSStore('offline-bucket','psa-private/v1/'+'a'*64+'.json',io=io,token=lambda:'offline-gcs-token')
        self.assertEqual(store.read(),('7',{'schema':'offline'}));self.assertFalse(store.write('7',{}));self.assertIn('ifGenerationMatch=7',calls[-1][0]);self.assertEqual(len(calls),3)
    def test_unknown_storage_commit_outcome_never_dispatches_psa(self):
        original=self.store.write
        def uncertain(g,v):original(g,v);raise StoreUnavailable()
        self.store.write=uncertain
        self.assertEqual(self.client().lookup(CERT)['reason'],'shared_store_unavailable');self.assertEqual(self.calls,[]);self.assertEqual(self.store.value['used'],1)

def offer():
    return dict(offer_id='retained-offer',source='snkrdunk',native_id='67890',url='https://snkrdunk.com/apparels/12345/used/67890',observed_at='2026-10-21T00:00:00+00:00',fresh_until='2026-10-21T00:05:00+00:00',grade={'company':'PSA','value':'10'},listing_photos=[dict(url='https://cdn.snkrdunk.com/apparel_used_listings/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/1234567.jpeg')],certificate_number_claim=None)

class ReaderTests(unittest.TestCase):
    def test_disabled_reader_never_downloads_images(self):
        with patch('socket.create_connection',side_effect=AssertionError('no network')):
            result=CertificateReader().read(offer(),authorize=lambda _:None)
        self.assertEqual(result['status'],'ocr_unavailable');self.assertFalse(result['psa_queried'])
    def reader(self,words):
        return CertificateReader(enabled=True,budget=object(),available=lambda:True,fetch=lambda *a,**k:b'offline-test-photo',ocr=lambda _:words,now=lambda:'2026-10-21T00:00:01+00:00')
    def test_ocr_candidates_preserve_zeros_and_never_promote_grade_or_authenticity(self):
        o=offer();r=self.reader([('00001234',99)]).read(o,authorize=lambda _:None)
        self.assertEqual(r['status'],'candidate_found');self.assertEqual(r['candidates'][0]['number'],'00001234');self.assertTrue(r['candidates'][0]['requires_confirmation']);self.assertFalse(r['certificate_verified']);self.assertIsNone(o['certificate_number_claim'])
    def test_conflicting_seller_and_photo_numbers_are_explicit(self):
        o=offer();o['certificate_number_claim']='12345678'
        r=self.reader([('87654321',99)]).read(o,authorize=lambda _:None);self.assertEqual(r['status'],'number_conflict')
    def test_low_confidence_unicode_long_and_malformed_numbers_are_not_guessed(self):
        r=self.reader([('12345678',84),('１２３４５６７８',99),('1'*13,99),('1234O678',99)]).read(offer(),authorize=lambda _:None)
        self.assertEqual(r['status'],'number_not_read')
    def test_revoked_photos_are_not_read(self):
        calls=[];reader=self.reader([('12345678',99)]);reader.fetch=lambda *a,**k:calls.append(a)
        def denied(_):raise ValueError('revoked')
        r=reader.read(offer(),authorize=denied);self.assertEqual(calls,[]);self.assertEqual(r['candidates'],[])
    def test_image_hosts_and_dimensions_are_checked_before_ocr(self):
        with self.assertRaises(ValueError):fetch_photo('https://127.0.0.1/x.jpg',source='snkrdunk',budget=object(),authorize=lambda:None)
        png=b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+(100).to_bytes(4,'big')+(200).to_bytes(4,'big')
        self.assertEqual(dimensions(png),(100,200))
        for body in (b'<html>login</html>',b'RIFFfake-webp'):
            with self.assertRaises(ValueError):dimensions(body)
    def test_slow_image_stream_stops_at_its_whole_http_deadline(self):
        from types import SimpleNamespace
        clock=[0];closed=[]
        class Response:
            status=200
            def getheader(self,key,default=None):return 'image/png' if key=='Content-Type' else default
            def read1(self,_):clock[0]=7;return b'partial'
        class Connection:
            def __init__(self,*a,**k):self.sock=SimpleNamespace(settimeout=lambda _:None)
            def connect(self):pass
            def request(self,*a,**k):pass
            def getresponse(self):self.sock=None;return Response()
            def close(self):closed.append(True)
        budget=SimpleNamespace(consume=lambda:None,check=lambda:60)
        with patch('pokemon_index.certificate_evidence._PinnedHTTPS',Connection),patch('pokemon_index.certificate_evidence.time.monotonic',lambda:clock[0]):
            with self.assertRaises(TimeoutError):fetch_photo(offer()['listing_photos'][0]['url'],source='snkrdunk',budget=budget,authorize=lambda:None)
        self.assertEqual(closed,[True])
    def test_tesseract_output_is_bounded_and_only_complete_high_confidence_numbers_survive(self):
        result=type('R',(),{'stdout':b'header\n5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t99.1\t00001234\n5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t40\t12345678\n'})()
        with patch('subprocess.run',return_value=result) as run,patch('pokemon_index.certificate_evidence.normalize_image',lambda b:b):
            self.assertEqual(tesseract(b'offline'),[('00001234',99.1)]);self.assertEqual(run.call_args.args[0][0],'/usr/bin/tesseract');self.assertEqual(run.call_args.kwargs['timeout'],3)

if __name__=='__main__':unittest.main()
