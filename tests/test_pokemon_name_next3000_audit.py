"""Reject rehashed append forgeries, historical drift and unreviewed release pins."""
import copy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pokemon_index import core, catalog_locale, catalog_locale_indexes
from scripts import audit_pokemon_name_next3000 as audit
from scripts import rehearse_international_next3000_release as release


def rehash(row):
    row['evidence_id']='catalog-locale:'+catalog_locale.digest({k:v for k,v in row.items() if k!='evidence_id'})


class Next3000ManifestTests(unittest.TestCase):
    def test_active_historical_helper_drift_changes_the_release_seal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            files=[audit.MANIFEST,audit.PRIOR,audit.ORIGINAL,
                   *(audit.DIRECTORY+'/'+n for n in ('basis-qualification.json','record-binding-review.json','selection.json','TCGDEX-LICENSE')),
                   *('scripts/'+n for n in ('audit_pokemon_name_next3000.py','build_pokemon_name_next3000.py','rehearse_international_next3000_release.py',
                       'audit_international_coverage_expansion.py','audit_pokemon_name_scale.py','audit_pokemon_name_eight_followup.py','rehearse_international_scale_release.py'))]
            for name in files:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"steps":[]}')
            inherited=[root/'scripts'/n for n in ('audit_international_coverage_expansion.py','audit_pokemon_name_eight_followup.py')]
            fake=SimpleNamespace(__file__=str(root/'scripts/build_pokemon_name_next3000.py'),compiler_inputs=lambda:{p:p.read_bytes() for p in inherited})
            with patch.object(audit,'compiler',return_value=fake):
                before=audit.input_hashes(root)
                for name in ('audit_international_coverage_expansion.py','audit_pokemon_name_scale.py','audit_pokemon_name_eight_followup.py','rehearse_international_scale_release.py'):
                    p=root/'scripts'/name;prior=p.read_bytes();p.write_bytes(prior+b' altered helper')
                    self.assertNotEqual(before,audit.input_hashes(root));p.write_bytes(prior)

    def fixtures(self,root):
        path=root/'catalog/input.jsonl';path.parent.mkdir();path.write_text('{}\n')
        step=dict(operation='import-catalog-locales',path='catalog/input.jsonl',sha256=audit.signature(path))
        original=dict(schema='pokemon.catalog-build.v1',steps=[copy.deepcopy(step) for _ in range(65)])
        prior=dict(schema=original['schema'],steps=[copy.deepcopy(step) for _ in range(86)],expected={'printings':70006})
        p=root/audit.DIRECTORY/'locales.jsonl';p.parent.mkdir();p.write_text('{}\n')
        manifest=dict(schema=prior['schema'],steps=copy.deepcopy(prior['steps'])+[dict(operation='import-catalog-locales',path=audit.DIRECTORY+'/locales.jsonl',sha256=audit.signature(p))],expected=copy.deepcopy(prior['expected']))
        return original,prior,manifest

    def test_exact87_single_append_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original,prior,manifest=self.fixtures(root)
            audit.manifest_checks(root,prior,manifest,original)

    def test_changed86_prefix_extra_operation_or_changed_expected_reject(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original,prior,manifest=self.fixtures(root)
            for kind in ('prefix','new_concept','expected','extra'):
                value=copy.deepcopy(manifest)
                if kind=='prefix':value['steps'][0]['sha256']='0'*64
                if kind=='new_concept':value['steps'][-1]['operation']='import-concept-review-bundle'
                if kind=='expected':value['expected']['printings']+=1
                if kind=='extra':value['steps'].append(copy.deepcopy(value['steps'][-1]))
                with self.subTest(kind=kind),self.assertRaises(ValueError):audit.manifest_checks(root,prior,value,original)

    def test_symlinked_hashed_append_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original,prior,manifest=self.fixtures(root)
            p=root/audit.DIRECTORY/'locales.jsonl';p.unlink();p.symlink_to(root/'catalog/input.jsonl')
            with self.assertRaisesRegex(ValueError,'path/hash'):audit.manifest_checks(root,prior,manifest,original)


class Next3000RowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=dict(source_pin='a'*40,license_sha256='b'*64,source_inventory={'LICENSE':{'git_blob':'c'*40}})
        cls.witnesses=[];cls.rows=[]
        for i in range(3000):
            group=i if i<1503 else i-1503
            card=dict(card_id='synthetic:'+str(i),language='en',set_code='S'+str(group%48),collector_number=str(group),variant='v'+str(i//1503),name='Name',provenance='synthetic',rights_reference=audit.RIGHTS)
            alias=dict(concept_id='concept',revision=1,name_ja='名前',name_en='Name')
            src=dict(native_id='data/S/1.ts',git_blob='d'*40,sha256='e'*64)
            witness=dict(identity=card,source=src,name_alias=alias,dex_id=1,release_snapshot={'language':'en'})
            source=dict(provider='tcgdex',language='en',region='ZZ',release_id='tcgdex-product:'+card['set_code'],native_id=src['native_id'],source_variant=card['variant'],revision=cls.packet['source_pin'],git_blob=src['git_blob'],sha256=src['sha256'],license_git_blob='c'*40,license_sha256='b'*64,retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at='2026-10-14T00:00:00Z',physical_distribution_region=None,rights_reference=audit.RIGHTS,rights_status='metadata_internal_reviewed')
            row=dict(identity=copy.deepcopy(card),source=source,name_aliases=[copy.deepcopy(alias)],release_snapshot={'language':'en'},character_scope=dict(dex_id=1,full_name='Name',category='Pokemon',form_inheritance_allowed=False),unresolved_conflicts=[],test_only=False,**{k:False for k in catalog_locale.FALSE_CLAIMS})
            rehash(row);cls.witnesses.append(witness);cls.rows.append(row)
        cls.packet['selected_card_ids']=sorted(w['identity']['card_id'] for w in cls.witnesses)

    def check(self,rows,witnesses=None):
        return audit.row_checks(self.packet,self.witnesses if witnesses is None else witnesses,rows,'b'*64)

    def test_all3000_exact_rows_reconstruct(self):
        self.assertEqual(len(self.check(self.rows)),3000)

    def test_rehashed_wrong_source_license_alias_dex_or_permission_reject(self):
        edits=[lambda r:r['source'].update(sha256='0'*64),lambda r:r['source'].update(license_sha256='0'*64),
               lambda r:r['name_aliases'][0].update(revision=2),lambda r:r['character_scope'].update(dex_id=2),
               lambda r:r.update(purchase_allowed=True),lambda r:r.update(test_only=True),
               lambda r:r['source'].update(region='US'),lambda r:r['source'].update(retrieved_at='2026-10-01T00:00:00Z')]
        for edit in edits:
            rows=copy.deepcopy(self.rows);edit(rows[0]);rehash(rows[0])
            with self.subTest(edit=edit),self.assertRaises(ValueError):self.check(rows)

    def test_rehashed_digital_or_absolute_source_rejects_even_if_witness_matches(self):
        for path in ('data/Pocket/1.ts','data/digital/1.ts','/data/S/1.ts','data/../S/1.ts'):
            rows=copy.deepcopy(self.rows);witnesses=copy.deepcopy(self.witnesses)
            rows[0]['source']['native_id']=path;witnesses[0]['source']['native_id']=path;rehash(rows[0])
            with self.subTest(path=path),self.assertRaises(ValueError):self.check(rows,witnesses)

    def test_missing_or_duplicate_record_inventory_rejects(self):
        for rows in (self.rows[:-1],self.rows[:-1]+[self.rows[0]]):
            with self.assertRaisesRegex(ValueError,'inventory'):self.check(rows)


class Next3000HistoryTests(unittest.TestCase):
    def connections(self):
        left=core.connect(':memory:');right=core.connect(':memory:')
        for db in (left,right):core.init_db(db);catalog_locale_indexes.import_manifest_evidence(db,[catalog_locale_indexes.RECORD])
        self.addCleanup(left.close);self.addCleanup(right.close)
        return left,right

    def preservation(self,mutation=None):
        left,right=self.connections();old={t:[] for t in audit.history.tables(left)};new=copy.deepcopy(old)
        new['catalog_locale_evidence']=[('locale',i) for i in range(3000)]
        new['catalog_source_mapping']=[('mapping',i) for i in range(3000)]
        if mutation:mutation(old,new)
        def records(db,table):return old[table] if db is left else new[table]
        with patch.object(audit.history,'records',side_effect=records),patch.object(audit.variant_dimension_hold,'rows_for',return_value=[{}]*44),patch.object(audit,'snapshot_guard_checks'):
            return audit.preserved(left,right)

    def test_only_two_exact_append_tables_pass(self):
        self.assertEqual(len(self.preservation()),51)

    def test_card_concept_or_historical_locale_mutation_rejects(self):
        edits=[lambda old,new:new['card'].append(('changed',)),lambda old,new:new['concept_review_event'].append(('new',)),
               lambda old,new:new['catalog_source_mapping'].pop(),
               lambda old,new:(old['catalog_locale_evidence'].append(('old',)),new['catalog_locale_evidence'].__setitem__(0,('changed',)))]
        for edit in edits:
            with self.subTest(edit=edit),self.assertRaisesRegex(ValueError,'historical'):self.preservation(edit)

    def test_even_additive_schema_change_rejects(self):
        left,right=self.connections();right.execute('CREATE INDEX unexpected_next3000 ON card(name)')
        with self.assertRaisesRegex(ValueError,'SQL schema'):audit.preserved(left,right)

    def test_omitted_or_changed_exact_lookup_index_rejects(self):
        left,right=self.connections();right.execute('DROP INDEX catalog_locale_evidence_card')
        with self.assertRaises(ValueError):audit.preserved(left,right)

    def test_rebuild_normalizes_only_named_timezone_bearing_columns(self):
        left,right=self.connections();table='card_identity_exception'
        columns=[r[1] for r in left.execute('PRAGMA table_info('+table+')')];index=columns.index('applied_at')
        a=['same']*len(columns);b=a.copy();a[index]='2026-10-13T00:00:00Z';b[index]='2026-10-14T00:00:00Z'
        def records(db,t):return [tuple(a if db is left else b)] if t==table else []
        with patch.object(audit.history,'records',side_effect=records):self.assertEqual(len(audit.rebuild_equal(left,right)[0]),51)
        b[0]='changed'
        with patch.object(audit.history,'records',side_effect=records),self.assertRaisesRegex(ValueError,'four named'):audit.rebuild_equal(left,right)
        b[0]='same';b[index]='2026-10-14T00:00:00'
        with patch.object(audit.history,'records',side_effect=records),self.assertRaisesRegex(ValueError,'timezone'):audit.rebuild_equal(left,right)

    def test_unset_release_pins_block_before_any_input_or_build(self):
        with patch.object(release,'MANIFEST_SHA',None), patch.object(release,'fingerprints') as fingerprints:
            with self.assertRaisesRegex(ValueError,'reviewed next3000'):release.rehearse(Path('/absent'))
            fingerprints.assert_not_called()


if __name__=='__main__':unittest.main()
