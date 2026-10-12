"""Synthetic-only larger batches retain exact names, versions and permissions."""
import copy,hashlib,json,subprocess,tempfile,unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale,core,tcgdex_source
from scripts import build_international_coverage_expansion as source
from scripts import build_pokemon_name_followup as compiler,build_pokemon_name_coverage as names
from scripts import audit_pokemon_name_followup as audit,audit_international_coverage_expansion as history
from scripts.qualify_international_product_documents import git_tree
from scripts.pokemon_release_witness import release_path,inspect_release


class PokemonNameExpandedTests(unittest.TestCase):
    TIME='2026-10-12T09:00:00Z'
    SETS=('FIXA','FIXB','FIXC')

    @staticmethod
    def native_name(dex):return '合成'+chr(0x4e00+dex)

    @staticmethod
    def english_name(dex):return 'Syntheticzz'+chr(97+(dex-1)//26)+chr(97+(dex-1)%26)

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.repo=self.root/'source';self.repo.mkdir()
        (self.repo/'LICENSE').write_text('Synthetic test-only licence\n')
        (self.root/'catalog').mkdir();(self.root/'catalog/TCGDEX-LICENSE').write_bytes((self.repo/'LICENSE').read_bytes())
        sources=[];offset=0
        for language,sets in (('ja',self.SETS),('en',('SMFIX',))):
            for code in sets:
                for number in range(1,51 if language=='ja' else 76):
                    dex=offset%75+1 if language=='ja' else number
                    if language=='ja':offset+=1
                    variants='[{type:"normal",subtype:"1st edition"},{type:"normal",subtype:"unlimited"}]' if language=='ja' else '[{type:"normal"}]'
                    text=f'const card: Card = {{name:{{ja:"{self.native_name(dex)}",en:"{self.english_name(dex)}"}},category:"Pokemon",dexId:[{dex}],variants:{variants}}}; export default card;'
                    path=f'{"data-asia" if language=="ja" else "data"}/FIX/{code}/{number:03}.ts'
                    target=self.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
                    sources.append((language,code,path,text))
        header_paths={}
        for language,code in {(s[0],s[1]) for s in sources}:
            path=f'{"data-asia" if language=="ja" else "data"}/FIX/{code}.ts';target=self.repo/path
            target.write_text(f'const fixtureRelease: Set = {{id:"{code.lower()}",name:{{ja:"Synthetic release",en:"Synthetic release"}},cardCount:{{official:100}},releaseDate:"2026-10-01"}}; export default fixtureRelease;')
            header_paths[(language,code)]=path
        for command in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','synthetic-only expanded batch']):
            subprocess.run(command,cwd=self.repo,check=True,capture_output=True)
        self.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        self.rights=f'https://github.com/tcgdex/cards-database/blob/{self.revision}/LICENSE'
        for module,key,value in ((compiler,'REVISION',self.revision),(compiler,'RIGHTS',self.rights),
                (source,'REVISION',self.revision),(source,'RIGHTS',self.rights),(names,'REVISION',self.revision)):
            mocked=patch.object(module,key,value);mocked.start();self.addCleanup(mocked.stop)
        self.before=self.root/'before.sqlite3';self.db=core.connect(self.before);core.init_db(self.db);self.addCleanup(self.db.close)
        for language,code in {(s[0],s[1]) for s in sources}:
            core.import_sets(self.db,[dict(language=language,set_code=code,name='Synthetic release',official_card_count=100,
                release_date='2026-10-01',provenance=f'tcgdex:{self.revision}:{header_paths[(language,code)]}',rights_reference=self.rights)])
        for language,code,path,text in sources:
            for card in tcgdex_source.parse_card_source(text,set_id=code,official_count=100,path=path,revision=self.revision,language=language):
                core.import_cards(self.db,[card]);cid=core.card_id(language,code,card['collector_number'],card['variant'])
                self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only',self.rights))
        events=[];concepts=[]
        for dex in range(1,76):
            frozen=dict(proposal_id=f'synthetic:{dex}',category='Pokemon',name_ja=self.native_name(dex),name_en=self.english_name(dex),
                dex_id=dex,source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only')
            snapshot=dict(frozen=frozen,ja_provenance='synthetic:ja',en_provenance='synthetic:en')
            proposal={**frozen,'source_snapshot':snapshot,'source_snapshot_sha256':names.spaced_digest(snapshot),
                      'ja_provenance':'synthetic:ja','en_provenance':'synthetic:en'}
            review=dict(decision='approve',review_revision=1,reviewer='synthetic:test-only',reviewed_at=self.TIME,
                evidence_note='Synthetic fixture only',ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True)
            event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review);event['event_id']=names.spaced_digest(event);events.append(event)
            concepts.append(dict(concept_id=f'synthetic:{dex}',revision=1,category='Pokemon',name_ja=self.native_name(dex),name_en=self.english_name(dex),
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only',reviewer='synthetic:test-only',
                reviewed_at=self.TIME,status='approved',review_event_id=event['event_id']))
        core.import_concept_review_bundle(self.db,dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts));self.db.commit()
        cards=[catalog_locale.snapshot(self.db,r[0]) for r in self.db.execute("SELECT card_id FROM card WHERE language='ja' ORDER BY card_id")]
        blobs=git_tree(self.repo,sorted({s[2] for s in sources}|set(header_paths.values())|{'LICENSE'}),revision=self.revision)
        license_sha=hashlib.sha256((self.repo/'LICENSE').read_bytes()).hexdigest();proposals=[]
        for card in cards:
            alias,dex=compiler.current_alias(self.db,card);path,sha=source.source_fields(card)
            proposals.append(dict(identity=card,name_alias=alias,dex_id=dex,status='source_qualified_proposed_unapplied',
                source_revision=self.revision,native_id=path,git_blob=blobs[path],sha256=sha,rights_reference=self.rights,
                license_sha256=license_sha,**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        self.image=self.root/compiler.EXPANDED_IMAGE_HANDOFF;self.image.parent.mkdir(parents=True,exist_ok=True)
        self.image.write_text(json.dumps(dict(targets=list(compiler.EXPANDED_IMAGE_TARGETS))))
        self.plan=self.root/'catalog/expanded-plan/plan.json';self.plan.parent.mkdir(parents=True)
        releases=[]
        for record in self.db.execute('SELECT * FROM catalog_set_localized ORDER BY language,set_code'):
            release=dict(record);path=release_path(release,self.revision,self.rights);raw=(self.repo/path).read_bytes()
            releases.append(dict(snapshot=release,native_id=path,git_blob=blobs[path],sha256=hashlib.sha256(raw).hexdigest(),
                facts=inspect_release(release,raw),**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        release_index={(w['snapshot']['language'],w['snapshot']['set_code']):w for w in releases};english=[]
        for record in self.db.execute("SELECT card_id FROM card WHERE language='en' ORDER BY card_id"):
            card=catalog_locale.snapshot(self.db,record[0]);alias,dex=compiler.current_alias(self.db,card);path,sha=source.source_fields(card)
            release=release_index[('en',card['set_code'])]
            english.append(dict(identity=card,name_alias=alias,dex_id=dex,source_revision=self.revision,native_id=path,git_blob=blobs[path],
                sha256=sha,rights_reference=self.rights,license_sha256=license_sha,release_snapshot=release['snapshot'],release_facts=release['facts'],
                release_header=dict(provider='tcgdex',revision=self.revision,native_id=release['native_id'],git_blob=release['git_blob'],sha256=release['sha256'],
                    rights_reference=self.rights,license_sha256=license_sha),**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        plan=dict(schema='pokemon.followup-next-batch-plan.v1',applied=False,expanded_batch=True,
            proposed_japanese_records=300,english_comparison_target=75,proposals=proposals,
            qualified_english_candidate_ids=sorted(w['identity']['card_id'] for w in english),english_candidate_witnesses=english,
            localized_release_witnesses=releases,
            release_header_inventory={path:dict(git_blob=blobs[path],sha256=hashlib.sha256((self.repo/path).read_bytes()).hexdigest(),bytes=len((self.repo/path).read_bytes())) for path in header_paths.values()},
            excluded_image_target_ids=sorted(compiler.EXPANDED_IMAGE_TARGETS),
            excluded_image_target_groups=compiler.expanded_excluded_groups(),held_image_handoff_sha256=hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.raw=(json.dumps(plan,ensure_ascii=False,indent=2)+'\n').encode();self.plan.write_bytes(self.raw)
        self.profile=compiler.FollowupProfile('pokemon-name-expanded','catalog/expanded',str(self.plan.relative_to(self.root)),
            hashlib.sha256(self.raw).hexdigest(),hashlib.sha256(self.before.read_bytes()).hexdigest(),self.SETS,300,
            'pokemon.followup-next-batch-plan.v1',strict_variant_dimensions=True,english=75,expanded_batch=True)

    def compile(self):return compiler.compile(self.before,self.repo,self.root,self.TIME,profile=self.profile)

    def test_expansion_is_explicit_and_default_caps_and_types_are_preserved(self):
        normal=source.RetrievalScope('normal',self.SETS,100)
        self.assertEqual((normal.english_records,normal.expanded_batch),(25,False))
        for changes in (dict(japanese=301),dict(english=76),dict(english=True),dict(english=75.0),
                        dict(japanese=True),dict(expanded_batch=1),dict(expanded_batch=False),dict(strict_variant_dimensions=False)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(self.profile,**changes)
        with self.assertRaises(ValueError):source.RetrievalScope('normal',self.SETS,101)
        with self.assertRaises(ValueError):source.RetrievalScope('normal',self.SETS,100,75)
        with self.assertRaisesRegex(ValueError,'frozen exact-name'):source.pairs(self.db,scope=source.RetrievalScope('expanded',self.SETS,300,75,True))

    def test_300_75_compilation_and_import_keep_distinct_versions_and_ids(self):
        before=self.before.read_bytes();rows,selection,_,raw=self.compile()
        self.assertEqual((selection['japanese'],selection['english'],selection['english_full_name_concepts']),(300,75,75))
        self.assertEqual(len(rows),375);self.assertEqual(len({r['identity']['card_id'] for r in rows}),375)
        history.bounded(rows,scope=source.RetrievalScope(self.profile.name,self.SETS,300,75,True))
        audit.checked_name_scopes(rows,compiler.checked_plan(raw,profile=self.profile),english=75)
        with closing(core.connect(':memory:')) as original:
            self.db.backup(original);old_ids={r[0] for r in self.db.execute('SELECT card_id FROM card')}
            self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=375,unchanged=0,quarantined=0))
            self.assertTrue(all(history.preserved(original,self.db,375).values()))
            self.assertEqual(old_ids,{r[0] for r in self.db.execute('SELECT card_id FROM card')})
            self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=0,unchanged=375,quarantined=0))
        self.assertEqual(raw,self.raw);self.assertTrue(all(r[k] is False for r in rows for k in catalog_locale.FALSE_CLAIMS))
        self.assertEqual(self.db.execute('SELECT count(*) FROM card WHERE display_allowed=1').fetchone()[0],0)

    def test_frozen_english_count_and_all_image_group_exclusions_cannot_drift(self):
        plan=json.loads(self.raw)
        for mutate in (lambda p:p.update(english_comparison_target=25),lambda p:p.update(expanded_batch=False),
                       lambda p:p.update(excluded_image_target_ids=[]),lambda p:p.update(excluded_image_target_groups=[]),
                       lambda p:p['proposals'][0]['identity'].update(set_code='PMCG1',collector_number='035/102',variant='normal_stamped')):
            changed=copy.deepcopy(plan);mutate(changed);raw=json.dumps(changed).encode();profile=replace(self.profile,plan_sha=hashlib.sha256(raw).hexdigest())
            with self.assertRaises(ValueError):compiler.checked_plan(raw,profile=profile)

    def test_insufficient_distinct_english_concepts_abstain_without_padding(self):
        plan=compiler.checked_plan(self.raw,profile=self.profile)
        pool=compiler.english_pool(self.db,compiler.planned_japanese(self.db,plan))
        with self.assertRaisesRegex(ValueError,'75 qualified'):compiler.choose_english(pool[:-1]+[pool[0]],count=75)
        with self.assertRaises(ValueError):compiler.choose_english(pool,count=True)
        with patch.object(tcgdex_source,'variant_dimension_losses',return_value=[dict(legacy_variant='normal',source_size='jumbo')]):
            with self.assertRaisesRegex(ValueError,'failed requalification'):self.compile()

    def test_audit_requires_exact_name_count_and_expanded_scope(self):
        scope=source.RetrievalScope(self.profile.name,self.SETS,300,75,True)
        auditing=history.AuditProfile('prior.json','manifest.json',self.profile.directory+'/locales.jsonl',78,scope,True)
        audit.settings_for(self.profile,auditing)
        for changed in (replace(scope,english_records=74),replace(scope,name='wrong-name'),source.RetrievalScope(self.profile.name,self.SETS,100)):
            with self.assertRaisesRegex(ValueError,'scope differs'):audit.settings_for(self.profile,replace(auditing,scope=changed))
        rows,_,_,_=self.compile()
        with self.assertRaises(ValueError):history.bounded(rows)
        with self.assertRaisesRegex(ValueError,'English comparisons'):audit.checked_name_scopes(rows,compiler.checked_plan(self.raw,profile=self.profile))

    def test_omitted_stamped_sibling_and_revoked_alias_abstain(self):
        plan=compiler.checked_plan(self.raw,profile=self.profile);card=copy.deepcopy(plan['records'][0]['card']);card['variant']='normal_stamped'
        core.import_cards(self.db,[{**card,'match_eligible':True}]);cid=core.card_id('ja',card['set_code'],card['collector_number'],card['variant'])
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only',self.rights));self.db.commit()
        with self.assertRaisesRegex(ValueError,'sibling'):compiler.planned_japanese(self.db,plan)
        self.db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'");self.db.commit()
        with self.assertRaisesRegex(ValueError,'current Pokemon'):compiler.planned_japanese(self.db,plan)

    def test_priority_witness_is_checked_before_and_after_compilation(self):
        original=compiler.english_pool
        def drift(db,japanese):
            self.image.write_bytes(self.image.read_bytes()+b' ');return original(db,japanese)
        with patch.object(compiler,'english_pool',side_effect=drift):
            with self.assertRaisesRegex(ValueError,'drifted'):self.compile()
        with self.assertRaisesRegex(ValueError,'source witness'):self.compile()

    def test_expanded_artifacts_publish_exclusively(self):
        output=self.root/'expanded-output'
        result=compiler.build(self.before,self.repo,self.root,output,self.TIME,profile=self.profile)
        self.assertEqual((result['japanese'],result['english']),(300,75));self.assertEqual((output/'basis-plan.json').read_bytes(),self.raw)
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,output,self.TIME,profile=self.profile)

    def test_exact_frozen_english_witness_cannot_be_forged_or_replaced(self):
        plan=json.loads(self.raw)
        changed=copy.deepcopy(plan);changed['qualified_english_candidate_ids'].pop()
        with self.assertRaises(ValueError):compiler.expanded_english_witnesses(changed)
        changed=copy.deepcopy(plan);changed['english_candidate_witnesses'][0]['purchase_allowed']=True
        with self.assertRaises(ValueError):compiler.expanded_english_witnesses(changed)
        changed=copy.deepcopy(plan);changed['english_candidate_witnesses'][0]['release_header']['sha256']='a'*64
        raw=json.dumps(changed).encode();self.plan.write_bytes(raw);self.profile=replace(self.profile,plan_sha=hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError,'failed requalification'):self.compile()

    def test_expanded_wrapper_and_audit_keep_the_prior_scope_default(self):
        from scripts import build_pokemon_name_expanded as expanded,audit_pokemon_name_expanded as checking,build_pokemon_name_vintage as vintage
        self.assertEqual((expanded.PROFILE.japanese,expanded.PROFILE.english,len(expanded.PROFILE.sets)),(300,75,58))
        self.assertEqual((checking.AUDIT_PROFILE.prior_inputs,checking.AUDIT_PROFILE.scope.english_records),(78,75))
        self.assertIs(expanded.PROFILE.expanded_batch,True);self.assertIs(expanded.PROFILE.strict_variant_dimensions,True)
        self.assertEqual((vintage.PROFILE.japanese,vintage.PROFILE.english,vintage.PROFILE.expanded_batch),(100,25,False))


class PokemonReleaseWitnessTests(unittest.TestCase):
    RELEASE=dict(language='ja',set_code='FIX',name='Synthetic release',release_date='2026-10-01',official_card_count=100)
    TEXT='const legacyRelease: Set = {id:"fix",name:{ja:"Synthetic release",en:"Other release"},cardCount:{official:100},releaseDate:"2026-10-01"}; export default legacyRelease;'

    def test_original_legacy_binding_and_localized_dates_are_extraction_only(self):
        raw=self.TEXT.encode();facts=inspect_release(self.RELEASE,raw)
        self.assertEqual(facts['date_kind'],'shared_scalar_provider_date');self.assertEqual(raw,self.TEXT.encode())
        localized=self.TEXT.replace('releaseDate:"2026-10-01"','releaseDate:{ja:"2026-10-01",en:"2026-10-02"}')
        self.assertEqual(inspect_release(self.RELEASE,localized.encode())['date_kind'],'localized_provider_date')
        decoy='/* const bad: Set = {}; export default bad; */ const note="const fake: Set = {}; export default fake;"; '
        self.assertEqual(inspect_release(self.RELEASE,(decoy+self.TEXT).encode()),facts)

    def test_ambiguous_exports_missing_fields_and_conflicts_are_held(self):
        cases=[self.TEXT.replace('export default legacyRelease','export default other'),
            self.TEXT+' export default other;',self.TEXT+' const other: Set = {};',
            self.TEXT.replace('official:100','official:true'),self.TEXT.replace('official:100','official:101'),
            self.TEXT.replace('releaseDate:"2026-10-01"','releaseDate:"2026-10-02"'),
            self.TEXT.replace('id:"fix"','id:"other"'),self.TEXT.replace('ja:"Synthetic release"','ja:"Different release"')]
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ValueError):inspect_release(self.RELEASE,text.encode())


if __name__=='__main__':unittest.main()
