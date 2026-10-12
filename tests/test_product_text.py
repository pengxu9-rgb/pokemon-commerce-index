import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import core, catalog_locale, product_text, coverage_qualification as qualification
from scripts import build_publisher_product_text as compiler
from scripts import audit_international_product_text as audit
from tests import test_coverage_qualification as held_fixture


class ProductTextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = held_fixture.CoverageQualificationTests()
        self.fixture.setUp(); self.db=self.fixture.db; self.cid=self.fixture.cid
        self.held = copy.deepcopy(self.fixture.row)
        self.caption = 'ポケモンカードゲームBW 拡張パック「ドラゴンセレクション」'
        self.held['source_product_declarations'] = [dict(name=self.caption, product_url=None)]
        self.fixture.sign(self.held)
        qualification.import_candidates(self.db, [self.held])
        page = self.held['cached_official_page']
        self.row = dict(schema=product_text.SCHEMA, candidate_id=self.held['candidate_id'], card_id=self.cid,
            publisher=dict(provider='pokemon-card-publisher', native_id='1', language='ja', url=page['url'],
                sha256=page['sha256'], revision='sha256:'+page['sha256'], retrieved_at=page['retrieved_at'],
                rights_status='existing_cached_factual_text_internal_only', metadata_license_grant=None,
                physical_distribution_region=None), products=product_text.declared_products(self.held),
            confidence=dict(source_text_correspondence=1.0, product_release_identity=None, physical_variant=None),
            scope=product_text.SCOPE, inspected_at='2026-10-11T10:57:06Z', test_only=False,
            **{k:False for k in product_text.FLAGS})
        self.sign(self.row)

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def sign(row):
        row.pop('evidence_id',None); row['evidence_id']='product-text:'+catalog_locale.digest(row); return row

    def test_idempotent_caption_retrieval_keeps_catalog_and_trading_exact(self):
        tables=[r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if r[0]!='catalog_product_text']
        before={t:[tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in tables}
        self.assertEqual(core.catalog_search_internal(self.db, 'ドラゴンセレクション ja')['total'],0)
        self.assertEqual(product_text.import_evidence(self.db,[self.row]),dict(inserted=1,unchanged=0,quarantined=0))
        self.assertEqual(product_text.import_evidence(self.db,[self.row]),dict(inserted=0,unchanged=1,quarantined=0))
        self.assertEqual(before,{t:[tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in tables})
        found=core.catalog_search_internal(self.db,'ドラゴンセレクション ja')['cards']
        self.assertEqual([c['card_id'] for c in found],[self.cid])
        self.assertEqual((found[0]['match_eligible'],found[0]['display_allowed']),(0,0))
        self.assertEqual(found[0]['publisher_product_text'][0]['scope'],product_text.SCOPE)
        self.assertEqual(qualification.status(self.db)['coverage_current_held'],1)

    def test_unicode_and_exact_language_filters(self):
        product_text.import_evidence(self.db,[self.row])
        self.assertEqual(core.catalog_search_internal(self.db,'ﾄﾞﾗｺﾞﾝｾﾚｸｼｮﾝ ja')['total'],1)
        for language in ('en','fr','ko','zh-tw'):
            self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション',language=language)['total'],0)
        self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション en')['total'],0)

    def test_repeated_number_neighbors_and_shared_art_do_not_inherit_caption(self):
        product_text.import_evidence(self.db,[self.row])
        others=[{**self.fixture.seed,**change,'attributes':{'artwork':'shared-test-only'}} for change in
                (dict(language='en'),dict(set_code='PROMO'),dict(collector_number='002/020'))]
        core.import_cards(self.db,others)
        self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション ja')['total'],1)
        for seed in others:
            cid=core.card_id(seed['language'],seed['set_code'],seed['collector_number'],seed['variant'])
            self.assertEqual(product_text.context(self.db,cid),[])
        core.import_cards(self.db,[{**self.fixture.seed,'variant':'holo_stamped_promo'}])
        self.assertEqual(product_text.context(self.db,self.cid)[0]['status'],'stale')
        self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション ja')['total'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],0)

    def test_source_reference_release_and_test_only_drift_suppress_alias(self):
        product_text.import_evidence(self.db,[self.row])
        for sql,restore in [
            ("UPDATE card SET provenance='drift'",'UPDATE card SET provenance=?'),
            ("UPDATE card_reference SET provenance='drift'",'UPDATE card_reference SET provenance=?')]:
            original=self.fixture.seed['provenance'] if 'UPDATE card SET' in sql else 'fixture-reference'
            self.db.execute(sql)
            self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション ja')['total'],0)
            self.db.execute(restore,(original,))
        self.db.execute('UPDATE card SET attributes_json=?',(json.dumps(dict(test_only=True)),))
        self.assertEqual(product_text.context(self.db,self.cid)[0]['status'],'stale')
        self.db.execute("UPDATE card SET attributes_json='{}'")
        core.import_sets(self.db,[dict(language='ja',set_code='DS',name_ja='別の商品',provenance='drift',rights_reference='fixture')])
        self.assertEqual(core.catalog_search_internal(self.db,'ドラゴンセレクション ja')['total'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_product_text').fetchone()[0],1)

    def test_forged_caption_provider_coordinate_and_license_claims_quarantine(self):
        changes=[dict(card_id='en:DS:001/020:unverified'),dict(candidate_id=[]),dict(products=[]),
            dict(products=[dict(name='Dragon Selection',publisher_link=None,link_kind='unlinked_text')]),
            dict(confidence=dict(source_text_correspondence=1.0,product_release_identity=1.0,physical_variant=1.0))]
        for change in changes:
            self.assertEqual(product_text.import_evidence(self.db,[self.sign({**self.row,**change})])['quarantined'],1)
        for key,value in [('provider','marketplace'),('native_id','2'),('sha256','a'*64),('language','en'),
                          ('metadata_license_grant','MIT'),('physical_distribution_region','JP')]:
            row=copy.deepcopy(self.row);row['publisher'][key]=value;self.sign(row)
            self.assertEqual(product_text.import_evidence(self.db,[row])['quarantined'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_product_text').fetchone()[0],0)

    def test_permissions_unknown_fields_and_malformed_payloads_fail_closed(self):
        changes=[{k:True} for k in product_text.FLAGS]+[dict(release_date='2012-01-27'),dict(publisher=[]),dict(inspected_at=[])]
        malformed=[None,[],'malformed']+[self.sign({**self.row,**change}) for change in changes]
        result=product_text.import_evidence(self.db,[*malformed,self.row])
        self.assertEqual(result,dict(inserted=1,unchanged=0,quarantined=len(malformed)))

    def test_uninspected_candidate_cannot_supply_publisher_caption(self):
        held=copy.deepcopy(self.held);held['cached_official_page']=None;self.fixture.sign(held)
        qualification.import_candidates(self.db,[held])
        row=self.sign({**self.row,'candidate_id':held['candidate_id']})
        self.assertEqual(product_text.import_evidence(self.db,[row])['quarantined'],1)

    def test_old_snapshot_remains_readable(self):
        self.db.execute('DROP TABLE catalog_product_text')
        self.assertEqual(product_text.search_aliases(self.db),{})
        self.assertEqual(product_text.context(self.db,self.cid),[])
        self.assertEqual(product_text.status(self.db)['product_text_events'],0)
        self.assertEqual(core.catalog_search_internal(self.db,'ミニリュウ')['total'],1)

    def test_audit_requires_exact_evidence_installed_in_after_snapshot(self):
        with self.assertRaisesRegex(ValueError,'complete current caption batch'):
            audit.verify_installed(self.db,[self.row])
        product_text.import_evidence(self.db,[self.row])
        audit.verify_installed(self.db,[self.row])
        bad=copy.deepcopy(self.row);bad['inspected_at']='2026-10-11T10:58:00Z';self.sign(bad)
        with self.assertRaisesRegex(ValueError,'payloads differ'):
            audit.verify_installed(self.db,[bad])

    def test_internal_cli_http_product_search_remains_readonly(self):
        from threading import Thread
        from urllib.parse import urlencode
        from urllib.request import urlopen
        from pokemon_index.cli import create_server
        product_text.import_evidence(self.db,[self.row])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.sqlite3';writer=core.connect(path);self.db.backup(writer);writer.close()
            original=path.read_bytes()
            result=subprocess.check_output(['python3','-m','pokemon_index','--db',str(path),
                'catalog-search','ドラゴンセレクション','--language','ja'],text=True)
            self.assertEqual(json.loads(result)['total'],1)
            with create_server(str(path),'127.0.0.1',0,True) as server:
                thread=Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    for language,total in [('ja',1),('en',0)]:
                        query=urlencode(dict(q='ドラゴンセレクション',language=language))
                        with urlopen(f'http://127.0.0.1:{server.server_port}/catalog-search?{query}') as response:
                            self.assertEqual(json.load(response)['total'],total)
                finally:server.shutdown();thread.join()
            self.assertEqual(path.read_bytes(),original)

    def test_cache_compiler_checks_receipts_coordinates_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory);page=cache/'card-DS.html';receipt=cache/'card-DS.receipt.json'
            raw=f"<div class='PopupSub'><li class='List_item'>{self.caption}</li></div>".encode()
            sha=hashlib.sha256(raw).hexdigest();self.held['cached_official_page']['sha256']=sha;self.fixture.sign(self.held)
            qualification.import_candidates(self.db,[self.held])
            # Remove the previous synthetic inspection only in this test fixture.
            self.db.execute('DELETE FROM catalog_coverage_candidate WHERE candidate_id<>?',(self.held['candidate_id'],))
            self.db.commit()
            page.write_bytes(raw)
            receipt.write_text(json.dumps(dict(url=self.held['cached_official_page']['url'],sha256=sha,fetched_at=self.held['cached_official_page']['retrieved_at'])))
            parsed=dict(name='ミニリュウ',numbered_entries=[dict(set_code='DS',collector_number='001/020')])
            with patch.object(compiler,'ANCHORS',(('DS','1'),)),patch.object(compiler,'parse_page',return_value=parsed):
                rows=compiler.select(self.db,cache,'2026-10-11T10:57:06Z')
                self.assertEqual(len(rows),1)
                page.write_bytes(raw+b' ')
                with self.assertRaisesRegex(ValueError,'bytes/receipt'):
                    compiler.select(self.db,cache,'2026-10-11T10:57:06Z')
                page.unlink()
                with self.assertRaises(FileNotFoundError):compiler.select(self.db,cache,'2026-10-11T10:57:06Z')


class CaptionParserTests(unittest.TestCase):
    URL='https://www.pokemon-card.com/card-search/details.php/card/1'

    def test_news_fragments_single_quotes_and_purchase_buttons_are_separate(self):
        raw=b'''<li class="List_item">footer unrelated</li><div class='Other PopupSub'>
          <li class='List_item'><a href='/info/2018/20180420_001166.html#1'>'''+'ポケモンカードゲーム GXスタートデッキ「草ラランテス」'.encode()+b'''</a></li>
          <li class='List_item'><a href='https://marketplace.example.invalid/checkout'>'''+ 'ポケモンセンターオンラインでの購入はこちら'.encode()+b'''</a></li></div>'''
        product=compiler.extract(raw,self.URL)[0]
        self.assertEqual(product['link_kind'],'official_news_article')
        self.assertEqual(product['publisher_link'],'https://www.pokemon-card.com/info/2018/20180420_001166.html#1')
        self.assertNotIn('marketplace',json.dumps(product))

    def test_outside_popup_duplicate_nested_missing_and_multiple_anchor_cases_abstain(self):
        caption='ポケモンカードゲーム テスト'.encode()
        item=b'<li class="List_item">'+caption+b'</li>'
        valid=b'<div class="PopupSub">'+item+b'</div>'
        cases=[item,valid+valid,b'<div class="PopupSub">'+item+item+b'</div>',
               b'<div class="PopupSub">'+item,b'<div class="PopupSub"><div class="PopupSub">'+item+b'</div></div>',
               b'<div class="PopupSub"><li class="List_item">'+caption+b'<a href="/ex/ds/">a</a><a href="/ex/sc/">b</a></li></div>']
        for raw in cases:
            with self.assertRaises(ValueError):compiler.extract(raw,self.URL)

    def test_product_link_namespace_never_rewrites_marketplaces_or_infers_dates(self):
        for url in ('https://marketplace.example.invalid/product','javascript:alert(1)',
                    'https://www.pokemon-card.comhttps://www.pokemoncenter-online.com/product',
                    'https://www.pokemon-card.com.evil.example.invalid/ex/ds/', '/ex/ds/'):
            with self.assertRaises(ValueError):product_text.link_kind(url)
        self.assertEqual(product_text.link_kind(None),'unlinked_text')
        self.assertEqual(product_text.link_kind('https://www.pokemon-card.com/ex/ds/'),'official_product_page')

    def test_empty_grafted_unbalanced_anchors_and_nested_plain_list_items_abstain(self):
        caption='ポケモンカードゲーム テスト'.encode()
        start=b'<div class="PopupSub"><li class="List_item">'
        end=b'</li></div>'
        cases=[start+caption+b'<a href="/ex/ds/"></a>'+end,
               start+b'<a href="/ex/ds/">'+caption+end,
               start+caption+b'<li>nested</li>'+end,
               start+caption+b'<a href="/ex/ds/">unrelated</a>'+end,
               start+b'<a href="/ex/ds/"><a href="/ex/sc/">'+caption+b'</a></a>'+end]
        for raw in cases:
            with self.assertRaises(ValueError):compiler.extract(raw,self.URL)


if __name__=='__main__':unittest.main()
