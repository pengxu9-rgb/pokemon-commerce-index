"""Full image binding normalizes bookkeeping, retaining identity/rights/schema."""
import sqlite3,unittest
from scripts.check_international_scale_image import logical_digest


class ScaleImageBindingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE card_identity_exception(card_id TEXT,applied_at TEXT,display_allowed INTEGER);CREATE TABLE mapping(provider TEXT,native_id TEXT);')
        self.db.execute('INSERT INTO card_identity_exception VALUES(?,?,?)',('synthetic:ja:test','2026-10-13T00:00:00Z',0));self.db.execute('INSERT INTO mapping VALUES(?,?)',('synthetic','record-1'))

    def test_only_documented_bookkeeping_time_changes_are_normalized(self):
        old=logical_digest(self.db);self.db.execute("UPDATE card_identity_exception SET applied_at='2026-10-13T01:00:00+00:00'");self.assertEqual(old,logical_digest(self.db))
        self.db.execute('UPDATE card_identity_exception SET display_allowed=1');self.assertNotEqual(old,logical_digest(self.db))

    def test_namespace_mapping_and_sql_schema_changes_affect_the_binding(self):
        old=logical_digest(self.db);self.db.execute("UPDATE mapping SET provider='other-synthetic'");self.assertNotEqual(old,logical_digest(self.db))
        self.db.execute("UPDATE mapping SET provider='synthetic'");self.assertEqual(old,logical_digest(self.db))
        self.db.execute('CREATE INDEX mapping_id ON mapping(native_id)');self.assertNotEqual(old,logical_digest(self.db))

    def test_naive_or_missing_generated_timestamp_is_rejected(self):
        for value in ('2026-10-13T00:00:00',None):
            with self.subTest(value=value):
                self.db.execute('UPDATE card_identity_exception SET applied_at=?',(value,))
                with self.assertRaises(ValueError):logical_digest(self.db)

    def test_autoincrement_sequence_is_part_of_the_full_row_binding(self):
        self.db.execute('CREATE TABLE reference_id(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT)')
        self.db.execute("INSERT INTO reference_id(value) VALUES('synthetic')")
        old=logical_digest(self.db)
        self.db.execute("UPDATE sqlite_sequence SET seq=2 WHERE name='reference_id'")
        self.assertNotEqual(old,logical_digest(self.db))
