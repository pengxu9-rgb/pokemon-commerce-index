"""Exact frozen-lexer equivalence and the existing artifact rejection boundaries.

The alternatives have disjoint prefixes: an ordinary byte excludes quote and
backslash; an escape starts with backslash and retains the original dot/LF rule.
Neither consumes an unescaped closing quote, so internal backtracking cannot
create a different closing delimiter. The unanchored search can still retry
escaped quotes in malformed strings: no global linear-time claim is made.
"""
from itertools import product
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

if __name__ == '__main__' and '--aggregate-bound-child' in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokemon_index import catalog_read_model_artifact as artifact
from pokemon_index import card_source_context_index as context_index
from pokemon_index import collector_runtime as runtime


# Explicit reference to the previously released lexer, independent of the
# production constant. All other decoder/type/rights/bound checks remain live.
OLD_STRINGS = re.compile(rb'"(?:[^"\\]|\\.)*"')
CURRENT_STRINGS = artifact._JSON_STRINGS


def typed_graph(value):
    """Compare DTO contents and exact Python types, including bool versus int."""
    kind = type(value)
    if kind is dict:
        return kind, tuple((typed_graph(k), typed_graph(v)) for k, v in value.items())
    if kind is list:
        return kind, tuple(typed_graph(item) for item in value)
    if kind is float:
        return kind, value.hex()
    return kind, value


def decode_outcome(pattern, raw, limit):
    with patch.object(artifact, '_JSON_STRINGS', pattern):
        try:
            return 'value', typed_graph(artifact._json(raw, limit))
        except artifact.ArtifactInvalid as exc:
            return 'error', type(exc), str(exc)


class ArtifactJsonLexerEquivalenceTests(unittest.TestCase):
    def assert_lexical_equal(self, raw):
        self.assertEqual([m.span() for m in OLD_STRINGS.finditer(raw)],
                         [m.span() for m in CURRENT_STRINGS.finditer(raw)])
        self.assertEqual(OLD_STRINGS.findall(raw), CURRENT_STRINGS.findall(raw))
        before = OLD_STRINGS.sub(b'', raw)
        after = CURRENT_STRINGS.sub(b'', raw)
        self.assertEqual(before, after)
        self.assertEqual(before.translate(None, artifact._NON_JSON_TOKENS),
                         after.translate(None, artifact._NON_JSON_TOKENS))

    def assert_decode_equal(self, raw, *, limit=None):
        limit = len(raw) if limit is None else limit
        old = decode_outcome(OLD_STRINGS, raw, limit)
        new = decode_outcome(CURRENT_STRINGS, raw, limit)
        self.assertEqual(old, new, repr(raw[:96]))
        return new

    def test_exhaustive_bounded_escape_delimiter_control_and_invalid_byte_language(self):
        # 137,257 inputs, including malformed bytes; enumerate independently of
        # the regex grammar rather than constructing only valid JSON strings.
        alphabet = (34, 92, 10, 97, 0, 255, 123)
        cases = 0
        for size in range(7):
            for symbols in product(alphabet, repeat=size):
                self.assert_lexical_equal(bytes(symbols))
                cases += 1
        self.assertEqual(cases, 137257)

    def test_decoded_dto_values_types_unicode_and_escaped_punctuation_equal(self):
        values = [None, True, False, 0, -1, 1.25, -0.0,
                  {'id': 'ja:FIX:001/100:normal', 'language': 'ja',
                   'name': 'ミュウツー', 'alias': 'Mewtwo', 'display_allowed': False,
                   'purchase_allowed': False, 'nested': [None, True, 1, 'é😀\u0000']},
                  {'brackets': '[]{}' * 40, 'escape': '"\\\n\r\t', 'number': '001/100'},
                  ['日本語', 'Español', 'e\u0301', '\ud800', '\udfff', '\ud83d\ude00']]
        for value in values:
            for ascii_only in (True, False):
                # Lone surrogates have a valid escaped JSON representation but
                # cannot be encoded as literal UTF-8. Preserve that distinction.
                try:
                    raw = json.dumps(value, ensure_ascii=ascii_only).encode('utf-8')
                except UnicodeEncodeError:
                    continue
                with self.subTest(value_type=type(value), ascii_only=ascii_only):
                    self.assert_lexical_equal(raw)
                    outcome = self.assert_decode_equal(raw)
                    self.assertEqual(outcome, ('value', typed_graph(json.loads(raw))))

    def test_malformed_unicode_utf8_escapes_and_syntax_preserve_rejections(self):
        cases = [b'"unterminated', b'"trailing\\', b'"bad\\q"', b'"bad\\u12xz"',
                 b'"bad\\u123"', b'"raw\nnewline"', b'"raw\x00control"',
                 b'{"x":"\xff"}', b'{"x":"\xc0\xaf"}',
                 b'{"x":"\xf4\x90\x80\x80"}', b'{"x":1,}', b'[1,]', b'"a" "b"',
                 b'{"x":', b'[]]', b'\\"', b'"\\\n"']
        for raw in cases:
            with self.subTest(raw=raw):
                self.assert_lexical_equal(raw)
                self.assertEqual(self.assert_decode_equal(raw)[0], 'error')

    def test_existing_surrogatepass_decode_and_strict_utf8_reencoding_are_preserved(self):
        # json.loads(bytes) retains its existing surrogatepass behavior. The
        # canonical UTF-8 serializer still rejects the resulting lone surrogate.
        for raw in (b'{"x":"\xed\xa0\x80"}', b'{"x":"\\ud800"}'):
            self.assert_lexical_equal(raw)
            self.assertEqual(self.assert_decode_equal(raw),
                             ('value', typed_graph({'x': '\ud800'})))
            for pattern in (OLD_STRINGS, CURRENT_STRINGS):
                with patch.object(artifact, '_JSON_STRINGS', pattern):
                    value = artifact._json(raw, len(raw))
                    with self.assertRaises(UnicodeEncodeError):
                        artifact._json_bytes(value)

    def test_bounded_unclosed_escaped_quote_search_family_has_equal_output(self):
        # Both unanchored regexes may retry internal escaped-quote openings;
        # this preexisting quadratic family is bounded, with no timing assertion.
        for count in (0, 1, 8, 64, 500, 1000, 2000):
            for suffix in (b'', b'"', b'\\', b'\n'):
                raw = b'"' + b'\\"' * count + suffix
                with self.subTest(count=count, suffix=suffix):
                    self.assert_lexical_equal(raw)
                    self.assert_decode_equal(raw)

    def test_actual_metadata_byte_cap_rejects_before_lexing(self):
        raw = b'0' + b' ' * artifact.MAX_METADATA_BYTES
        for pattern in (OLD_STRINGS, CURRENT_STRINGS):
            with patch.object(artifact, '_JSON_STRINGS', pattern), \
                 patch.object(artifact.json, 'loads', side_effect=AssertionError('decoder reached')):
                with self.assertRaisesRegex(artifact.ArtifactInvalid, 'JSON byte bound'):
                    artifact._json(raw, artifact.MAX_METADATA_BYTES)
        self.assertEqual(self.assert_decode_equal(raw[:-1], limit=artifact.MAX_METADATA_BYTES),
                         ('value', typed_graph(0)))

    def test_actual_depth_cap_and_quoted_nesting_have_identical_outcomes(self):
        for depth in (31, 32, 33):
            raw = b'[' * depth + b'0' + b']' * depth
            outcome = self.assert_decode_equal(raw)
            self.assertEqual(outcome[0], 'value' if depth <= 32 else 'error')
        raw = json.dumps({'quoted': '[' * 100 + ']' * 100}).encode()
        self.assertEqual(self.assert_decode_equal(raw)[0], 'value')

    def test_actual_member_cap_includes_commas_and_keeps_scalar_types(self):
        # A JSON array of N scalar zeros has N+1 counted punctuation tokens.
        for members in (artifact.MAX_JSON_MEMBERS - 1, artifact.MAX_JSON_MEMBERS,
                        artifact.MAX_JSON_MEMBERS + 1):
            elements = members - 1
            raw = b'[' + b'0,' * (elements - 1) + b'0]'
            for pattern in (OLD_STRINGS, CURRENT_STRINGS):
                with patch.object(artifact, '_JSON_STRINGS', pattern):
                    if members > artifact.MAX_JSON_MEMBERS:
                        with self.assertRaisesRegex(artifact.ArtifactInvalid, 'JSON member bound'):
                            artifact._json(raw, artifact.MAX_METADATA_BYTES)
                    else:
                        value = artifact._json(raw, artifact.MAX_METADATA_BYTES)
                        self.assertIs(type(value), list)
                        self.assertEqual(len(value), elements)
                        self.assertTrue(all(type(item) is int and item == 0 for item in value))

    def test_actual_aggregate_cap_counts_outer_and_unique_nested_roots(self):
        # The released reference regex's near-million-token string fixture
        # raises process-lifetime peak RSS. Run its unchanged assertions in a
        # fresh interpreter so later caller memory benchmarks measure their own
        # workload. Neither the artifact nor benchmark limits are patched.
        if '--aggregate-bound-child' not in sys.argv:
            result = subprocess.run(
                [sys.executable, '-B', str(Path(__file__).resolve()),
                 '--aggregate-bound-child'],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Ran 1 test', result.stderr)
            self.assertTrue(result.stderr.rstrip().endswith('OK'))
            return
        def state_for(elements):
            nested = '[' + '0,' * (elements - 1) + '0]'
            return {'affiliations_json': '[]', 'release_aliases_json': '[]',
                    'card_source_context_index': {'context_strings': [nested, nested],
                                                  'default_string': nested}}
        tiny = json.dumps(state_for(1), separators=(',', ':')).encode()
        outer = len(OLD_STRINGS.sub(b'', tiny).translate(None, artifact._NON_JSON_TOKENS))
        # Duplicate nested strings count once, and the repeated [] root once.
        elements = artifact.MAX_JSON_MEMBERS - outer - 2 - 1
        for over in (0, 1):
            state = state_for(elements + over)
            raw = json.dumps(state, separators=(',', ':')).encode()
            for pattern in (OLD_STRINGS, CURRENT_STRINGS):
                with patch.object(artifact, '_JSON_STRINGS', pattern):
                    artifact._json(raw, artifact.MAX_METADATA_BYTES)
                    if over:
                        with self.assertRaisesRegex(artifact.ArtifactInvalid, 'aggregate nested JSON member bound'):
                            context_index.validate_aggregate_json_members(state, raw)
                    else:
                        context_index.validate_aggregate_json_members(state, raw)

    def test_duplicate_decoded_keys_and_nonfinite_literals_keep_errors(self):
        cases = [b'{"x":1,"x":2}', b'{"x":1,"\\u0078":2}',
                 b'{"nested":{"x":1,"x":2}}', b'NaN', b'Infinity', b'-Infinity',
                 b'{"value":NaN}', b'[Infinity]']
        for raw in cases:
            with self.subTest(raw=raw):
                outcome = self.assert_decode_equal(raw)
                self.assertEqual(outcome[0], 'error')
                self.assertTrue('duplicate JSON field' in outcome[2] or
                                'JSON nonfinite value' in outcome[2])

    def test_original_cooperative_checkpoints_still_reject_expired_work(self):
        for pattern in (OLD_STRINGS, CURRENT_STRINGS):
            for raw in (b'[0]', b'0'):
                with patch.object(artifact, '_JSON_STRINGS', pattern), \
                     patch.object(runtime, 'checkpoint', side_effect=runtime.CatalogDeadline) as checkpoint:
                    with self.assertRaises(runtime.CatalogDeadline):
                        artifact._json(raw, 100)
                    checkpoint.assert_called_once()


if __name__ == '__main__':
    if '--aggregate-bound-child' in sys.argv:
        unittest.main(argv=[sys.argv[0],
            'ArtifactJsonLexerEquivalenceTests.test_actual_aggregate_cap_counts_outer_and_unique_nested_roots'])
    else:
        unittest.main()
