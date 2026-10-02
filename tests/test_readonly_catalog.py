import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pokemon_index import core


class ReadonlyCatalogTests(unittest.TestCase):
    def test_reader_can_query_but_cannot_mutate_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog with spaces.sqlite3'
            with closing(core.connect(path)) as db:
                core.init_db(db)
            before = path.read_bytes()
            path.chmod(0o444)
            try:
                with closing(core.connect(path, readonly=True)) as db:
                    self.assertEqual(core.catalog_status(db)['printings'], 0)
                    with self.assertRaises(sqlite3.OperationalError):
                        db.execute('CREATE TABLE unexpected_write (id INTEGER)')
                self.assertEqual(path.read_bytes(), before)
            finally:
                path.chmod(0o600)

    def test_missing_snapshot_is_not_created_by_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite3'
            with self.assertRaises(FileNotFoundError):
                core.connect(path, readonly=True)
            self.assertFalse(path.exists())

    def test_correction_snapshot_missing_effective_view_cannot_fallback_to_raw_refs(self):
        for view in ('effective_card_reference', 'discovery_card_facet'):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'damaged.sqlite3'
                with closing(core.connect(path)) as db:
                    core.init_db(db)
                    db.execute('DROP VIEW ' + view)
                    db.commit()
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'correction view is missing'):
                    core.connect(path, readonly=True)
                self.assertEqual(path.read_bytes(), before)
