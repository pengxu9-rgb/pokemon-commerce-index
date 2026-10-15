"""Derived literals preserve the concrete native parser's Unicode semantics."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_discovery as discovery
from pokemon_index import collector_runtime as runtime, collector_release_alias
from pokemon_index import catalog_read_model_artifact as artifact
from pokemon_index import printing_evidence, source_corrections, supported_catalog
from scripts.rehearse_collector_recommendations import create_fixture, SUITE
from tests import test_printing_evidence as printing_fixture


def typed(value):
    """Keep container and scalar types visible in the native comparison."""
    if type(value) is dict:
        return ('dict', tuple((key, typed(item)) for key, item in sorted(value.items())))
    if type(value) in (tuple, list):
        return (type(value).__name__, tuple(typed(item) for item in value))
    if type(value) in (set, frozenset):
        return (type(value).__name__, tuple(sorted(typed(item) for item in value)))
    return (type(value).__name__, value)


class NormalizedMentionTests(unittest.TestCase):
    def test_prepared_literal_matches_native_boundary_and_unicode_predicate(self):
        terms = ['', ' ', 'Alpha', 'Alpha Beta', "O'Neil", 'a-b.c', '151',
                 'ß', 'Straße', 'ß\u0301', 'ẞ\u0301', 'é', 'e\u0301',
                 'カタカナ', 'ｶﾀｶﾅ', 'ピカチュウ', 'ＡＢＣ', 'İ', 'Σ']
        wrappers = [('', ''), (' ', ' '), ('x', ''), ('', '9'),
                    ('(', ').'), ('é', '界'), ('/', '/'), ('-', '.a')]
        for term in terms:
            literal = discovery._norm(term)
            for prefix, suffix in wrappers:
                for raw in (term, literal, term.swapcase()):
                    text = discovery._norm(prefix + raw + suffix)
                    with self.subTest(term=term, text=text):
                        self.assertIs(discovery._normalized_mentioned(text, literal),
                                      discovery._mentioned(text, term))
            self.assertIs(discovery._normalized_mentioned('unrelated', literal),
                          discovery._mentioned('unrelated', term))

    def test_non_idempotent_casefold_sequence_is_normalized_exactly_once(self):
        # Casefold expands sharp S after NFKC. Another NFKC pass composes the
        # final s with the accent, changing substring matching.
        for raw in ('ß\u0301', 'ẞ\u0301'):
            once = discovery._norm(raw)
            twice = discovery._norm(once)
            self.assertEqual(once, 'ss\u0301')
            self.assertEqual(twice, 'sś')
            self.assertNotEqual(once, twice)
            self.assertTrue(discovery._mentioned(once, raw))
            self.assertTrue(discovery._normalized_mentioned(once, once))
            self.assertFalse(discovery._normalized_mentioned(once, twice))

    def test_ascii_boundaries_remain_distinct_from_unicode_substrings(self):
        examples = [('xalpha', 'Alpha', False), ('alpha9', 'Alpha', False),
                    ('éalpha界', 'Alpha', True), ('(alpha).', 'Alpha', True),
                    ('xピカチュウ9', 'ピカチュウ', True),
                    ('strasse', 'Straße', True), ('xstrasse', 'Straße', False),
                    ('', '', True), ('anything', '', True)]
        for text, raw, expected in examples:
            with self.subTest(text=text, term=raw):
                self.assertIs(discovery._normalized_mentioned(text, discovery._norm(raw)), expected)
                self.assertIs(discovery._mentioned(text, raw), expected)


class NormalizedParserFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.path = self.base / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        with closing(core.connect(self.path)) as db:
            self._enrich(db)
            db.commit()
        aliases = self.base / 'synthetic-aliases.json'
        aliases.write_text(json.dumps(self.alias_payload, ensure_ascii=False))
        patcher = patch.object(collector_release_alias, 'BINDINGS_PATH', aliases)
        patcher.start(); self.addCleanup(patcher.stop)
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text('{"synthetic_only":true}')
        with closing(core.connect(self.path, readonly=True)) as db:
            self.native = runtime.CatalogReadModel(db)
        with closing(core.connect(self.path, readonly=True)) as db:
            seal = artifact.write(db, self.manifest, self.base / 'artifact')
        with closing(core.connect(self.path, readonly=True)) as db:
            self.loaded, _, _ = artifact.load(db, self.base / 'artifact', self.manifest,
                                              expected_seal_sha256=seal['seal_sha256'])
        self.models = (self.native, self.loaded)
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        for scope in (runtime._catalog_scope, runtime._snapshot_scope, runtime._parser_plan_scope):
            self.assertIsNone(scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def _enrich(self, db):
        releases = [('ja', 'N151', '151'), ('en', 'EN151', '151'),
                    ('ja', 'SV-P', 'Synthetic Promo'), ('ja', 'SV.P', 'Synthetic Dot'),
                    ('ja', 'SHARED', '名探偵ピカチュウ'),
                    ('ja', 'NEST', 'ピカチュウ'), ('ja', 'UNICODE', 'Synthetic Unicode')]
        for language, code, name in releases:
            core.import_sets(db, [dict(language=language, set_code=code, name=name,
                                      provenance='synthetic:normalized-parser',
                                      rights_reference='synthetic:no-display')])
            core.import_cards(db, [dict(language=language, set_code=code,
                                       collector_number='001/151', variant='unverified',
                                       name='Pikachu', provenance='synthetic:normalized-parser',
                                       rights_reference='synthetic:no-display')])
        for language, code, kind, alias in [
            ('ja', 'N151', 'set_name', 'ポケモンカード151'),
            ('ja', 'N151', 'set_name', 'ポケモンカード１５１'),
            ('ja', 'SV-P', 'printed_code', 'ＳＶ－Ｐ'),
            ('ja', 'SV.P', 'printed_code', 'sv.p'),
            ('en', 'EN151', 'printed_code', 'EN.151'),
            ('ja', 'UNICODE', 'printed_code', 'ß\u0301')]:
            db.execute('INSERT INTO catalog_vocabulary VALUES (?,?,?,?,?)',
                       (language, code, alias, kind, '{"synthetic_only":true}'))
        cid = 'ja:FIX:001/100:normal'
        for artist in ['Alpha Beta', 'ＡＬＰＨＡ ＢＥＴＡ', 'HACCAN', 'Straße',
                       'ß\u0301', 'ẞ\u0301', 'ｶﾀｶﾅ', 'A\u00a0B', 'One\u200bTwo', '']:
            db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                       (cid, 'illustrator', artist, 'synthetic:normalized-parser', 'synthetic:no-display'))
        # Same title and equal spans retain ambiguity; a longer current title
        # suppresses only the nested occurrence, just as the native reader does.
        for number, name, dex in [('090/100', 'Shared Name', 25),
                                  ('091/100', 'Shared Name', 133),
                                  ('092/100', 'ミュウツー', 150), ('093/100', 'ミュウ', 151)]:
            core.import_cards(db, [dict(language='ja', set_code='FIX', collector_number=number,
                                       variant='normal', name=name, provenance='synthetic:normalized-parser',
                                       rights_reference='synthetic:no-display')])
            db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                       (core.card_id('ja', 'FIX', number, 'normal'), 'dex_id', str(dex),
                        'synthetic:normalized-parser', 'synthetic:no-display'))
        # Adapt an existing explicitly synthetic source-reading fixture through
        # the normal validators. No provider acquisition or real rights claim.
        fixture = printing_fixture.PrintingEvidenceTests(); fixture.setUp()
        try:
            core.import_card_references(db, [dict(row, source_jp_id=row['native_id'])
                for row in fixture.db.execute('SELECT * FROM card_reference')])
            parent = copy.deepcopy(fixture.row)
        finally:
            fixture.db.close(); fixture.doCleanups()
        parent['identity_sha256'] = supported_catalog.digest(printing_evidence.identity(db, 'coordinate', 'ja:FIX:001/100'))
        parent['observations'][0].update(claim='printed_qualifier', value='オーリム博士')
        for reviewer in parent['reviewers']:
            reviewer['observations_sha256'] = supported_catalog.digest(parent['observations'])
        parent['event_id'] = printing_evidence.event_id(parent)
        printing_evidence.import_evidence(db, [parent])
        encoded = db.execute('SELECT record_json FROM printing_source_evidence WHERE event_id=?',
                             (parent['event_id'],)).fetchone()[0]
        correction = dict(schema='pokemon.source-correction.v1', revision=1,
            kind='printed_qualifier', language='ja', set_code='FIX', collector_number='001/100',
            correction_key='printed_qualifier:ja:FIX:001/100',
            snapshot=source_corrections.snapshot(db, 'ja', 'FIX', '001/100'),
            parent_event_id=parent['event_id'], parent_record_json=encoded,
            parent_record_sha256=supported_catalog.digest(parent), value='オーリム博士',
            reference_exclusion=None, new_card=None, new_reference=None, official_page=None,
            recorded_at='2026-10-02T00:01:00Z', **{key: False for key in source_corrections.FALSE_CLAIMS})
        correction['event_id'] = source_corrections.event_id(correction)
        source_corrections.import_evidence(db, [correction])
        # A deliberately stale conflicting source head stays visible as an
        # inactive finding; the parser must not promote it to active evidence.
        stale = copy.deepcopy(correction)
        stale.update(event_id='synthetic-stale-qualifier', value='フトゥー博士',
                     correction_key='printed_qualifier:ja:FIX:099/100', collector_number='099/100')
        db.execute('INSERT INTO source_correction_evidence VALUES (?,?,?,?,?,?,?,?)',
                   (stale['event_id'], stale['correction_key'], 1, 'printed_qualifier',
                    'ja', 'FIX', '099/100', json.dumps(stale, ensure_ascii=False)))
        evidence = dict(official_url='https://example.invalid/synthetic-release', official_page_sha256='a' * 64)
        db.execute('INSERT INTO catalog_release_evidence VALUES (?,?,?)', ('ja', 'SHARED', json.dumps(evidence)))
        current = dict(db.execute("SELECT * FROM catalog_set_localized WHERE language='ja' AND set_code='SHARED'").fetchone())
        self.alias_payload = dict(schema='pokemon.reviewed-release-name-aliases.v1', records=[dict(
            schema='pokemon.reviewed-release-name-alias.v1', alias='Synthetic Detective Pikachu',
            language='ja', set_code='SHARED', derivation='reviewed_english_rendering_of_exact_official_japanese_title.v1',
            source_published_alias=False, source_title='名探偵ピカチュウ',
            current_release=current, release_evidence=evidence)])

    def native_projection(self, db, text, languages):
        # These are the original concrete DB readers, outside a model scope.
        # Their SQL, correction validation and public return types are the
        # oracle; no copy of the eager plan implementation is embedded here.
        without = discovery._without_release_names(db, text, list(languages))
        return (discovery._artists(db, text),
                discovery._release_name_mentions(db, text, list(languages)),
                discovery._release_codes(db, text, list(languages)), without,
                discovery._character_ids(db, text), discovery._character_ids(db, without),
                discovery._qualifier_findings(db, text, list(languages)),
                discovery._unsupported_professors(db, text),
                discovery.requested_name_suffix(db, text, list(languages)),
                discovery.reviewed_release_interpretations(db, text, list(languages)))

    @staticmethod
    def plan_projection(plan):
        return (list(plan.artists), list(plan.names), set(plan.codes), plan.without,
                list(plan.ids), list(plan.without_ids), json.loads(plan.qualifiers_json),
                list(plan.professors), plan.suffix, json.loads(plan.interpretations_json))

    def test_all_plan_dimensions_match_concrete_native_readers(self):
        questions = ['Japanese cards 001/151', 'English set 151', 'Japanese 151',
            'Japanese 151 ポケモンカード', 'English 151 ポケモンカード',
            'Japanese cards from ポケモンカード１５１', 'Japanese SV-P.',
            'Japanese SV-P-extra', 'Japanese SV.P', 'Japanese sv.p-extra',
            'English EN.151.', 'English EN.151-extra', 'Japanese ＳＶ－Ｐ 001/151',
            'Japanese cards from 名探偵ピカチュウ Pikachu ex',
            'Japanese cards from Synthetic Detective Pikachu',
            'cards by Alpha Beta', 'ＡＬＰＨＡ ＢＥＴＡ！', 'AlphaBeta',
            'HACCAN', 'by HACCAN', 'by Straße', 'by ß\u0301', 'by ẞ\u0301',
            'by ｶﾀｶﾅ', 'A\u00a0B', 'One\u200bTwo', ' .Alpha Beta。!！',
            'Japanese オーリム博士 フトゥー博士', 'English オーリム博士',
            '博士の研究 オダマキ博士', 'Professor Oak', 'which professor is printed?',
            'Shared Name ex', 'ミュウツー and ミュウ ex', 'unknown private question marker']
        for raw in questions:
            text = discovery._norm(raw)
            for languages in [('ja',), ('en',), ('ja', 'en'), ('en', 'ja'), ('ja', 'ja')]:
                with closing(core.connect(self.path, readonly=True)) as db:
                    expected = self.native_projection(db, text, languages)
                for model in self.models:
                    for strict in (False, True):
                        with self.subTest(question=raw, languages=languages, loaded=model is self.loaded, strict=strict):
                            direct = discovery._question_plan_from_facts(text, languages, model._parser_facts)
                            self.assertEqual(typed(self.plan_projection(direct)), typed(expected))
                            with closing(core.connect(self.path, readonly=True)) as db, model.request(db, strict_readonly=strict):
                                scoped = runtime.snapshot_question_plan(db, text, languages)
                                self.assertEqual(typed(scoped), typed(direct))

    def test_exact_artist_raw_split_strip_and_one_pass_normalization(self):
        cases = [('Alpha Beta', ('Alpha Beta', 'ＡＬＰＨＡ ＢＥＴＡ')),
                 (' .ＡＬＰＨＡ ＢＥＴＡ。!！', ('Alpha Beta', 'ＡＬＰＨＡ ＢＥＴＡ')),
                 ('A\u00a0B', ('A\u00a0B',)), ('One\u200bTwo', ('One\u200bTwo',)),
                 ('ß\u0301', ('ß\u0301', 'ẞ\u0301')), ('HACCAN', ('HACCAN',))]
        for model in self.models:
            for raw, expected in cases:
                with self.subTest(raw=raw, loaded=model is self.loaded):
                    plan = discovery._question_plan_from_facts(discovery._norm(raw), ('ja', 'en'), model._parser_facts)
                    self.assertEqual(plan.exact_artists, expected)
                    # Raw Unicode whitespace controls whether intent is needed;
                    # zero-width space is not silently converted to whitespace.
                    if raw == 'A\u00a0B': self.assertIn('A\u00a0B', plan.artists)
                    if raw in ('One\u200bTwo', 'HACCAN'): self.assertNotIn(raw, plan.artists)

    def test_numeric_slash_code_continuation_and_conflict_guards_have_real_matches(self):
        for model in self.models:
            facts = model._parser_facts
            for question, codes in [('Japanese cards 001/151', set()),
                                    ('Japanese 151', {'N151'}),
                                    ('English set 151', {'EN151'}),
                                    ('Japanese SV-P.', {'SV-P'}),
                                    ('Japanese SV-P-extra', set()),
                                    ('Japanese SV.P', {'SV.P'}),
                                    ('Japanese SV.P-extra', set())]:
                languages = ('en',) if question.startswith('English') else ('ja',)
                with self.subTest(question=question, loaded=model is self.loaded):
                    self.assertEqual(set(discovery._question_plan_from_facts(
                        discovery._norm(question), languages, facts).codes), codes)
            plan = discovery._question_plan_from_facts('オーリム博士 フトゥー博士', ('ja',), facts)
            findings = {row['value']: row['active'] for row in json.loads(plan.qualifiers_json)}
            self.assertEqual(findings, {'オーリム博士': True, 'フトゥー博士': False})
            english = discovery._question_plan_from_facts('オーリム博士', ('en',), facts)
            self.assertFalse(json.loads(english.qualifiers_json)[0]['active'])
            ambiguity = discovery._question_plan_from_facts('shared name ex', ('ja',), facts)
            self.assertEqual(ambiguity.ids, (25, 133))
            self.assertIsNone(ambiguity.suffix)
            alias = discovery._question_plan_from_facts('synthetic detective pikachu', ('ja',), facts)
            self.assertEqual(json.loads(alias.interpretations_json)[0]['set_code'], 'SHARED')

    def test_derived_fields_are_immutable_raw_serialization_and_memory_accounted(self):
        for model in self.models:
            facts = model._parser_facts; state = facts.to_state()
            self.assertEqual(set(state), {'schema', 'vocabulary', 'qualifiers', 'known_qualifiers'})
            self.assertNotIn('normalized', json.dumps(state, ensure_ascii=False))
            self.assertIn('ß\u0301', [row[0] for row in facts.artists])
            self.assertIn(('ß\u0301', 'ss\u0301', False), facts.normalized.artists)
            with self.assertRaises(AttributeError): facts.normalized = ()
            with self.assertRaises(AttributeError): facts.normalized.artists = ()
            with self.assertRaises(TypeError): facts.normalized.artists[0] = ()
            restored = discovery._restore_parser_facts(copy.deepcopy(state), model)
            self.assertEqual(typed(restored), typed(facts))
            self.assertEqual(restored.to_state(), state)
            with self.assertRaises(TypeError): facts.normalized.character_names['unreviewed'] = ()
            if facts.normalized.character_names:
                rows = next(iter(facts.normalized.character_names.values()))
                with self.assertRaises(TypeError): rows[0] = ()
            raw_only = facts._replace(normalized=discovery._NormalizedParserFacts((), (), (), (), (), MappingProxyType({})))
            self.assertGreater(artifact._deep_size(facts), artifact._deep_size(raw_only))
            raw_model = dict(model.__dict__); raw_model['_parser_facts'] = raw_only
            self.assertGreater(artifact._deep_size(model.__dict__), artifact._deep_size(raw_model))
            state['vocabulary'].clear(); state['qualifiers'].clear(); state['known_qualifiers'].clear()
            self.assertTrue(facts.vocabulary); self.assertTrue(facts.qualifiers)
            self.assertNotIn('unknown private question marker', repr(model.__dict__))

    def test_candidate_filter_preserves_full_scan_occurrences_ambiguity_and_order(self):
        rows = (('', 999, False), ('a', 1, True), ('ab', 2, True),
                ('abc', 3, False), ('ab', 4, False), ('a-b', 5, True),
                ('ミュウ', 151, True), ('ミュウツー', 150, True),
                ('shared name', 25, True), ('shared name', 133, True),
                ('ss\u0301', 6, True), ('sś', 7, True), ('\u0301', 8, True), ('x', 9, False))
        raw_model = SimpleNamespace(_vocabularies=self.native._vocabularies,
            _release_names=self.native._release_names, _character_names={False: rows},
            _release_aliases_json=self.native._release_aliases_json)
        facts = discovery._parser_facts_from_state(self.native._parser_facts.to_state(), raw_model)
        index = facts.normalized.character_names
        self.assertNotIn('', index)
        self.assertIn('a', index)
        self.assertTrue(all(1 <= len(key) <= 2 for key in index))
        questions = ['', 'unrelated', 'a', 'a a', 'xab9', 'abc', 'a-b',
                     'ミュウツー and ミュウ', 'shared name and shared name',
                     'ss\u0301', 'sś', '\u0301', 'ミュウab shared name a-b x']
        for text in questions:
            candidates = discovery._candidate_character_names(text, index)
            # Prefix selection must retain each original row once, in native
            # traversal order, including duplicate names with different IDs.
            expected_order = tuple(row for row in rows if row[0] and row[0][:2] in text)
            self.assertEqual(candidates, expected_order, text)
            for maximal in (False, True):
                with self.subTest(text=text, maximal=maximal):
                    expected = discovery._character_mentions_from_names(text, rows, maximal=maximal)
                    observed = discovery._character_mentions_from_names(text, candidates, maximal=maximal)
                    self.assertEqual(typed(observed), typed(expected))
        self.assertEqual({row[0] for row in discovery._character_mentions_from_names('shared name', rows)}, {25, 133})
        with self.assertRaises(TypeError): index['ab'] = ()


if __name__ == '__main__': unittest.main()
