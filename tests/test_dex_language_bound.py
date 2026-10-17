"""Language pruning is a proven necessary condition, never an ID convention."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pokemon_index import core, collector_runtime as runtime
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class DexLanguageBoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'catalog.sqlite3'
        self.suite=json.loads(SUITE.read_text());create_fixture(self.path,self.suite)
        row=copy.deepcopy(next(r for r in self.suite['cards'] if r['dex_id']==25))
        row.update(language='en',collector_number='099/100',variant='normal')
        with closing(core.connect(self.path)) as db:
            core.import_cards(db,[{k:v for k,v in row.items() if k not in {'dex_id','illustrator'}}])
            self.extra=core.card_id(row['language'],row['set_code'],row['collector_number'],row['variant'])
            db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                       (self.extra,'dex_id','25',row['provenance'],row['rights_reference']))
            db.commit()

    def model(self):
        with closing(core.connect(self.path,readonly=True)) as db:return runtime.CatalogReadModel(db)

    def test_both_memberships_keep_native_language_sql_results_and_original_default(self):
        model=self.model();self.assertTrue(model._dex_language_prefix_exact)
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db,strict_readonly=True):
            for helper,operands,predicate in [
                    (runtime.snapshot_cast_dex_card_ids,[25],"CAST(f.value AS INTEGER) IN (25)"),
                    (runtime.snapshot_text_dex_card_ids,['25'],"f.value IN ('25')")]:
                all_ids=helper(db,operands)
                self.assertTrue(any(cid.startswith('ja:') for cid in all_ids))
                self.assertIn(self.extra,all_ids)
                for languages in [('ja',),('en',),('ja','en'),('ko',),('JA',)]:
                    sql="SELECT DISTINCT c.card_id FROM card c JOIN collector_snapshot.facets f ON f.card_id=c.card_id WHERE f.facet_type='dex_id' AND "+predicate+' AND c.language IN ('+','.join('?' for _ in languages)+')'
                    expected=frozenset(r[0] for r in db.execute(sql,languages))
                    self.assertEqual(helper(db,operands,languages=languages),expected)
                self.assertEqual(helper(db,operands),all_ids)

    def test_mismatched_custom_id_disables_pruning_without_dropping_native_record(self):
        wrong='ja:WRONG:099/100:normal'
        with closing(core.connect(self.path)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('UPDATE card SET card_id=? WHERE card_id=?',(wrong,self.extra))
            db.execute('UPDATE card_facet SET card_id=? WHERE card_id=?',(wrong,self.extra));db.commit()
        model=self.model();self.assertFalse(model._dex_language_prefix_exact)
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db,strict_readonly=True):
            for helper,operands in [(runtime.snapshot_cast_dex_card_ids,[25]),
                                    (runtime.snapshot_text_dex_card_ids,['25'])]:
                self.assertEqual(helper(db,operands,languages=('en',)),helper(db,operands))
                self.assertIn(wrong,helper(db,operands,languages=('en',)))
                self.assertEqual(db.execute('SELECT language FROM card WHERE card_id=?',(wrong,)).fetchone()[0],'en')

    def test_prefix_proof_rejects_type_nul_empty_colon_and_case_counterexamples(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE card(card_id,language)')
            for cid,language in [('opaque','ja'),('en:x','ja'),('JA:x','ja'),
                    ('ja\x00:x','ja'),('ja:x\x00','ja'),('ja:x','ja\x00'),
                    ('ja:sub:x','ja:sub'),(':x',''),(b'ja:x','ja'),('ja:x',b'ja'),
                    (None,'ja'),('ja:x',None),(1,'1')]:
                with self.subTest(cid=cid,language=language):
                    db.execute('DELETE FROM card');db.execute('INSERT INTO card VALUES (?,?)',(cid,language))
                    self.assertFalse(runtime.CatalogReadModel._build_dex_language_prefix_proof(db))
            for cid,language in [('ja:x','ja'),('en:x','en'),('JA:x','JA'),('zh-Hant:x','zh-Hant')]:
                db.execute('DELETE FROM card');db.execute('INSERT INTO card VALUES (?,?)',(cid,language))
                self.assertTrue(runtime.CatalogReadModel._build_dex_language_prefix_proof(db))

    def test_bad_language_arguments_and_preexisting_union_bound_keep_native_fallback(self):
        model=self.model()
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db,strict_readonly=True):
            for helper,operands in [(runtime.snapshot_cast_dex_card_ids,[25]),
                                    (runtime.snapshot_text_dex_card_ids,['25'])]:
                for languages in [[],['ja'],(),('ja',1),('ja\x00',),('ja:sub',),('',),('a'*65,),('ja',)*33]:
                    with self.subTest(languages=languages):self.assertIsNone(helper(db,operands,languages=languages))
                model.MAX_DEX_QUERY_IDS=1
                self.assertIsNone(helper(db,operands,languages=('ko',)))
                del model.MAX_DEX_QUERY_IDS

    def test_noncanonical_declared_language_or_id_collation_cannot_build_model(self):
        for column in ['card_id TEXT PRIMARY KEY','language TEXT NOT NULL']:
            with self.subTest(column=column), closing(core.connect(self.path)) as db:
                db.execute('PRAGMA writable_schema=ON')
                original=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='card'").fetchone()[0]
                altered=original.replace(column,column.replace(' TEXT',' TEXT COLLATE NOCASE'))
                self.assertNotEqual(altered,original)
                db.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name='card'",(altered,));db.commit()
                try:
                    with self.assertRaises(runtime.CatalogReadModelUnsupported):self.model()
                finally:
                    db.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name='card'",(original,));db.commit()

    def test_artifact_state_requires_boolean_proof_and_current_version(self):
        model=self.model();state=artifact.model_state(model)
        self.assertTrue(state['dex_language_prefix_exact'])
        restored=artifact._restore(state,model._image)
        self.assertIs(restored._dex_language_prefix_exact,True)
        for value in [0,1,None,'true',[],{}]:
            changed=copy.deepcopy(state);changed['dex_language_prefix_exact']=value
            with self.subTest(value=value),self.assertRaises(artifact.ArtifactInvalid):artifact._restore(changed,model._image)
        missing=copy.deepcopy(state);del missing['dex_language_prefix_exact']
        with self.assertRaises(artifact.ArtifactInvalid):artifact._restore(missing,model._image)
        old=copy.deepcopy(state);old['schema']='pokemon.catalog-read-model-state.v4'
        with self.assertRaises(artifact.ArtifactInvalid):artifact._restore(old,model._image)


if __name__=='__main__':unittest.main()
