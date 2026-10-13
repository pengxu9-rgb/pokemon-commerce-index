"""Material release-proof failures on disposable databases only."""
import copy, inspect, json, sqlite3, unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path
from pokemon_index import core, catalog_locale, variant_dimension_hold
from scripts.rehearse_international_scale_release import logical_snapshot_digest, _verify_installed_rows, _verify_holds, _verify_reviewed_logical_snapshot


class LogicalScaleReleaseTests(unittest.TestCase):
    def test_image_checker_can_copy_digest_without_project_imports(self):
        namespace={};exec(inspect.getsource(logical_snapshot_digest),namespace)
        db,_=self.databases()
        self.assertEqual(namespace['logical_snapshot_digest'](db),logical_snapshot_digest(db))

    def databases(self):
        databases=[]
        for _ in range(2):
            db=core.connect(':memory:');core.init_db(db);self.addCleanup(db.close)
            core.import_cards(db,[dict(language='ja',set_code='TEST',collector_number='001/100',variant='normal',name='試験',
                rarity='Common',provenance='synthetic:test-only',rights_reference='synthetic:test-only',display_allowed=False,match_eligible=True)])
            databases.append(db)
        return databases

    def test_full_schema_metadata_and_unapproved_permissions_are_bound(self):
        mutations=["UPDATE card SET display_allowed=1", "UPDATE card SET name='Changed native name'",
                   "UPDATE card SET rights_reference='different rights'", "PRAGMA user_version=7",
                   "PRAGMA application_id=17", "CREATE INDEX arbitrary_card_name ON card(name COLLATE NOCASE)"]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                old,new=self.databases();self.assertEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))
                new.execute(mutation);self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))

    def test_unknown_tables_and_typed_values_are_not_ignored(self):
        old,new=self.databases()
        for db in (old,new):db.execute('CREATE TABLE synthetic_extra(value BLOB)');db.execute('INSERT INTO synthetic_extra VALUES (?)',('001',))
        self.assertEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))
        new.execute('UPDATE synthetic_extra SET value=?',(b'001',))
        self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))
        new.execute('UPDATE synthetic_extra SET value=?',(1,))
        self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))

    def test_historical_row_change_beyond_runtime_revision_rejects(self):
        from pokemon_index.collector_journey import catalog_revision
        db,_=self.databases()
        db.execute("INSERT INTO card_number_conflict_rule VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ('synthetic:test-only','ja','TEST','100','101','synthetic:test-only','test-only',2,'0'*64,
             'synthetic:test-only','initial qualification','2026-10-13T00:00:00Z'))
        baseline=logical_snapshot_digest(db);runtime_revision=catalog_revision(db)
        with patch('scripts.rehearse_international_scale_release.LOGICAL_SNAPSHOT_SHA',baseline):
            self.assertEqual(_verify_reviewed_logical_snapshot(db),baseline)
            db.execute("UPDATE card_number_conflict_rule SET reason='altered historical qualification'")
            self.assertEqual(catalog_revision(db),runtime_revision)
            with self.assertRaisesRegex(ValueError,'full51 logical snapshot'):_verify_reviewed_logical_snapshot(db)

    def test_only_four_documented_build_time_columns_normalize(self):
        generated={'card_relationship_assertion':'asserted_at','card_identity_exception':'applied_at',
                   'card_rarity_correction':'applied_at','card_number_conflict_rule':'applied_at'}
        old=sqlite3.connect(':memory:');new=sqlite3.connect(':memory:');self.addCleanup(old.close);self.addCleanup(new.close)
        for table,column in generated.items():
            for db,timestamp in ((old,'2026-10-13T01:00:00Z'),(new,'2026-10-13T02:00:00+00:00')):
                db.execute(f'CREATE TABLE {table}(identity TEXT,{column} TEXT)');db.execute(f'INSERT INTO {table} VALUES (?,?)',('same source',timestamp))
        for db in (old,new):db.execute('CREATE TABLE source_review(reviewed_at TEXT)');db.execute("INSERT INTO source_review VALUES ('2026-10-13T01:00:00Z')")
        self.assertEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))
        new.execute("UPDATE source_review SET reviewed_at='2026-10-13T02:00:00Z'")
        self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))
        new.execute("UPDATE source_review SET reviewed_at='2026-10-13T01:00:00Z'")
        new.execute("UPDATE card_rarity_correction SET identity='different source'")
        self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))

    def test_invalid_generated_timestamp_cannot_hide_corruption(self):
        for timestamp in ('not a date','2026-10-13T02:00:00',None):
            with self.subTest(timestamp=timestamp),closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE card_rarity_correction(identity TEXT,applied_at TEXT)')
                db.execute('INSERT INTO card_rarity_correction VALUES (?,?)',('same source',timestamp))
                with self.assertRaises((ValueError,TypeError)):logical_snapshot_digest(db)

    def test_encoding_is_bound_even_with_identical_empty_schema(self):
        with closing(sqlite3.connect(':memory:')) as old,closing(sqlite3.connect(':memory:')) as new:
            old.execute("PRAGMA encoding='UTF-8'");new.execute("PRAGMA encoding='UTF-16le'")
            old.execute('CREATE TABLE synthetic(value TEXT)');new.execute('CREATE TABLE synthetic(value TEXT)')
            self.assertNotEqual(logical_snapshot_digest(old),logical_snapshot_digest(new))


class ScaleReleaseInstalledEvidenceTests(unittest.TestCase):
    def binding_fixture(self):
        # Reuse a small synthetic fixture without adding its class to discovery.
        import importlib
        fixture=importlib.import_module('test_international_coverage').InternationalCoverageTests()
        fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.row['source']['region']='ZZ';fixture.row['source']['release_id']='tcgdex-product:FIX';fixture.sign(fixture.row)
        catalog_locale.import_evidence(fixture.db,[fixture.row]);_verify_installed_rows(fixture.db,[fixture.row])
        return fixture

    def test_missing_mapping_and_foreign_provider_namespace_reject(self):
        for mutation in ("DELETE FROM catalog_source_mapping","UPDATE catalog_source_mapping SET provider='different-provider'"):
            with self.subTest(mutation=mutation):
                fixture=self.binding_fixture();fixture.db.execute(mutation)
                with self.assertRaises(ValueError):_verify_installed_rows(fixture.db,[fixture.row])

    def test_changed_identity_rights_and_permission_widening_reject(self):
        fixture=self.binding_fixture();fixture.db.execute("UPDATE card SET rights_reference='other licence'")
        with self.assertRaises(ValueError):_verify_installed_rows(fixture.db,[fixture.row])
        fixture=self.binding_fixture();forged=copy.deepcopy(fixture.row);forged['purchase_allowed']=True;fixture.sign(forged)
        with self.assertRaises(ValueError):_verify_installed_rows(fixture.db,[forged])

    def test_rehashed_alternate_region_or_release_namespace_reject(self):
        for field,value in (('region','JP'),('release_id','other-provider:release')):
            fixture=self.binding_fixture();forged=copy.deepcopy(fixture.row);forged['source'][field]=value;fixture.sign(forged)
            with self.assertRaisesRegex(ValueError,'namespace'):_verify_installed_rows(fixture.db,[forged])

    def held_fixture(self):
        db=core.connect(':memory:');core.init_db(db);self.addCleanup(db.close)
        path=Path(__file__).resolve().parents[1]/'catalog/variant-dimension-holds-v1/holds.jsonl'
        holds=[json.loads(line) for line in path.read_text().splitlines()]
        core.import_cards(db,[dict(row['identity'],match_eligible=row['prior_structural_match_eligible']) for row in holds])
        variant_dimension_hold.import_evidence(db,holds);holds=variant_dimension_hold.rows_for(db);_verify_holds(db,holds)
        return db,holds

    def test_missing_or_changed_hold_guards_reject(self):
        for name in ('variant_dimension_hold_card_id','variant_dimension_hold_card_insert','variant_dimension_hold_card_update'):
            with self.subTest(name=name):
                db,holds=self.held_fixture();db.execute(('DROP INDEX ' if name.endswith('card_id') else 'DROP TRIGGER ')+name)
                with self.assertRaises(ValueError):_verify_holds(db,holds)
        db,holds=self.held_fixture();db.execute('DROP TRIGGER variant_dimension_hold_card_update')
        db.execute('CREATE TRIGGER variant_dimension_hold_card_update AFTER UPDATE ON card BEGIN SELECT 1; END')
        with self.assertRaises(ValueError):_verify_holds(db,holds)


if __name__=='__main__':unittest.main()
