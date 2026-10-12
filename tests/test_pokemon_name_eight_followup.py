"""Disposable synthetic pins and approvals; no real acquisition or model call."""
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
from scripts import build_pokemon_name_eight_followup as compiler
from scripts import build_pokemon_name_coverage as kanto
from scripts import build_pokemon_name_johto_pilot as johto
from scripts import build_pokemon_name_followup as previous
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts
from scripts.pokemon_release_witness import inspect_release
from scripts.qualify_international_product_documents import git_tree


class PokemonNameEightFollowupTests(unittest.TestCase):
    TIME = '2026-10-12T16:00:00Z'
    REVIEW_TIME = '2026-10-12T15:00:00Z'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.repo = self.root/'synthetic-source'; self.repo.mkdir()
        (self.repo/'LICENSE').write_text('Synthetic test-only metadata licence\n')
        (self.root/'catalog').mkdir(); (self.root/'catalog/TCGDEX-LICENSE').write_bytes((self.repo/'LICENSE').read_bytes())
        ja_numbers = {173:('SM12A','096',173),187:('SM12A','004',173),188:('SM12A','005',173),
            189:('SM12A','006',173),213:('SM12A','007',173),218:('SM8B','010',150),
            219:('SM8B','011',150),236:('SM12A','068',173)}
        en_numbers = {173:('SV03','080',197,'normal'),187:('SV02','001',193,'normal'),
            188:('SV02','002',193,'normal'),189:('SV02','003',193,'holo'),213:('SV03','005',197,'normal'),
            218:('SV05','028',162,'normal'),219:('SV05','029',162,'holo'),236:('ME01','071',132,'normal')}
        self.sources = []; self.headers = {}
        for dex,ja,en in sorted(compiler.PAIRS):
            for language in ('ja','en'):
                if language == 'ja':code,number,count = ja_numbers[dex]; variant = 'normal'
                else:code,number,count,variant = en_numbers[dex]
                path = f'{"data-asia" if language=="ja" else "data"}/FIX/{code}/{number}.ts'
                variants = f'{{type:"{variant}"}}' + (',{type:"reverse"}' if language=='en' else '')
                raw = (f'const card: Card = {{name:{{ja:"{ja}",en:"{en}"}},category:"Pokemon",dexId:[{dex}],'
                    f'rarity:"Common",variants:[{variants}],image:"https://synthetic.invalid/shared-art"}}; export default card;')
                target = self.repo/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(raw)
                self.sources.append((language,code,path,raw,count,dex))
                self.headers[(language,code)] = (str(Path(path).parent)+'.ts',count)
        for (language,code),(path,count) in self.headers.items():
            (self.repo/path).write_text(f'const fixtureRelease: Set = {{id:"{code}",name:{{ja:"Synthetic release",en:"Synthetic release"}},'
                f'cardCount:{{official:{count}}},releaseDate:{{ja:"2026-10-01",en:"2026-10-02"}}}}; export default fixtureRelease;')
        for command in (['git','init','-q'],['git','add','.'],
                ['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','synthetic-only eight-name fixtures']):
            subprocess.run(command,cwd=self.repo,check=True,capture_output=True)
        self.revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()
        self.rights = f'https://github.com/tcgdex/cards-database/blob/{self.revision}/LICENSE'
        # Only this new module's immutable fixture bindings change in tests.
        # No legacy helper's pair/Dex policy or runtime implementation is patched.
        for key,value in [('REVISION',self.revision),('RIGHTS',self.rights)]:
            mock = patch.object(compiler,key,value); mock.start(); self.addCleanup(mock.stop)
        self.before = self.root/'before.sqlite3'; self.db = core.connect(self.before); core.init_db(self.db); self.addCleanup(self.db.close)
        for (language,code),(path,count) in self.headers.items():
            core.import_sets(self.db,[dict(language=language,set_code=code,name='Synthetic release',official_card_count=count,
                release_date='2026-10-01' if language=='ja' else '2026-10-02',
                provenance=f'tcgdex:{self.revision}:{path}',rights_reference=self.rights)])
        self.ids = dict(ja=[],en=[])
        for language,code,path,raw,count,dex in self.sources:
            for card in tcgdex_source.parse_card_source(raw,set_id=code,official_count=count,path=path,revision=self.revision,language=language):
                core.import_cards(self.db,[card]); cid = core.card_id(language,code,card['collector_number'],card['variant'])
                self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,card['provenance'],self.rights))
                if cid in compiler.JAPANESE_IDS | compiler.ENGLISH_IDS:self.ids[language].append(cid)
        holds_path = Path(__file__).resolve().parents[1]/'catalog/variant-dimension-holds-v1/holds.jsonl'
        holds = [json.loads(line) for line in holds_path.read_text().splitlines()]
        core.import_cards(self.db,[dict(row['identity'],match_eligible=row['prior_structural_match_eligible']) for row in holds])
        variant_dimension_hold.import_evidence(self.db,holds)
        self.add_retained_concepts()
        self.db.commit()
        paths = {r[2] for r in self.sources}|{h[0] for h in self.headers.values()}|{'LICENSE'}
        self.blobs = git_tree(self.repo,sorted(paths),revision=self.revision)
        self.raws = {p:(self.repo/p).read_bytes() for p in paths}
        self.releases = {}
        for release in self.db.execute('SELECT * FROM catalog_set_localized ORDER BY language,set_code'):
            release = dict(release); path = self.headers[(release['language'],release['set_code'])][0]
            self.releases[(release['language'],release['set_code'])] = dict(snapshot=release,
                **self.source_witness(path),facts=inspect_release(release,self.raws[path]),
                **{k:False for k in catalog_locale.FALSE_CLAIMS})
        japanese = [self.witness(cid) for cid in sorted(self.ids['ja'])]
        english = [self.witness(cid) for cid in self.ids['en']]
        proposals = []
        for dex,ja,en in sorted(compiler.PAIRS):
            jw = next(w for w in japanese if w['identity']['name']==ja); ew = next(w for w in english if w['identity']['name']==en)
            proposals.append(dict(dex_id=dex,name_ja=ja,name_en=en,ja=jw,en=ew,potential_ja_bindings=[jw],
                semantic_approved=False,approved_concept_id=None,unresolved_source_conflicts=[],
                unresolved_conflicts=[compiler.PENDING_SEMANTIC_REVIEW],**{k:False for k in catalog_locale.FALSE_CLAIMS}))
        audit = []
        for c in self.db.execute('SELECT * FROM bilingual_concept_revision ORDER BY concept_id'):
            event = json.loads(self.db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(c['review_event_id'],)).fetchone()[0])
            audit.append(dict(concept_id=c['concept_id'],revision=c['revision'],name_ja=c['name_ja'],name_en=c['name_en'],
                review_event_id=c['review_event_id'],dex_id=event['proposal']['source_snapshot']['frozen']['dex_id'],requires_exact_card_binding=True))
        self.packet = dict(schema='pokemon.stage18-eight-source-qualification.v1',applied=False,
            input_database_sha256=compiler.signature(self.before.read_bytes()),source_pin=self.revision,rights_reference=self.rights,
            current_localized_bindings=0,current_source_mappings=0,current_bound_card_ids_sha256=compiler.signature(b'[]'),
            current_concept_audit=audit,current_approved_pokemon_full_name_concepts=len(audit),identity_holds_preserved=44,
            license_sha256=compiler.signature(self.raws['LICENSE']),source_inventory_entry_count=len(paths),maximum_authorized_source_entries=100,
            source_inventory={p:dict(**self.source_witness(p),kind='license' if p=='LICENSE' else 'card' if p in {r[2] for r in self.sources} else 'release_header',available=True) for p in sorted(paths)},
            parsing_source_sha256={k:compiler.signature((Path(compiler.__file__).resolve().parents[1]/p).read_bytes()) for k,p in compiler.CODE_INPUTS.items()},
            johto_semantic_review_tranche=dict(proposals=proposals),
            next_concrete_draft=dict(japanese_records=8,english_comparison_records=8,existing_review_witnesses=[],
                unapproved_new_name_witnesses=japanese,english_witnesses=english,card_ids=sorted(self.ids['ja']),
                by_set=dict(Counter(w['identity']['set_code'] for w in japanese)),**{k:False for k in catalog_locale.FALSE_CLAIMS}),
            five_image_targets_excluded=sorted(previous.EXPANDED_IMAGE_TARGETS),localized_release_source_witnesses=list(self.releases.values()),
            demand='Synthetic test-only; unmeasured',authorized_supply='Synthetic test-only metadata',**{k:False for k in catalog_locale.FALSE_CLAIMS})
        self.review = dict(schema='pokemon.independent-name-review.v1',reviewer='GPT-6.1 Sol high',decision='approve_all_exact_pairs',
            approved_pairs=8,approved_exact_pairs=[dict(dex_id=d,name_ja=j,name_en=e) for d,j,e in sorted(compiler.PAIRS)],
            rejected_pairs=[],uncertain_pairs=[],approved_into_catalog=False,sources_fetched=False,
            review_completed_at=self.REVIEW_TIME,review_completed_at_status='attested_by_UTC_clock_after_independent_review',
            historical_retrieved_at=None,historical_retrieval_status='historical_snapshot_time_not_recorded',
            scope='Synthetic test-only approval fixture; no real model or clock attestation occurred')
        self.packet_path = self.root/'qualification.json'; self.review_path = self.root/'semantic.json'
        self.refresh()

    def add_retained_concepts(self):
        events,concepts = [],[]
        pairs = [(1,'テスト前名','Synthetic Prior')]+[sorted(johto.JOHTO_PAIRS)[0]]
        for dex,ja,en in pairs:
            frozen = dict(proposal_id=f'synthetic:retained:{dex}',category='Pokemon',name_ja=ja,name_en=en,dex_id=dex,
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only')
            snapshot = dict(frozen=frozen,ja_provenance='synthetic:ja',en_provenance='synthetic:en')
            proposal = dict(**frozen,source_snapshot=snapshot,source_snapshot_sha256=kanto.spaced_digest(snapshot),
                ja_provenance='synthetic:ja',en_provenance='synthetic:en')
            review = dict(decision='approve',review_revision=1,reviewer='synthetic:test-only',reviewed_at=self.REVIEW_TIME,
                evidence_note='Synthetic retained concept fixture',ja_identity_checked=True,en_identity_checked=True,
                translation_checked=True,requires_card_binding=True)
            event = dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review); event['event_id'] = kanto.spaced_digest(event); events.append(event)
            concepts.append(dict(concept_id=f'synthetic:retained:{dex}',revision=1,category='Pokemon',name_ja=ja,name_en=en,
                source_ja='synthetic:ja',source_en='synthetic:en',rights_reference='synthetic:test-only',reviewer='synthetic:test-only',
                reviewed_at=self.REVIEW_TIME,status='approved',review_event_id=event['event_id']))
        core.import_concept_review_bundle(self.db,dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts))

    def source_witness(self,path):
        raw = self.raws[path]
        return dict(provider='tcgdex',native_id=path,revision=self.revision,git_blob=self.blobs[path],sha256=compiler.signature(raw),
            bytes=len(raw),rights_reference=self.rights,rights_status='metadata_internal_reviewed',license_sha256=compiler.signature(self.raws['LICENSE']),
            retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=self.TIME,physical_distribution_region=None)

    def witness(self,cid):
        card = catalog_locale.snapshot(self.db,cid); path,_ = compiler.source_fields(card)
        fields = compiler.header_fields(self.raws[path].decode(),declaration_name='card',declaration_type='Card')
        dex = int(fields['dexId'].strip('[]'))
        release = self.releases[(card['language'],card['set_code'])]
        w = dict(identity=card,dex_id=dex,localized_names=kanto.names(fields['name']),source=self.source_witness(path),
            release_snapshot=release['snapshot'],release_source=release,literal_variant_structure_verified=True,literal_nonempty_variants=True,
            variant_dimension_losses=[],source_tuple_reconstructed_eligible=True,source_rarity='Common',
            existing_localized_binding=False,semantic_approved=False,approved_concept_id=None,unresolved_source_conflicts=[],
            unresolved_conflicts=[compiler.PENDING_SEMANTIC_REVIEW],**{k:False for k in catalog_locale.FALSE_CLAIMS})
        if card['language']=='ja':w.update(eligible_unbound_sibling_ids=[cid],complete_eligible_unbound_group=True)
        return w

    def refresh(self):
        self.db.commit(); self.packet['input_database_sha256'] = compiler.signature(self.before.read_bytes())
        self.packet_path.write_text(json.dumps(self.packet,ensure_ascii=False,indent=2)+'\n')
        self.review['proposal_sha256'] = compiler.signature(self.packet_path.read_bytes())
        self.review_path.write_text(json.dumps(self.review,ensure_ascii=False,indent=2)+'\n')
        for key,value in [('BEFORE_SHA',self.packet['input_database_sha256']),('PACKET_SHA',self.review['proposal_sha256']),
                ('REVIEW_SHA',compiler.signature(self.review_path.read_bytes()))]:
            mock = patch.object(compiler,key,value); mock.start(); self.addCleanup(mock.stop)

    def compile(self):
        return compiler.compile(self.before,self.repo,self.root,self.packet_path,self.review_path,self.TIME)

    def inspect_synthetic_changed_source(self,witness,raw):
        witness = copy.deepcopy(witness); path = witness['source']['native_id']; cid = witness['identity']['card_id']
        scratch = self.root/'synthetic-changed.sqlite3'; scratch.write_bytes(self.before.read_bytes())
        raws = dict(self.raws); raws[path] = raw
        blobs = dict(self.blobs); blobs[path] = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        witness['source'].update(sha256=compiler.signature(raw),git_blob=blobs[path],bytes=len(raw))
        witness['identity']['provenance'] = f'tcgdex:{self.revision}:{path}:sha256:{compiler.signature(raw)}'
        with closing(core.connect(scratch)) as db:
            db.execute('UPDATE card SET provenance=? WHERE card_id=?',(witness['identity']['provenance'],cid)); db.commit()
            pair = next(p for p in self.packet['johto_semantic_review_tranche']['proposals'] if p['dex_id']==witness['dex_id'])
            return compiler.inspect_witness(db,witness,raws,blobs,pair=pair)

    def test_exact_append_unicode_search_ids_history_and_idempotence(self):
        before_bytes = self.before.read_bytes(); bundle,rows,selection,*_ = self.compile()
        self.assertEqual((len(bundle['review_events']),len(bundle['concept_revisions']),len(rows)),(8,8,16))
        self.assertEqual(selection['concepts_without_record_bindings_abstain'],16)
        self.assertEqual(selection['japanese_coordinate_groups'],8)
        self.assertTrue(all(selection['historical_tables_preserved'].values()))
        self.assertEqual(selection['idempotent_reimport'],dict(concepts=dict(review_events=0,concept_revisions=0),locales=dict(inserted=0,unchanged=16,quarantined=0)))
        after = self.root/'after.sqlite3'; after.write_bytes(before_bytes)
        with closing(core.connect(after)) as db:
            cards = history.records(db,'card'); core.import_concept_review_bundle(db,bundle)
            self.assertEqual(catalog_locale.import_evidence(db,rows),dict(inserted=16,unchanged=0,quarantined=0))
            self.assertEqual(history.records(db,'card'),cards)
            for row in rows:
                query = compiler.translated_query(row['identity'],row['name_aliases'][0])
                wide = ''.join(chr(ord(c)+0xFEE0) if '!'<=c<='~' else '\u3000' if c==' ' else c for c in query)
                found = core.catalog_search_internal(db,unicodedata.normalize('NFD',wide),set_code=row['identity']['set_code'],limit=100)
                self.assertIn(row['identity']['card_id'],[c['card_id'] for c in found['cards']])
                wrong = core.catalog_search_internal(db,query,language='en' if row['identity']['language']=='ja' else 'ja',limit=100)
                self.assertNotIn(row['identity']['card_id'],[c['card_id'] for c in wrong['cards']])
                self.assertTrue(all(row[k] is False for k in catalog_locale.FALSE_CLAIMS))
            self.assertEqual(len(variant_dimension_hold.rows_for(db)),44)
        self.assertEqual(self.before.read_bytes(),before_bytes)

    def test_missing_uncertain_or_wrong_semantic_pairs_are_rejected(self):
        original = copy.deepcopy(self.review)
        for key,value in [('approved_pairs',7),('uncertain_pairs',['synthetic uncertainty']),('decision','pending'),
                ('approved_exact_pairs',self.review['approved_exact_pairs'][:-1]),('review_completed_at',None)]:
            self.review = copy.deepcopy(original); self.review[key] = value; self.refresh()
            with self.assertRaises(ValueError):self.compile()

    def test_actual_review_time_remains_distinct_from_inspection_and_retrieval(self):
        bundle,rows,*_ = self.compile()
        for event in bundle['review_events']:
            self.assertEqual(event['review']['reviewed_at'],self.TIME)
            self.assertEqual(event['review']['semantic_reviewed_at'],self.REVIEW_TIME)
            self.assertEqual(event['review']['semantic_review_time_status'],'recorded_in_independent_approval_packet')
        self.assertTrue(all(r['source']['retrieved_at'] is None for r in rows))
        self.review['review_completed_at'] = '2026-10-13T15:00:00Z'; self.refresh()
        with self.assertRaisesRegex(ValueError,'predates'):self.compile()

    def test_wrong_frozen_name_dex_or_existing_review_scope_is_rejected(self):
        self.packet['johto_semantic_review_tranche']['proposals'][0]['dex_id'] = 172; self.refresh()
        with self.assertRaisesRegex(ValueError,'exact 8 reviewed'):self.compile()

    def test_legacy_kanto_and_twenty_five_policies_are_unchanged(self):
        pair = self.packet['johto_semantic_review_tranche']['proposals'][0]; raw = self.raws[pair['ja']['source']['native_id']]
        with self.assertRaisesRegex(ValueError,'outside reviewed Kanto'):kanto.metadata(raw)
        with self.assertRaisesRegex(ValueError,'unreviewed Johto'):johto.johto_metadata(raw,pair)
        self.assertEqual(len(johto.JOHTO_PAIRS),25); self.assertFalse(compiler.PAIRS & johto.JOHTO_PAIRS)

    def test_missing_fields_multi_dex_and_forms_abstain(self):
        pair = self.packet['johto_semantic_review_tranche']['proposals'][0]; raw = self.raws[pair['ja']['source']['native_id']]; dex = pair['dex_id']
        for changed in [raw.replace(f'dexId:[{dex}]'.encode(),b'dexId:[]'),raw.replace(f'dexId:[{dex}]'.encode(),f'dexId:[{dex},151]'.encode()),
                raw.replace(b'category:"Pokemon"',b'category:"Trainer"'),raw.replace(b'category:"Pokemon",',b'')]:
            with self.assertRaises(ValueError):compiler.eight_metadata(changed,pair)
        form = dict(pair,name_ja='パルデア '+pair['name_ja'],name_en='Paldean '+pair['name_en'])
        with self.assertRaisesRegex(ValueError,'unreviewed eight'):compiler.eight_metadata(raw,form)

    def test_missing_nonliteral_or_projected_source_variants_remain_held(self):
        w = self.packet['next_concrete_draft']['english_witnesses'][0]; raw = self.raws[w['source']['native_id']]
        for replacement in [b'',b'variants:[],',b'variants:[{type:"normal"},...otherVariants],',
                b'variants:[{type:dynamicType}],',b'variants:[{type:"normal",size:"jumbo"}],',
                b'variants:[{type:"normal",edition:"unknown"}],']:
            changed = raw.replace(b'variants:[{type:"normal"},{type:"reverse"}],',replacement)
            with self.assertRaises(ValueError):self.inspect_synthetic_changed_source(w,changed)

    def test_source_foil_stamp_and_promo_coordinates_cannot_fall_back(self):
        w = self.packet['next_concrete_draft']['english_witnesses'][0]; raw = self.raws[w['source']['native_id']]
        for replacement in [b'variants:[{type:"normal",foil:"cosmos"}],',b'variants:[{type:"normal",stamp:["Prerelease"]}],',
                b'variants:[{type:"holo"}],']:
            with self.assertRaisesRegex(ValueError,'tuple'):self.inspect_synthetic_changed_source(w,raw.replace(b'variants:[{type:"normal"},{type:"reverse"}],',replacement))
        changed = copy.deepcopy(w); changed['identity']['collector_number'] = '080/SVP'; self.packet['next_concrete_draft']['english_witnesses'][0] = changed; self.refresh()
        with self.assertRaises(ValueError):self.compile()

    def test_source_eligibility_assertions_and_source_conflicts_are_mandatory(self):
        original = copy.deepcopy(self.packet)
        for key,value in [('literal_nonempty_variants',False),('source_tuple_reconstructed_eligible',False),
                ('unresolved_source_conflicts',['ambiguous source']),('unresolved_conflicts',['unresolved printing'])]:
            self.packet = copy.deepcopy(original); self.packet['next_concrete_draft']['english_witnesses'][0][key] = value; self.refresh()
            with self.assertRaises(ValueError):self.compile()

    def test_release_name_date_count_hash_and_missing_localized_date_reject(self):
        w = self.packet['next_concrete_draft']['english_witnesses'][0]; release = w['release_source']; raw = self.raws[release['native_id']]
        for changed in [raw.replace(b'Synthetic release',b'Incorrect release'),raw.replace(b'2026-10-02',b'2026-10-03'),
                raw.replace(b'official:197',b'official:198'),raw.replace(b',en:"2026-10-02"',b'')]:
            with self.assertRaises(ValueError):inspect_release(w['release_snapshot'],changed)
        release['sha256'] = '0'*64; self.refresh()
        with self.assertRaisesRegex(ValueError,'release header'):self.compile()

    def test_rights_or_source_path_drift_cannot_be_approved(self):
        original = copy.deepcopy(self.packet)
        for field,value in [('rights_status','display_allowed'),('rights_reference','synthetic:unreviewed'),
                ('native_id','data/Pocket/001.ts'),('retrieved_at',self.TIME),('physical_distribution_region','JP')]:
            self.packet = copy.deepcopy(original); self.packet['next_concrete_draft']['english_witnesses'][0]['source'][field] = value; self.refresh()
            with self.assertRaises(ValueError):self.compile()
        self.packet = copy.deepcopy(original); self.packet['display_allowed'] = True; self.refresh()
        with self.assertRaisesRegex(ValueError,'cannot grant'):self.compile()

    def test_unselected_repeated_number_or_shared_artwork_never_merge(self):
        bundle,rows,*_ = self.compile(); after = self.root/'shared.sqlite3'; after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            core.import_concept_review_bundle(db,bundle); catalog_locale.import_evidence(db,rows)
            ja = next(r for r in rows if r['identity']['card_id']=='ja:SM12A:004/173:normal')
            result = resolver.resolve_question(db,facts(ja,'Hoppip'))
            self.assertEqual(result['resolution']['candidate_ids'],[ja['identity']['card_id']])
            self.assertEqual(db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],16)
            for table in ('card_relationship_assertion','priceable_unit','listing','observation','verified_sale','source_image_fact_evidence'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            # Same number in a different release is a separate existing identity.
            sibling = dict(ja['identity'],set_code='SM8B',card_id='ja:SM8B:004/173:normal')
            core.import_cards(db,[dict(sibling,match_eligible=True)])
            result = resolver.resolve_question(db,facts(ja,'Hoppip'))
            self.assertEqual(result['resolution']['candidate_ids'],[ja['identity']['card_id']])

    def test_incomplete_whole_group_and_unqualified_sibling_reject(self):
        target = self.packet['next_concrete_draft']['unapproved_new_name_witnesses'][0]['identity']; cid = target['card_id']+'_stamp'
        self.db.execute('INSERT INTO card SELECT ?,language,set_code,collector_number,?,name,rarity,provenance,rights_reference,display_allowed,match_eligible,attributes_json FROM card WHERE card_id=?',
            (cid,'normal_prerelease',target['card_id']))
        self.db.execute('INSERT INTO card_classification SELECT ?,category,subtype,provenance,rights_reference FROM card_classification WHERE card_id=?',(cid,target['card_id'])); self.refresh()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.compile()

    def test_review_without_exact_binding_abstains_and_mapping_collision_quarantines(self):
        bundle,rows,*_ = self.compile(); after = self.root/'collision.sqlite3'; after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            core.import_concept_review_bundle(db,bundle); row = rows[0]
            result = resolver.resolve_question(db,facts(row,row['name_aliases'][0]['name_en']))
            self.assertEqual(result['reason'],'reviewed_name_record_binding_required'); self.assertEqual(result['resolution']['candidate_ids'],[])
            values = tuple(row['source'][k] for k in catalog_locale.SOURCE_FIELDS)
            db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',(*values,self.ids['en'][0])); db.commit()
            self.assertEqual(catalog_locale.import_evidence(db,[row]),dict(inserted=0,unchanged=0,quarantined=1))
            self.assertEqual(db.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0],0)

    def test_english_reverse_sibling_is_not_bound_by_normal_comparison(self):
        bundle,rows,*_ = self.compile(); after = self.root/'unbound_reverse.sqlite3'; after.write_bytes(self.before.read_bytes())
        with closing(core.connect(after)) as db:
            core.import_concept_review_bundle(db,bundle); catalog_locale.import_evidence(db,rows)
            for row in [r for r in rows if r['identity']['language']=='en']:
                reverse = dict(row['identity'],card_id=row['identity']['card_id'].rsplit(':',1)[0]+':reverse',variant='reverse')
                self.assertEqual(catalog_locale.snapshot(db,reverse['card_id']),reverse)
                self.assertIsNone(db.execute('SELECT 1 FROM catalog_locale_evidence WHERE card_id=?',(reverse['card_id'],)).fetchone())
                scoped = dict(row,identity=reverse)
                result = resolver.resolve_question(db,facts(scoped,row['name_aliases'][0]['name_ja']))
                self.assertNotIn(reverse['card_id'],result['resolution']['candidate_ids'])

    def test_current_audit_drift_rejects(self):
        self.packet['current_concept_audit'][0]['dex_id'] = 999; self.refresh()
        with self.assertRaisesRegex(ValueError,'concept inventory'):self.compile()

    def test_same_name_concept_collision_requires_explicit_revision_review(self):
        proposals = self.packet['johto_semantic_review_tranche']['proposals']
        self.db.execute('UPDATE bilingual_concept_revision SET name_en=? WHERE concept_id=?',
            (proposals[0]['name_en'],self.packet['current_concept_audit'][0]['concept_id'])); self.db.commit()
        with self.assertRaisesRegex(ValueError,'colliding name concept'):
            compiler.review_bundle(self.db,proposals,self.raws,self.blobs,compiler.signature(self.raws['LICENSE']),
                compiler.signature(self.review_path.read_bytes()),self.TIME,self.REVIEW_TIME)

    def test_frozen_source_collision_aborts_compilation_and_publication(self):
        bundle,rows,*_ = self.compile(); row = rows[0]
        namespace = tuple(row['source'][k] for k in catalog_locale.SOURCE_FIELDS)
        held_id = variant_dimension_hold.rows_for(self.db)[0]['identity']['card_id']
        self.db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',(*namespace,held_id)); self.db.commit()
        self.packet['current_source_mappings'] = 1
        self.packet['current_bound_card_ids_sha256'] = compiler.signature(json.dumps([held_id],ensure_ascii=False,separators=(',',':')).encode())
        self.refresh(); output = self.root/'collision_output'
        with self.assertRaisesRegex(ValueError,'provider source collision'):
            compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_late_compiler_dependency_drift_prevents_publication(self):
        compiled = self.compile(); output = self.root/'late_dependency'
        frozen_reader = compiler.compiler_inputs
        def changed_inputs():
            result = frozen_reader(); path = Path(core.__file__).resolve()
            result[path] += b'\n// synthetic in-memory dependency drift\n'; return result
        with patch.object(compiler,'compile',return_value=compiled), patch.object(compiler,'compiler_inputs',side_effect=changed_inputs):
            with self.assertRaisesRegex(ValueError,'source,licence,parser'):
                compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_source_packet_database_or_parser_drift_prevents_publication(self):
        path = self.repo/self.sources[0][2]; path.write_text(path.read_text()+'\n// synthetic drift\n'); output = self.root/'output'
        with self.assertRaises(ValueError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_frozen_packet_database_and_parser_bindings_detect_drift(self):
        self.packet_path.write_text(self.packet_path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'frozen'):self.compile()
        self.refresh(); self.db.execute('UPDATE card SET display_allowed=1 WHERE card_id=?',(self.ids['ja'][0],)); self.db.commit()
        with self.assertRaisesRegex(ValueError,'immutable input database'):self.compile()
        self.refresh(); self.packet['parsing_source_sha256']['tcgdex_source'] = '0'*64; self.refresh()
        with self.assertRaisesRegex(ValueError,'parser checkpoint'):self.compile()

    def test_late_review_or_cache_drift_prevents_atomic_publication(self):
        compiled = self.compile(); output = self.root/'late_output'
        with patch.object(compiler,'compile',return_value=compiled):
            self.review_path.write_text(self.review_path.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'publication inputs'):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists()); self.review_path.write_bytes(compiled[-1])
        with patch.object(compiler,'compile',return_value=compiled):
            path = self.repo/self.sources[0][2]; path.write_text(path.read_text()+'\n// synthetic cache drift\n')
            with self.assertRaises(ValueError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertFalse(output.exists())

    def test_six_file_atomic_exclusive_artifacts_and_unknown_acquisition(self):
        output = self.root/'published'; result = compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertEqual((result['japanese'],result['english'],result['exact_name_pairs']),(8,8,8))
        self.assertEqual({p.name for p in output.iterdir()},{'concept-review-bundle.json','selection.json','locales.jsonl','basis-qualification.json','semantic-review.json','TCGDEX-LICENSE'})
        self.assertEqual((output/'basis-qualification.json').read_bytes(),self.packet_path.read_bytes())
        self.assertEqual((output/'semantic-review.json').read_bytes(),self.review_path.read_bytes())
        before = {p.name:p.read_bytes() for p in output.iterdir()}
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,self.packet_path,self.review_path,output,self.TIME)
        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()},before)
        temporary = self.root/'temporary_publish'; temporary.mkdir(); occupied = self.root/'occupied'; occupied.mkdir()
        with self.assertRaises(FileExistsError):compiler.publish_exclusive(temporary,occupied)
        self.assertTrue(temporary.exists()); self.assertEqual(list(occupied.iterdir()),[])


if __name__ == '__main__':unittest.main()
