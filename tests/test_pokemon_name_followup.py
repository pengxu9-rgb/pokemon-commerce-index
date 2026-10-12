"""Frozen follow-up boundaries using exclusively synthetic local fixtures."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, catalog_question_resolver_v2 as resolver, core, tcgdex_source
from scripts import build_international_coverage_expansion as expansion
from scripts import build_pokemon_name_coverage as names
from scripts import build_pokemon_name_followup as compiler
from scripts import audit_pokemon_name_followup as audit
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts


class PokemonNameFollowupTests(unittest.TestCase):
    TIME='2026-10-12T03:03:38Z'

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'source';self.repo.mkdir()
        (self.repo/'LICENSE').write_text('Synthetic test-only licence\n')
        (self.root/'catalog').mkdir();(self.root/'catalog/TCGDEX-LICENSE').write_bytes((self.repo/'LICENSE').read_bytes())
        records=[];offset=0
        for lang,codes in (('ja',compiler.SETS),('en',('SMFIX',))):
            for index,code in enumerate(codes):
                count=(11 if index<5 else 10) if lang=='ja' else 25
                for number in range(1,count+1):
                    dex=(offset%25)+1 if lang=='ja' else number
                    if lang=='ja':offset+=1
                    text=f'''const card: Card = {{name: {{ja: "合成{dex}", en: "Synthetic {dex}"}},
                        category: "Pokemon", dexId: [{dex}], variants: [{{type: "normal"}}]}}; export default card;'''
                    path=f'{"data-asia" if lang=="ja" else "data"}/FIX/{code}/{number:03}.ts'
                    target=self.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
                    records.append((lang,code,path,text,dex))
        subprocess.run(['git','init','-q'],cwd=self.repo,check=True,capture_output=True)
        subprocess.run(['git','add','.'],cwd=self.repo,check=True,capture_output=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','test-only metadata'],
                       cwd=self.repo,check=True,capture_output=True)
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        rights=f'https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE'
        for module,key,value in ((compiler,'REVISION',revision),(compiler,'RIGHTS',rights),
                (expansion,'REVISION',revision),(expansion,'RIGHTS',rights),(names,'REVISION',revision)):
            p=patch.object(module,key,value);p.start();self.addCleanup(p.stop)
        self.before=self.root/'before.sqlite3';self.db=core.connect(self.before);core.init_db(self.db);self.addCleanup(self.db.close)
        for lang,code in { (r[0],r[1]) for r in records }:
            core.import_sets(self.db,[dict(language=lang,set_code=code,name='Fixture release',official_card_count=100,
                                          provenance='synthetic:test-only',rights_reference=rights)])
        japanese=[]
        for lang,code,path,text,dex in records:
            cards=tcgdex_source.parse_card_source(text,set_id=code,official_count=100,path=path,revision=revision,language=lang)
            core.import_cards(self.db,cards);cid=core.card_id(lang,code,cards[0]['collector_number'],'normal')
            self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only',rights))
            if lang=='ja':japanese.append(dict(card=catalog_locale.snapshot(self.db,cid),
                full_name_pair=dict(name_ja=f'合成{dex}',name_en=f'Synthetic {dex}',dex_id=dex),status='source_qualified_not_applied'))
        self.install_reviews()
        self.db.commit()
        plan=dict(schema='pokemon.name-coverage-next-batch.v1',applied=False,japanese_records=85,english_comparison_target=25,records=japanese)
        self.plan=self.root/compiler.PLAN;self.plan.parent.mkdir(parents=True,exist_ok=True)
        self.plan.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
        self.plan_bytes=self.plan.read_bytes()
        for key,value in (('PLAN_SHA',hashlib.sha256(self.plan_bytes).hexdigest()),('BEFORE_SHA',hashlib.sha256(self.before.read_bytes()).hexdigest())):
            p=patch.object(compiler,key,value);p.start();self.addCleanup(p.stop)

    def install_reviews(self):
        events=[];concepts=[]
        for dex in range(1,26):
            frozen=dict(proposal_id='synthetic:'+str(dex),category='Pokemon',name_ja=f'合成{dex}',name_en=f'Synthetic {dex}',
                dex_id=dex,source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only')
            snapshot=dict(frozen=frozen,ja_provenance='synthetic:ja',en_provenance='synthetic:en')
            proposal={**frozen,'source_snapshot':snapshot,'source_snapshot_sha256':names.spaced_digest(snapshot),
                      'ja_provenance':'synthetic:ja','en_provenance':'synthetic:en'}
            review=dict(decision='approve',review_revision=1,reviewer='synthetic:test-only',reviewed_at=self.TIME,
                evidence_note='Synthetic fixture only',ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True)
            event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review);event['event_id']=names.spaced_digest(event);events.append(event)
            concepts.append(dict(concept_id='synthetic:'+str(dex),revision=1,category='Pokemon',name_ja=f'合成{dex}',name_en=f'Synthetic {dex}',
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only',reviewer='synthetic:test-only',
                reviewed_at=self.TIME,status='approved',review_event_id=event['event_id']))
        core.import_concept_review_bundle(self.db,dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts))

    def compile(self):return compiler.compile(self.before,self.repo,self.root,self.TIME)

    def test_exact_plan_hash_identity_count_and_set_scope_cannot_drift(self):
        self.assertEqual(len(compiler.checked_plan(self.plan_bytes)['records']),85)
        with self.assertRaisesRegex(ValueError,'frozen'):compiler.checked_plan(self.plan_bytes+b' ')
        plan=json.loads(self.plan_bytes);plan['records'][0]['card']['set_code']='OTHER'
        raw=json.dumps(plan).encode()
        with patch.object(compiler,'PLAN_SHA',hashlib.sha256(raw).hexdigest()),self.assertRaisesRegex(ValueError,'scope'):
            compiler.checked_plan(raw)

    def test_changed_or_already_bound_plan_identity_is_refused(self):
        plan=json.loads(self.plan_bytes);cid=plan['records'][0]['card']['card_id']
        self.db.execute('UPDATE card SET name="changed" WHERE card_id=?',(cid,))
        with self.assertRaisesRegex(ValueError,'changed'):compiler.planned_japanese(self.db,plan)
        self.db.execute('UPDATE card SET name=? WHERE card_id=?',(plan['records'][0]['card']['name'],cid))
        with patch.object(compiler,'bound_ids',return_value={cid}),self.assertRaisesRegex(ValueError,'already bound'):
            compiler.planned_japanese(self.db,plan)

    def test_eligible_foil_or_stamped_sibling_cannot_be_omitted(self):
        plan=json.loads(self.plan_bytes);card=copy.deepcopy(plan['records'][0]['card'])
        card.update(variant='normal-stamped',display_allowed=False,match_eligible=True)
        core.import_cards(self.db,[card]);cid=core.card_id('ja',card['set_code'],card['collector_number'],card['variant'])
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only','fixture'))
        with self.assertRaisesRegex(ValueError,'sibling'):compiler.planned_japanese(self.db,plan)

    def test_wrong_name_dex_or_withdrawn_review_is_refused(self):
        plan=json.loads(self.plan_bytes);plan['records'][0]['full_name_pair']['dex_id']=151
        with self.assertRaisesRegex(ValueError,'name/Dex'):compiler.planned_japanese(self.db,plan)
        self.db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'")
        with self.assertRaisesRegex(ValueError,'current Pokemon'):compiler.planned_japanese(self.db,json.loads(self.plan_bytes))

    def test_forged_retained_review_digest_cannot_authorize_binding(self):
        self.db.execute("UPDATE concept_review_event SET record_json=replace(record_json,'Synthetic 1','Changed 1')")
        with self.assertRaisesRegex(ValueError,'review scope'):compiler.current_alias(self.db,json.loads(self.plan_bytes)['records'][0]['card'])

    def test_english_comparisons_are_disjoint_distinct_names_and_do_not_pad(self):
        japanese=compiler.planned_japanese(self.db,json.loads(self.plan_bytes));pool=compiler.english_pool(self.db,japanese)
        selected=compiler.choose_english(pool)
        self.assertEqual(len({a['concept_id'] for c,a,d in selected}),25)
        with self.assertRaisesRegex(ValueError,'25 qualified'):compiler.choose_english(pool[:-1])
        with patch.object(compiler,'bound_ids',return_value={pool[0][0]['card_id']}):
            self.assertNotIn(pool[0][0]['card_id'],{c['card_id'] for c,a,d in compiler.english_pool(self.db,japanese)})

    def test_pinned_requalification_preserves_input_and_all_false_claims(self):
        old=self.before.read_bytes();rows,selection,licence,plan=self.compile()
        self.assertEqual((selection['japanese'],selection['english']),(85,25))
        self.assertEqual(len(rows),110);self.assertEqual(plan,self.plan_bytes)
        self.assertEqual(selection['holds'],[]);self.assertEqual(self.before.read_bytes(),old)
        for row in rows:
            for flag in catalog_locale.FALSE_CLAIMS:self.assertIs(row[flag],False)
            self.assertEqual(row['source']['region'],'ZZ');self.assertIsNone(row['source']['retrieved_at'])

    def test_source_drift_or_wrong_snapshot_prevents_publication(self):
        output=self.root/'artifacts'
        path=next(self.repo.rglob('001.ts'));path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ValueError):compiler.build(self.before,self.repo,self.root,output,self.TIME)
        self.assertFalse(output.exists())
        with patch.object(compiler,'BEFORE_SHA','0'*64),self.assertRaisesRegex(ValueError,'database differs'):
            self.compile()

    def test_plan_drift_during_queries_prevents_publication(self):
        output=self.root/'artifacts';original=core.catalog_search_internal;changed=False
        def mutate(*args,**kwargs):
            nonlocal changed
            result=original(*args,**kwargs)
            if not changed:self.plan.write_bytes(self.plan_bytes+b' ');changed=True
            return result
        with patch.object(core,'catalog_search_internal',side_effect=mutate),self.assertRaisesRegex(ValueError,'drifted'):
            compiler.build(self.before,self.repo,self.root,output,self.TIME)
        self.assertFalse(output.exists())

    def test_output_creation_is_exclusive_and_reimport_preserves_all_rows(self):
        output=self.root/'artifacts';compiler.build(self.before,self.repo,self.root,output,self.TIME)
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,output,self.TIME)
        rows=[json.loads(line) for line in (output/'locales.jsonl').read_text().splitlines()]
        with closing(core.connect(self.root/'baseline-copy.sqlite3')) as before:
            self.db.backup(before)
            self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=110,unchanged=0,quarantined=0))
            self.assertTrue(all(history.preserved(before,self.db,110).values()))
        values={table:history.records(self.db,table) for table in history.tables(self.db)}
        self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=0,unchanged=110,quarantined=0))
        for table,old in values.items():self.assertEqual(history.records(self.db,table),old)

    def test_explicit_resolution_growth_requires_current_exact_record_names(self):
        rows,_,_,_=self.compile();row=rows[0];name=row['name_aliases'][0]['name_en']
        old=resolver.resolve_question(self.db,facts(row,name));catalog_locale.import_evidence(self.db,[row])
        new=resolver.resolve_question(self.db,facts(row,name))
        self.assertTrue(history.bound_name_resolution(None,self.db,row,name,old,new))
        wrong=copy.deepcopy(new);wrong['resolution']['candidate_ids']=[rows[11]['identity']['card_id']]
        self.assertFalse(history.bound_name_resolution(None,self.db,row,name,old,wrong))
        self.db.execute('UPDATE card SET provenance=provenance||"changed" WHERE card_id=?',(row['identity']['card_id'],))
        self.assertFalse(history.bound_name_resolution(None,self.db,row,name,old,new))

    def test_legacy_audit_profiles_do_not_enable_resolution_growth(self):
        self.assertIs(history.profile_or_default(None).allow_bound_name_resolution_growth,False)
        self.assertIs(audit.PROFILE.allow_bound_name_resolution_growth,True)
        with self.assertRaises(ValueError):history.AuditProfile('before','after','locales',72,None,'true')

    def test_auxiliary_evidence_drift_cannot_publish_incremental_snapshot(self):
        output=self.root/'after.sqlite3';counter=0
        def inputs(root):
            nonlocal counter
            counter+=1;return {'plan':str(counter)}
        def append(before,scratch,root,**kwargs):scratch.write_bytes(b'synthetic snapshot');return dict(inserted=110,unchanged=0,quarantined=0)
        with patch.object(audit,'inputs',side_effect=inputs),patch.object(history,'append',side_effect=append):
            with self.assertRaisesRegex(ValueError,'drifted'):audit.append(self.before,output,self.root)
        self.assertFalse(output.exists())

    def test_rehashed_locale_dex_or_name_cannot_depart_from_frozen_pair(self):
        rows,_,_,_=self.compile();plan=json.loads(self.plan_bytes);audit.checked_name_scopes(rows,plan)
        for change in ('dex','name'):
            changed=copy.deepcopy(rows)
            if change=='dex':changed[0]['character_scope']['dex_id']=151
            else:changed[0]['name_aliases'][0]['name_en']='Unreviewed name'
            changed[0]['evidence_id']='catalog-locale:'+catalog_locale.digest({k:v for k,v in changed[0].items() if k!='evidence_id'})
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'frozen planned pair'):
                audit.checked_name_scopes(changed,plan)

    def test_english_comparison_must_match_selected_japanese_alias_and_dex(self):
        rows,_,_,_=self.compile();plan=json.loads(self.plan_bytes)
        for change in ('concept','dex','revision'):
            changed=copy.deepcopy(rows);english=next(r for r in changed if r['identity']['language']=='en')
            if change=='concept':english['name_aliases'][0]['concept_id']='another:concept'
            elif change=='dex':english['character_scope']['dex_id']=151
            else:english['name_aliases'][0]['revision']=2
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'outside exact planned'):
                audit.checked_name_scopes(changed,plan)


if __name__=='__main__':unittest.main()
