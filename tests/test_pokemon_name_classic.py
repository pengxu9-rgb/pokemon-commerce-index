"""Historical variant groups stay separate, using synthetic local Git fixtures."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from collections import defaultdict
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts import build_pokemon_name_classic as classic
from scripts import build_pokemon_name_extended as extended
from scripts import build_pokemon_name_followup as compiler
from scripts import build_pokemon_name_coverage as names
from scripts import build_international_coverage_expansion as source
from scripts import build_tcgdex_international as international
from scripts import audit_pokemon_name_classic as classic_audit
from scripts import audit_pokemon_name_extended as extended_audit
from scripts import audit_pokemon_name_followup as audit
from scripts import audit_international_coverage_expansion as history
from scripts.qualify_international_product_documents import git_tree
from tests import test_pokemon_name_followup as fixtures


class PokemonNameClassicTests(unittest.TestCase):
    TIME='2026-10-12T05:25:21Z'

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'source';self.repo.mkdir()
        (self.repo/'LICENSE').write_text('Synthetic test-only licence\n')
        (self.root/'catalog').mkdir();(self.root/'catalog/TCGDEX-LICENSE').write_bytes((self.repo/'LICENSE').read_bytes())
        records=[];offset=0
        for lang,codes in (('ja',classic.PROFILE.sets),('en',('SMFIX',))):
            for code in codes:
                for number in range(1,11 if lang=='ja' else 26):
                    dex=(offset%25)+1 if lang=='ja' else number
                    if lang=='ja':offset+=1
                    variants=('[{type: "normal", subtype: "1st edition"}, {type: "normal", subtype: "unlimited"}]'
                              if lang=='ja' else '[{type: "normal"}]')
                    text=f'const card: Card = {{name: {{ja: "合成{dex}", en: "Synthetic {dex}"}}, category: "Pokemon", dexId: [{dex}], variants: {variants}}}; export default card;'
                    path=f'{"data-asia" if lang=="ja" else "data"}/FIX/{code}/{number:03}.ts'
                    target=self.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
                    records.append((lang,code,path,text))
        for args in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','test-only metadata']):
            subprocess.run(args,cwd=self.repo,check=True,capture_output=True)
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        rights=f'https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE'
        for module,key,value in ((compiler,'REVISION',revision),(compiler,'RIGHTS',rights),
                (source,'REVISION',revision),(source,'RIGHTS',rights),(names,'REVISION',revision)):
            p=patch.object(module,key,value);p.start();self.addCleanup(p.stop)
        self.before=self.root/'before.sqlite3';self.db=core.connect(self.before);core.init_db(self.db);self.addCleanup(self.db.close)
        for lang,code in {(r[0],r[1]) for r in records}:
            core.import_sets(self.db,[dict(language=lang,set_code=code,name='Fixture release',official_card_count=100,
                                          provenance='synthetic:test-only',rights_reference=rights)])
        for lang,code,path,text in records:
            rows=tcgdex_source.parse_card_source(text,set_id=code,official_count=100,path=path,revision=revision,language=lang)
            core.import_cards(self.db,rows)
            for row in rows:
                cid=core.card_id(lang,code,row['collector_number'],row['variant'])
                self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only',rights))
        fixtures.PokemonNameFollowupTests.install_reviews(self);self.db.commit()
        cards=[catalog_locale.snapshot(self.db,r[0]) for r in self.db.execute("SELECT card_id FROM card WHERE language='ja' ORDER BY card_id")]
        paths={source.source_fields(c)[0] for c in cards}|{'LICENSE'};blobs=git_tree(self.repo,sorted(paths),revision=revision)
        licence_sha=hashlib.sha256((self.repo/'LICENSE').read_bytes()).hexdigest();proposals=[]
        for card in cards:
            alias,dex=compiler.current_alias(self.db,card);path,sha=source.source_fields(card)
            proposals.append(dict(identity=card,name_alias=alias,dex_id=dex,status='source_qualified_proposed_unapplied',
                source_revision=revision,native_id=path,git_blob=blobs[path],sha256=sha,rights_reference=rights,
                license_sha256=licence_sha,**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        self.plan=self.root/classic.PROFILE.plan;self.plan.parent.mkdir(parents=True,exist_ok=True)
        self.plan.write_text(json.dumps(dict(schema='pokemon.followup-next-batch-plan.v1',applied=False,
            proposed_japanese_records=100,english_comparison_target=25,proposals=proposals),ensure_ascii=False,indent=2)+'\n')
        self.raw=self.plan.read_bytes();self.profile=replace(classic.PROFILE,plan_sha=hashlib.sha256(self.raw).hexdigest(),
            before_sha=hashlib.sha256(self.before.read_bytes()).hexdigest())

    def compile(self):return compiler.compile(self.before,self.repo,self.root,self.TIME,profile=self.profile)

    def test_fixed_five_set_profile_does_not_change_prior_scope(self):
        self.assertEqual((classic.PROFILE.japanese,len(classic.PROFILE.sets)),(100,5))
        self.assertIs(classic.PROFILE.strict_variant_dimensions,True)
        self.assertIs(extended.PROFILE.strict_variant_dimensions,False)
        self.assertEqual(classic_audit.AUDIT_PROFILE.prior_inputs,75)
        self.assertEqual((extended.PROFILE.japanese,len(extended.PROFILE.sets)),(100,12))
        with self.assertRaises(FrozenInstanceError):self.profile.japanese=101
        with self.assertRaisesRegex(ValueError,'scope differs'):audit.settings_for(self.profile,extended_audit.AUDIT_PROFILE)

    def test_size_loss_is_exposed_without_reassigning_legacy_ids(self):
        text='const card: Card = {variants: [{type: "normal", size: "jumbo"}, {type: "normal", subtype: "unlimited"}]} '
        self.assertEqual(tcgdex_source.variant_dimension_losses(text),[dict(legacy_variant='normal',source_size='jumbo')])
        self.assertEqual(tcgdex_source.variant_dimension_losses('const card: Card = {variants: [{type: "normal"}]}'),[])
        with self.assertRaises(ValueError):tcgdex_source.variant_dimension_losses('const card: Card = {variants: [{type: "normal", size: dynamicSize}]}')
        with self.assertRaises(ValueError):replace(self.profile,strict_variant_dimensions='yes')

    def test_strict_source_import_holds_size_bearing_file_and_keeps_legacy_mode(self):
        text='const card: Card = {name: {en: "Synthetic 1"}, variants: [{type: "normal", size: "jumbo"}, {type: "normal", subtype: "unlimited"}]} '
        arguments=dict(set_id='SMFIX',official_count=100,path='data/FIX/SMFIX/001.ts',revision=compiler.REVISION,language='en')
        self.assertEqual([r['variant'] for r in tcgdex_source.parse_card_source(text,**arguments)],['normal','normal_unlimited'])
        with self.assertRaisesRegex(ValueError,'identity correction review'):
            tcgdex_source.parse_card_source(text,**arguments,strict_variant_dimensions=True)
        with self.assertRaises(ValueError):tcgdex_source.parse_card_source(text,**arguments,strict_variant_dimensions=1)

    def test_strict_guard_cannot_be_bypassed_by_quotes_strings_or_comments(self):
        arguments=dict(set_id='SMFIX',official_count=100,path='data/FIX/SMFIX/001.ts',revision=compiler.REVISION,language='en',strict_variant_dimensions=True)
        cases=(
            'const card: Card = {name:{en:"Synthetic 1"}, variants:[{type:"normal","size":"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, "variants":[{type:"normal",size:"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, description:"variants: []", variants:[{type:"normal",size:"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, /* variants: [] */ variants:[{type:"normal",size:"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, variants:[{type:"normal",size:dynamicSize}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, variants:[{type:"normal",["size"]:"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, ["variants"]:[{type:"normal",size:"jumbo"}]}',
            'const card: Card = {name:{en:"Synthetic 1"}, variants:[], "variants":[{type:"normal",size:"jumbo"}]}',
            'const decoy="const card: Card = {variants:[]}"; const card: Card = {name:{en:"Synthetic 1"}, variants:[{type:"normal",size:"jumbo"}]}',
        )
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ValueError):tcgdex_source.parse_card_source(text,**arguments)
        no_size='const card: Card = {variants:[{type:"normal",thirdParty:{size:"vendor-detail"}, /* size:"jumbo" */}]} '
        self.assertEqual(tcgdex_source.variant_dimension_losses(no_size),[])

    def test_fresh_international_import_emits_gap_instead_of_size_loss_identity(self):
        directory=self.repo/'data/Base/Base Set';directory.mkdir(parents=True)
        directory.with_suffix('.ts').write_text('const set = {id:"base1",name:{en:"Fixture release"},cardCount:{official:102}}')
        (directory/'58.ts').write_text('const card: Card = {name:{en:"Synthetic 1"},description:"variants: []","variants":[{type:"normal","size":"jumbo"},{type:"normal",subtype:"unlimited"}]}')
        subprocess.run(['git','add','data/Base'],cwd=self.repo,check=True,capture_output=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','test-only size loss'],cwd=self.repo,check=True,capture_output=True)
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        output,sets,report,gaps=[self.root/name for name in ('size-cards.jsonl','size-sets.jsonl','size-report.json','size-gaps.jsonl')]
        result=international.build(self.repo,revision,['Base'],output,sets,report,gaps)
        self.assertEqual(result['identities'],0);self.assertEqual(result['gap_count'],1)
        self.assertEqual(output.read_text(),'')
        self.assertRegex(json.loads(gaps.read_text())['reason'],r'identity (?:correction )?review')

    def test_fresh_builder_rejects_unapproved_remote_before_source_lookup(self):
        subprocess.run(['git','remote','add','unapproved','https://source.invalid'],cwd=self.repo,check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'unexpected source remote'):
            international.verify_source(self.repo,compiler.REVISION,['FIX'],'data')

    def test_strict_japanese_dimension_loss_aborts_before_publication(self):
        with patch.object(tcgdex_source,'variant_dimension_losses',return_value=[dict(legacy_variant='normal_1st_edition',source_size='jumbo')]):
            with self.assertRaisesRegex(ValueError,'Japanese requalification failed'):self.compile()

    def test_strict_english_dimension_loss_is_held_without_padding(self):
        with patch.object(tcgdex_source,'variant_dimension_losses',return_value=[dict(legacy_variant='normal',source_size='jumbo')]):
            with self.assertRaisesRegex(ValueError,'25 qualified'):self.compile()

    def test_edition_twins_and_repeated_numbers_keep_all_ids_separate(self):
        before=self.before.read_bytes();rows,selection,_,_=self.compile();groups=defaultdict(list)
        for row in rows:
            card=row['identity']
            if card['language']=='ja':groups[(card['set_code'],card['collector_number'])].append(row)
            for key in catalog_locale.FALSE_CLAIMS:self.assertIs(row[key],False)
        self.assertEqual((selection['japanese'],selection['english']),(100,25));self.assertEqual(len(groups),50)
        self.assertEqual(len({r['identity']['card_id'] for r in rows}),125)
        for pair in groups.values():
            self.assertEqual({r['identity']['variant'] for r in pair},{'normal_1st_edition','normal_unlimited'})
            self.assertEqual(pair[0]['source']['sha256'],pair[1]['source']['sha256'])
        self.assertEqual(self.before.read_bytes(),before)

    def test_missing_edition_sibling_is_held_instead_of_merged(self):
        plan=compiler.checked_plan(self.raw,profile=self.profile);plan['records'].pop(0)
        with self.assertRaisesRegex(ValueError,'sibling'):compiler.planned_japanese(self.db,plan)

    def test_rehashed_plan_cannot_substitute_variant_or_review(self):
        for kind in ('variant','review'):
            plan=json.loads(self.raw)
            if kind=='variant':plan['proposals'][0]['identity']['variant']='normal'
            else:plan['proposals'][0]['name_alias']['revision']=2
            raw=json.dumps(plan,ensure_ascii=False).encode();profile=replace(self.profile,plan_sha=hashlib.sha256(raw).hexdigest())
            with self.subTest(kind=kind),self.assertRaises(ValueError):compiler.planned_japanese(self.db,compiler.checked_plan(raw,profile=profile))

    def test_exact_source_proof_and_current_alias_are_required_by_audit(self):
        rows,_,_,_=self.compile();plan=compiler.checked_plan(self.raw,profile=self.profile)
        audit.checked_name_scopes(rows,plan)
        changed=copy.deepcopy(rows);changed[0]['source']['git_blob']='0'*40
        with self.assertRaisesRegex(ValueError,'source witness'):audit.checked_name_scopes(changed,plan)

    def test_wrapper_and_reimport_keep_exclusive_outputs_and_history(self):
        output=self.root/'compiled'
        with patch.object(classic,'PROFILE',self.profile):
            classic.build(self.before,self.repo,self.root,output,self.TIME)
            with self.assertRaises(FileExistsError):classic.build(self.before,self.repo,self.root,output,self.TIME)
        rows=[json.loads(line) for line in (output/'locales.jsonl').read_text().splitlines()]
        with closing(core.connect(self.root/'copy.sqlite3')) as before:
            self.db.backup(before);catalog_locale.import_evidence(self.db,rows)
            self.assertTrue(all(history.preserved(before,self.db,125).values()))
        values={table:history.records(self.db,table) for table in history.tables(self.db)}
        self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=0,unchanged=125,quarantined=0))
        for table,old in values.items():self.assertEqual(history.records(self.db,table),old)


if __name__=='__main__':unittest.main()
