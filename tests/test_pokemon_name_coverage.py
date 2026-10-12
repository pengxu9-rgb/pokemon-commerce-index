"""Offline discovery boundaries, using synthetic fixtures and frozen artifacts."""
import copy
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_coverage as compiler
from scripts import audit_pokemon_name_coverage as audit
from scripts.audit_international_coverage import facts
from scripts.qualify_international_product_documents import checked_source, git_tree

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT/audit.DIRECTORY


class NameCompilerTests(unittest.TestCase):
    def raw(self, fields=''):
        return ('const card: Card = {name: {ja: "ピカチュウ", en: "Pikachu"}, '
                'category: "Pokemon", dexId: [25], '+fields+'}; export default card;').encode()

    def test_literal_name_and_singleton_dex_are_required(self):
        self.assertEqual(compiler.metadata(self.raw())['dex_id'],25)
        self.assertEqual(compiler.metadata(self.raw())['names']['ja'],'ピカチュウ')
        for value in ('[]','[25,26]','unknown','[152]','[true]'):
            with self.subTest(value=value),self.assertRaises((ValueError,SyntaxError)):
                compiler.metadata(self.raw().replace(b'[25]',value.encode()))
        with self.assertRaises(ValueError):
            compiler.metadata(self.raw().replace(b'dexId: [25],',b''))

    def test_duplicate_category_dex_and_name_fields_are_held(self):
        for fields in ('category: "Pokemon",','dexId: [25],','name: {ja: "別名"},'):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                compiler.metadata(self.raw(fields))
        for value in ('{ja:"A", ja:"B"}','{en:"A", EN:"B"}','{ja: expression}',
                      '{ja:""}','{ja:"A"} + other','[]'):
            with self.subTest(value=value),self.assertRaises((ValueError,SyntaxError)):
                compiler.names(value)

    def test_localized_keys_unicode_and_punctuation_preserve_literal_names(self):
        result=compiler.names('{"pt-BR": "Nidoran♀", ja: "ニドラン♀", en: "Farfetch\'d"}')
        self.assertEqual(result,{'pt-br':'Nidoran♀','ja':'ニドラン♀','en':"Farfetch'd"})

    def test_full_review_is_bound_to_exact_proposal_bytes_and_all_decisions(self):
        raw=(ARTIFACT/'proposals.json').read_bytes();review=json.loads((ARTIFACT/'semantic-review.json').read_text())
        self.assertEqual(len(compiler.checked_review(raw,review)),163)
        for key,value in [('reviewer','another'),('approved_pairs',162),('decision','uncertain'),
                          ('uncertain_pairs',[1]),('rejected_pairs',[1]),('proposal_sha256','0'*64)]:
            changed={**review,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):compiler.checked_review(raw,changed)
        with self.assertRaises(ValueError):compiler.checked_review(raw+b' ',review)

    def test_colliding_full_name_proposals_cannot_be_approved(self):
        raw=(ARTIFACT/'proposals.json').read_bytes();review=json.loads((ARTIFACT/'semantic-review.json').read_text())
        pairs=json.loads(raw);pairs[1]['name_en']=pairs[0]['name_en']
        changed=json.dumps(pairs).encode();review['proposal_sha256']=hashlib.sha256(changed).hexdigest()
        with self.assertRaisesRegex(ValueError,'ambiguous'):compiler.checked_review(changed,review)

    def pool(self):
        ja=[];en=[]
        for index,code in enumerate(compiler.SETS):
            pair=dict(dex_id=index+1,name_ja='合成'+str(index),name_en='Synthetic '+str(index))
            for number in range(20):
                for variant in ('foil','stamp'):
                    ja.append((dict(card_id=f'ja:{code}:{number}:{variant}',language='ja',set_code=code,
                                    collector_number=str(number),variant=variant,name=pair['name_ja']),pair))
            en.append((dict(card_id=f'en:FIX:{index}:normal',language='en',set_code='FIX',
                            collector_number=str(index),variant='normal',name=pair['name_en']),pair))
        return ja,en

    def test_thousand_selection_retains_whole_variant_groups_and_all_fixed_sets(self):
        ja,en=self.pool();selected=compiler.choose(ja,en)
        self.assertEqual(len(selected),1025)
        self.assertEqual({c['set_code'] for c,p in selected if c['language']=='ja'},set(compiler.SETS))
        for code in compiler.SETS:
            for number in range(20):
                self.assertEqual({c['variant'] for c,p in selected if c['set_code']==code and c['collector_number']==str(number)}, {'foil','stamp'})

    def test_selection_cannot_split_groups_pad_or_substitute_sets(self):
        ja,en=self.pool()
        with patch.object(compiler,'JAPANESE_LIMIT',999),self.assertRaisesRegex(ValueError,'falls short'):
            compiler.choose(ja,en)
        with self.assertRaisesRegex(ValueError,'fixed scope'):
            compiler.choose([p for p in ja if p[0]['set_code']!=compiler.SETS[0]],en)
        with self.assertRaisesRegex(ValueError,'25 qualified'):
            compiler.choose(ja,en[:-1])

    def test_manifest_prefix_and_real_batch_have_exact_disjoint_bound_scope(self):
        manifest,bundle,rows=audit.inputs(ROOT)
        self.assertEqual(len(manifest['steps']),72);self.assertEqual(len(rows),1025)
        old=[]
        for directory in ('international-coverage-pilot-v1','international-coverage-expansion-v1','international-coverage-hundred-v1'):
            old.extend(json.loads(line)['identity']['card_id'] for line in (ROOT/'catalog'/directory/'locales.jsonl').read_text().splitlines())
        self.assertFalse(set(old)&{r['identity']['card_id'] for r in rows})
        for row in rows:
            for flag in catalog_locale.FALSE_CLAIMS:self.assertIs(row[flag],False)
            self.assertIsNone(row['source']['retrieved_at']);self.assertIsNone(row['source']['physical_distribution_region'])
        for changed in (rows[:-1],rows+[rows[0]]):
            with self.assertRaises(ValueError):audit.bounded(changed)
        changed=copy.deepcopy(rows);changed[0]['character_scope']['form_inheritance_allowed']=True
        with self.assertRaises(ValueError):audit.bounded(changed)

    def test_exclusive_artifacts_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'owned';output.mkdir();(output/'keep').write_text('other work')
            with self.assertRaises(FileExistsError):compiler.build(None,None,None,None,None,output,'invalid')
            self.assertEqual((output/'keep').read_text(),'other work')
            with self.assertRaises(FileExistsError):audit.append(None,output,None)

    def test_frozen_review_input_mismatch_prevents_artifact_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft=root/'draft';review=root/'review';output=root/'output'
            draft.write_bytes(b'[]');review.write_bytes(b'{}')
            selection=dict(proposal_sha256='0'*64,semantic_review_sha256=hashlib.sha256(b'{}').hexdigest())
            with patch.object(compiler,'compile',return_value=({},[],selection,b'fixture')):
                with self.assertRaisesRegex(ValueError,'frozen artifact inputs'):
                    compiler.build(None,None,None,draft,review,output,'2026-10-12T00:00:00Z')
            self.assertFalse(output.exists())

    def test_utf8_pinned_git_paths_and_local_bytes_are_verified_without_fetching(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory);subprocess.run(['git','init','-q'],cwd=repo,check=True)
            path='data/Pokémon GO/ニドラン♀.ts';target=repo/path;target.parent.mkdir(parents=True);target.write_bytes(self.raw())
            subprocess.run(['git','add','.'],cwd=repo,check=True)
            subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','test-only'],cwd=repo,check=True)
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
            inventory=git_tree(repo,[path],revision=revision)
            self.assertEqual(checked_source(repo,path,inventory[path]),self.raw())
            target.write_bytes(self.raw()+b' ')
            with self.assertRaises(ValueError):checked_source(repo,path,inventory[path])


class NameResolverBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;core.init_db(self.db)
        self.addCleanup(self.db.close)
        for lang in ('ja','en'):
            core.import_sets(self.db,[dict(language=lang,set_code='FIX',name='Synthetic test',official_card_count=100,
                provenance='synthetic:test-only',rights_reference='fixture')])

    def card(self,name,number,*,lang='ja',variant='normal',code='FIX'):
        path=f'data/{lang}/{code}/{number}.ts';sha=hashlib.sha256(path.encode()).hexdigest()
        card=dict(language=lang,set_code=code,collector_number=number,variant=variant,name=name,rarity=None,
            provenance='tcgdex:'+'a'*40+':'+path+':sha256:'+sha,rights_reference='fixture',display_allowed=False,match_eligible=True)
        core.import_cards(self.db,[card]);cid=core.card_id(lang,code,number,variant)
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only','fixture'))
        return cid

    def alias(self,ja,en,*,requires_binding=False):
        cid='synthetic:'+en;event='event:'+en if requires_binding else None
        if event:
            self.db.execute('INSERT INTO concept_review_event VALUES (?,?,?,?,?,?,?,?)',
                (event,cid,1,'0'*64,'approve','fixture','2026-10-12T00:00:00Z',json.dumps({'review':{'requires_card_binding':True}})))
        self.db.execute('''INSERT INTO bilingual_concept_revision VALUES (?,?, 'Pokemon',?,?,
            'synthetic-ja','synthetic-en','fixture','fixture','2026-10-12T00:00:00Z','approved',?)''',(cid,1,ja,en,event))
        return dict(concept_id=cid,revision=1,category='Pokemon',name_ja=ja,name_en=en,review_event_id=event)

    def row(self,cid,alias):
        card=catalog_locale.snapshot(self.db,cid);parts=card['provenance'].split(':')
        row=dict(schema='pokemon.catalog-locale.v1',identity=card,
            source=dict(provider='tcgdex',language=card['language'],region='ZZ',release_id='synthetic:'+card['set_code'],
                native_id=parts[2],source_variant=card['variant'],revision='a'*40,sha256=parts[-1],retrieved_at=None,
                retrieval_status='historical_snapshot_time_not_recorded',inspected_at='2026-10-12T00:00:00Z',
                rights_reference='fixture',rights_status='metadata_internal_reviewed'),
            release_snapshot=dict(self.db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                (card['language'],card['set_code'])).fetchone()),name_aliases=[alias],confidence=1,
            unresolved_conflicts=[],test_only=False,**{f:False for f in catalog_locale.FALSE_CLAIMS})
        row['evidence_id']='catalog-locale:'+catalog_locale.digest(row);return row

    def lookup(self,cid,name):
        return resolver.resolve_question(self.db,facts(dict(identity=catalog_locale.snapshot(self.db,cid)),name))

    def test_nidoran_sex_is_preserved_in_native_and_translated_coordinates(self):
        female=self.card('ニドラン♀','001/100');male=self.card('ニドラン♂','002/100')
        self.alias('ニドラン♀','Nidoran♀');self.alias('ニドラン♂','Nidoran♂')
        for cid,own,wrong in ((female,'Nidoran♀','Nidoran♂'),(male,'Nidoran♂','Nidoran♀')):
            self.assertEqual(self.lookup(cid,own)['resolution']['candidate_ids'],[cid])
            self.assertFalse(self.lookup(cid,wrong)['resolution']['candidate_ids'])
        self.assertFalse(self.lookup(female,'ニドラン♂')['resolution']['candidate_ids'])
        self.assertEqual(self.lookup(female,'Ｎｉｄｏｒａｎ♀')['resolution']['candidate_ids'],[female])

    def test_native_and_translated_uppercase_EX_never_resolve_lowercase_ex(self):
        ja=self.card('リザードンex','006/100');en=self.card('Charizard ex','006/100',lang='en')
        self.alias('リザードンex','Charizard ex')
        for cid,names in ((ja,('リザードンEX','リザードンＥＸ','Charizard EX','CHARIZARDEX','CharizardEX')),
                          (en,('Charizard EX','CHARIZARDEX','ＣＨＡＲＩＺＡＲＤＥＸ','リザードンEX'))):
            for name in names:
                with self.subTest(name=name):self.assertFalse(self.lookup(cid,name)['resolution']['candidate_ids'])
        self.assertEqual(self.lookup(ja,'Charizard ex')['resolution']['candidate_ids'],[ja])
        self.assertEqual(self.lookup(en,'リザードンex')['resolution']['candidate_ids'],[en])
        old=self.card('MewEX','004/100',lang='en')
        self.assertFalse(self.lookup(old,'Mewex')['resolution']['candidate_ids'])
        self.assertEqual(self.lookup(old,'MEWEX')['resolution']['candidate_ids'],[old])

    def test_ordinary_species_words_accept_capitals_without_appended_EX(self):
        for index,name in enumerate(('Toxapex','Calyrex')):
            cid=self.card(name,f'00{index+1}/100',lang='en')
            self.assertEqual(self.lookup(cid,name.upper())['resolution']['candidate_ids'],[cid])
            for query in (name.upper()+'EX',name+' EX',name+' ex'):
                with self.subTest(query=query):self.assertFalse(self.lookup(cid,query)['resolution']['candidate_ids'])

    def test_species_translation_does_not_inherit_owner_region_or_mechanic(self):
        cid=self.card('ピカチュウ','001/100');self.alias('ピカチュウ','Pikachu')
        for query in ("Ash's Pikachu",'Alolan Pikachu','Pikachu V','Pikachu VSTAR','Pikachu VMAX','Pikachu ex','Pikachu EX'):
            with self.subTest(query=query):self.assertFalse(self.lookup(cid,query)['resolution']['candidate_ids'])

    def test_new_review_requires_each_current_source_bound_variant(self):
        cid=self.card('ピカチュウ','001/100');alias=self.alias('ピカチュウ','Pikachu',requires_binding=True)
        self.assertEqual(self.lookup(cid,'Pikachu')['reason'],'reviewed_name_record_binding_required')
        row=self.row(cid,alias);self.assertEqual(catalog_locale.import_evidence(self.db,[row])['inserted'],1)
        self.assertEqual(self.lookup(cid,'Pikachu')['resolution']['candidate_ids'],[cid])
        self.db.execute('UPDATE card SET provenance=provenance||"changed" WHERE card_id=?',(cid,))
        self.assertEqual(self.lookup(cid,'Pikachu')['reason'],'reviewed_name_record_binding_required')

    def test_forged_sql_binding_and_withdrawn_revision_cannot_translate(self):
        cid=self.card('ピカチュウ','001/100');other=self.card('ピカチュウ','002/100')
        alias=self.alias('ピカチュウ','Pikachu',requires_binding=True);catalog_locale.import_evidence(self.db,[self.row(other,alias)])
        self.db.execute('UPDATE catalog_locale_evidence SET card_id=?',(cid,))
        self.assertFalse(catalog_locale.has_current_alias(self.db,cid,[alias]))
        self.assertEqual(self.lookup(cid,'Pikachu')['reason'],'reviewed_name_record_binding_required')
        self.db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'")
        self.assertFalse(self.lookup(cid,'Pikachu')['resolution']['candidate_ids'])

    def test_shared_name_foil_stamp_and_repeated_numbers_keep_separate_ids(self):
        normal=self.card('ピカチュウ','001/100');stamp=self.card('ピカチュウ','001/100',variant='normal-stamped')
        alias=self.alias('ピカチュウ','Pikachu',requires_binding=True)
        catalog_locale.import_evidence(self.db,[self.row(normal,alias)])
        self.assertEqual(self.lookup(normal,'Pikachu')['reason'],'reviewed_name_record_binding_required')
        catalog_locale.import_evidence(self.db,[self.row(stamp,alias)])
        self.assertEqual(set(self.lookup(normal,'Pikachu')['resolution']['candidate_ids']),{normal,stamp})
        core.import_sets(self.db,[dict(language='ja',set_code='OTHER',name='Other test',official_card_count=100,
                provenance='synthetic:test-only',rights_reference='fixture')])
        repeated=self.card('ピカチュウ','001/100',code='OTHER')
        self.assertNotIn(repeated,self.lookup(normal,'Pikachu')['resolution']['candidate_ids'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM card').fetchone()[0],3)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],0)

    def test_set_filtered_aliases_do_not_leak_from_other_release(self):
        cid=self.card('ピカチュウ','001/100');alias=self.alias('ピカチュウ','Pikachu')
        catalog_locale.import_evidence(self.db,[self.row(cid,alias)])
        self.assertIn(cid,catalog_locale.search_aliases(self.db,set_code='fix'))
        self.assertEqual(catalog_locale.search_aliases(self.db,set_code='other'),{})

    def test_new_four_table_audit_rejects_prior_row_changes_and_wrong_append_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'copy.sqlite3'
            cid=self.card('ピカチュウ','001/100');self.db.commit()
            other=core.connect(target);self.addCleanup(other.close);self.db.backup(other)
            alias=self.alias('ピカチュウ','Pikachu',requires_binding=True)
            # The baseline now has one event/concept, so compare against the copy
            # as the old state, with one event/concept and one locale/mapping added.
            catalog_locale.import_evidence(self.db,[self.row(cid,alias)])
            small=dict(bilingual_concept_revision=1,concept_review_event=1,catalog_locale_evidence=1,catalog_source_mapping=1)
            with patch.object(audit,'ADDITIONS',small):
                self.assertTrue(all(audit.preserved(other,self.db).values()))
                self.db.execute('UPDATE card SET name="changed" WHERE card_id=?',(cid,))
                with self.assertRaisesRegex(ValueError,'card'):audit.preserved(other,self.db)
                self.db.execute('UPDATE card SET name="ピカチュウ" WHERE card_id=?',(cid,))
                self.db.execute('DELETE FROM catalog_source_mapping')
                with self.assertRaisesRegex(ValueError,'catalog_source_mapping'):audit.preserved(other,self.db)


if __name__=='__main__':unittest.main()
