"""Hundred-record immutable profiles, with synthetic pinned metadata only."""
import copy
import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale
from scripts import audit_pokemon_name_followup as audit
from scripts import audit_pokemon_name_modern as modern_audit
from scripts import build_pokemon_name_followup as compiler
from scripts import build_pokemon_name_modern as modern
from scripts.build_international_coverage_expansion import source_fields
from scripts.qualify_international_product_documents import git_tree
from tests import test_pokemon_name_followup as fixtures


class PokemonNameModernTests(unittest.TestCase):
    def setUp(self):
        # Reuse the local Git fixture, not its test methods. Ten fixture scopes
        # initially have 105 records; remove 5 complete one-record groups to get 100.
        p=patch.object(compiler,'SETS',modern.PROFILE.sets);p.start();self.addCleanup(p.stop)
        fixture=fixtures.PokemonNameFollowupTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.root,self.repo,self.db,self.before,self.TIME=fixture.root,fixture.repo,fixture.db,fixture.before,fixture.TIME
        old=json.loads(fixture.plan_bytes)
        for item in old['records'][100:]:
            self.db.execute('DELETE FROM card_classification WHERE card_id=?',(item['card']['card_id'],))
            self.db.execute('DELETE FROM card_number_context WHERE card_id=?',(item['card']['card_id'],))
            self.db.execute('DELETE FROM card WHERE card_id=?',(item['card']['card_id'],))
        self.db.commit()
        cards=old['records'][:100]
        all_aliases={}
        paths={'LICENSE'}
        for item in cards:
            alias,dex=compiler.current_alias(self.db,item['card']);all_aliases[item['card']['card_id']]=(alias,dex)
            paths.add(source_fields(item['card'])[0])
        blobs=git_tree(self.repo,sorted(paths),revision=compiler.REVISION)
        licence_sha=hashlib.sha256((self.repo/'LICENSE').read_bytes()).hexdigest()
        proposals=[]
        for item in cards:
            card=item['card'];alias,dex=all_aliases[card['card_id']];path,sha=source_fields(card)
            proposals.append(dict(identity=card,name_alias=alias,dex_id=dex,status='source_qualified_proposed_unapplied',
                source_revision=compiler.REVISION,native_id=path,git_blob=blobs[path],sha256=sha,
                rights_reference=card['rights_reference'],license_sha256=licence_sha,
                **{k:False for k in catalog_locale.FALSE_CLAIMS}))
        self.plan=self.root/modern.PROFILE.plan;self.plan.parent.mkdir(parents=True,exist_ok=True)
        self.plan.write_text(json.dumps(dict(schema='pokemon.followup-next-batch-plan.v1',applied=False,
            proposed_japanese_records=100,english_comparison_target=25,proposals=proposals),ensure_ascii=False,indent=2)+'\n')
        self.raw=self.plan.read_bytes()
        self.profile=replace(modern.PROFILE,plan_sha=hashlib.sha256(self.raw).hexdigest(),
                             before_sha=hashlib.sha256(self.before.read_bytes()).hexdigest())

    def compile(self):return compiler.compile(self.before,self.repo,self.root,self.TIME,profile=self.profile)

    def changed_plan(self,change):
        plan=json.loads(self.raw);change(plan);raw=json.dumps(plan,ensure_ascii=False).encode()
        return raw,replace(self.profile,plan_sha=hashlib.sha256(raw).hexdigest())

    def test_profile_is_immutable_bounded_and_has_safe_paths_hashes(self):
        self.assertEqual(modern.PROFILE.japanese,100);self.assertEqual(len(modern.PROFILE.sets),10)
        with self.assertRaises(FrozenInstanceError):self.profile.japanese=101
        for change in (dict(japanese=101),dict(japanese=True),dict(directory='/outside'),dict(plan='../outside'),
                       dict(plan_sha='missing'),dict(before_sha='0'*63),dict(plan_schema='unsupported'),dict(sets=('A','A','B'))):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(self.profile,**change)
        with self.assertRaisesRegex(ValueError,'validated'):compiler.profile_or_default({})

    def test_proposed_schema_requires_exact_hash_counts_language_and_false_rights(self):
        self.assertEqual(len(compiler.checked_plan(self.raw,profile=self.profile)['records']),100)
        with self.assertRaises(ValueError):compiler.checked_plan(self.raw+b' ',profile=self.profile)
        changes=(lambda p:p.update(proposed_japanese_records=100.0),lambda p:p.update(english_comparison_target=25.0),
                 lambda p:p['proposals'][0].update(dex_id=True),lambda p:p['proposals'][0].update(display_allowed=True),
                 lambda p:p['proposals'][0]['identity'].update(language='fr'),lambda p:p['proposals'].pop())
        for change in changes:
            raw,profile=self.changed_plan(change)
            with self.subTest(change=change),self.assertRaises(ValueError):compiler.checked_plan(raw,profile=profile)

    def test_frozen_alias_revision_cannot_be_substituted_even_with_same_names(self):
        raw,profile=self.changed_plan(lambda p:p['proposals'][0]['name_alias'].update(revision=2))
        plan=compiler.checked_plan(raw,profile=profile)
        with self.assertRaisesRegex(ValueError,'name/Dex review'):compiler.planned_japanese(self.db,plan)

    def test_frozen_git_blob_or_licence_witness_cannot_be_rehashed_away(self):
        for field in ('git_blob','license_sha256','native_id'):
            raw,profile=self.changed_plan(lambda p:p['proposals'][0].update({field:'changed'}))
            self.plan.write_bytes(raw)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'source witness'):
                compiler.compile(self.before,self.repo,self.root,self.TIME,profile=profile)
        self.plan.write_bytes(self.raw)

    def test_hundred_compilation_is_disjoint_exact_and_preserves_input_bytes(self):
        old=self.before.read_bytes();rows,selection,licence,raw=self.compile()
        self.assertEqual(len(rows),125);self.assertEqual(selection['japanese'],100);self.assertEqual(selection['english'],25)
        self.assertEqual(len({r['identity']['card_id'] for r in rows}),125)
        self.assertEqual(selection['new_concepts'],0);self.assertEqual(raw,self.raw)
        self.assertEqual(self.before.read_bytes(),old)
        for row in rows:
            for flag in catalog_locale.FALSE_CLAIMS:self.assertIs(row[flag],False)

    def test_compiler_and_audit_profiles_must_agree(self):
        self.assertEqual(audit.settings_for(self.profile,modern_audit.AUDIT_PROFILE)[0],self.profile)
        with self.assertRaisesRegex(ValueError,'scope differs'):audit.settings_for(self.profile,audit.PROFILE)
        with self.assertRaises(ValueError):audit.settings_for(self.profile,{})
        with self.assertRaises(ValueError):audit.settings_for({},modern_audit.AUDIT_PROFILE)

    def test_audit_enforces_frozen_review_and_source_proof(self):
        rows,_,_,_=self.compile();plan=compiler.checked_plan(self.raw,profile=self.profile)
        audit.checked_name_scopes(rows,plan)
        for field in ('git_blob','license_sha256','revision'):
            changed=copy.deepcopy(rows);changed[0]['source'][field]='changed'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'source witness'):
                audit.checked_name_scopes(changed,plan)
        changed=copy.deepcopy(rows)
        # Alter every occurrence of the first concept, so English inclusion alone
        # cannot hide a stale Japanese review-event reference.
        cid=changed[0]['name_aliases'][0]['concept_id']
        for row in changed:
            if row['name_aliases'][0]['concept_id']==cid:row['name_aliases'][0]['review_event_id']='0'*64
        with self.assertRaisesRegex(ValueError,'alias revision'):audit.checked_name_scopes(changed,plan)

    def test_default_profile_keeps_legacy_schema_and_does_not_widen_scope(self):
        default=compiler.profile_or_default(None)
        self.assertEqual(default.japanese,85);self.assertEqual(default.plan_schema,'pokemon.name-coverage-next-batch.v1')
        self.assertEqual(default.directory,'catalog/international-pokemon-followup-v1')
        self.assertIs(audit.PROFILE.allow_bound_name_resolution_growth,True)

    def test_profile_outputs_are_exclusive_and_input_drift_blocks_publication(self):
        output=self.root/'artifact';compiler.build(self.before,self.repo,self.root,output,self.TIME,profile=self.profile)
        with self.assertRaises(FileExistsError):compiler.build(self.before,self.repo,self.root,output,self.TIME,profile=self.profile)
        with self.assertRaisesRegex(ValueError,'database differs'):
            compiler.build(self.before,self.repo,self.root,self.root/'other',self.TIME,profile=replace(self.profile,before_sha='0'*64))
        self.assertFalse((self.root/'other').exists())


if __name__=='__main__':unittest.main()
