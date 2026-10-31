"""Offline regressions for independently reproduced R1/R3/R4 defects."""
from pathlib import Path
import copy,sys,threading,unittest
from datetime import timedelta
from unittest.mock import patch
sys.dont_write_bytecode=True
from pokemon_index.psa_shared import SharedPSA
from pokemon_index.psa_cert import PSACertClient
from pokemon_index.commerce_loop import CommerceLoop,CommerceError
from pokemon_index.certificate_evidence import CertificateReader
from pokemon_index.approved_sources import ApprovedSources
from pokemon_index.marketplace_crawl import Crawler
from pokemon_index.dispatch_budget import DispatchBudget
from pokemon_index.source_readiness import source_readiness
from tests.test_commerce_loop import Clock,Producer,CARD
from tests.test_psa_cert import PAYLOAD,TOKEN
from tests.test_psa_strategy import MemoryCAS

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.store=MemoryCAS();self.calls=[]
        for name in ['socket.create_connection','socket.socket.connect','socket.getaddrinfo']:
            p=patch(name,side_effect=AssertionError('offline only'));p.start();self.addCleanup(p.stop)
    def co(self,**kw):
        args=dict(namespace='review-account',window_start=self.clock(),window_end=(self.clock.instant+timedelta(hours=1)).isoformat(),limit=4,purchase_reserve=4)
        args.update(kw);return SharedPSA(self.store,**args)
    def api(self,url,**kw):
        number=url.rsplit('/',1)[1];self.calls.append(number);value=copy.deepcopy(PAYLOAD);value['PSACert']['CertNumber']=number
        return dict(status=200,body=value)
    def setup_offer(self,claim=None,raw=False):
        producer=Producer(self.clock)
        if claim:producer.row['certificate_number_claim']=claim
        if raw:producer.row.update(title='Pikachu raw card',grade_company='RAW',grade_value=None)
        loop=CommerceLoop(producer,now=self.clock,psa_client=PSACertClient(token=TOKEN,allow_live=True,transport=self.api,coordinator=self.co(),now=self.clock))
        offer=loop.research('owner',dict(card_id=CARD,query='Pikachu',platforms=['mercari']))['offers'][0]
        request=dict(card_id=CARD,offer_id=offer['offer_id'],expected_observed_at=offer['observed_at'],expected_price_minor=offer['price_minor'],currency=offer['currency'])
        return loop,offer,request
    def test_selection_without_number_or_non_psa_cannot_unlock_reserve(self):
        for raw,claim in [(False,None),(True,None),(True,'00001234')]:
            with self.subTest(raw=raw,claim=claim):
                self.store=MemoryCAS();loop,o,p=self.setup_offer(claim,raw);loop.select('owner',p)
                for n in ['00001234','11111111','22222222']:
                    if claim and n!=claim:
                        with self.assertRaises(CommerceError):loop.psa('owner',dict(offer_id=o['offer_id'],certificate_number=n))
                    else:self.assertEqual(loop.psa('owner',dict(offer_id=o['offer_id'],certificate_number=n))['verification']['reason'],'purchase_quota_reserved')
                self.assertEqual(self.calls,[])
    def test_exact_retained_psa_number_can_use_reserve_once_despite_reselection(self):
        loop,o,p=self.setup_offer('00001234');loop.select('owner',p)
        req=dict(offer_id=o['offer_id'],certificate_number='00001234')
        self.assertEqual(loop.psa('owner',req)['verification']['status'],'found')
        loop.select('owner',p)
        self.assertEqual(loop.psa('owner',req)['verification']['reason'],'purchase_quota_reserved')
        self.assertEqual(self.calls,['00001234']);self.assertEqual(self.store.value['used'],1)
        with self.assertRaises(CommerceError):loop.psa('owner',dict(offer_id=o['offer_id'],certificate_number='11111111'))
    def test_failed_reserved_dispatch_is_not_refunded_or_reenabled_on_another_replica(self):
        co=self.co();lease=co.acquire('00001234',now=self.clock,purpose='purchase');self.assertEqual(lease['status'],'admitted')
        self.assertTrue(co.finish(lease,None,now=self.clock))
        self.assertEqual(self.co().acquire('00001234',now=self.clock,purpose='purchase')['status'],'purchase_quota_reserved')
        self.assertEqual(self.store.value['used'],1)
    def test_repeat_purchase_can_use_ordinary_allowance_but_not_spend_reserve(self):
        co=self.co(purchase_reserve=2)
        for _ in range(2):
            lease=co.acquire('00001234',now=self.clock,purpose='purchase');self.assertEqual(lease['status'],'admitted');self.assertTrue(co.finish(lease,None,now=self.clock))
        self.assertEqual(co.acquire('00001234',now=self.clock,purpose='purchase')['status'],'purchase_quota_reserved')
        self.assertEqual(self.store.value['used'],2)
    def test_reordered_request_entries_are_not_clock_rollback(self):
        entered,release=threading.Event(),threading.Event();original=self.store.read;results={};first=self.clock()
        def delayed():
            if threading.current_thread().name=='earlier':entered.set();self.assertTrue(release.wait(2))
            return original()
        self.store.read=delayed;co=self.co(purchase_reserve=0)
        thread=threading.Thread(name='earlier',target=lambda:results.update(early=co.acquire('11111111',now=first)))
        thread.start();self.assertTrue(entered.wait(1));self.clock.instant+=timedelta(milliseconds=50)
        results['late']=co.acquire('22222222',now=self.clock);release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(results['early']['status'],'admitted');self.assertEqual(results['late']['status'],'admitted');self.assertEqual(self.store.value['used'],2)
    def test_time_is_resampled_after_slow_read_and_cas_conflict(self):
        co=self.co(purchase_reserve=0);original=self.store.read
        def slow_read():self.clock.advance(3601);return original()
        self.store.read=slow_read
        self.assertEqual(co.acquire('11111111',now=self.clock)['status'],'quota_window_closed');self.assertIsNone(self.store.value)
        self.clock.advance(-3601);self.store.read=original
        def lost_write(generation,state):self.clock.advance(3601);return False
        self.store.write=lost_write
        self.assertEqual(co.acquire('11111111',now=self.clock)['status'],'quota_window_closed');self.assertIsNone(self.store.value)
    def test_earlier_delayed_client_accepts_a_newer_shared_cache_fill(self):
        entered,release=threading.Event(),threading.Event();original=self.store.read;responses={}
        co=self.co(purchase_reserve=0,cache_seconds=30,cache_approval='offline-review')
        def delayed():
            if threading.current_thread().name=='earlier-client':entered.set();self.assertTrue(release.wait(2))
            return original()
        self.store.read=delayed
        def client():return PSACertClient(token=TOKEN,allow_live=True,transport=self.api,coordinator=co,now=self.clock)
        thread=threading.Thread(name='earlier-client',target=lambda:responses.update(earlier=client().lookup('00001234')))
        thread.start();self.assertTrue(entered.wait(1));self.clock.instant+=timedelta(milliseconds=50)
        responses['later']=client().lookup('00001234');release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(responses['earlier']['status'],'found');self.assertTrue(responses['earlier']['cached'])
        self.assertEqual(len(self.calls),1);self.assertEqual(self.store.value['used'],1)
    def test_large_midwindow_clock_rollback_fails_without_reset(self):
        co=self.co(purchase_reserve=0);self.clock.advance(10)
        self.assertEqual(co.acquire('11111111',now=self.clock)['status'],'admitted');self.clock.advance(-2)
        self.assertEqual(co.acquire('22222222',now=self.clock)['status'],'shared_store_unavailable');self.assertEqual(self.store.value['used'],1)
    def test_cached_client_uses_effective_time_but_still_checks_final_expiry_and_rollback(self):
        for delta in [None,31,-2]:
            with self.subTest(delta=delta):
                self.clock=Clock();self.store=MemoryCAS();co=self.co(purchase_reserve=0,cache_seconds=30,cache_approval='offline-review')
                self.clock.advance(10);self.clock.instant+=timedelta(milliseconds=500)
                def client():return PSACertClient(token=TOKEN,allow_live=True,transport=self.api,coordinator=co,now=self.clock)
                self.assertEqual(client().lookup('00001234')['status'],'found')
                if delta is None:self.clock.instant-=timedelta(milliseconds=500)
                cached=client()
                if delta is not None:
                    original=cached._record
                    def moving(*a,**kw):value=original(*a,**kw);self.clock.advance(delta);return value
                    cached._record=moving
                result=cached.lookup('00001234')
                self.assertEqual(result['status'],'found' if delta is None else 'unavailable')
                if delta is None:self.assertTrue(result['cached'])
    def test_photo_revocation_filters_detached_snapshot_and_keeps_independent_text_claim(self):
        for claim in [None,'11111111']:
            with self.subTest(claim=claim):
                producer=Producer(self.clock);photo='https://static.mercdn.net/item/detail/orig/photos/m1001_1.jpg'
                producer.row['listing_photos']=[dict(url=photo,role='listing_photo',listing_url=producer.row['url'],evidence_ref='offline-photo',observed_at=self.clock())]
                if claim:producer.row['certificate_number_claim']=claim
                budget=DispatchBudget(max_requests=40,seconds=300)
                crawler=Crawler(allow_network=True,authorized_sources=['mercari'],dispatch_budget=budget)
                sources=ApprovedSources(policies={'mercari':dict(mode='crawl_only',api_approved=False,crawl_approved=True,access_approval='offline',photo_display_approved=True,partner_handoff_allowed=False)},budget=budget,crawler=crawler,enabled=True)
                reader=CertificateReader(enabled=True,budget=budget,available=lambda:True,fetch=lambda *a,**k:b'fake-photo',ocr=lambda _:[('00001234',99)],now=self.clock)
                loop=CommerceLoop(sources,now=self.clock,certificate_reader=reader)
                with patch.object(Crawler,'search',lambda self,source,query,limit:producer.search(source,query,limit)|{'source':source}):
                    offer=loop.research('owner',dict(card_id=CARD,query='Pikachu',platforms=['mercari']))['offers'][0]
                payload=dict(card_id=CARD,offer_id=offer['offer_id'],expected_observed_at=offer['observed_at'],expected_price_minor=offer['price_minor'],currency=offer['currency'])
                def revoke(crawler):
                    with crawler._revocation_lock:crawler.policies['mercari']['photo_display_approved']=False
                    return source_readiness(crawler)
                with patch('pokemon_index.source_readiness.source_readiness',revoke):result=loop.read_certificate('owner',payload)
                self.assertEqual(result['offer']['listing_photos'],[])
                self.assertTrue(all(c['basis']=='seller_text' and c['photo_url'] is None for c in result['evidence']['candidates']))
                self.assertEqual([c['number'] for c in result['evidence']['candidates']],[claim] if claim else [])
                self.assertEqual(result['evidence']['status'],'candidate_found' if claim else 'number_not_read')

if __name__=='__main__':unittest.main()
