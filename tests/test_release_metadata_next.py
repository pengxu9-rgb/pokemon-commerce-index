import copy,json,sqlite3,unittest
from pokemon_index import core,supported_catalog

class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='S3',collector_number='001/100',variant='unverified',name='テスト',provenance='fixture-card',rights_reference='fixture')])
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='12345',set_code='S3',collector_number='001/100',name='テスト',provenance='fixture-ref',rights_reference='fixture')])
        self.row=dict(schema='pokemon.catalog-release-metadata.v1',language='ja',set_code='S3',name='ムゲンゾーン',release_date=None,date_scope='unknown_or_multiple_product_dates',original_release=None,original_name=None,source_provenance='official-release:sha256:'+'a'*64,official_url='https://www.pokemon-card.com/ex/s3/index.html',official_page_sha256='a'*64,scope_snapshot=supported_catalog.release_scope_snapshot(self.db,'ja','S3'),coordinate_reference=dict(native_id='12345',collector_number='001/100',provenance='fixture-ref',official_url='https://www.pokemon-card.com/card-search/details.php/card/12345',official_page_sha256='b'*64,product_href='/ex/s3/',product_link_text='拡張パック「ムゲンゾーン」'),physical_finish_verified=False,price_comparable=False,automatic_offer_join_allowed=False,display_allowed=False)
    def tearDown(self):self.db.close()
    def test_unknown_date_stays_unknown_and_import_is_idempotent(self):
        supported_catalog.import_release_metadata(self.db,[self.row]);supported_catalog.import_release_metadata(self.db,[self.row])
        r=self.db.execute('SELECT * FROM catalog_set_localized').fetchone()
        self.assertEqual(r['name'],'ムゲンゾーン');self.assertIsNone(r['release_date']);self.assertFalse(r['display_allowed'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_release_evidence').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT match_eligible FROM card').fetchone()[0],0)
    def test_positive_permission_forgery_rolls_back_batch(self):
        forged=copy.deepcopy(self.row);forged['price_comparable']=True
        with self.assertRaisesRegex(ValueError,'widen'):supported_catalog.import_release_metadata(self.db,[self.row,forged])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_release_evidence').fetchone()[0],0)
    def test_numbering_scope_drift_and_mixed_product_codes_fail(self):
        core.import_cards(self.db,[dict(language='ja',set_code='S3',collector_number='001/048',name='混合',variant='unverified',provenance='fixture-second',rights_reference='fixture')])
        for snap in [self.row['scope_snapshot'],supported_catalog.release_scope_snapshot(self.db,'ja','S3')]:
            bad=copy.deepcopy(self.row);bad['scope_snapshot']=snap
            with self.assertRaisesRegex(ValueError,'stale or combines'):supported_catalog.import_release_metadata(self.db,[bad])
    def test_exact_reference_or_product_link_drift_fails(self):
        for field,value in [('provenance','changed'),('product_href','/ex/s2/'),('product_link_text','別の商品')]:
            bad=copy.deepcopy(self.row);bad['coordinate_reference'][field]=value
            with self.assertRaises(ValueError):supported_catalog.import_release_metadata(self.db,[bad])
    def test_name_date_scope_and_namespace_are_not_inferred(self):
        for mutation in [dict(name='別の商品'),dict(language='en'),dict(release_date='2020-06-05'),dict(date_scope='copy_date')]:
            bad={**self.row,**mutation}
            with self.assertRaises(ValueError):supported_catalog.import_release_metadata(self.db,[bad])
        supported_catalog.import_release_metadata(self.db,[self.row])
        for alias in ['S-3','S3a','SV3']:
            with self.assertRaisesRegex(ValueError,'printed code'):supported_catalog.import_vocabulary(self.db,[dict(language='ja',set_code='S3',alias=alias,alias_kind='printed_code',evidence=self.row)])

if __name__=='__main__':unittest.main()
