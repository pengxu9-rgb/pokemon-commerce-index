"""Synthetic regressions for inherited hold guards in the offline pilot audit."""
import copy,json,unittest
from contextlib import closing
from pathlib import Path
from pokemon_index import core, variant_dimension_hold as holds
from scripts.audit_pokemon_name_johto_pilot import snapshot_guard_checks, approved_bundle_checks
from scripts.build_pokemon_name_coverage import spaced_digest
from tests import test_variant_dimension_hold as fixtures


class JohtoPilotAuditGuardTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.VariantDimensionHoldTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.db, self.row, self.cid = fixture.db, fixture.row, fixture.cid
        holds.import_evidence(self.db,[self.row])
        self.assertTrue(snapshot_guard_checks(self.db,[self.row]))

    def test_missing_or_altered_trigger_and_index_reject_identical_table_rows(self):
        mutations = [
            ['DROP TRIGGER variant_dimension_hold_card_update'],
            ['DROP TRIGGER variant_dimension_hold_card_insert'],
            ['DROP INDEX variant_dimension_hold_card_id'],
            ['DROP INDEX variant_dimension_hold_card_id',
             'CREATE INDEX variant_dimension_hold_card_id ON catalog_identity_quarantine(reason)'],
            ['DROP TRIGGER variant_dimension_hold_card_update',
             'CREATE TRIGGER variant_dimension_hold_card_update AFTER UPDATE ON card BEGIN SELECT 1; END'],
        ]
        for statements in mutations:
            with self.subTest(statements=statements), closing(core.connect(':memory:')) as scratch:
                self.db.backup(scratch)
                old = [tuple(r) for r in scratch.execute('SELECT * FROM card')]
                for statement in statements:
                    scratch.execute(statement)
                scratch.commit()
                self.assertEqual(old,[tuple(r) for r in scratch.execute('SELECT * FROM card')])
                with self.assertRaisesRegex(ValueError,'retention guards'):
                    snapshot_guard_checks(scratch,[self.row])

    def test_current_held_flags_and_source_context_must_stay_current(self):
        for change in ["UPDATE card SET provenance='changed'",
                       'UPDATE card SET match_eligible=1']:
            with self.subTest(change=change), closing(core.connect(':memory:')) as scratch:
                self.db.backup(scratch)
                scratch.execute('DROP TRIGGER variant_dimension_hold_card_update')
                scratch.execute(change)
                holds.install_guards(scratch)
                scratch.commit()
                with self.assertRaisesRegex(ValueError,'held identity'):
                    snapshot_guard_checks(scratch,[self.row])


class JohtoPilotAuditProvenanceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]/'catalog/international-pokemon-johto-pilot-v1'
        self.bundle = json.loads((root/'concept-review-bundle.json').read_text())
        self.packet = json.loads((root/'basis-qualification.json').read_text())
        self.proposals = self.packet['johto_semantic_review_tranche']['proposals']
        self.time = self.bundle['review_events'][0]['review']['reviewed_at']

    def rehash(self,bundle):
        event = bundle['review_events'][0]; proposal = event['proposal']
        proposal['source_snapshot_sha256'] = spaced_digest(proposal['source_snapshot'])
        old = event['event_id']
        event['event_id'] = spaced_digest({k:v for k,v in event.items() if k!='event_id'})
        for concept in bundle['concept_revisions']:
            if concept['review_event_id'] == old:
                concept['review_event_id'] = event['event_id']

    def test_exact_approved_packet_binds_all_actual_events(self):
        self.assertEqual(len(approved_bundle_checks(self.bundle,self.packet,self.proposals,self.time)),25)

    def test_forged_semantic_sha_or_source_witness_rejects_even_after_rehash(self):
        mutations = [
            lambda e:e['review'].update(semantic_review_sha256='0'*64),
            lambda e:e['proposal']['source_snapshot']['witnesses']['ja'].update(native_id='data-asia/S/OTHER/1.ts'),
            lambda e:e['proposal']['source_snapshot']['witnesses']['en'].update(sha256='0'*64),
            lambda e:e['proposal']['source_snapshot']['witnesses']['en'].update(license_sha256='0'*64),
            lambda e:e['proposal'].update(dex_id=999),
            lambda e:e['review'].update(purchase_allowed=True),
        ]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle); mutate(bundle['review_events'][0]); self.rehash(bundle)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):
                approved_bundle_checks(bundle,self.packet,self.proposals,self.time)


if __name__=='__main__':
    unittest.main()
