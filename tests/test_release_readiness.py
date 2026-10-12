import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import core, catalog_locale, product_text, coverage_qualification as qualification
from scripts import plan_international_release_evidence as planner
from tests import test_product_text as caption_fixture


class ReleaseReadinessTests(unittest.TestCase):
    TIME='2026-10-11T11:37:14Z'

    def setUp(self):
        self.fixture=caption_fixture.ProductTextTests();self.fixture.setUp()
        self.db=self.fixture.db;self.held=self.fixture.held;self.caption=self.fixture.row
        product_text.import_evidence(self.db,[self.caption])
        page=self.held['cached_official_page']
        self.documents={page['url']:dict(url=page['url'],sha256=page['sha256'],retrieved_at=page['retrieved_at'],
            document_file='card-DS.html',receipt_file='card-DS.receipt.json',receipt_sha256='e'*64,
            rights_status='existing_cached_evidence_no_display_grant')}

    def tearDown(self):self.fixture.tearDown()

    def add_held(self,number='002/020',native='2',code='DS',language='ja',variant='unverified',products=None):
        source=copy.deepcopy(self.held['source']);source['native_id']=f'data_jp/{code}/{native}.json';source['language']=language
        seed={**self.fixture.fixture.seed,'set_code':code,'collector_number':number,'language':language,'variant':variant,
              'provenance':f"ptcg-database:{source['revision']}:{source['native_id']}:sha256:{source['sha256']}"}
        core.import_cards(self.db,[seed])
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id=native,set_code=code,
            collector_number=number,name=seed['name'],provenance='fixture-reference',rights_reference='fixture')])
        identity=catalog_locale.snapshot(self.db,core.card_id(language,code,number,variant))
        held={**copy.deepcopy(self.held),'identity':identity,'source':source,'cached_official_page':None,
            'coordinate_snapshot':qualification.coordinate_snapshot(self.db,identity),
            'coordinate_references':qualification.references_snapshot(self.db,identity),
            'release_snapshot':qualification.release_snapshot(self.db,identity),'numbering_scope':f'provisional:{language}:{code}'}
        if products is not None:held['source_product_declarations']=products
        self.fixture.fixture.sign(held);qualification.import_candidates(self.db,[held]);return held

    def plan(self,rows=None,captions=None,documents=None):
        return planner.assemble(self.db,rows if rows is not None else [self.held],
            captions if captions is not None else [self.caption],documents if documents is not None else self.documents,self.TIME)

    def test_exact_caption_anchor_plan_is_deterministic_and_preserves_all_tables(self):
        original={r[0]:[tuple(x) for x in self.db.execute('SELECT * FROM '+r[0])] for r in
                  self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        first=self.plan();self.assertEqual(first,self.plan())
        self.assertEqual(first['summary']['prioritized_caption_anchors'],1)
        self.assertIsNone(first['requests'][0]['document_url'])
        self.assertIsNone(first['subjects'][0]['release_date'])
        for name,rows in original.items():self.assertEqual(rows,[tuple(x) for x in self.db.execute('SELECT * FROM '+name)])

    def test_uncached_provider_declaration_is_not_a_checked_caption(self):
        held=self.add_held();report=self.plan([held],[],{})
        self.assertEqual(report['summary']['by_request_kind'],dict(exact_coordinate_publisher_page=1,product_release_document=1))
        need=next(r for r in report['requests'] if r['kind']=='product_release_document')
        self.assertEqual(need['subject_bindings'][0]['caption_status'],'provider_declaration_only')
        self.assertIsNone(need['document_url'])
        self.assertEqual(report['subjects'][0]['publisher_card_url'],'https://www.pokemon-card.com/card-search/details.php/card/2')

    def test_shared_caption_work_group_keeps_each_exact_coordinate_and_no_alias_transfer(self):
        second=self.add_held();report=self.plan([self.held,second],[self.caption])
        need=next(r for r in report['requests'] if r['kind']=='product_release_document')
        self.assertEqual({r['card_id'] for r in need['subject_bindings']},{self.held['identity']['card_id'],second['identity']['card_id']})
        self.assertFalse(need['release_binding_verified'])
        result=core.catalog_search_internal(self.db,'ドラゴンセレクション',language='ja')
        self.assertEqual([r['card_id'] for r in result['cards']],[self.held['identity']['card_id']])

    def test_same_number_in_different_set_keeps_separate_unknown_product_requests(self):
        second=self.add_held(number='001/020',code='SC');report=self.plan([self.held,second],[self.caption])
        needs=[r for r in report['requests'] if r['kind']=='product_release_document']
        self.assertEqual(len(needs),2)
        self.assertEqual({r['selector']['provisional_set_code'] for r in needs},{'DS','SC'})

    def test_fragment_dedup_saves_document_work_without_merging_caption_bindings(self):
        first=self.add_held(native='2',number='002/020',products=[dict(name='ポケモンカードゲーム 草',product_url='https://www.pokemon-card.com/info/2018/20180420_001166.html#1')])
        second=self.add_held(native='3',number='003/020',products=[dict(name='ポケモンカードゲーム 炎',product_url='https://www.pokemon-card.com/info/2018/20180420_001166.html#2')])
        report=self.plan([first,second],[],{})
        needs=[r for r in report['requests'] if r['kind']=='product_release_document']
        self.assertEqual(len(needs),1)
        self.assertEqual({r['publisher_link'].rsplit('#',1)[1] for r in needs[0]['subject_bindings']},{'1','2'})
        self.assertTrue(all(r['caption_status']=='provider_declaration_only' for r in needs[0]['subject_bindings']))

    def test_newly_cached_release_document_still_requires_review(self):
        url='https://www.pokemon-card.com/info/2018/20180420_001166.html'
        held=self.add_held(products=[dict(name='ポケモンカードゲーム 草',product_url=url+'#1')])
        report=self.plan([held],[],{url:dict(url=url,sha256='a'*64,retrieved_at=self.TIME)})
        need=next(r for r in report['requests'] if r['kind']=='product_release_document')
        self.assertEqual(need['cache_status'],'cached_needs_separate_review')
        self.assertFalse(need['release_binding_verified']);self.assertIsNone(report['subjects'][0]['release_date'])

    def test_duplicate_and_non_japanese_subjects_abstain(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):self.plan([self.held,self.held])
        foreign=self.add_held(language='en')
        with self.assertRaisesRegex(ValueError,'non-Japanese'):self.plan([foreign],[])

    def test_reference_shared_by_foil_siblings_is_not_silently_assigned(self):
        second=self.add_held(number='001/020',native='1',variant='foil-stamp')
        first=copy.deepcopy(self.held);first['coordinate_snapshot']=qualification.coordinate_snapshot(self.db,first['identity'])
        first['cached_official_page']=None;self.fixture.fixture.sign(first);qualification.import_candidates(self.db,[first])
        with self.assertRaisesRegex(ValueError,'reference collides'):self.plan([first,second],[])

    def test_stale_or_uninstalled_source_and_caption_evidence_abstain(self):
        self.db.execute('DELETE FROM catalog_product_text')
        with self.assertRaisesRegex(ValueError,'installed caption'):self.plan()
        self.db.execute('DELETE FROM catalog_coverage_candidate')
        with self.assertRaisesRegex(ValueError,'installed held'):self.plan(captions=[])
        qualification.import_candidates(self.db,[self.held])
        self.db.execute("UPDATE card SET provenance='changed'")
        with self.assertRaisesRegex(ValueError,'identity snapshot'):self.plan(captions=[])

    def test_permission_forgery_and_missing_cached_anchor_abstain(self):
        bad=copy.deepcopy(self.held);bad['purchase_allowed']=True;self.fixture.fixture.sign(bad)
        with self.assertRaisesRegex(ValueError,'cannot grant'):self.plan([bad],[])
        with self.assertRaisesRegex(ValueError,'absent or differs'):self.plan(documents={})

    def test_namespace_never_rewrites_or_follows_merchant_urls(self):
        for url in ['https://www.pokemon-card.com.evil.invalid/info/x','http://www.pokemon-card.com/info/x',
                    'https://merchant.invalid/product','https://www.pokemon-card.comhttps://www.pokemoncenter-online.com/product',
                    'https://www.pokemon-card.com/info/x?merchant=1']:
            with self.assertRaises(ValueError):planner.document_url(url)
        self.assertEqual(planner.document_url('https://www.pokemon-card.com/info/2018/20180420_001166.html#1'),
                         'https://www.pokemon-card.com/info/2018/20180420_001166.html')

    def test_cache_hash_redirect_collision_and_path_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory);raw=b'<p>authorized offline fixture</p>'
            url='https://www.pokemon-card.com/ex/test/index.html'
            page=cache/'test.html';page.write_bytes(raw)
            receipt=cache/'test.receipt.json';record=dict(url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=self.TIME)
            receipt.write_text(json.dumps(record));original=page.read_bytes()
            self.assertEqual(planner.cache_inventory(cache)[url]['sha256'],record['sha256']);self.assertEqual(page.read_bytes(),original)
            page.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'bytes differ'):planner.cache_inventory(cache)
            page.write_bytes(raw);record['final_url']='https://merchant.invalid/product';receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'redirect differs'):planner.cache_inventory(cache)
            record.pop('final_url');receipt.write_text(json.dumps(record))
            (cache/'duplicate.receipt.json').write_text(json.dumps(record));(cache/'duplicate.html').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'multiple cache receipts'):planner.cache_inventory(cache)
            (cache/'duplicate.receipt.json').unlink();(cache/'duplicate.html').unlink()
            outside=cache.parent/(cache.name+'-outside.html');outside.write_bytes(raw)
            try:
                page.unlink();page.symlink_to(outside)
                with self.assertRaisesRegex(ValueError,'escapes'):planner.cache_inventory(cache)
            finally:outside.unlink()

    def test_partial_sale_marker_retains_no_price_and_never_infers_year_from_links(self):
        parser=planner.SaleMarker();parser.feed('<a href="/info/2018/news.html">2018</a><p class="sale"><img alt="7.13[金] 発売!!500円（+税）60枚"></p>')
        marker=parser.markers[0]
        self.assertEqual((marker['month'],marker['day']),(7,13));self.assertIsNone(marker['year']);self.assertIsNone(marker['release_date'])
        self.assertNotIn('500',json.dumps(marker));self.assertNotIn('60枚',json.dumps(marker,ensure_ascii=False))
        for alt in ['13.1[金] 発売!!','2.31[金] 発売!!','2018年7月13日発売','7.13']:
            with self.assertRaises(ValueError):planner.SaleMarker().feed(f'<p class="sale"><img alt="{alt}"></p>')
        with self.assertRaisesRegex(ValueError,'nested'):planner.SaleMarker().feed('<p class="sale"><p>nested</p></p>')

    def test_family_page_cannot_replace_exact_caption_target_or_supply_year(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory);raw='<p class="sale"><img alt="7.13[金] 発売!!500円"></p>'
            (cache/'smh.html').write_text(raw);sha=hashlib.sha256(raw.encode()).hexdigest()
            doc=dict(url=planner.SMH_URL,sha256=sha,retrieved_at=self.TIME,document_file='smh.html')
            with self.assertRaisesRegex(ValueError,'pinned'):planner.smh_family_observation(cache,{planner.SMH_URL:doc})
            with patch.object(planner,'SMH_SHA',sha):
                observation=planner.smh_family_observation(cache,{planner.SMH_URL:doc})
                self.assertFalse(observation['release_binding_verified']);self.assertIsNone(observation['observed_sale_marker']['year'])
                self.assertIn('not_exact_caption_link_target',observation['scope'])
                (cache/'smh.html').write_text(raw.replace('7.13','7.14'))
                with self.assertRaisesRegex(ValueError,'observed bytes differ'):
                    planner.smh_family_observation(cache,{planner.SMH_URL:doc})

    def test_input_change_or_added_receipt_during_inspection_abstains(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory);raw=b'<p>offline fixture</p>';page=cache/'test.html';page.write_bytes(raw)
            receipt=cache/'test.receipt.json';receipt.write_text(json.dumps(dict(url='https://www.pokemon-card.com/ex/test/',
                sha256=hashlib.sha256(raw).hexdigest(),fetched_at=self.TIME)))
            documents=planner.cache_inventory(cache)
            manifest=cache/'manifest.json';manifest.write_text('{"version":1}')
            signatures={p:planner.digest_file(p) for p in (page,receipt,manifest)}
            planner.assert_inputs_unchanged(signatures,cache,documents)
            for target in (page,receipt,manifest):
                original=target.read_bytes();target.write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError,'input changed'):
                    planner.assert_inputs_unchanged(signatures,cache,documents)
                target.write_bytes(original)
            (cache/'new.receipt.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'input changed'):
                planner.assert_inputs_unchanged(signatures,cache,documents)

    def test_cli_refuses_overwrite_and_has_no_network_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'plan.json';result=self.plan()
            args=['planner','--db','offline.sqlite3','--cache','offline-cache','--output',str(output),'--inspected-at',self.TIME]
            with patch.object(sys,'argv',args),patch.object(planner,'build',return_value=result) as build:
                planner.main();self.assertEqual(json.loads(output.read_text()),result)
                with self.assertRaises(FileExistsError):planner.main()
                self.assertEqual(build.call_count,1)


if __name__=='__main__':unittest.main()
