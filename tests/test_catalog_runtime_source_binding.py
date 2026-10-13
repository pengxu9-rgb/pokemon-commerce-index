"""Schema trust policy changes must invalidate saved catalogue conversations."""
from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch

from pokemon_index import collector_journey, core


class SchemaTrustRevisionTests(unittest.TestCase):
    def test_schema_trust_helper_change_invalidates_saved_conversation(self):
        original = Path.read_bytes

        def changed_helper(path):
            value = original(path)
            return value + b'\n# changed schema trust policy\n' if path.name == 'catalog_locale_indexes.py' else value

        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            before = collector_journey.catalog_revision(db)
            with patch.object(Path, 'read_bytes', changed_helper):
                after = collector_journey.catalog_revision(db)
                self.assertNotEqual(before, after)
                with self.assertRaisesRegex(ValueError, 'policy changed'):
                    collector_journey.replay(db, {
                        'turns': [{'type': 'ask', 'question': 'Recommend Japanese Pikachu cards'}],
                        'expected_revision': before,
                    })
            self.assertEqual(before, collector_journey.catalog_revision(db))


if __name__ == '__main__':
    unittest.main()
