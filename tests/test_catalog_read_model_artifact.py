"""Artifact authenticity boundaries, complete state and fail-closed lifetimes."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime, collector_journey
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class ReadModelArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.db_path = self.base/'catalog.sqlite3'
        self.suite = json.loads(SUITE.read_text()); create_fixture(self.db_path, self.suite)
        self.manifest = self.base/'manifest.json'; self.manifest.write_text('{"synthetic_only":true}')
        self.directory = self.base/'artifact'
        with closing(core.connect(self.db_path, readonly=True)) as db:
            self.receipt = artifact.write(db, self.manifest, self.directory)
        self.db_sha = hashlib.sha256(self.db_path.read_bytes()).hexdigest()

    def load(self, **kwargs):
        with closing(core.connect(self.db_path, readonly=True)) as db:
            return artifact.load(db, self.directory, self.manifest,
                expected_seal_sha256=kwargs.get('pin',self.receipt['seal_sha256']))

    def reseal(self, mutate=None):
        """A deliberate test-only producer; never treat its new pin as authority."""
        state = json.loads((self.directory/'metadata.json').read_text())
        if mutate: mutate(state)
        raw = artifact._json_bytes(state); (self.directory/'metadata.json').write_bytes(raw)
        seal = json.loads((self.directory/'seal.json').read_text())
        seal.update(metadata_sha256=hashlib.sha256(raw).hexdigest(), metadata_bytes=len(raw), model_state_sha256=hashlib.sha256(raw).hexdigest())
        seal_raw = artifact._json_bytes(seal); (self.directory/'seal.json').write_bytes(seal_raw)
        return hashlib.sha256(seal_raw).hexdigest()

    def test_full_native_state_revision_row_access_and_journey_outputs_equal(self):
        loaded, revision, evidence = self.load()
        with closing(core.connect(self.db_path,readonly=True)) as db:
            self.assertEqual(revision,collector_journey.catalog_revision(db))
        with closing(core.connect(self.db_path,readonly=True)) as db:
            native = runtime.CatalogReadModel(db)
        self.assertEqual(artifact.model_state(native),artifact.model_state(loaded))
        for key, rows in loaded._vocabularies.items():
            for actual, expected in zip(rows,native._vocabularies[key]):
                self.assertIsInstance(actual,sqlite3.Row); self.assertEqual(actual.keys(),expected.keys())
                self.assertEqual(tuple(actual),tuple(expected))
                for index,name in enumerate(actual.keys()): self.assertEqual(actual[name],actual[index])
        for journey in self.suite['journeys']:
            payload={'turns':[copy.deepcopy(step['action']) for step in journey['steps']], 'limit':self.suite['limit']}
            outputs=[]
            for model in (native,loaded):
                with closing(core.connect(self.db_path,readonly=True)) as db,model.request(db):
                    try: outputs.append(('result',collector_journey.replay(db,payload,revision=revision)))
                    except ValueError as exc: outputs.append(('error',str(exc)))
            self.assertEqual(*outputs,journey['id'])
        self.assertEqual(evidence['seal_sha256'],self.receipt['seal_sha256'])
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(),self.db_sha)

    def test_external_original_pin_rejects_coordinated_resealed_fact_mutation(self):
        self.reseal(lambda state: state['media_ids'].append(['s','ja:invented:001:normal']))
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'external seal pin'):
            self.load()
        with closing(core.connect(self.db_path,readonly=True)) as db:
            with self.assertRaisesRegex(artifact.ArtifactInvalid,'pin required'):
                artifact.load(db,self.directory,self.manifest,expected_seal_sha256=None)

    def test_bootstrap_diagnostics_preserve_exact_receipt_and_model_contract(self):
        plain_model, revision, original = self.load()
        timings = {}
        with closing(core.connect(self.db_path, readonly=True)) as db:
            measured_model, measured_revision, measured = artifact.load(
                db, self.directory, self.manifest,
                expected_seal_sha256=self.receipt['seal_sha256'],
                bootstrap_timings=timings)
        self.assertEqual(measured.keys(), original.keys())
        # Python may shrink a subsequent instance's shared-key __dict__ by a
        # few bytes. The allocation observation is not part of the sealed facts.
        for key in original.keys() - {'decoded_state_bytes'}:
            self.assertEqual(measured[key], original[key], key)
        for receipt in (original, measured):
            self.assertIs(type(receipt['decoded_state_bytes']), int)
            self.assertTrue(0 < receipt['decoded_state_bytes'] <= artifact.MAX_DECODED_BYTES)
        self.assertEqual(measured_revision, revision)
        self.assertEqual(artifact.model_state(measured_model), artifact.model_state(plain_model))
        self.assertEqual(len(timings), 8)
        self.assertTrue(all(type(value) is float and 0 <= value < 8 for value in timings.values()))
        with closing(core.connect(self.db_path, readonly=True)) as db:
            with self.assertRaisesRegex(artifact.ArtifactInvalid, 'plain dictionary'):
                artifact.load(db, self.directory, self.manifest,
                    expected_seal_sha256=self.receipt['seal_sha256'], bootstrap_timings=[])

    def test_full_native_gate_detects_self_consistent_same_count_fact_rewrite(self):
        # Adjacent self hashes cannot authenticate a producer. This demonstrates
        # why the independent immutable-image full-native-state gate is required.
        def alter(state): state['character_names']['false'][0][0]=['s','invented exact name']
        new_pin=self.reseal(alter)
        forged,_,_=self.load(pin=new_pin)  # this test deliberately supplies a new pin
        with closing(core.connect(self.db_path,readonly=True)) as db: native=runtime.CatalogReadModel(db)
        self.assertNotEqual(artifact.model_state(forged),artifact.model_state(native))

    def test_duplicate_unknown_and_wrong_typed_state_reject_after_structure_check(self):
        original=(self.directory/'metadata.json').read_bytes()
        cases=[lambda state:state.update(unapproved_field=True),
               lambda state:state['media_ids'].extend([['s','same'],['s','same']]),
               lambda state:state['cast_dex_card_ids'].append(state['cast_dex_card_ids'][0]),
               lambda state:state['character_names']['false'][0].__setitem__(2,['i',1]),
               lambda state:state['vocabularies']['artists'].update(columns=['arbitrary_sql']),
               lambda state:state['vocabularies']['artists']['rows'][0].__setitem__(0,['unknown','value'])]
        for mutate in cases:
            with self.subTest(mutation=mutate):
                (self.directory/'metadata.json').write_bytes(original)
                new_pin=self.reseal(mutate)
                with self.assertRaises(artifact.ArtifactInvalid):self.load(pin=new_pin)
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'duplicate JSON'):
            artifact._json(b'{"a":1,"a":2}',100)
        for raw in [b'['*33+b'0'+b']'*33,b'{"a":NaN}']:
            with self.assertRaises(artifact.ArtifactInvalid): artifact._json(raw,1000)

    def test_exact_scalar_codec_roundtrip_null_unicode_numeric_blob_and_no_coercion(self):
        for value in [None,'025','25e0','25foo','ミュウツー\u0000ex',b'25',25,-1,2**63-1,-2**63,25.9,-0.0,True,False]:
            actual=artifact._decode(artifact._encode(value))
            self.assertIs(type(actual),type(value));self.assertEqual(actual,value)
            if type(value) is float:self.assertEqual(actual.hex(),value.hex())
        for value in [['i',True],['i',2**63],['r','25.9'],['b','MjU'],['n',None],['s',None],['t',1]]:
            with self.assertRaises(artifact.ArtifactInvalid):artifact._decode(value)

    def test_database_byte_drift_even_native_ignored_generated_timestamp_rejects(self):
        # A native ignored build timestamp still changes the actual DB bytes.
        with closing(core.connect(self.db_path)) as db:
            row=db.execute('SELECT * FROM card LIMIT 1').fetchone()
            db.execute('INSERT INTO card_rarity_correction VALUES (?,?,?,?,?,?,?,?,?,?)',
                (row['card_id'],row['name'],row['rarity'],row['provenance'],'synthetic-rarity','synthetic','https://example.invalid','a'*64,'R','2026-10-13T00:00:00Z'))
            db.commit()
        directory=self.base/'timestamp-artifact'
        with closing(core.connect(self.db_path,readonly=True)) as db:
            receipt=artifact.write(db,self.manifest,directory)
        with closing(core.connect(self.db_path,readonly=True)) as db:before=collector_journey.catalog_revision(db)
        with closing(core.connect(self.db_path)) as db:
            db.execute("UPDATE card_rarity_correction SET applied_at='2026-10-14T00:00:00Z'");db.commit()
        with closing(core.connect(self.db_path,readonly=True)) as db:
            self.assertEqual(collector_journey.catalog_revision(db),before)
            with self.assertRaisesRegex(artifact.ArtifactInvalid,'database byte mismatch'):
                artifact.load(db,directory,self.manifest,expected_seal_sha256=receipt['seal_sha256'])

    def test_wrong_manifest_roster_and_missing_guards_reject_before_restore(self):
        self.manifest.write_text('{"synthetic_only":false}')
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'manifest mismatch'):self.load()
        self.manifest.write_text('{"synthetic_only":true}')
        seal=json.loads((self.directory/'seal.json').read_text());seal['runtime_source_sha256']['core.py']='0'*64
        raw=artifact._json_bytes(seal);(self.directory/'seal.json').write_bytes(raw)
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'source roster'):
            self.load(pin=hashlib.sha256(raw).hexdigest())
        with closing(core.connect(self.db_path)) as db:
            db.execute('CREATE INDEX unknown_policy ON card(name)');db.commit()
        with closing(core.connect(self.db_path,readonly=True)) as db,patch.object(artifact,'_restore',side_effect=AssertionError('partial allocation')):
            with self.assertRaises(runtime.CatalogReadModelUnsupported):
                artifact.load(db,self.directory,self.manifest,expected_seal_sha256=self.receipt['seal_sha256'])

    def test_foreign_sqlite_compile_options_and_unicode_profiles_reject_before_allocation(self):
        original = (self.directory/'seal.json').read_bytes()
        for field, value in [('sqlite_version','unknown-engine'),('unicode_version','unknown-Unicode'),
                             ('compile_options',[]),('compile_options',['UNAUTHORIZED_OPTION'])]:
            with self.subTest(field=field):
                seal=json.loads(original);seal['engine_profile'][field]=value
                raw=artifact._json_bytes(seal);(self.directory/'seal.json').write_bytes(raw)
                with closing(core.connect(self.db_path,readonly=True)) as db,patch.object(artifact,'_restore',side_effect=AssertionError('foreign semantics allocated')):
                    with self.assertRaisesRegex(artifact.ArtifactInvalid,'engine profile'):
                        artifact.load(db,self.directory,self.manifest,expected_seal_sha256=hashlib.sha256(raw).hexdigest())

    def test_nonempty_wal_temp_shadows_and_uncommitted_namespace_never_bootstrap(self):
        with closing(core.connect(self.db_path)) as db:
            db.execute('CREATE TEMP VIEW card AS SELECT * FROM main.card')
            with patch.object(artifact,'_restore',side_effect=AssertionError('partial allocation')):
                with self.assertRaises(runtime.CatalogReadModelUnsupported):
                    artifact.load(db,self.directory,self.manifest,expected_seal_sha256=self.receipt['seal_sha256'])
        with closing(core.connect(self.db_path)) as db:
            db.execute("UPDATE card SET name='uncommitted'")
            with self.assertRaisesRegex(ValueError,'committed snapshot'):
                artifact.load(db,self.directory,self.manifest,expected_seal_sha256=self.receipt['seal_sha256'])
            db.rollback()
        with closing(core.connect(self.db_path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            with closing(core.connect(self.db_path,readonly=True)) as reader:
                writer.execute("UPDATE card SET name='committed'");writer.commit()
                self.assertGreater(Path(str(self.db_path)+'-wal').stat().st_size,0)
                with self.assertRaisesRegex(artifact.ArtifactInvalid,'nonempty WAL'):
                    artifact.load(reader,self.directory,self.manifest,expected_seal_sha256=self.receipt['seal_sha256'])

    def test_symlinks_partial_members_and_changed_artifact_after_load_fail_closed(self):
        loaded,_,_=self.load()
        (self.directory/'metadata.json').write_bytes((self.directory/'metadata.json').read_bytes()+b'\n')
        with closing(core.connect(self.db_path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
            with loaded.request(db):self.fail('stale artifact accepted')
        (self.directory/'unexpected').write_text('extra')
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'members'):self.load()
        (self.directory/'unexpected').unlink()
        target=self.directory/'metadata.json';saved=self.base/'metadata-original';target.rename(saved);target.symlink_to(saved)
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'symlink'):self.load()
        target.unlink();saved.rename(target);(self.directory/'seal.json').unlink()
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'members'):self.load()

    def test_optional_all_absent_diagnostic_required_absence_and_present_invalid(self):
        absent=self.base/'absent'
        with closing(core.connect(self.db_path,readonly=True)) as db,patch.object(artifact,'_PACKAGED_DIR',absent):
            self.assertIsNone(artifact.load_packaged(db))
            with self.assertRaisesRegex(artifact.ArtifactInvalid,'required'):artifact.load_packaged(db,required=True)
            absent.mkdir()
            with self.assertRaises(artifact.ArtifactInvalid):artifact.load_packaged(db)

    def test_bounds_deadline_exclusive_publication_and_no_partial_model(self):
        with patch.object(artifact,'MAX_DECODED_BYTES',1),self.assertRaisesRegex(artifact.ArtifactInvalid,'allocation bound'):self.load()
        with patch.object(artifact,'MAX_METADATA_BYTES',1),self.assertRaises(artifact.ArtifactInvalid):self.load()
        with closing(core.connect(self.db_path,readonly=True)) as db:
            with self.assertRaises(runtime.CatalogDeadline),runtime.sqlite_deadline(db,time.monotonic()-1):
                artifact.load(db,self.directory,self.manifest,expected_seal_sha256=self.receipt['seal_sha256'])
        with closing(core.connect(self.db_path,readonly=True)) as db,self.assertRaisesRegex(artifact.ArtifactInvalid,'already exists'):
            artifact.write(db,self.manifest,self.directory)
        self.assertIsNone(runtime._snapshot_scope.get())

    def test_facet_image_never_executes_unknown_schema_or_trigger_sql(self):
        image=(self.directory/'facet-image.sqlite3').read_bytes()
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(image)
            db.execute('CREATE TRIGGER unexpected AFTER INSERT ON facets BEGIN DELETE FROM facets; END')
            changed=db.serialize()
        with self.assertRaisesRegex(artifact.ArtifactInvalid,'image schema'):
            artifact._validate_image(changed)
        with self.assertRaises(sqlite3.DatabaseError):artifact._validate_image(b'not sqlite')


if __name__=='__main__':unittest.main()
