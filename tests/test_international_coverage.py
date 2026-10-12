import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core, catalog_locale, tcgdex_source, catalog_question_resolver_v2
from scripts import build_tcgdex_international


class InternationalCoverageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.seed = dict(language='ja', set_code='FIX', collector_number='001/100', variant='normal',
                         name='ピカチュウ', rarity=None, provenance='tcgdex:'+'a'*40+':data/FIX/001.ts:sha256:'+'b'*64,
                         rights_reference='pinned-metadata-license', display_allowed=False, match_eligible=True)
        core.import_cards(self.db, [self.seed])
        core.import_sets(self.db, [dict(language='ja', set_code='FIX', name_ja='テスト',
              provenance='fixture', rights_reference='fixture', official_card_count=100)])
        self.cid = core.card_id('ja', 'FIX', '001/100', 'normal')
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)', (self.cid,'Pokemon',None,'fixture','fixture'))
        self.db.execute('''INSERT INTO bilingual_concept_revision
            (concept_id,revision,category,name_ja,name_en,source_ja,source_en,rights_reference,reviewer,reviewed_at,status)
            VALUES ('pikachu',1,'Pokemon','ピカチュウ','Pikachu','fixture','fixture','fixture','reviewer','2026-10-11T00:00:00Z','approved')''')
        self.alias = dict(concept_id='pikachu', revision=1, name_ja='ピカチュウ', name_en='Pikachu',
                          category='Pokemon', review_event_id=None)
        self.row = dict(schema='pokemon.catalog-locale.v1', identity=catalog_locale.snapshot(self.db,self.cid),
            source=dict(provider='tcgdex', language='ja', region='JP', release_id='FIX:release1',
                native_id='data/FIX/001.ts', source_variant='normal', revision='a'*40, sha256='b'*64,
                retrieved_at=None, retrieval_status='historical_snapshot_time_not_recorded',
                inspected_at='2026-10-11T00:00:00Z', rights_reference='pinned-metadata-license', rights_status='metadata_internal_reviewed'),
            release_snapshot=dict(self.db.execute('SELECT * FROM catalog_set_localized').fetchone()),
            name_aliases=[self.alias], confidence=1.0, unresolved_conflicts=[], test_only=False,
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        self.sign(self.row)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def sign(self, row):
        row.pop('evidence_id', None)
        row['evidence_id'] = 'catalog-locale:' + catalog_locale.digest(row)
        return row

    def test_idempotent_import_and_unchanged_cards_and_references(self):
        before=[tuple(r) for r in self.db.execute('SELECT * FROM card')]
        refs=[tuple(r) for r in self.db.execute('SELECT * FROM card_reference')]
        self.assertEqual(catalog_locale.import_evidence(self.db,[self.row]),dict(inserted=1,unchanged=0,quarantined=0))
        self.assertEqual(catalog_locale.import_evidence(self.db,[self.row]),dict(inserted=0,unchanged=1,quarantined=0))
        core.import_cards(self.db,[self.seed])
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM card')])
        self.assertEqual(refs,[tuple(r) for r in self.db.execute('SELECT * FROM card_reference')])
        self.assertEqual(self.db.execute('SELECT count(*) FROM observation').fetchone()[0],0)

    def test_unicode_search_and_scoped_resolver_preserve_variants(self):
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu ja')['total'],0)
        catalog_locale.import_evidence(self.db,[self.row])
        self.assertEqual(core.catalog_search_internal(self.db,'Ｐｉｋａｃｈｕ ja')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'ピカチュウ')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu en')['total'],0)
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu',language='en')['total'],0)
        # The English language token must not match inside the alias Energy.
        changed=copy.deepcopy(self.row)
        self.db.execute("UPDATE bilingual_concept_revision SET name_en='Pikachu Energy'")
        changed['name_aliases'][0]['name_en']='Pikachu Energy';self.sign(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['inserted'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu Energy en')['total'],0)
        for language in ('de', 'es', 'it', 'fr', 'zh-tw'):
            self.assertEqual(core.catalog_search_internal(self.db,'Pikachu Energy '+language)['total'],0)
        self.db.execute("UPDATE bilingual_concept_revision SET name_en='Pikachu'")
        facts=dict(object_type='single_card', primary_goal='price_comparison', transaction_context='prospective_buy',
            seller_channel='none', identity_tokens=dict(card_names=['Pikachu'],set_name='FIX',collector_number='001/100',
              language='ja',rarity=None,finish=None,grade=None),media_state='none',language_mentions=['ja'],
              platform_refs=[],merchant_ref=None,destination=None)
        result=catalog_question_resolver_v2.resolve_question(self.db,facts)
        self.assertEqual(result['resolution']['candidate_ids'],[self.cid])
        core.import_cards(self.db,[{**self.seed,'variant':'holo'}])
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu ja')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'ピカチュウ')['total'],2)
        self.db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'")
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu ja')['total'],0)

    def test_provider_native_id_collision_and_regional_release_hold(self):
        catalog_locale.import_evidence(self.db,[self.row])
        changed=copy.deepcopy(self.row); changed['source']['region']='KR';self.sign(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        core.import_cards(self.db,[{**self.seed,'collector_number':'002/100'}])
        changed=copy.deepcopy(self.row);changed['identity']=catalog_locale.snapshot(self.db,core.card_id('ja','FIX','002/100','normal'))
        changed['name_aliases']=[];self.sign(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],1)

    def test_missing_fields_conflicts_and_permission_widening_quarantined(self):
        changes=[{'purchase_allowed':True},{'image_display_allowed':True},{'unresolved_conflicts':['variant ambiguous']},
                 {'test_only':True},{'confidence':float('nan')}]
        for change in changes:
            self.assertEqual(catalog_locale.import_evidence(self.db,[self.sign({**self.row,**change})])['quarantined'],1)
        changed=copy.deepcopy(self.row);changed['source'].pop('region');self.sign(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0],0)

    def test_shared_art_promos_stamps_repeated_numbers_never_merge(self):
        rows=[{**self.seed,'variant':v,'attributes':{'artwork':'shared-test-only'}}
              for v in ['holo','holo_first_edition','holo_stamped_promo','normal']]
        rows += [{**self.seed,'language':'en'},{**self.seed,'set_code':'PROMO','collector_number':'001/PROMO'}]
        core.import_cards(self.db,rows)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card').fetchone()[0],6)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],0)
        self.assertNotEqual(core.card_id('ja','FIX','001/100','normal'),core.card_id('en','FIX','001/100','normal'))
        core.import_cards(self.db,[{**self.seed,'variant':'unverified_source_variants','match_eligible':False}])
        changed=copy.deepcopy(self.row);changed['identity']=catalog_locale.snapshot(self.db,core.card_id('ja','FIX','001/100','unverified_source_variants'))
        self.sign(changed);self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)

    def test_third_language_test_only_unicode_and_localized_date_no_fallback(self):
        source='''const card: Card = {name: {fr: "Évoli", ja: "イーブイ"}, variants: [{type: "holo"}]};'''
        row=tcgdex_source.parse_card_source(source,set_id='TEST',official_count=100,
              path='data/Test/TEST/1.ts',revision='a'*40,language='fr')[0]
        row.update(match_eligible=False,attributes={'test_only':True})
        core.import_cards(self.db,[row])
        core.import_sets(self.db,[dict(language='fr',set_code='TEST',name='Épreuve',provenance='synthetic:test-only',rights_reference='fixture')])
        self.assertEqual(core.catalog_search_internal(self.db,'E\u0301voli fr')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'Évoli ja')['total'],0)
        meta=tcgdex_source.parse_set_metadata("const set = {id:'TEST', name:{fr:'Épreuve'},cardCount:{official:100},releaseDate:{ja:'2026-01-01'}}",'fr')
        self.assertIsNone(meta['release_date'])
        self.assertEqual(meta['name'],'Épreuve')
        with self.assertRaises(ValueError):core.import_sets(self.db,[dict(language='fr:ja',set_code='X',provenance='fixture',rights_reference='fixture')])
        with self.assertRaisesRegex(ValueError,'lacks fr name'):
            tcgdex_source.parse_card_source('const card = {name:{ja:"イーブイ"}}',set_id='TEST',official_count=100,
              path='data/Test/TEST/1.ts',revision='a'*40,language='fr')

    def test_malformed_payloads_are_quarantined_without_partial_writes(self):
        for change in ({'source':[]},{'identity':None},{'name_aliases':[None]}):
            self.assertEqual(catalog_locale.import_evidence(self.db,[self.sign({**self.row,**change})])['quarantined'],1)
        for value in ([], {}, None, ''):
            changed=copy.deepcopy(self.row);changed['identity']['card_id']=value;self.sign(changed)
            self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        for value in ([], {}, None):
            changed=copy.deepcopy(self.row);changed['source']['inspected_at']=value;self.sign(changed)
            self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        changed=copy.deepcopy(self.row);changed['name_aliases'][0]['concept_id']=[];self.sign(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db,[changed])['quarantined'],1)
        for row in (None, [], 'malformed'):
            self.assertEqual(catalog_locale.import_evidence(self.db,[row])['quarantined'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],0)

    def test_provider_namespaces_and_source_revision_staleness(self):
        catalog_locale.import_evidence(self.db,[self.row])
        seed={**self.seed,'collector_number':'002/100','provenance':self.seed['provenance'].replace('tcgdex:', 'provider_b:')}
        core.import_cards(self.db,[seed])
        row=copy.deepcopy(self.row)
        row['identity']=catalog_locale.snapshot(self.db,core.card_id('ja','FIX','002/100','normal'))
        row['source']['provider']='provider_b';row['name_aliases']=[];self.sign(row)
        self.assertEqual(catalog_locale.import_evidence(self.db,[row])['inserted'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],2)
        core.import_cards(self.db,[{**self.seed,'provenance':self.seed['provenance'].replace('a'*40,'c'*40)}])
        self.assertEqual(core.catalog_search_internal(self.db,'Pikachu ja')['total'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0],2)

    def test_checked_in_third_language_fixture_is_test_only_and_not_commerce(self):
        row=json.loads((Path(__file__).parent/'fixtures/international/fr-test-only.jsonl').read_text())
        core.import_cards(self.db,[row])
        card=core.catalog_search_internal(self.db,'Créature Démo fr')['cards'][0]
        self.assertTrue(card['attributes']['test_only'])
        self.assertEqual((card['match_eligible'],card['display_allowed']),(0,0))
        self.assertEqual(core.catalog_search_internal(self.db,'Créature Démo ja')['total'],0)

    def test_cli_explicit_language_filter(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.sqlite3'
            writer=core.connect(path);core.init_db(writer)
            core.import_cards(writer,[self.seed]);writer.close()
            result=subprocess.check_output(['python3','-m','pokemon_index','--db',str(path),
                'catalog-search','ピカチュウ','--language','en'],text=True)
            self.assertEqual(json.loads(result)['total'],0)
            result=subprocess.check_output(['python3','-m','pokemon_index','--db',str(path),
                'catalog-search','ピカチュウ','--language','ja'],text=True)
            self.assertEqual(json.loads(result)['total'],1)

    def test_http_explicit_language_filter_remains_readonly(self):
        from contextlib import closing
        from threading import Thread
        from urllib.request import urlopen
        from urllib.parse import urlencode
        from pokemon_index.cli import create_server
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.sqlite3'
            with closing(core.connect(path)) as writer:
                core.init_db(writer);core.import_cards(writer,[self.seed])
            original=path.read_bytes()
            with create_server(str(path),'127.0.0.1',0,True) as server:
                thread=Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    for language,total in [('en',0),('ja',1),('de',0)]:
                        query=urlencode(dict(q='ピカチュウ',language=language))
                        with urlopen(f'http://127.0.0.1:{server.server_port}/catalog-search?{query}') as response:
                            self.assertEqual(json.load(response)['total'],total)
                finally:server.shutdown();thread.join()
            self.assertEqual(path.read_bytes(),original)

    def test_legacy_set_code_takes_precedence_over_ambiguous_language_word(self):
        core.import_cards(self.db,[{**self.seed,'set_code':'EL'}])
        self.assertEqual(core.catalog_search_internal(self.db,'EL')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'el')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'ピカチュウ ja EL')['total'],1)
        core.import_cards(self.db,[{**self.seed,'language':'el','set_code':'OTHER','match_eligible':False}])
        self.assertEqual(core.catalog_search_internal(self.db,'EL',language='el')['total'],0)

    def test_hyphenated_card_name_is_not_a_language_tag(self):
        core.import_cards(self.db,[{**self.seed,'language':'en','name':'Ho-Oh'}])
        self.assertEqual(core.catalog_search_internal(self.db,'Ho-Oh')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'Ho-Oh en')['total'],1)
        self.assertEqual(core.catalog_search_internal(self.db,'Ho-Oh ja')['total'],0)

    def test_builder_third_language_pins_files_and_keeps_matching_disabled(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); folder=root/'data-asia/Test/SET';folder.mkdir(parents=True)
            (root/'LICENSE').write_text('SYNTHETIC TEST ONLY; NO REAL LICENSE CLAIM')
            folder.with_suffix('.ts').write_text("const set = {id:'SET',name:{fr:'Épreuve'},cardCount:{official:100},releaseDate:{fr:'2026-01-01',ja:'2025-01-01'}}")
            card=folder/'1.ts';card.write_text('const card = {name:{fr:"Créature Démo"},variants:[{type:"holo",stamp:["test-only"]}]}')
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','synthetic test only'],check=True)
            revision=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            files=[root/name for name in ('cards.jsonl','sets.jsonl','report.json','gaps.jsonl')]
            result=build_tcgdex_international.build(root,revision,['Test'],*files,language='fr',data_root='data-asia')
            self.assertEqual(result['identities'],1)
            self.assertEqual(result['match_eligible'],0)
            row=json.loads(files[0].read_text());self.assertEqual(row['language'],'fr')
            self.assertFalse(row['display_allowed']);self.assertEqual(row['variant'],'holo_test_only')
            self.assertEqual(json.loads(files[1].read_text())['release_date'],'2026-01-01')
            card.write_text(card.read_text()+' // dirty')
            with self.assertRaisesRegex(ValueError,'Git blob changed'):
                build_tcgdex_international.build(root,revision,['Test'],*[root/('new-'+p.name) for p in files],language='fr',data_root='data-asia')

    def test_pocket_and_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            import subprocess
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','synthetic test only'],check=True)
            revision=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            (root/'LICENSE').write_text('SYNTHETIC TEST ONLY')
            args=(root,revision,['Pokémon TCG Pocket'],root/'rows',root/'sets',root/'report',root/'gaps')
            with self.assertRaisesRegex(ValueError,'digital'):build_tcgdex_international.build(*args)
            with self.assertRaisesRegex(ValueError,'escapes'):build_tcgdex_international.build(root,revision,['../../outside'],*args[3:])


if __name__=='__main__':unittest.main()
