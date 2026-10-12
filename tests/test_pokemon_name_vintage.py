"""Next bounded profile uses independent synthetic fixtures and prior guards."""
import unittest
from unittest.mock import patch
from scripts import build_pokemon_name_vintage as vintage,build_pokemon_name_classic as classic
from scripts import audit_pokemon_name_vintage as audit
from scripts import build_pokemon_name_followup as compiler
from tests import test_pokemon_name_classic as fixtures


class PokemonNameVintageTests(unittest.TestCase):
    TIME='2026-10-12T07:07:36Z'
    def setUp(self):
        with patch.object(classic,'PROFILE',vintage.PROFILE):fixtures.PokemonNameClassicTests.setUp(self)

    def test_fixed_next_scope_and_hold_checkpoint_leave_prior_profiles_unchanged(self):
        self.assertEqual(vintage.PROFILE.sets,('PMCG1','PMCG2','PMCG3','E3','E5'))
        self.assertEqual((vintage.PROFILE.japanese,audit.AUDIT_PROFILE.prior_inputs),(100,77))
        self.assertIs(vintage.PROFILE.strict_variant_dimensions,True)
        self.assertEqual(classic.PROFILE.sets,('PCG1','E1','E4','PMCG4','PMCG2'))

    def test_requalifies_all_disjoint_editions_without_new_ids_or_rights(self):
        rows,selection,_,plan=compiler.compile(self.before,self.repo,self.root,self.TIME,profile=self.profile)
        self.assertEqual((selection['japanese'],selection['english']),(100,25))
        self.assertEqual(len({r['identity']['card_id'] for r in rows}),125)
        self.assertEqual(plan,self.raw)
        self.assertEqual({r['identity']['variant'] for r in rows if r['identity']['language']=='ja'},{'normal_1st_edition','normal_unlimited'})
        self.assertEqual(selection['new_card_identities'],0)

    def test_wrapper_publishes_frozen_plan_exclusively(self):
        output=self.root/'vintage'
        with patch.object(vintage,'PROFILE',self.profile):
            vintage.build(self.before,self.repo,self.root,output,self.TIME)
            with self.assertRaises(FileExistsError):vintage.build(self.before,self.repo,self.root,output,self.TIME)
        self.assertEqual((output/'basis-plan.json').read_bytes(),self.raw)


if __name__=='__main__':unittest.main()
