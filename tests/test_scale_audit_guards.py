"""Independent bulk audit rejects index omissions and rehashed approval forgeries."""
import copy,json,unittest
from pathlib import Path
from contextlib import closing
from pokemon_index import core,catalog_locale_indexes
from scripts import audit_pokemon_name_scale as audit
from scripts.build_pokemon_name_coverage import spaced_digest


class ScaleAuditIndexesTests(unittest.TestCase):
    def test_standalone_audit_rejects_wrong_baseline_before_reading_other_inputs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);before=root/'wrong.sqlite3';before.write_bytes(b'Synthetic wrong baseline')
            with self.assertRaisesRegex(ValueError,'exact frozen prior'):
                audit.run(before,root/'absent-after.sqlite3',root/'absent-rebuilt.sqlite3',root)

    def test_missing_partial_or_altered_lookup_indexes_are_rejected(self):
        mutations=[[],[catalog_locale_indexes.SQL['catalog_locale_evidence_card']],
            [catalog_locale_indexes.SQL['catalog_locale_evidence_card'],
             'CREATE INDEX catalog_source_mapping_card ON catalog_source_mapping(provider)']]
        for statements in mutations:
            with self.subTest(statements=statements),closing(core.connect(':memory:')) as db:
                core.init_db(db)
                for statement in statements:db.execute(statement)
                with self.assertRaisesRegex(ValueError,'both exact'):audit.require_indexes(db)
        with closing(core.connect(':memory:')) as db:
            core.init_db(db);catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD]);audit.require_indexes(db)


class ScaleAuditApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]/'catalog/international-pokemon-scale-v1'
        cls.original=json.loads((root/'concept-review-bundle.json').read_text());cls.packet=json.loads((root/'basis-qualification.json').read_text())
        cls.proposals=cls.packet['new_name_proposals'];cls.inspected_at=cls.original['review_events'][0]['review']['reviewed_at'];cls.semantic_time=json.loads((root/'semantic-review.json').read_text())['review_completed_at']

    def rehash(self,bundle):
        event=bundle['review_events'][0];proposal=event['proposal'];proposal['source_snapshot_sha256']=spaced_digest(proposal['source_snapshot']);old=event['event_id'];event['event_id']=spaced_digest({k:v for k,v in event.items() if k!='event_id'})
        for c in bundle['concept_revisions']:
            if c['review_event_id']==old:c['review_event_id']=event['event_id']

    def test_all400_exact_approved_events_reconstruct(self):
        self.assertEqual(len(audit.approved_bundle_checks(self.original,self.packet,self.proposals,self.inspected_at,self.semantic_time)),400)

    def test_inspection_cannot_predate_actual_semantic_approval(self):
        with self.assertRaisesRegex(ValueError,'predates actual'):
            audit.approved_bundle_checks(self.original,self.packet,self.proposals,'2026-10-12T00:00:00Z',self.semantic_time)

    def test_rehashed_wrong_source_pair_license_dex_semantics_or_permission_reject(self):
        mutations=[lambda e:e['review'].update(semantic_review_sha256='0'*64),
            lambda e:e['review'].update(semantic_reviewed_at='2026-10-12T00:00:00Z'),
            lambda e:e['proposal']['source_snapshot']['witnesses']['ja'].update(native_id='data-asia/OTHER/1.ts'),
            lambda e:e['proposal']['source_snapshot']['witnesses']['en'].update(sha256='0'*64),
            lambda e:e['proposal']['source_snapshot']['witnesses']['ja'].update(license_sha256='0'*64),
            lambda e:e['proposal'].update(dex_id=1025),lambda e:e['review'].update(purchase_allowed=True),
            lambda e:e['review'].update(requires_card_binding=False)]
        for mutation in mutations:
            bundle=copy.deepcopy(self.original);mutation(bundle['review_events'][0]);self.rehash(bundle)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                audit.approved_bundle_checks(bundle,self.packet,self.proposals,self.inspected_at,self.semantic_time)


if __name__=='__main__':unittest.main()
