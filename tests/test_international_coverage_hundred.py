"""Hundred-level scope guards using synthetic, local Git-pinned metadata only."""
import copy
import json
import sqlite3
import subprocess
import unittest
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts import audit_international_coverage_expansion as audit
from scripts import audit_international_coverage_hundred as hundred_audit
from scripts import build_international_coverage_expansion as compiler
from scripts import build_international_coverage_hundred as hundred
from tests import test_international_coverage_expansion as fixtures


class HundredCoverageTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing source fixture without inheriting its test methods.
        fixture = fixtures.InternationalCoverageExpansionTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.db, self.repo, self.root, self.TIME = fixture.db, fixture.repo, fixture.root, fixture.TIME
        text = '''const card: Card = {name: {ja: "霧の水晶", en: "Fog Crystal"},
            category: "Trainer", variants: [{type: "normal"}]}; export default card;'''
        paths = []
        # All19 fixed scopes contribute; the synthetic total is exactly100 IDs.
        for index, code in enumerate(hundred.SCOPE.sets):
            core.import_sets(self.db, [dict(language='ja', set_code=code, name='合成テスト', official_card_count=100,
                provenance='synthetic:test-only', rights_reference='fixture')])
            for number in range(1, (5 if index < 14 else 6) + 1):
                path = f'data-asia/FIX/{code}/{number:03}.ts'; target = self.repo/path
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text); paths.append((code, path))
        subprocess.run(['git', 'add', '.'], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid',
                        'commit', '-qm', 'synthetic hundred pin'], cwd=self.repo, check=True, capture_output=True)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.repo, text=True).strip()
        old_revision = compiler.REVISION
        rights = f'https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE'
        # Existing synthetic English bytes are also members of the new fixture pin.
        self.db.execute('UPDATE card SET provenance=replace(provenance,?,?),rights_reference=?',
                        (old_revision, revision, rights))
        patcher = patch.object(compiler, 'REVISION', revision); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(compiler, 'RIGHTS', rights); patcher.start(); self.addCleanup(patcher.stop)
        for code, path in paths:
            rows = tcgdex_source.parse_card_source(text, set_id=code, official_count=100, path=path,
                                                  revision=revision, language='ja')
            core.import_cards(self.db, rows)
            self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',
                (core.card_id('ja', code, rows[0]['collector_number'], 'normal'), 'Trainer', None, 'fixture', 'fixture'))
        self.db.commit()

    def compile(self):
        return compiler.compile_rows(self.db, self.repo, self.root, self.TIME, scope=hundred.SCOPE)

    def frozen(self, name):
        target = self.root/name
        with closing(sqlite3.connect(target)) as db:
            self.db.backup(db)
        return target

    def test_exact_hundred_scope_is_fixed_immutable_and_disjoint_from_legacy_scope(self):
        selected = compiler.pairs(self.db, scope=hundred.SCOPE)
        self.assertEqual(sum(c['language']=='ja' for c, _ in selected), 100)
        self.assertEqual(sum(c['language']=='en' for c, _ in selected), 25)
        self.assertEqual({c['set_code'] for c, _ in selected if c['language']=='ja'}, set(hundred.SCOPE.sets))
        self.assertEqual(len({c['card_id'] for c, _ in selected}), 125)
        with self.assertRaises(FrozenInstanceError):
            hundred.SCOPE.japanese_records = 101

    def test_existing_five_set_default_remains_unchanged(self):
        selected = compiler.pairs(self.db)
        self.assertEqual(sum(c['language']=='ja' for c, _ in selected), 6)
        self.assertTrue({c['set_code'] for c, _ in selected if c['language']=='ja'}.issubset(compiler.SETS))
        self.assertEqual(audit.profile_or_default(None).prior_inputs, 68)
        self.assertEqual(hundred_audit.PROFILE.prior_inputs, 69)

    def test_short_batch_abstains_without_filling_from_other_sets(self):
        target = compiler.pairs(self.db, scope=hundred.SCOPE)[0][0]['card_id']
        self.db.execute('DELETE FROM card_classification WHERE card_id=?', (target,))
        with self.assertRaisesRegex(ValueError, 'explicit Japanese'):
            compiler.pairs(self.db, scope=hundred.SCOPE)

    def test_overfull_batch_abstains_without_truncation(self):
        card = dict(compiler.pairs(self.db, scope=hundred.SCOPE)[0][0]); card['collector_number']='099/100'
        card.update(display_allowed=False,match_eligible=True)
        core.import_cards(self.db, [card])
        self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',
            (core.card_id('ja', card['set_code'], '099/100', card['variant']), 'Trainer', None, 'fixture', 'fixture'))
        with self.assertRaisesRegex(ValueError, 'bounded Japanese'):
            compiler.pairs(self.db, scope=hundred.SCOPE)

    def test_missing_fixed_set_does_not_substitute_another_release(self):
        self.db.execute('DELETE FROM card_classification WHERE card_id LIKE ?', ('ja:'+hundred.SCOPE.sets[0]+':%',))
        with self.assertRaisesRegex(ValueError, 'explicit Japanese'):
            compiler.pairs(self.db, scope=hundred.SCOPE)

    def test_invalid_or_unvalidated_scope_cannot_widen_import(self):
        for count in (0, 101, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                compiler.RetrievalScope('fixture', hundred.SCOPE.sets, count)
        for sets in (('A','A','B'), ('A','B','../C'), tuple('S'+str(i) for i in range(20))):
            with self.subTest(sets=sets), self.assertRaises(ValueError):
                compiler.RetrievalScope('fixture', sets, 100)
        with self.assertRaisesRegex(ValueError, 'validated RetrievalScope'):
            compiler.pairs(self.db, scope={'japanese_records': 1000})

    def test_audit_profile_rejects_foreign_paths_and_unvalidated_scopes(self):
        for path in ('/outside.json', '../outside.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit.AuditProfile(path, 'after.json', 'catalog/locales.jsonl', 69, hundred.SCOPE)
        with self.assertRaises(ValueError):
            audit.AuditProfile('before.json','after.json','catalog/locales.jsonl',True,hundred.SCOPE)
        with self.assertRaises(ValueError):
            audit.profile_or_default({'prior_inputs': 0})

    def test_compiler_requires_pins_for_all_125_bindings_and_keeps_false_claims(self):
        old = {table: audit.records(self.db, table) for table in audit.tables(self.db)}
        rows, selection, _ = self.compile()
        self.assertEqual(selection['batch_scope']['japanese_records'], 100)
        self.assertEqual(len(selection['source_inventory']), 114)
        for row in rows:
            for flag in catalog_locale.FALSE_CLAIMS:
                self.assertFalse(row[flag])
            self.assertEqual(row['source']['region'], 'ZZ')
            self.assertIsNone(row['source']['retrieved_at'])
        for table, values in old.items():
            self.assertEqual(audit.records(self.db, table), values)

    def test_hundred_audit_rejects_duplicate_or_unapproved_language_set_scope(self):
        rows, _, _ = self.compile(); audit.bounded(rows, scope=hundred.SCOPE)
        for field, value in (('set_code','OUTSIDE'), ('language','fr')):
            changed = copy.deepcopy(rows); changed[0]['identity'][field]=value
            if field=='set_code':
                # Replace the entire first set so it cannot hide as a sibling.
                old_code=rows[0]['identity']['set_code']
                for row in changed:
                    if row['identity']['set_code']==old_code:row['identity']['set_code']=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.bounded(changed, scope=hundred.SCOPE)
        with self.assertRaises(ValueError):
            audit.bounded(rows[:-1], scope=hundred.SCOPE)
        changed=copy.deepcopy(rows);changed[1]=copy.deepcopy(changed[0])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            audit.bounded(changed,scope=hundred.SCOPE)

    def test_missing_english_comparisons_cannot_be_filled_with_duplicate_ids(self):
        self.db.execute('''DELETE FROM card_classification WHERE card_id IN
            (SELECT card_id FROM card WHERE language='en' ORDER BY card_id LIMIT 26)''')
        with self.assertRaisesRegex(ValueError,'25 distinct English'):
            compiler.pairs(self.db,scope=hundred.SCOPE)

    def test_profile_append_and_reimport_preserve_every_existing_column(self):
        rows, _, _ = self.compile(); artifact = self.root/Path(hundred_audit.PROFILE.locales).parent
        artifact.mkdir(parents=True); (artifact/'locales.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        before_path=self.frozen('before.sqlite3'); after_path=self.root/'after.sqlite3'
        self.assertEqual(hundred_audit.append(before_path, after_path, self.root), dict(inserted=125,unchanged=0,quarantined=0))
        with closing(core.connect(before_path,readonly=True)) as before, closing(core.connect(after_path)) as after:
            self.assertTrue(all(audit.preserved(before,after,125).values()))
            self.assertTrue(audit.installed(after,rows))
            self.assertEqual(catalog_locale.import_evidence(after,rows), dict(inserted=0,unchanged=125,quarantined=0))
            self.assertTrue(all(audit.preserved(before,after,125).values()))
        with self.assertRaises(FileExistsError):
            hundred_audit.append(before_path,after_path,self.root)

    def test_locale_input_drift_prevents_snapshot_publication(self):
        rows, _, _ = self.compile(); artifact=self.root/Path(hundred_audit.PROFILE.locales).parent
        artifact.mkdir(parents=True); path=artifact/'locales.jsonl'
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows)); before=self.frozen('before.sqlite3'); after=self.root/'after.sqlite3'
        original=catalog_locale.import_evidence
        def mutate(*args):
            result=original(*args);path.write_text(path.read_text()+'\n');return result
        with patch.object(catalog_locale,'import_evidence',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'locale input changed'):
                hundred_audit.append(before,after,self.root)
        self.assertFalse(after.exists())

    def test_wrapper_produces_125_records_exclusively_without_touching_input_db(self):
        before=self.frozen('before.sqlite3');old=before.read_bytes();output=self.root/'artifact'
        result=hundred.build(before,self.repo,self.root,output,self.TIME)
        self.assertEqual((result['japanese'],result['english']),(100,25))
        self.assertEqual(len((output/'locales.jsonl').read_text().splitlines()),125)
        self.assertEqual(before.read_bytes(),old)
        with self.assertRaises(FileExistsError):
            hundred.build(before,self.repo,self.root,output,self.TIME)


if __name__ == '__main__':
    unittest.main()
