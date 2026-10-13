"""Thousand-record disposable fixtures, never real acquisitions or approvals."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, tcgdex_source, variant_dimension_hold
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_scale as compiler
from scripts import build_pokemon_name_coverage as names
from scripts import build_pokemon_name_followup as previous
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts
from scripts.pokemon_release_witness import inspect_release
from scripts.qualify_international_product_documents import git_tree


class PokemonNameScaleTests(unittest.TestCase):
    TIME='2026-10-13T16:00:00Z'
    REVIEW_TIME='2026-10-13T15:00:00Z'

    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temporary.cleanup)
        cls.root=Path(cls.temporary.name);cls.repo=cls.root/'synthetic-source';cls.repo.mkdir()
        (cls.repo/'LICENSE').write_text('Synthetic test-only metadata licence\n')
        (cls.root/'catalog').mkdir();(cls.root/'catalog/TCGDEX-LICENSE').write_bytes((cls.repo/'LICENSE').read_bytes())
        cls.triples=[(1,'試験既存名','Fixture Existing'),(1,'試験既存名ex','Fixture Existing ex')]+[(252+i,'試験新名'+chr(0x4e00+i),'Fixture New '+str(i)) for i in range(6)]
        cls.sources=[];cls.headers={}
        for lang,codes,numbers in [('ja',('TESTJA1','TESTJA2','TESTJA3','TESTJA4'),100),('en',('TESTEN1','TESTEN2'),50)]:
            for code in codes:
                for number in range(1,numbers+1):
                    dex,ja,en=cls.triples[(number-1)%8]
                    p=f'{"data-asia" if lang=="ja" else "data"}/FIX/{code}/{number:03}.ts'
                    raw=f'const card: Card = {{name:{{ja:"{ja}",en:"{en}"}},category:"Pokemon",dexId:[{dex}],rarity:"Common",variants:[{{type:"normal"}},{{type:"reverse"}}],image:"https://synthetic.invalid/shared"}}; export default card;'
                    target=cls.repo/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(raw)
                    cls.sources.append((lang,code,p,raw,dex));cls.headers[(lang,code)]=str(Path(p).parent)+'.ts'
        for (lang,code),p in cls.headers.items():
            (cls.repo/p).write_text(f'const fixtureRelease: Set = {{id:"{code}",name:{{ja:"Synthetic release",en:"Synthetic release"}},cardCount:{{official:999}},releaseDate:{{ja:"2026-10-01",en:"2026-10-02"}}}}; export default fixtureRelease;')
        for command in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','synthetic-only thousand-name batch fixture']):
            subprocess.run(command,cwd=cls.repo,check=True,capture_output=True)
        cls.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cls.repo,text=True).strip()
        cls.rights=f'https://github.com/tcgdex/cards-database/blob/{cls.revision}/LICENSE'
        paths={r[2] for r in cls.sources}|set(cls.headers.values())|{'LICENSE'}
        cls.blobs=git_tree(cls.repo,sorted(paths),revision=cls.revision);cls.raws={p:(cls.repo/p).read_bytes() for p in paths}
        cls.before=cls.root/'before.sqlite3'
        with closing(core.connect(cls.before)) as db:
            core.init_db(db)
            for (lang,code),p in cls.headers.items():
                core.import_sets(db,[dict(language=lang,set_code=code,name='Synthetic release',official_card_count=999,
                    release_date='2026-10-01' if lang=='ja' else '2026-10-02',provenance=f'tcgdex:{cls.revision}:{p}',rights_reference=cls.rights)])
            for lang,code,p,raw,dex in cls.sources:
                cards=tcgdex_source.parse_card_source(raw,set_id=code,official_count=999,path=p,revision=cls.revision,language=lang)
                core.import_cards(db,cards)
                for card in cards:
                    cid=core.card_id(lang,code,card['collector_number'],card['variant'])
                    db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,card['provenance'],cls.rights))
                    db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,'dex_id',str(dex),card['provenance'],cls.rights))
            holds_path=Path(compiler.__file__).resolve().parents[1]/'catalog/variant-dimension-holds-v1/holds.jsonl'
            holds=[json.loads(line) for line in holds_path.read_text().splitlines()]
            core.import_cards(db,[dict(r['identity'],match_eligible=r['prior_structural_match_eligible']) for r in holds]);variant_dimension_hold.import_evidence(db,holds)
            cls.releases={}
            for r in db.execute('SELECT * FROM catalog_set_localized ORDER BY language,set_code'):
                r=dict(r);p=cls.headers[(r['language'],r['set_code'])]
                cls.releases[(r['language'],r['set_code'])]=dict(snapshot=r,**cls.source(p),facts=inspect_release(r,cls.raws[p]),**compiler.claims())
            rows=[dict(r) for r in db.execute("SELECT c.* FROM card c JOIN card_classification cl USING(card_id) WHERE c.language IN ('ja','en') AND c.set_code LIKE 'TEST%' ORDER BY card_id")]
            cls.events=[];cls.concepts=[]
            for index in range(196):
                if index<2:dex,ja,en=cls.triples[index]
                else:dex=(index%151)+1;ja='未選択旧名'+str(index);en='Unselected Existing '+str(index)
                cid=f'synthetic:existing:{index:03}';witnesses={}
                if index<2:
                    for lang in ('ja','en'):
                        card=next({k:r[k] for k in catalog_locale.IDENTITY_FIELDS} for r in rows if r['language']==lang and r['name']==(ja if lang=='ja' else en))
                        p=card['provenance'].split(':',2)[2].split(':sha256:')[0]
                        witnesses[lang]=dict(identity=card,**cls.source(p),category='Pokemon',dex_id=dex,release_snapshot=cls.releases[(lang,card['set_code'])]['snapshot'])
                frozen=dict(proposal_id=cid,category='Pokemon',name_ja=ja,name_en=en,dex_id=dex,source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only')
                snapshot=dict(frozen=frozen,ja_provenance='synthetic:ja',en_provenance='synthetic:en',witnesses=witnesses)
                proposal=dict(**frozen,source_snapshot=snapshot,source_snapshot_sha256=names.spaced_digest(snapshot),ja_provenance='synthetic:ja',en_provenance='synthetic:en')
                review=dict(decision='approve',review_revision=1,reviewer='synthetic:test-only',reviewed_at=cls.REVIEW_TIME,ja_identity_checked=True,en_identity_checked=True,
                    translation_checked=True,requires_card_binding=True,evidence_note='Synthetic historical exact-scope fixture; no real model',**compiler.claims())
                event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review);event['event_id']=names.spaced_digest(event);cls.events.append(event)
                cls.concepts.append(dict(concept_id=cid,revision=1,category='Pokemon',name_ja=ja,name_en=en,source_ja='synthetic:ja',source_en='synthetic:en',
                    rights_reference='synthetic:test-only',reviewer='synthetic:test-only',reviewed_at=cls.REVIEW_TIME,status='approved',review_event_id=event['event_id']))
            core.import_concept_review_bundle(db,dict(schema='pokemon.concept_review_bundle.v1',review_events=cls.events,concept_revisions=cls.concepts))
            alias={k:cls.concepts[0][k] for k in compiler.ALIAS_FIELDS}
            core.import_sets(db,[dict(language='ja',set_code='HIST',name='Synthetic historical',official_card_count=9999,release_date='2026-01-01',provenance='synthetic:historical',rights_reference=cls.rights)])
            rel=dict(db.execute("SELECT * FROM catalog_set_localized WHERE language='ja' AND set_code='HIST'").fetchone());historical=[]
            for i in range(2412):
                p=f'data-asia/FIX/HIST/{i+1:04}.ts';digest=compiler.signature(f'Synthetic already-bound historical record {i}'.encode())
                card=dict(language='ja',set_code='HIST',collector_number=f'{i+1:04}/9999',variant='normal',name=alias['name_ja'],rarity='Common',
                    provenance=f'tcgdex:{cls.revision}:{p}:sha256:{digest}',rights_reference=cls.rights,match_eligible=True,display_allowed=False)
                core.import_cards(db,[card]);cid=core.card_id('ja','HIST',card['collector_number'],'normal')
                db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,card['provenance'],cls.rights))
                row=dict(schema='pokemon.catalog-locale.v1',identity=catalog_locale.snapshot(db,cid),source=dict(provider='tcgdex',language='ja',region='ZZ',release_id='tcgdex-product:HIST',
                    native_id=p,source_variant='normal',revision=cls.revision,sha256=digest,rights_reference=cls.rights,rights_status='metadata_internal_reviewed',
                    retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=cls.TIME),release_snapshot=rel,name_aliases=[alias],confidence=1.0,
                    unresolved_conflicts=[],test_only=False,**compiler.claims())
                row['evidence_id']='catalog-locale:'+catalog_locale.digest(row);historical.append(row)
            cls.assert_counts(catalog_locale.import_evidence(db,historical),dict(inserted=2412,unchanged=0,quarantined=0));db.commit()
            audit=[]
            for c in cls.concepts:
                e=next(e for e in cls.events if e['event_id']==c['review_event_id'])
                audit.append(dict(concept_id=c['concept_id'],revision=1,name_ja=c['name_ja'],name_en=c['name_en'],review_event_id=c['review_event_id'],
                    dex_id=e['proposal']['source_snapshot']['frozen']['dex_id'],requires_exact_card_binding=True,
                    review_record_sha256=compiler.signature(catalog_locale.encoded(e).encode())))
            japanese=[];english=[]
            for r in rows:
                card={k:r[k] for k in catalog_locale.IDENTITY_FIELDS};p=card['provenance'].split(':',2)[2].split(':sha256:')[0]
                fields=compiler.header_fields(cls.raws[p].decode(),declaration_name='card',declaration_type='Card');dex=ast_literal(fields['dexId'])[0]
                w=dict(identity=card,dex_id=dex,localized_names=names.names(fields['name']),source=cls.source(p),release_snapshot=cls.releases[(card['language'],card['set_code'])]['snapshot'],
                    release_source=cls.releases[(card['language'],card['set_code'])],source_rarity='Common',literal_variant_structure_verified=True,literal_nonempty_variants=True,
                    variant_dimension_losses=[],source_tuple_reconstructed_eligible=True,unresolved_source_conflicts=[],unresolved_conflicts=[],**compiler.claims())
                if card['name'] in {c['name_'+card['language']] for c in cls.concepts[:2]}:
                    c=next(c for c in cls.concepts[:2] if c['name_'+card['language']]==card['name']);w['name_alias']={k:c[k] for k in compiler.ALIAS_FIELDS}
                else:w['unresolved_conflicts']=[compiler.PENDING_SEMANTIC_REVIEW]
                (japanese if card['language']=='ja' else english).append(w)
            existing=[w for w in japanese if w.get('name_alias')];new=[w for w in japanese if not w.get('name_alias')];proposals=[]
            for dex,ja,en in cls.triples[2:]:
                potential=[w for w in new if w['identity']['name']==ja];ew=next(w for w in english if w['identity']['name']==en)
                proposals.append(dict(dex_id=dex,name_ja=ja,name_en=en,ja=potential[0],en=ew,potential_ja_bindings=potential,
                    unresolved_source_conflicts=[],unresolved_conflicts=[compiler.PENDING_SEMANTIC_REVIEW],**compiler.claims()))
            counts=dict(ja=800,en=200,total=1000,newpairs=6,existing_ja=len(existing),new_ja=len(new),existing_en=sum(bool(w.get('name_alias')) for w in english),new_en=sum(not w.get('name_alias') for w in english))
            cls.packet=dict(schema='pokemon.stage19-scale-source-qualification.v1',applied=False,input_database_sha256=compiler.signature(cls.before.read_bytes()),source_pin=cls.revision,
                rights_reference=cls.rights,license_sha256=compiler.signature(cls.raws['LICENSE']),current_localized_bindings=2412,current_source_mappings=2412,
                current_bound_card_ids_sha256=catalog_locale.digest(sorted(previous.bound_ids(db))),current_approved_pokemon_full_name_concepts=196,current_concept_audit=audit,
                source_inventory={p:dict(**cls.source(p),available=True) for p in sorted(paths)},
                parsing_source_sha256={k:compiler.signature((Path(compiler.__file__).resolve().parents[1]/p).read_bytes()) for k,p in compiler.CODE_INPUTS.items()},
                existing_review_witnesses=existing,new_name_witnesses=new,english_witnesses=english,new_name_proposals=proposals,
                selection_counts=counts,selected_card_ids=sorted(w['identity']['card_id'] for w in japanese+english),
                five_image_targets_excluded=sorted(previous.EXPANDED_IMAGE_TARGETS),identity_holds_preserved=44,
                existing_semantic_reviews=[dict(name_alias={k:c[k] for k in compiler.ALIAS_FIELDS},
                    event_record_sha256=compiler.signature(db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(c['review_event_id'],)).fetchone()[0].encode()),
                    source_snapshot_sha256=next(e['proposal']['source_snapshot_sha256'] for e in cls.events if e['event_id']==c['review_event_id'])) for c in cls.concepts[:2]],
                demand='Synthetic; unmeasured',authorized_supply='Synthetic test-only metadata',**compiler.claims())
        cls.review=dict(schema='pokemon.independent-name-review.v1',reviewer='GPT-6.1 Sol high',decision='approve_all_exact_pairs',approved_pairs=6,
            approved_exact_pairs=[dict(dex_id=d,name_ja=j,name_en=e) for d,j,e in cls.triples[2:]],rejected_pairs=[],uncertain_pairs=[],approved_into_catalog=False,sources_fetched=False,
            review_completed_at=cls.REVIEW_TIME,review_completed_at_status='attested_by_UTC_clock_after_independent_review',historical_retrieved_at=None,
            historical_retrieval_status='historical_snapshot_time_not_recorded',scope='Synthetic test-only approval fixture; no real model or clock attestation')

    @staticmethod
    def assert_counts(actual,expected):
        if actual!=expected:raise AssertionError((actual,expected))

    @classmethod
    def source(cls,p):
        raw=cls.raws[p]
        return dict(provider='tcgdex',native_id=p,revision=cls.revision,git_blob=cls.blobs[p],sha256=compiler.signature(raw),bytes=len(raw),rights_reference=cls.rights,
            rights_status='metadata_internal_reviewed',license_sha256=compiler.signature(cls.raws['LICENSE']),retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',
            inspected_at=cls.TIME,physical_distribution_region=None)

    def setUp(self):
        self.case=tempfile.TemporaryDirectory();self.addCleanup(self.case.cleanup);self.case_root=Path(self.case.name)
        self.packet=copy.deepcopy(type(self).packet);self.review=copy.deepcopy(type(self).review)
        self.packet_path=self.case_root/'qualification.json';self.review_path=self.case_root/'review.json'
        self.refresh()
        for key,value in [('REVISION',self.revision),('RIGHTS',self.rights)]:
            mock=patch.object(compiler,key,value);mock.start();self.addCleanup(mock.stop)

    def refresh(self):
        self.packet_path.write_text(json.dumps(self.packet,ensure_ascii=False)+'\n');self.review['proposal_sha256']=compiler.signature(self.packet_path.read_bytes())
        self.review_path.write_text(json.dumps(self.review,ensure_ascii=False)+'\n')
        for key,value in [('PACKET_SHA',self.review['proposal_sha256']),('REVIEW_SHA',compiler.signature(self.review_path.read_bytes())),
            ('BEFORE_SHA',self.packet['input_database_sha256']),('BATCH_COUNTS',self.packet['selection_counts'])]:
            mock=patch.object(compiler,key,value);mock.start();self.addCleanup(mock.stop)

    def compile(self,db=None):return compiler.compile(db or self.before,self.repo,self.root,self.packet_path,self.review_path,self.TIME)

    def test_real_thousand_record_flow_keeps_ids_history_rights_and_idempotence(self):
        original=self.before.read_bytes();bundle,rows,selection,*_=self.compile()
        self.assertEqual((len(bundle['review_events']),len(rows)),(6,1000));self.assertTrue(all(selection['historical_tables_preserved'].values()))
        self.assertEqual(selection['concepts_without_record_bindings_abstain'],1000)
        self.assertEqual(selection['idempotent_reimport'],dict(concepts=dict(review_events=0,concept_revisions=0),locales=dict(inserted=0,unchanged=1000,quarantined=0)))
        self.assertEqual(self.before.read_bytes(),original)
        after=self.case_root/'after.sqlite3';after.write_bytes(original)
        with closing(core.connect(after)) as db:
            cards=history.records(db,'card');compiler.install_indexes(db);core.import_concept_review_bundle(db,bundle);catalog_locale.import_evidence(db,rows)
            self.assertEqual(history.records(db,'card'),cards)
            with closing(core.connect(self.before,readonly=True)) as before:self.assertTrue(compiler.schema_preserved(before,db))
            for row in rows[::53]:
                q=compiler.translated_query(row['identity'],row['name_aliases'][0]);wide=''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in q)
                found=core.catalog_search_internal(db,unicodedata.normalize('NFD',wide),language=row['identity']['language'],set_code=row['identity']['set_code'],limit=100)
                self.assertIn(row['identity']['card_id'],[r['card_id'] for r in found['cards']]);self.assertTrue(all(row[k] is False for k in catalog_locale.FALSE_CLAIMS))
            for table in ('card_relationship_assertion','priceable_unit','listing','observation','verified_sale','source_image_fact_evidence'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        type(self).compiled=(bundle,rows,selection,*_[0:])

    def test_exact_pair_approval_uncertainty_time_and_bounds_are_fail_closed(self):
        baseline=copy.deepcopy(self.review)
        for key,value in [('uncertain_pairs',['synthetic uncertainty']),('approved_pairs',5),('approved_exact_pairs',baseline['approved_exact_pairs'][:-1]),
                ('review_completed_at',None),('review_completed_at_status','unknown'),('sources_fetched',True)]:
            self.review=copy.deepcopy(baseline);self.review[key]=value;self.refresh()
            with self.assertRaises(ValueError):compiler.checked_packet(self.packet_path.read_bytes(),self.review_path.read_bytes())
        self.review=baseline;self.packet['selection_counts']['total']=999;self.refresh()
        with self.assertRaisesRegex(ValueError,'thousand-level'):compiler.checked_packet(self.packet_path.read_bytes(),self.review_path.read_bytes())

    def test_wrong_or_inherited_full_names_dex_language_variant_and_priority_selection_reject(self):
        baseline=copy.deepcopy(self.packet)
        for section,field,value in [('new_name_proposals','dex_id',9999),('new_name_witnesses','language','fr'),('new_name_witnesses','name','Fixture New 0'),
                ('new_name_witnesses','variant','normal_prerelease'),('new_name_witnesses','set_code','SV4A')]:
            self.packet=copy.deepcopy(baseline)
            if section=='new_name_proposals':self.packet[section][0][field]=value
            else:self.packet[section][0]['identity'][field]=value
            self.refresh()
            with self.assertRaises(ValueError):compiler.checked_packet(self.packet_path.read_bytes(),self.review_path.read_bytes())

    def test_metadata_missing_multi_dex_foil_stamp_size_and_unknown_dimensions_hold(self):
        w=self.packet['new_name_witnesses'][0];p=w['source']['native_id'];raw=self.raws[p];dex=w['dex_id'];name=w['identity']['name'];lang=w['identity']['language']
        changes=[raw.replace(f'dexId:[{dex}]'.encode(),b'dexId:[]'),raw.replace(f'dexId:[{dex}]'.encode(),f'dexId:[{dex},1]'.encode()),
            raw.replace(b'category:"Pokemon"',b'category:"Trainer"'),raw.replace(b'variants:[{type:"normal"},{type:"reverse"}],',b''),
            raw.replace(b'{type:"normal"}',b'{type:"normal",size:"jumbo"}'),raw.replace(b'{type:"normal"}',b'{type:"normal",edition:"unknown"}'),
            raw.replace(b'{type:"normal"}',b'{type:variableType}'),raw.replace(b'{type:"normal"}',b'{type:"normal",stamp:variableStamp}')]
        for changed in changes:
            with self.assertRaises(ValueError):compiler.literal_metadata(changed,dex,name,lang)
        with self.assertRaisesRegex(ValueError,'native full name'):compiler.literal_metadata(raw,dex,name+'ex',lang)
        self.assertTrue(compiler.literal_metadata(raw,dex,name,lang)['category']=='Pokemon')

    def test_source_tuple_facet_classification_rights_release_and_current_alias_reject_drift(self):
        baseline=copy.deepcopy(self.packet['existing_review_witnesses'][0]);scope=dict(**baseline['name_alias'],dex_id=baseline['dex_id'])
        with closing(core.connect(self.before,readonly=True)) as db:
            for kind,key,value in [('source','sha256','0'*64),('source','rights_status','display_allowed'),('source','retrieved_at',self.TIME),
                    ('release_source','sha256','0'*64),('identity','variant','holo'),('identity','name',baseline['identity']['name']+'ex')]:
                w=copy.deepcopy(baseline);w[kind][key]=value
                with self.assertRaises(ValueError):compiler.inspect_witness(db,w,self.raws,self.blobs,scope)
            w=copy.deepcopy(baseline);w['source_tuple_reconstructed_eligible']=False
            with self.assertRaisesRegex(ValueError,'assertions'):compiler.inspect_witness(db,w,self.raws,self.blobs,scope)
        scratch=self.case_root/'facet.sqlite3';scratch.write_bytes(self.before.read_bytes())
        with closing(core.connect(scratch)) as db:
            db.execute("UPDATE card_facet SET value='999' WHERE card_id=? AND facet_type='dex_id'",(baseline['identity']['card_id'],));db.commit()
            with self.assertRaisesRegex(ValueError,'facet source'):compiler.inspect_witness(db,baseline,self.raws,self.blobs,scope)

    def test_literal_foil_and_stamp_cannot_reuse_the_same_printing_identity(self):
        baseline=self.packet['new_name_witnesses'][0];scope=next(p for p in self.packet['new_name_proposals'] if p['dex_id']==baseline['dex_id'])
        path=baseline['source']['native_id'];original=self.raws[path]
        for extra in (b',foil:"cosmos"',b',stamp:["Prerelease"]'):
            raw=original.replace(b'{type:"normal"}',b'{type:"normal"'+extra+b'}');w=copy.deepcopy(baseline);raws=dict(self.raws);raws[path]=raw;blobs=dict(self.blobs)
            blobs[path]=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();digest=compiler.signature(raw)
            provenance=f'tcgdex:{self.revision}:{path}:sha256:{digest}';w['identity']['provenance']=provenance;w['source'].update(sha256=digest,git_blob=blobs[path],bytes=len(raw))
            scratch=self.case_root/('foil.sqlite3' if b'foil' in extra else 'stamp.sqlite3');scratch.write_bytes(self.before.read_bytes())
            with closing(core.connect(scratch)) as db:
                cid=w['identity']['card_id']
                for table in ('card','card_classification','card_facet'):db.execute('UPDATE '+table+' SET provenance=? WHERE card_id=?',(provenance,cid))
                db.commit()
                with self.assertRaisesRegex(ValueError,'printing tuple'):compiler.inspect_witness(db,w,raws,blobs,scope)

    def test_retained_raw_record_hash_is_distinct_from_canonical_review_hash(self):
        ref=self.packet['existing_semantic_reviews'][0]
        with closing(core.connect(self.before,readonly=True)) as db:
            raw=db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(ref['name_alias']['review_event_id'],)).fetchone()[0]
            self.assertEqual(ref['event_record_sha256'],compiler.signature(raw.encode()))
            self.assertNotEqual(ref['event_record_sha256'],compiler.signature(catalog_locale.encoded(json.loads(raw)).encode()))
        ref['event_record_sha256']='0'*64;self.refresh()
        with self.assertRaisesRegex(ValueError,'reference hash'):self.compile()

    def test_complete_groups_and_source_collision_preserve_distinct_printings(self):
        scratch=self.case_root/'group.sqlite3';scratch.write_bytes(self.before.read_bytes());target=self.packet['new_name_witnesses'][0]['identity']
        with closing(core.connect(scratch)) as db:
            db.execute('INSERT INTO card SELECT ?,language,set_code,collector_number,?,name,rarity,provenance,rights_reference,display_allowed,match_eligible,attributes_json FROM card WHERE card_id=?',
                (target['card_id']+'_stamp','normal_prerelease',target['card_id']))
            db.execute('INSERT INTO card_classification SELECT ?,category,subtype,provenance,rights_reference FROM card_classification WHERE card_id=?',(target['card_id']+'_stamp',target['card_id']));db.commit()
            with self.assertRaisesRegex(ValueError,'incomplete'):compiler.complete_groups(db,self.packet['existing_review_witnesses']+self.packet['new_name_witnesses'],previous.bound_ids(db))
        with closing(core.connect(self.before,readonly=True)) as db:
            compiler.complete_groups(db,self.packet['existing_review_witnesses']+self.packet['new_name_witnesses'],previous.bound_ids(db))

    def test_retained_mechanic_name_scope_and_legacy_policies_do_not_widen(self):
        with closing(core.connect(self.before,readonly=True)) as db:
            audit,events,aliases=compiler.current_concepts(db,self.packet)
            bare=aliases['synthetic:existing:000'];mechanic=aliases['synthetic:existing:001'];self.assertEqual(bare[1],mechanic[1]);self.assertNotEqual(bare[0]['name_ja'],mechanic[0]['name_ja'])
            w=next(w for w in self.packet['existing_review_witnesses'] if w['identity']['name']==mechanic[0]['name_ja'])
            with self.assertRaisesRegex(ValueError,'full-name/Dex'):compiler.inspect_witness(db,w,self.raws,self.blobs,dict(**bare[0],dex_id=bare[1]))
        w=self.packet['new_name_witnesses'][0]
        with self.assertRaisesRegex(ValueError,'outside reviewed Kanto'):names.metadata(self.raws[w['source']['native_id']])

    def test_lookup_indexes_are_exact_optional_and_leave_hold_guards_intact(self):
        scratch=self.case_root/'indexed.sqlite3';scratch.write_bytes(self.before.read_bytes())
        with closing(core.connect(scratch)) as db,closing(core.connect(self.before,readonly=True)) as before:
            compiler.install_indexes(db);self.assertTrue(compiler.schema_preserved(before,db))
            compiler.install_indexes(db);self.assertTrue(compiler.schema_preserved(before,db))
            db.execute('CREATE INDEX unapproved_extra_index ON card(name)');db.commit()
            with self.assertRaisesRegex(ValueError,'SQL schema'):compiler.schema_preserved(before,db)

    def test_chunked_tree_does_not_exceed_512_paths_or_fetch(self):
        calls=[]
        def fake_tree(repo,paths,revision):
            calls.append(paths);return {p:'f'*40 for p in paths}
        paths=[f'data/FIX/{i:05}.ts' for i in range(1400)]
        with patch.object(compiler,'git_tree',side_effect=fake_tree):self.assertEqual(set(compiler.tree_chunks(self.repo,paths)),set(paths))
        self.assertEqual([len(c) for c in calls],[512,512,376])

    def test_grouped_search_paginates_and_retains_unseen_ids(self):
        w=self.packet['new_name_witnesses'][0];row=dict(identity=w['identity'],name_aliases=[dict(name_en='Fixture New 0',name_ja=w['identity']['name'])]);calls=[]
        def fake_search(db,name,**kwargs):
            calls.append(kwargs['offset']);start=kwargs['offset'];return dict(total=205,cards=[dict(card_id='synthetic:'+str(i)) for i in range(start,min(start+100,205))])
        with closing(core.connect(':memory:')) as db,patch.object(core,'catalog_search_internal',side_effect=fake_search):result=compiler.grouped_search(db,[row,row])
        self.assertEqual(calls,[0,100,200]);self.assertEqual(len(next(iter(result.values()))['card_ids']),205)

    def test_atomic_seven_file_publication_and_late_drift_refuse_overwrite(self):
        compiled=self.compile();output=self.case_root/'published'
        with patch.object(compiler,'compile',return_value=compiled):
            compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        expected={'concept-review-bundle.json','selection.json','locales.jsonl','basis-qualification.json','semantic-review.json','TCGDEX-LICENSE','lookup-indexes.jsonl'}
        self.assertEqual({p.name for p in output.iterdir()},expected)
        self.assertEqual(json.loads((output/'lookup-indexes.jsonl').read_text()),compiler.lookup_indexes.RECORD)
        self.assertEqual((output/'basis-qualification.json').read_bytes(),self.packet_path.read_bytes())
        self.assertEqual((output/'semantic-review.json').read_bytes(),self.review_path.read_bytes())
        before={p.name:p.read_bytes() for p in output.iterdir()}
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertEqual(before,{p.name:p.read_bytes() for p in output.iterdir()})
        occupied=self.case_root/'occupied';occupied.mkdir();temporary=self.case_root/'pending';temporary.mkdir()
        with self.assertRaises(FileExistsError):compiler.publish_exclusive(temporary,occupied)
        self.assertTrue(temporary.exists());self.assertEqual(list(occupied.iterdir()),[])
        late=self.case_root/'late';self.review_path.write_text(self.review_path.read_text()+'\n')
        with patch.object(compiler,'compile',return_value=compiled):
            with self.assertRaisesRegex(ValueError,'publication inputs'):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,late,self.TIME)
        self.assertFalse(late.exists())

    def test_late_census_drift_rejects_publication_without_changing_frozen_sources(self):
        name='synthetic-census.json';path=self.case_root/name;path.write_text('{"synthetic":true}\n')
        self.packet['qualification_census_sha256']={name:compiler.signature(path.read_bytes())};self.refresh()
        compiled=self.compile();path.write_text('{"synthetic":"late drift"}\n');output=self.case_root/'late_census'
        with patch.object(compiler,'compile',return_value=compiled):
            with self.assertRaisesRegex(ValueError,'census drift'):
                compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_no_cross_language_or_mechanic_inheritance_from_matching_dex_or_art(self):
        bundle,rows,*_=self.compile();scratch=self.case_root/'negative.sqlite3';scratch.write_bytes(self.before.read_bytes())
        with closing(core.connect(scratch)) as db:
            compiler.install_indexes(db);core.import_concept_review_bundle(db,bundle);catalog_locale.import_evidence(db,rows)
            row=next(r for r in rows if r['identity']['language']=='ja' and r['identity']['name']=='試験既存名ex')
            own=row['name_aliases'][0]
            wrong=facts(row,'Fixture Existing');result=resolver.resolve_question(db,wrong)
            self.assertNotIn(row['identity']['card_id'],result['resolution']['candidate_ids'])
            right=facts(row,own['name_en']);right['identity_tokens']['language']='en'
            result=resolver.resolve_question(db,right)
            self.assertNotIn(row['identity']['card_id'],result['resolution']['candidate_ids'])
            self.assertEqual(db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],0)

    def test_source_collision_quarantines_instead_of_reusing_another_printing(self):
        bundle,rows,*_=self.compile();scratch=self.case_root/'collision.sqlite3';scratch.write_bytes(self.before.read_bytes())
        with closing(core.connect(scratch)) as db:
            compiler.install_indexes(db);core.import_concept_review_bundle(db,bundle);row=rows[0]
            namespace=tuple(row['source'][k] for k in catalog_locale.SOURCE_FIELDS)
            other=next(r['identity']['card_id'] for r in rows if r['identity']['language']!=row['identity']['language'])
            db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',(*namespace,other));db.commit()
            self.assertEqual(catalog_locale.import_evidence(db,[row]),dict(inserted=0,unchanged=0,quarantined=1))
            self.assertIsNone(db.execute('SELECT 1 FROM catalog_locale_evidence WHERE card_id=?',(row['identity']['card_id'],)).fetchone())

    def test_actual_review_timestamp_database_and_packet_drift_fail(self):
        self.review['review_completed_at']='2026-10-14T15:00:00Z';self.refresh()
        with self.assertRaisesRegex(ValueError,'predates'):self.compile()
        self.review['review_completed_at']=self.REVIEW_TIME;self.refresh()
        scratch=self.case_root/'changed.sqlite3';scratch.write_bytes(self.before.read_bytes())
        with closing(core.connect(scratch)) as db:db.execute("UPDATE card SET display_allowed=1 WHERE card_id=?",(self.packet['new_name_witnesses'][0]['identity']['card_id'],));db.commit()
        with self.assertRaisesRegex(ValueError,'immutable input'):self.compile(scratch)
        self.packet_path.write_text(self.packet_path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'frozen scale'):self.compile()


def ast_literal(value):
    import ast
    return ast.literal_eval(value)


if __name__=='__main__':unittest.main()
