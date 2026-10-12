"""Synthetic pinned Johto-policy fixtures; no real acquisition/model review."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, tcgdex_source, variant_dimension_hold
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_johto_pilot as compiler
from scripts import build_international_coverage_expansion as sources
from scripts import build_pokemon_name_coverage as names
from scripts import build_pokemon_name_followup as previous
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts
from scripts.pokemon_release_witness import inspect_release
from scripts.qualify_international_product_documents import git_tree


class PokemonNameJohtoPilotTests(unittest.TestCase):
    TIME = '2026-10-12T12:00:00Z'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.repo = self.root/'synthetic-source'; self.repo.mkdir()
        (self.repo/'LICENSE').write_text('Synthetic test-only metadata licence\n')
        (self.root/'catalog').mkdir(); (self.root/'catalog/TCGDEX-LICENSE').write_bytes((self.repo/'LICENSE').read_bytes())
        self.source_records = []; self.headers = {}
        self.pairs = sorted(compiler.JOHTO_PAIRS)
        self.kanto = [(i,'テスト名'+chr(0x4e00+i),'Synthetic Kanto '+str(i)) for i in range(1,10)]
        for group in range(9):
            dex,ja,en = self.kanto[group]
            self.card_source('ja','PMCG1' if group<8 else 'PMCG3',group+1,dex,ja,en,
                '[{type:"normal"},{type:"normal",subtype:"no rarity"}]' if group<8 else '[{type:"holo"}]','existing')
            self.card_source('en','SMSEM',group+1,dex,ja,en,'[{type:"normal"}]','semantic')
        modern = compiler.SETS[2:]
        for group in range(43):
            dex,ja,en = self.pairs[group%25]
            variants='[{type:"normal"},{type:"reverse"}]' if group<29 else '[{type:"holo"}]'
            if group==0 and self._testMethodName=='test_nonliteral_source_variants_are_held_instead_of_projected':
                variants='[{type:"normal"},{type:"reverse"},...otherVariants]'
            self.card_source('ja',modern[group%5],group+1,dex,ja,en,
                variants,'new')
        for index,(dex,ja,en) in enumerate(self.pairs,1):
            self.card_source('en','SMFIX',index,dex,ja,en,'[{type:"normal"}]','english')
        for language,code in {(r[0],r[1]) for r in self.source_records}:
            path=f'{"data-asia" if language=="ja" else "data"}/FIX/{code}.ts'
            (self.repo/path).write_text(f'const fixtureRelease: Set = {{id:"{code}",name:{{ja:"Synthetic release",en:"Synthetic release"}},cardCount:{{official:100}},releaseDate:"2026-10-01"}}; export default fixtureRelease;')
            self.headers[(language,code)] = path
        for command in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','synthetic-only Johto policy fixtures']):
            subprocess.run(command,cwd=self.repo,check=True,capture_output=True)
        self.revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        self.rights = f'https://github.com/tcgdex/cards-database/blob/{self.revision}/LICENSE'
        for module,key,value in ((compiler,'REVISION',self.revision),(compiler,'RIGHTS',self.rights),
                                  (sources,'REVISION',self.revision),(sources,'RIGHTS',self.rights)):
            mocked=patch.object(module,key,value); mocked.start(); self.addCleanup(mocked.stop)
        self.before = self.root/'before.sqlite3'; self.db=core.connect(self.before); core.init_db(self.db); self.addCleanup(self.db.close)
        for (language,code),path in self.headers.items():
            core.import_sets(self.db,[dict(language=language,set_code=code,name='Synthetic release',official_card_count=100,
                release_date='2026-10-01',provenance=f'tcgdex:{self.revision}:{path}',rights_reference=self.rights)])
        self.records = dict(existing=[],semantic=[],new=[],english=[])
        for language,code,path,raw,role in self.source_records:
            for card in tcgdex_source.parse_card_source(raw,set_id=code,official_count=100,path=path,revision=self.revision,language=language):
                core.import_cards(self.db,[card]); cid=core.card_id(language,code,card['collector_number'],card['variant'])
                self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,card['provenance'],self.rights))
                self.records[role].append(cid)
        # Preserve the actual 44 historical hold records inside this disposable
        # fixture. They are metadata only, and are never copied to a real DB.
        frozen=Path(__file__).resolve().parents[1]/'catalog/variant-dimension-holds-v1/holds.jsonl'
        holds=[json.loads(line) for line in frozen.read_text().splitlines()]
        core.import_cards(self.db,[dict(row['identity'],match_eligible=row['prior_structural_match_eligible']) for row in holds])
        variant_dimension_hold.import_evidence(self.db,holds)
        self.db.commit()
        paths={r[2] for r in self.source_records}|set(self.headers.values())|{'LICENSE'}
        self.blobs=git_tree(self.repo,sorted(paths),revision=self.revision)
        self.release_witnesses={}
        for release in self.db.execute('SELECT * FROM catalog_set_localized ORDER BY language,set_code'):
            release=dict(release); path=self.headers[(release['language'],release['set_code'])]; raw=(self.repo/path).read_bytes()
            self.release_witnesses[(release['language'],release['set_code'])]=dict(snapshot=release,native_id=path,
                git_blob=self.blobs[path],sha256=compiler.signature(raw),bytes=len(raw),facts=inspect_release(release,raw),
                rights_status='metadata_internal_reviewed',retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',
                **{k:False for k in catalog_locale.FALSE_CLAIMS})
        events,concepts=[],[]
        for dex,ja,en in self.kanto:
            jw=next(self.witness(cid,dex) for cid in self.records['existing'] if self.db.execute('SELECT name FROM card WHERE card_id=?',(cid,)).fetchone()[0]==ja)
            ew=self.witness(self.records['semantic'][dex-1],dex)
            frozen=dict(proposal_id=f'synthetic:kanto:{dex}',category='Pokemon',name_ja=ja,name_en=en,dex_id=dex,
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only')
            snapshot=dict(frozen=frozen,ja_provenance=jw['identity']['provenance'],en_provenance=ew['identity']['provenance'],
                witnesses=dict(ja=dict(identity=jw['identity']),en=dict(identity=ew['identity'])))
            proposal={**frozen,'source_snapshot':snapshot,'source_snapshot_sha256':names.spaced_digest(snapshot),
                'ja_provenance':snapshot['ja_provenance'],'en_provenance':snapshot['en_provenance']}
            review=dict(decision='approve',review_revision=1,reviewer='synthetic:test-only',reviewed_at=self.TIME,
                evidence_note='Synthetic fixture only',ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True)
            event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review);event['event_id']=names.spaced_digest(event);events.append(event)
            concepts.append(dict(concept_id=f'synthetic:kanto:{dex}',revision=1,category='Pokemon',name_ja=ja,name_en=en,
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only',reviewer='synthetic:test-only',
                reviewed_at=self.TIME,status='approved',review_event_id=event['event_id']))
        core.import_concept_review_bundle(self.db,dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts));self.db.commit()
        existing=[]
        for cid in sorted(self.records['existing']):
            card=catalog_locale.snapshot(self.db,cid); alias,dex=previous.current_alias(self.db,card);w=self.witness(cid,dex)
            event=json.loads(self.db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(alias['review_event_id'],)).fetchone()[0])
            semantic={language:self.witness(s['identity']['card_id'],dex) for language,s in event['proposal']['source_snapshot']['witnesses'].items()}
            w.update(name_alias=alias,existing_semantic_witnesses=semantic);existing.append(w)
        new=[self.witness(cid,self.source_dex(cid)) for cid in sorted(self.records['new'])]
        english=[self.witness(cid,self.source_dex(cid)) for cid in self.records['english']]
        proposals=[]
        for dex,ja,en in self.pairs:
            candidates=[w for w in new if w['identity']['name']==ja];ew=next(w for w in english if w['identity']['name']==en)
            proposals.append(dict(dex_id=dex,name_ja=ja,name_en=en,ja=candidates[0],en=ew,potential_ja_bindings=candidates,
                unresolved_conflicts=[compiler.PENDING_SEMANTIC_REVIEW],**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        audit=[]
        for c in self.db.execute('SELECT * FROM bilingual_concept_revision ORDER BY concept_id'):
            event=json.loads(self.db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(c['review_event_id'],)).fetchone()[0])
            audit.append(dict(concept_id=c['concept_id'],revision=c['revision'],name_ja=c['name_ja'],name_en=c['name_en'],
                review_event_id=c['review_event_id'],dex_id=event['proposal']['source_snapshot']['frozen']['dex_id'],requires_exact_card_binding=True))
        japanese=existing+new
        self.packet=dict(schema='pokemon.stage16-next-source-qualification.v1',applied=False,source_pin=self.revision,rights_reference=self.rights,
            input_database_sha256=compiler.signature(self.before.read_bytes()),current_localized_bindings=0,identity_holds_preserved=44,
            current_concept_audit=audit,current_approved_pokemon_full_name_concepts=9,
            license_sha256=compiler.signature((self.repo/'LICENSE').read_bytes()),
            parsing_source_sha256={key:compiler.signature((Path(compiler.__file__).resolve().parents[1]/path).read_bytes()) for key,path in compiler.CODE_INPUTS.items()},
            source_inventory={path:dict(git_blob=self.blobs[path],sha256=compiler.signature((self.repo/path).read_bytes()),bytes=len((self.repo/path).read_bytes())) for path in sorted(paths)},
            input_packet_sha256={},johto_semantic_review_tranche=dict(proposals=proposals),
            five_image_targets_excluded=sorted(previous.EXPANDED_IMAGE_TARGETS),localized_release_source_witnesses=list(self.release_witnesses.values()),
            next_concrete_draft=dict(japanese_records=89,english_comparison_records=25,existing_review_witnesses=existing,
                unapproved_new_name_witnesses=new,english_witnesses=english,card_ids=sorted(w['identity']['card_id'] for w in japanese),
                by_set=dict(Counter(w['identity']['set_code'] for w in japanese)),
                **{k:False for k in catalog_locale.FALSE_CLAIMS}),demand='Synthetic test-only',authorized_supply='Synthetic test-only metadata',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        self.review=dict(schema='pokemon.independent-name-review.v1',reviewer='GPT-6.1 Sol high',decision='approve_all_exact_pairs',
            approved_pairs=25,rejected_pairs=[],uncertain_pairs=[],approved_into_catalog=False,sources_fetched=False,
            scope='Synthetic test-only approval fixture; no real model was called')
        self.packet_path=self.root/'qualification.json';self.review_path=self.root/'semantic.json'
        self.refresh()

    def card_source(self,language,code,number,dex,ja,en,variants,role):
        text=f'const card: Card = {{name:{{ja:"{ja}",en:"{en}"}},category:"Pokemon",dexId:[{dex}],variants:{variants}}}; export default card;'
        path=f'{"data-asia" if language=="ja" else "data"}/FIX/{code}/{number:03}.ts'
        target=self.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
        self.source_records.append((language,code,path,text,role))

    def source_dex(self,cid):
        card=catalog_locale.snapshot(self.db,cid);path,_=sources.source_fields(card)
        return ast_literal_dex((self.repo/path).read_text())

    def witness(self,cid,dex):
        card=catalog_locale.snapshot(self.db,cid);path,sha=sources.source_fields(card);raw=(self.repo/path).read_bytes()
        fields=compiler.header_fields(raw.decode(),declaration_name='card',declaration_type='Card')
        release=self.release_witnesses[(card['language'],card['set_code'])]
        return dict(dex_id=dex,localized_names=names.names(fields['name']),identity=card,
            source=dict(provider='tcgdex',native_id=path,revision=self.revision,git_blob=self.blobs[path],sha256=sha,bytes=len(raw),
                rights_reference=self.rights,rights_status='metadata_internal_reviewed',retrieved_at=None,
                retrieval_status='historical_snapshot_time_not_recorded',physical_distribution_region=None),
            release_snapshot=release['snapshot'],release_source=release,**{k:False for k in catalog_locale.FALSE_CLAIMS})

    def refresh(self):
        self.db.commit();self.packet['input_database_sha256']=compiler.signature(self.before.read_bytes())
        self.packet_path.write_text(json.dumps(self.packet,ensure_ascii=False,indent=2)+'\n')
        self.review['proposal_sha256']=compiler.signature(self.packet_path.read_bytes())
        self.review_path.write_text(json.dumps(self.review,ensure_ascii=False,indent=2)+'\n')
        for key,value in [('BEFORE_SHA',self.packet['input_database_sha256']),('PACKET_SHA',self.review['proposal_sha256']),
                          ('REVIEW_SHA',compiler.signature(self.review_path.read_bytes()))]:
            mocked=patch.object(compiler,key,value);mocked.start();self.addCleanup(mocked.stop)

    def compile(self):
        return compiler.compile(self.before,self.repo,self.root,self.packet_path,self.review_path,self.TIME)

    def test_bounded_unicode_import_keeps_ids_groups_and_idempotent_history(self):
        bundle,rows,selection,*_=self.compile()
        self.assertEqual((len(bundle['review_events']),len(rows)),(25,114))
        self.assertTrue(all(e['review']['requires_card_binding'] for e in bundle['review_events']))
        self.assertEqual(selection['concepts_without_record_bindings_abstain'],114)
        self.assertEqual(selection['japanese_coordinate_groups'],52)
        after=self.root/'after.sqlite3';after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM card ORDER BY card_id')]
            core.import_concept_review_bundle(db,bundle);self.assertEqual(catalog_locale.import_evidence(db,rows),dict(inserted=114,unchanged=0,quarantined=0))
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM card ORDER BY card_id')],before)
            for row in rows[::7]:
                alias=row['name_aliases'][0];query=sources.translated_query(row['identity'],alias)
                wide=''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in query)
                found=core.catalog_search_internal(db,unicodedata.normalize('NFD',wide),set_code=row['identity']['set_code'],limit=100)
                self.assertIn(row['identity']['card_id'],[c['card_id'] for c in found['cards']])
                wrong=core.catalog_search_internal(db,query,language='en' if row['identity']['language']=='ja' else 'ja',limit=100)
                self.assertNotIn(row['identity']['card_id'],[c['card_id'] for c in wrong['cards']])
            old={table:history.records(db,table) for table in history.tables(db)}
            self.assertEqual(core.import_concept_review_bundle(db,bundle),dict(review_events=0,concept_revisions=0))
            self.assertEqual(catalog_locale.import_evidence(db,rows),dict(inserted=0,unchanged=114,quarantined=0))
            self.assertEqual(old,{table:history.records(db,table) for table in history.tables(db)})
            self.assertFalse(any(row['display_allowed'] or row['purchase_allowed'] or row['price_comparable'] for row in rows))
        with self.assertRaisesRegex(ValueError,'outside reviewed Kanto'):names.metadata((self.repo/self.source_records[18][2]).read_bytes())

    def test_missing_uncertain_or_expanded_semantic_scope_is_rejected(self):
        self.review['approved_pairs']=24;self.refresh()
        with self.assertRaisesRegex(ValueError,'semantic approval'):self.compile()
        self.review['approved_pairs']=25;self.review['uncertain_pairs']=['Synthetic uncertainty'];self.refresh()
        with self.assertRaisesRegex(ValueError,'semantic approval'):self.compile()
        self.review['uncertain_pairs']=[]
        self.packet['johto_semantic_review_tranche']['proposals'][0]['dex_id']=252;self.refresh()
        with self.assertRaisesRegex(ValueError,'exact 25 reviewed'):self.compile()

    def test_english_identity_or_release_header_drift_aborts_without_publication(self):
        self.packet['next_concrete_draft']['english_witnesses'][0]['identity']['collector_number']='999/100';self.refresh()
        with self.assertRaises(ValueError):self.compile()

    def test_frozen_release_header_or_name_witness_cannot_be_rebound(self):
        for field,value in [('git_blob','0'*40),('sha256','0'*64)]:
            packet=copy.deepcopy(self.packet)
            self.packet['next_concrete_draft']['english_witnesses'][0]['release_source'][field]=value;self.refresh()
            with self.assertRaisesRegex(ValueError,'release header'):self.compile()
            self.packet=packet
        self.packet['next_concrete_draft']['english_witnesses'][0]['source']['native_id']='data/OTHER/001.ts';self.refresh()
        with self.assertRaisesRegex(ValueError,'witness pin'):self.compile()

    def test_singleton_name_policy_rejects_missing_fields_multi_dex_and_unreviewed_forms(self):
        pair=self.packet['johto_semantic_review_tranche']['proposals'][0]
        path=pair['ja']['source']['native_id'];raw=(self.repo/path).read_bytes();dex=pair['dex_id']
        for changed in [raw.replace(f'dexId:[{dex}]'.encode(),b'dexId:[]'),
                        raw.replace(f'dexId:[{dex}]'.encode(),f'dexId:[{dex},151]'.encode()),
                        raw.replace(b'category:"Pokemon"',b'category:"Trainer"')]:
            with self.assertRaises(ValueError):compiler.johto_metadata(changed,pair)
        unreviewed={**pair,'name_ja':'パルデア '+pair['name_ja'],'name_en':'Paldean '+pair['name_en']}
        with self.assertRaisesRegex(ValueError,'unreviewed Johto'):compiler.johto_metadata(raw,unreviewed)

    def test_approval_only_clears_exact_semantic_hold_and_never_grants_rights(self):
        original=copy.deepcopy(self.packet)
        self.packet['johto_semantic_review_tranche']['proposals'][0]['unresolved_conflicts'].append('Unresolved source identity conflict');self.refresh()
        with self.assertRaisesRegex(ValueError,'conflicted name'):self.compile()
        self.packet=copy.deepcopy(original)
        self.packet['next_concrete_draft']['english_witnesses'][0]['display_allowed']=True;self.refresh()
        with self.assertRaisesRegex(ValueError,'cannot grant'):self.compile()
        self.packet=copy.deepcopy(original)
        self.packet['next_concrete_draft']['english_witnesses'][0]['source']['rights_status']='display_and_purchase_allowed';self.refresh()
        with self.assertRaisesRegex(ValueError,'source rights'):self.compile()

    def test_nonliteral_source_variants_are_held_instead_of_projected(self):
        with self.assertRaisesRegex(ValueError,'literal source variant'):self.compile()

    def test_complete_group_missing_or_new_unqualified_sibling_is_rejected(self):
        target=self.packet['next_concrete_draft']['unapproved_new_name_witnesses'][0]['identity']
        self.db.execute('INSERT INTO card SELECT ?,language,set_code,collector_number,?,name,rarity,provenance,rights_reference,display_allowed,match_eligible,attributes_json FROM card WHERE card_id=?',
            (target['card_id']+'_unreviewed','normal_unreviewed',target['card_id']))
        self.db.execute('INSERT INTO card_classification SELECT ?,category,subtype,provenance,rights_reference FROM card_classification WHERE card_id=?',
            (target['card_id']+'_unreviewed',target['card_id']));self.refresh()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.compile()

    def test_review_only_abstains_and_source_mapping_collision_quarantines(self):
        bundle,rows,*_=self.compile();after=self.root/'collision.sqlite3';after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            core.import_concept_review_bundle(db,bundle)
            row=next(r for r in rows if r['identity']['language']=='ja' and r['character_scope']['dex_id']>151)
            lookup=resolver.resolve_question(db,facts(row,row['name_aliases'][0]['name_en']))
            self.assertEqual(lookup['reason'],'reviewed_name_record_binding_required');self.assertEqual(lookup['resolution']['candidate_ids'],[])
            src=row['source'];mapping=tuple(src[k] for k in catalog_locale.SOURCE_FIELDS)
            db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',(*mapping,self.records['english'][0]));db.commit()
            self.assertEqual(catalog_locale.import_evidence(db,[row])['quarantined'],1)
            self.assertEqual(db.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0],0)

    def test_variant_ambiguity_and_cross_language_records_remain_distinct(self):
        bundle,rows,*_=self.compile();after=self.root/'ambiguity.sqlite3';after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            core.import_concept_review_bundle(db,bundle);catalog_locale.import_evidence(db,rows)
            row=next(r for r in rows if r['identity']['language']=='ja' and r['character_scope']['dex_id']>151 and r['identity']['variant']=='normal')
            query=facts(row,row['name_aliases'][0]['name_en']);query['identity_tokens']['finish']=None
            result=resolver.resolve_question(db,query)
            self.assertEqual(result['resolution']['status'],'multiple_candidates')
            self.assertEqual(set(result['resolution']['candidate_ids']),{r['identity']['card_id'] for r in rows
                if r['identity']['language']=='ja' and r['identity']['set_code']==row['identity']['set_code'] and r['identity']['collector_number']==row['identity']['collector_number']})
            self.assertTrue(all(cid.startswith('ja:') for cid in result['resolution']['candidate_ids']))
            self.assertEqual(db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],114)
            for table in ('card_relationship_assertion','priceable_unit','listing','observation','verified_sale'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_source_bytes_or_late_review_drift_prevents_output(self):
        path=self.repo/self.source_records[0][2];path.write_text(path.read_text()+'\n// changed synthetic cache\n')
        output=self.root/'output'
        with self.assertRaises(ValueError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_late_review_or_cache_drift_after_compilation_prevents_publication(self):
        compiled=self.compile();output=self.root/'late_output'
        with patch.object(compiler,'compile',return_value=compiled):
            self.review_path.write_text(self.review_path.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'publication inputs'):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())
        self.review_path.write_bytes(compiled[-1])
        with patch.object(compiler,'compile',return_value=compiled):
            path=self.repo/self.source_records[0][2];path.write_text(path.read_text()+'\n// synthetic drift after compilation\n')
            with self.assertRaises(ValueError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_whole_artifact_publication_retains_exact_review_and_unknown_times(self):
        output=self.root/'published_pilot'
        result=compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertEqual((result['japanese'],result['english']),(89,25))
        self.assertEqual({p.name for p in output.iterdir()}, {'concept-review-bundle.json','selection.json','locales.jsonl','basis-qualification.json','semantic-review.json','TCGDEX-LICENSE'})
        self.assertEqual((output/'basis-qualification.json').read_bytes(),self.packet_path.read_bytes())
        self.assertEqual((output/'semantic-review.json').read_bytes(),self.review_path.read_bytes())
        bundle=json.loads((output/'concept-review-bundle.json').read_text())
        self.assertTrue(all(e['review']['semantic_reviewed_at'] is None and e['review']['requires_card_binding'] for e in bundle['review_events']))
        before={p.name:p.read_bytes() for p in output.iterdir()}
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()},before)

    def test_exclusive_atomic_publication_refuses_even_empty_existing_destination(self):
        temporary=self.root/'publish_source';temporary.mkdir();(temporary/'proof').write_text('synthetic')
        existing=self.root/'occupied';existing.mkdir()
        with self.assertRaises(FileExistsError):compiler.publish_exclusive(temporary,existing)
        self.assertTrue((temporary/'proof').is_file());self.assertEqual(list(existing.iterdir()),[])
        destination=self.root/'published';compiler.publish_exclusive(temporary,destination)
        self.assertEqual((destination/'proof').read_text(),'synthetic');self.assertFalse(temporary.exists())


def ast_literal_dex(source):
    import ast
    fields=compiler.header_fields(source,declaration_name='card',declaration_type='Card')
    return ast.literal_eval(fields['dexId'])[0]


if __name__ == '__main__':unittest.main()
