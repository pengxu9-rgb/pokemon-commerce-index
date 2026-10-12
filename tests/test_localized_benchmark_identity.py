"""Synthetic versioned evidence and decimal-release regressions; no approvals."""
import copy,json,unittest
from pathlib import Path
from pokemon_index import core,collector_discovery
from scripts import collector_catalog_evidence as evidence,benchmark_collector_mixed as mixed


class LocalizedBenchmarkIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');self.addCleanup(self.db.close);core.init_db(self.db)
        core.import_cards(self.db,[dict(language='en',set_code='SM3.5',collector_number='018/073',variant='normal',name='Totodile',provenance='synthetic:test-only',rights_reference='synthetic:test-only',match_eligible=True)])
        self.cid='en:SM3.5:018/073:normal'

    def test_new_evidence_version_binds_all_localization_and_hold_rows(self):
        changes=[
            ('INSERT INTO catalog_locale_evidence VALUES (?,?,?)',('synthetic-locale',self.cid,'{"test_only":true}')),
            ('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',('synthetic','en','ZZ','SM3.5','018','normal',self.cid)),
            ('INSERT INTO bilingual_concept_revision VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('synthetic-name',1,'Pokemon','合成','Synthetic name','synthetic:ja','synthetic:en','synthetic:test-only','synthetic:test-only','2026-10-01T00:00:00Z','withdrawn',None)),
            ('INSERT INTO concept_review_event VALUES (?,?,?,?,?,?,?,?)',('synthetic-review','synthetic-proposal',1,'a'*64,'uncertain','synthetic:test-only','2026-10-01T00:00:00Z','{"test_only":true}')),
            ('INSERT INTO catalog_identity_quarantine VALUES (?,?,?)',('synthetic-held','synthetic:test-only','{"test_only":true}')),
        ]
        legacy=evidence.catalog_evidence_digest(self.db)
        for statement,values in changes:
            before=evidence.catalog_evidence_digest(self.db,schema=evidence.LOCALIZED_SCHEMA)
            self.db.execute(statement,values);self.db.commit()
            self.assertNotEqual(evidence.catalog_evidence_digest(self.db,schema=evidence.LOCALIZED_SCHEMA),before)
            self.assertEqual(evidence.catalog_evidence_digest(self.db),legacy)
        with self.assertRaises(ValueError):evidence.catalog_evidence_digest(self.db,schema='unknown')

    def test_workload_versions_require_their_exact_evidence_version(self):
        p=Path(__file__).resolve().parents[1]/'tests/fixtures/collector-mixed-workload-v1.json'
        old=json.loads(p.read_text());self.assertIs(mixed.validate_workload(old),old)
        new=copy.deepcopy(old);new['schema']='pokemon.collector-mixed-workload.v2';new['catalog_evidence']['schema']=evidence.LOCALIZED_SCHEMA
        self.assertIs(mixed.validate_workload(new),new)
        for value in [dict(new,catalog_evidence=old['catalog_evidence']),dict(old,catalog_evidence=new['catalog_evidence']),dict(new,schema='unknown')]:
            with self.assertRaises(ValueError):mixed.validate_workload(value)

    def test_decimal_and_hyphen_release_codes_do_not_match_prefixes(self):
        core.import_cards(self.db,[dict(language='en',set_code=code,collector_number='018/073',variant='normal',name='Totodile',provenance='synthetic:test-only',rights_reference='synthetic:test-only',match_eligible=True) for code in ['SM3','30TH','30TH-C']])
        for alias,code in [('SM3','SM3'),('SM3.5','SM3.5')]:
            self.db.execute('INSERT INTO catalog_vocabulary VALUES (?,?,?,?,?)',('en',code,alias,'printed_code','synthetic:test-only'))
        self.db.commit()
        for query,expected in [('SM3.5 cards',{'SM3.5'}),('ＳＭ３．５ cards',{'SM3.5'}),('SM3.5.',{'SM3.5'}),('SM3 and SM3.5',{'SM3','SM3.5'}),('30TH-C cards',{'30TH-C'})]:
            self.assertEqual(collector_discovery._release_codes(self.db,collector_discovery._norm(query),['en']),expected)
        result=collector_discovery.execute(self.db,'Totodile en SM3.5 018/073')
        self.assertEqual([row['card_id'] for row in result['cards']],[self.cid])


if __name__=='__main__':unittest.main()
