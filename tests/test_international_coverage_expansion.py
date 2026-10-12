import copy
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts import audit_international_coverage_expansion as audit
from scripts import build_international_coverage_expansion as compiler


class InternationalCoverageExpansionTests(unittest.TestCase):
    TIME = '2026-10-11T13:43:00Z'

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name); self.repo = self.root / 'source'; self.repo.mkdir()
        license_bytes = b'Synthetic test-only licence notice\n'
        (self.repo / 'LICENSE').write_bytes(license_bytes)
        (self.root / 'catalog').mkdir(); (self.root / 'catalog/TCGDEX-LICENSE').write_bytes(license_bytes)
        self.paths = []
        for code in compiler.SETS[:3]:
            self.paths.append(('ja', code, f'data-asia/FIX/{code}/001.ts'))
        self.paths.extend(('en', 'SM7', f'data/FIX/SM7/{i:03}.ts') for i in range(1, 26))
        for _, _, relative in self.paths:
            target = self.repo / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('''const card: Card = {name: {ja: "霧の水晶", en: "Fog Crystal"},
                category: "Trainer", variants: [{type: "normal"}, {type: "reverse"}]};
                export default card;''')
        for command in (['git', 'init', '-q'], ['git', 'add', '.'],
                        ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid', 'commit', '-qm', 'test-only pin']):
            subprocess.run(command, cwd=self.repo, check=True, capture_output=True)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.repo, text=True).strip()
        self.addCleanup(patch.stopall)
        patch.object(compiler, 'REVISION', revision).start()
        patch.object(compiler, 'RIGHTS', f'https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE').start()
        self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close); core.init_db(self.db)
        for language, code in {(language, code) for language, code, _ in self.paths}:
            core.import_sets(self.db, [dict(language=language, set_code=code, name='合成テスト',
                official_card_count=100, provenance='synthetic:test-only', rights_reference='fixture')])
        for language, code, path in self.paths:
            cards = tcgdex_source.parse_card_source((self.repo/path).read_text(), set_id=code,
                official_count=100, path=path, revision=revision, language=language)
            core.import_cards(self.db, cards)
            for card in cards:
                self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',
                    (core.card_id(language, code, card['collector_number'], card['variant']), 'Trainer', None, 'fixture', 'fixture'))
        self.db.execute('''INSERT INTO bilingual_concept_revision
            (concept_id,revision,category,name_ja,name_en,source_ja,source_en,rights_reference,reviewer,reviewed_at,status)
            VALUES ('fog',1,'Trainer','霧の水晶','Fog Crystal','fixture','fixture','fixture','reviewer',?,'approved')''', (self.TIME,))
        self.db.commit()

    def compile(self):
        return compiler.compile_rows(self.db, self.repo, self.root, self.TIME)

    def test_bounded_selection_preserves_ids_unknown_regions_and_all_trading_flags(self):
        old = audit.records(self.db, 'card'); rows, selection, _ = self.compile()
        self.assertEqual((selection['japanese'], selection['english']), (6, 25))
        self.assertEqual(len({r['identity']['card_id'] for r in rows}), 31)
        self.assertEqual(audit.records(self.db, 'card'), old)
        for row in rows:
            self.assertEqual(row['source']['region'], 'ZZ')
            self.assertIsNone(row['source']['physical_distribution_region'])
            self.assertIsNone(row['source']['retrieved_at'])
            self.assertEqual(len(row['source']['git_blob']), 40)
            for flag in catalog_locale.FALSE_CLAIMS:
                self.assertFalse(row[flag])

    def test_existing_mapping_is_excluded_even_without_locale_evidence(self):
        rows, _, _ = self.compile(); source = rows[0]['source']; cid = rows[0]['identity']['card_id']
        self.db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',
            (*(source[k] for k in catalog_locale.SOURCE_FIELDS), cid))
        selected = {c['card_id'] for c, _ in compiler.pairs(self.db)}
        self.assertNotIn(cid, selected)

    def test_already_translated_query_is_not_reimported_under_new_evidence(self):
        with patch.object(core, 'catalog_search_internal', return_value={'total': 1, 'cards': [{'card_id': compiler.pairs(self.db)[0][0]['card_id']}]}):
            with self.assertRaisesRegex(ValueError, 'already retrievable'):
                self.compile()

    def test_ambiguous_reviewed_concepts_abort_instead_of_guessing(self):
        self.db.execute("INSERT INTO bilingual_concept_revision SELECT 'other', revision, category, name_ja, name_en, source_ja, source_en, rights_reference, reviewer, reviewed_at, status, review_event_id FROM bilingual_concept_revision")
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            compiler.pairs(self.db)

    def test_withdrawn_current_revision_does_not_reuse_old_review(self):
        self.db.execute("INSERT INTO bilingual_concept_revision SELECT concept_id, 2, category, name_ja, name_en, source_ja, source_en, rights_reference, reviewer, reviewed_at, 'withdrawn', review_event_id FROM bilingual_concept_revision")
        with self.assertRaisesRegex(ValueError, 'bounded'):
            compiler.pairs(self.db)

    def test_source_category_must_match_even_if_database_and_alias_agree(self):
        self.db.execute("UPDATE card_classification SET category='Energy'")
        self.db.execute("UPDATE bilingual_concept_revision SET category='Energy'")
        with self.assertRaisesRegex(ValueError, 'source category'):
            self.compile()

    def test_cap_and_set_bounds_abstain_without_silent_truncation(self):
        with patch.object(compiler, 'MAX_JAPANESE', 5):
            with self.assertRaisesRegex(ValueError, 'bounded'):
                compiler.pairs(self.db)
        self.db.execute('DELETE FROM card_classification WHERE card_id LIKE ?', ('ja:' + compiler.SETS[0] + ':%',))
        with self.assertRaisesRegex(ValueError, 'bounded'):
            compiler.pairs(self.db)

    def test_missing_fields_and_pocket_or_unreviewed_provenance_abstain(self):
        card = dict(compiler.pairs(self.db)[0][0])
        for path in ['data/Pocket/A/001.ts', '/data/FIX/001.ts', 'data/../001.ts', 'data/Digital/A/001.ts']:
            changed = {**card, 'provenance': f'tcgdex:{compiler.REVISION}:{path}:sha256:' + 'a'*64}
            with self.subTest(path=path), self.assertRaises(ValueError):
                compiler.source_fields(changed)
        for field in ('provenance', 'rights_reference'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                compiler.source_fields({**card, field: 'unreviewed'})
        self.db.execute('UPDATE catalog_set_localized SET official_card_count=0')
        with self.assertRaisesRegex(ValueError, 'name/count missing'):
            self.compile()

    def test_unresolved_variants_are_not_promoted(self):
        self.db.execute("UPDATE card SET variant='unverified_' || variant WHERE language='ja'")
        with self.assertRaisesRegex(ValueError, 'bounded'):
            compiler.pairs(self.db)

    def test_missing_dates_remain_unknown_without_cross_language_fallback(self):
        self.db.execute("UPDATE catalog_set_localized SET release_date='2024-01-01' WHERE language='en'")
        rows, _, _ = self.compile()
        self.assertTrue(all(r['release_snapshot']['release_date'] is None for r in rows if r['identity']['language']=='ja'))

    def test_source_bytes_and_license_must_match_the_pin_and_review(self):
        path = self.repo / self.paths[0][2]; old = path.read_bytes()
        path.write_bytes(old + b'// drift\n')
        with self.assertRaisesRegex(ValueError, 'pinned Git blob'):
            self.compile()
        path.write_bytes(old)
        (self.root/'catalog/TCGDEX-LICENSE').write_bytes(b'different review')
        with self.assertRaisesRegex(ValueError, 'licence differs'):
            self.compile()

    def test_late_source_mutation_is_rejected(self):
        original = core.catalog_search_internal; path = self.repo / self.paths[0][2]
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs); path.write_bytes(path.read_bytes()+b'// late drift\n'); return result
        with patch.object(core, 'catalog_search_internal', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'pinned Git blob'):
                self.compile()

    def test_compilation_is_deterministic_and_expansion_reimport_is_idempotent(self):
        rows, selection, license_bytes = self.compile()
        self.assertEqual((rows, selection, license_bytes), self.compile())
        old = {table: audit.records(self.db, table) for table in audit.tables(self.db)}
        self.assertEqual(catalog_locale.import_evidence(self.db, rows), dict(inserted=31, unchanged=0, quarantined=0))
        for table in audit.tables(self.db):
            if table not in audit.APPEND_TABLES:
                self.assertEqual(audit.records(self.db, table), old[table])
        self.assertEqual(catalog_locale.import_evidence(self.db, rows), dict(inserted=0, unchanged=31, quarantined=0))

    def test_unicode_localized_search_and_variant_siblings_keep_distinct_ids(self):
        rows, _, _ = self.compile(); catalog_locale.import_evidence(self.db, rows)
        target = rows[0]['identity']; result = core.catalog_search_internal(self.db,
            'Ｆｏｇ Ｃｒｙｓｔａｌ ja', set_code=target['set_code'])
        self.assertEqual(result['total'], 2)
        self.assertEqual({r['variant'] for r in result['cards']}, {'normal', 'reverse'})
        self.assertEqual(len({r['card_id'] for r in result['cards']}), 2)
        self.assertEqual(core.catalog_search_internal(self.db, '霧の水晶 en', set_code=target['set_code'])['total'], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0], 0)

    def test_provider_collision_and_cross_region_reuse_are_quarantined(self):
        rows, _, _ = self.compile(); first = rows[0]; catalog_locale.import_evidence(self.db, [first])
        changed = copy.deepcopy(first); changed['source']['region']='JP'; changed.pop('evidence_id')
        changed['evidence_id']='catalog-locale:'+catalog_locale.digest(changed)
        self.assertEqual(catalog_locale.import_evidence(self.db, [changed])['quarantined'], 1)
        sibling = next(r for r in rows if r['identity']['language']=='ja' and r['identity']['set_code'] != first['identity']['set_code'])
        self.db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',
            (*(sibling['source'][k] for k in catalog_locale.SOURCE_FIELDS), first['identity']['card_id']))
        self.assertEqual(catalog_locale.import_evidence(self.db, [sibling])['quarantined'], 1)

    def test_mutated_database_and_existing_output_are_rejected_before_publication(self):
        db_path = self.root/'frozen.sqlite3'
        with closing(sqlite3.connect(db_path)) as output_db:
            self.db.backup(output_db)
        output = self.root/'artifact'; output.mkdir()
        with self.assertRaises(FileExistsError):
            compiler.build(db_path, self.repo, self.root, output, self.TIME)
        output.rmdir(); original = compiler.compile_rows
        def mutate(*args):
            result = original(*args)
            db_path.write_bytes(db_path.read_bytes()+b'test-only external file drift')
            return result
        with patch.object(compiler, 'compile_rows', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                compiler.build(db_path, self.repo, self.root, output, self.TIME)
        self.assertFalse(output.exists())

    def test_incremental_append_preserves_every_historical_table_and_refuses_replacement(self):
        rows, _, _ = self.compile(); artifact = self.root / Path(audit.LOCALES).parent
        artifact.mkdir(parents=True); (artifact/'locales.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        db_path = self.root/'before.sqlite3'; output = self.root/'after.sqlite3'
        with closing(sqlite3.connect(db_path)) as output_db:
            self.db.backup(output_db)
        self.assertEqual(audit.append(db_path, output, self.root)['inserted'], 31)
        with closing(core.connect(db_path, readonly=True)) as before, closing(core.connect(output)) as after:
            self.assertTrue(all(audit.preserved(before, after, 31).values()))
            after.execute("UPDATE card SET name='changed' WHERE language='ja'"); after.commit()
            with self.assertRaisesRegex(ValueError, 'historical records changed'):
                audit.preserved(before, after, 31)
        with self.assertRaises(FileExistsError):
            audit.append(db_path, output, self.root)

    def test_searchable_json_does_not_mask_wrong_stored_card_binding(self):
        rows, _, _ = self.compile(); catalog_locale.import_evidence(self.db, rows)
        self.assertTrue(audit.installed(self.db, rows))
        first = rows[0]; self.db.execute('UPDATE catalog_locale_evidence SET card_id=? WHERE evidence_id=?',
                                        (rows[1]['identity']['card_id'], first['evidence_id']))
        self.assertEqual(catalog_locale.import_evidence(self.db, rows)['unchanged'], 31)
        with self.assertRaisesRegex(ValueError, 'SQL binding differs'):
            audit.installed(self.db, rows)

    def test_missing_or_changed_source_mapping_is_detected(self):
        rows, _, _ = self.compile(); catalog_locale.import_evidence(self.db, rows)
        first = rows[0]
        self.db.execute('DELETE FROM catalog_source_mapping WHERE card_id=?', (first['identity']['card_id'],))
        with self.assertRaisesRegex(ValueError, 'source mapping differs'):
            audit.installed(self.db, rows)


if __name__ == '__main__':
    unittest.main()
