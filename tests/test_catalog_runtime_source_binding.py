"""Schema trust policy changes must invalidate saved catalogue conversations."""
from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch

from pokemon_index import collector_journey, core


class SchemaTrustRevisionTests(unittest.TestCase):
    def test_schema_file_is_part_of_policy_and_stale_conversation_binding(self):
        original = Path.read_bytes

        def changed_schema(path):
            value = original(path)
            return value + b'\n-- changed schema trust policy\n' if path.name == 'schema.sql' else value

        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            before = collector_journey.catalog_revision(db)
            sources = collector_journey.runtime_source_hashes()
            self.assertIn('schema.sql', sources)
            with patch.object(Path, 'read_bytes', changed_schema):
                after = collector_journey.catalog_revision(db)
                self.assertNotEqual(before, after)
                self.assertNotEqual(sources['schema.sql'], collector_journey.runtime_source_hashes()['schema.sql'])
                with self.assertRaisesRegex(ValueError, 'policy changed'):
                    collector_journey.replay(db, {
                        'turns': [{'type': 'ask', 'question': 'Recommend Japanese Pikachu cards'}],
                        'expected_revision': before,
                    })
            self.assertEqual(before, collector_journey.catalog_revision(db))

    def test_schema_trust_helper_change_invalidates_saved_conversation(self):
        original = Path.read_bytes

        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            before = collector_journey.catalog_revision(db)
            for helper in ('catalog_locale_indexes.py', 'catalog_read_model_artifact.py'):
                def changed_helper(path):
                    value = original(path)
                    return value + b'\n# changed schema trust policy\n' if path.name == helper else value

                with self.subTest(helper=helper), patch.object(Path, 'read_bytes', changed_helper):
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
