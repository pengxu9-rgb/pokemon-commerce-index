"""Bounds and object accounting for the faster immutable-model bootstrap."""
import json
import sqlite3
import sys
from types import MappingProxyType
import unittest
from unittest.mock import patch

from pokemon_index import catalog_read_model_artifact as artifact
from pokemon_index import collector_runtime as runtime


class BootstrapValidationFastPathTests(unittest.TestCase):
    def test_quoted_delimiters_unicode_and_escape_sequences_are_data(self):
        values = [
            {'名前': '[{,}] ポケモン', 'quote': '\\"[{'} ,
            ['\\', '"', '\\"', '\u0000', ['[', ']', '{', '}']],
            {'a': {'b': [True, False, None, 12, -3, 1.25]}},
        ]
        for value in values:
            for ensure_ascii in (True, False):
                with self.subTest(value=value, ensure_ascii=ensure_ascii):
                    raw = json.dumps(value, ensure_ascii=ensure_ascii).encode()
                    self.assertEqual(artifact._json(raw, 4096), value)

    def test_duplicate_decoded_names_and_invalid_json_never_load(self):
        invalid = [b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}',
            b'[NaN]', b'[Infinity]', b'[-Infinity]', b'{', b']',
            b'[]]', b'"unterminated[', b'{"x":"\\q"}', b'"\xff"']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(artifact.ArtifactInvalid):
                artifact._json(raw, 4096)

    def test_depth_members_and_bytes_remain_exact_bounds(self):
        maximum = b'[' * 32 + b'0' + b']' * 32
        artifact._json(maximum, len(maximum))
        with self.assertRaisesRegex(artifact.ArtifactInvalid, 'nesting'):
            artifact._json(b'[' + maximum + b']', 4096)
        with patch.object(artifact, 'MAX_JSON_MEMBERS', 4):
            # Two brackets and two commas; numbers are not structural tokens.
            self.assertEqual(artifact._json(b'[0,1,2]', 32), [0, 1, 2])
            with self.assertRaisesRegex(artifact.ArtifactInvalid, 'member'):
                artifact._json(b'[0,1,2,3]', 32)
        with self.assertRaisesRegex(artifact.ArtifactInvalid, 'byte'):
            artifact._json(b'[]', 1)

    def test_expired_budget_cannot_finish_valid_decode(self):
        with patch.object(runtime, 'checkpoint', side_effect=runtime.CatalogDeadline):
            with self.assertRaises(runtime.CatalogDeadline):
                artifact._json(b'{"valid":true}', 32)

    def test_shared_objects_cycles_and_optional_seen_are_counted_once(self):
        shared = ['payload' * 100]
        root = [shared, shared]
        root.append(root)
        expected = sum(sys.getsizeof(value) for value in (root, shared, shared[0]))
        self.assertEqual(artifact._deep_size(root), expected)
        seen = {id(shared[0])}
        self.assertEqual(artifact._deep_size(root, seen), expected - sys.getsizeof(shared[0]))
        self.assertTrue({id(root), id(shared), id(shared[0])} <= seen)
        self.assertEqual(artifact._deep_size(root, seen), 0)
        # Separate root calls intentionally do not share a visited set.
        self.assertEqual(artifact._deep_size(root), expected)

    def test_mapping_proxy_and_sqlite_rows_preserve_accounting(self):
        key = 'unique-key' * 20
        value = b'unique-value' * 20
        proxy = MappingProxyType({key: value})
        self.assertEqual(artifact._deep_size(proxy),
            sys.getsizeof(proxy) + sys.getsizeof(key) + sys.getsizeof(value))
        with sqlite3.connect(':memory:') as db:
            cursor = db.execute('SELECT 1 AS number, NULL AS missing')
            row = sqlite3.Row(cursor, (value, value))
            self.assertEqual(artifact._deep_size(row),
                sys.getsizeof(row) + sys.getsizeof(value))


if __name__ == '__main__':
    unittest.main()
