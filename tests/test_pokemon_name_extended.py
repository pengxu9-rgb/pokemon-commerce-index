"""The next frozen hundred-record scope, using only synthetic local metadata."""
import copy
import hashlib
import json
import unittest
from collections import defaultdict
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from itertools import zip_longest
from unittest.mock import patch

from pokemon_index import catalog_locale, core
from scripts import build_pokemon_name_followup as compiler
from scripts import build_pokemon_name_extended as extended
from scripts import build_pokemon_name_modern as modern
from scripts import audit_pokemon_name_followup as audit
from scripts import audit_pokemon_name_extended as extended_audit
from scripts import audit_pokemon_name_modern as modern_audit
from scripts import audit_international_coverage_expansion as history
from scripts.build_international_coverage_expansion import source_fields
from scripts.qualify_international_product_documents import git_tree
from tests import test_pokemon_name_followup as fixtures


class PokemonNameExtendedTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(compiler,'SETS',extended.PROFILE.sets);p.start();self.addCleanup(p.stop)
        fixture=fixtures.PokemonNameFollowupTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.root,self.repo,self.db,self.before,self.TIME=fixture.root,fixture.repo,fixture.db,fixture.before,fixture.TIME
        old=json.loads(fixture.plan_bytes);groups=defaultdict(list)
        for item in old['records']:groups[item['card']['set_code']].append(item)
        cards=[item for group in zip_longest(*(groups[code] for code in extended.PROFILE.sets))
               for item in group if item is not None][:100]
        kept={item['card']['card_id'] for item in cards}
        for item in old['records']:
            if item['card']['card_id'] in kept:continue
            for table in ('card_classification','card_number_context','card'):
                self.db.execute('DELETE FROM '+table+' WHERE card_id=?',(item['card']['card_id'],))
        self.db.commit()
        paths={source_fields(item['card'])[0] for item in cards}|{'LICENSE'}
        blobs=git_tree(self.repo,sorted(paths),revision=compiler.REVISION)
        licence_sha=hashlib.sha256((self.repo/'LICENSE').read_bytes()).hexdigest()
        proposals=[]
        for item in cards:
            card=item['card'];alias,dex=compiler.current_alias(self.db,card);path,sha=source_fields(card)
            proposals.append(dict(identity=card,name_alias=alias,dex_id=dex,status='source_qualified_proposed_unapplied',
                source_revision=compiler.REVISION,native_id=path,git_blob=blobs[path],sha256=sha,
                rights_reference=card['rights_reference'],license_sha256=licence_sha,
                **{k:False for k in catalog_locale.FALSE_CLAIMS}))
        self.plan=self.root/extended.PROFILE.plan;self.plan.parent.mkdir(parents=True,exist_ok=True)
        self.plan.write_text(json.dumps(dict(schema='pokemon.followup-next-batch-plan.v1',applied=False,
            proposed_japanese_records=100,english_comparison_target=25,proposals=proposals),ensure_ascii=False,indent=2)+'\n')
        self.raw=self.plan.read_bytes()
        self.profile=replace(extended.PROFILE,plan_sha=hashlib.sha256(self.raw).hexdigest(),
                             before_sha=hashlib.sha256(self.before.read_bytes()).hexdigest())

    def compile(self):return compiler.compile(self.before,self.repo,self.root,self.TIME,profile=self.profile)

    def changed_plan(self,change):
        plan=json.loads(self.raw);change(plan);raw=json.dumps(plan,ensure_ascii=False).encode()
        return raw,replace(self.profile,plan_sha=hashlib.sha256(raw).hexdigest())

    def test_new_profile_is_fixed_and_prior_profiles_remain_unchanged(self):
        self.assertEqual((extended.PROFILE.japanese,len(extended.PROFILE.sets)),(100,12))
        self.assertEqual(extended_audit.AUDIT_PROFILE.prior_inputs,74)
        self.assertEqual((modern.PROFILE.japanese,len(modern.PROFILE.sets)),(100,10))
        self.assertEqual(compiler.profile_or_default(None).japanese,85)
        with self.assertRaises(FrozenInstanceError):self.profile.japanese=101

    def test_all_twelve_scopes_compile_disjointly_with_false_claims(self):
        old=self.before.read_bytes();rows,selection,licence,raw=self.compile()
        self.assertEqual((selection['japanese'],selection['english']),(100,25))
        self.assertEqual(len({row['identity']['card_id'] for row in rows}),125)
        self.assertEqual({row['identity']['set_code'] for row in rows if row['identity']['language']=='ja'},set(self.profile.sets))
        self.assertEqual(selection['new_card_identities'],0);self.assertEqual(selection['new_concepts'],0)
        self.assertEqual(self.before.read_bytes(),old);self.assertEqual(raw,self.raw)
        for row in rows:
            for flag in catalog_locale.FALSE_CLAIMS:self.assertIs(row[flag],False)

    def test_other_set_underfill_duplicate_or_rights_claim_cannot_rehash_scope(self):
        for change in (lambda p:p['proposals'][0]['identity'].update(set_code='OUTSIDE'),
                       lambda p:p['proposals'].pop(),lambda p:p['proposals'].__setitem__(1,p['proposals'][0]),
                       lambda p:p['proposals'][0].update(purchase_allowed=True)):
            raw,profile=self.changed_plan(change)
            with self.subTest(change=change),self.assertRaises(ValueError):compiler.checked_plan(raw,profile=profile)

    def test_current_alias_revision_and_pinned_witness_are_mandatory(self):
        raw,profile=self.changed_plan(lambda p:p['proposals'][0]['name_alias'].update(revision=2))
        with self.assertRaisesRegex(ValueError,'name/Dex review'):
            compiler.planned_japanese(self.db,compiler.checked_plan(raw,profile=profile))
        raw,profile=self.changed_plan(lambda p:p['proposals'][0].update(git_blob='0'*40))
        self.plan.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'source witness'):
            compiler.compile(self.before,self.repo,self.root,self.TIME,profile=profile)

    def test_eligible_stamped_sibling_cannot_be_omitted(self):
        plan=compiler.checked_plan(self.raw,profile=self.profile);card=copy.deepcopy(plan['records'][0]['card'])
        card.update(variant='normal-stamped',display_allowed=False,match_eligible=True)
        core.import_cards(self.db,[card]);cid=core.card_id('ja',card['set_code'],card['collector_number'],card['variant'])
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',(cid,'Pokemon',None,'synthetic:test-only','fixture'))
        with self.assertRaisesRegex(ValueError,'sibling'):compiler.planned_japanese(self.db,plan)

    def test_wrapper_publication_is_exclusive_and_rejects_wrong_database(self):
        output=self.root/'compiled'
        with patch.object(extended,'PROFILE',self.profile):
            extended.build(self.before,self.repo,self.root,output,self.TIME)
            with self.assertRaises(FileExistsError):extended.build(self.before,self.repo,self.root,output,self.TIME)
        with patch.object(extended,'PROFILE',replace(self.profile,before_sha='0'*64)):
            with self.assertRaisesRegex(ValueError,'database differs'):
                extended.build(self.before,self.repo,self.root,self.root/'wrong',self.TIME)
        self.assertFalse((self.root/'wrong').exists())

    def test_audit_uses_exact_profile_and_frozen_source_scope(self):
        self.assertEqual(audit.settings_for(self.profile,extended_audit.AUDIT_PROFILE)[0],self.profile)
        with self.assertRaisesRegex(ValueError,'scope differs'):audit.settings_for(self.profile,modern_audit.AUDIT_PROFILE)
        rows,_,_,_=self.compile();plan=compiler.checked_plan(self.raw,profile=self.profile)
        audit.checked_name_scopes(rows,plan)
        changed=copy.deepcopy(rows);changed[0]['source']['revision']='unreviewed'
        with self.assertRaisesRegex(ValueError,'source witness'):audit.checked_name_scopes(changed,plan)

    def test_import_and_idempotence_preserve_all_historical_tables(self):
        rows,_,_,_=self.compile()
        with closing(core.connect(self.root/'copy.sqlite3')) as before:
            self.db.backup(before)
            self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=125,unchanged=0,quarantined=0))
            self.assertTrue(all(history.preserved(before,self.db,125).values()))
        values={table:history.records(self.db,table) for table in history.tables(self.db)}
        self.assertEqual(catalog_locale.import_evidence(self.db,rows),dict(inserted=0,unchanged=125,quarantined=0))
        for table,old in values.items():self.assertEqual(history.records(self.db,table),old)


if __name__=='__main__':unittest.main()
