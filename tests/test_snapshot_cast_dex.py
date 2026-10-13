"""Native SQLite CAST/affinity equivalence and unsafe-scope abstention."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import collector_discovery as discovery,collector_runtime as runtime,core
from scripts.rehearse_collector_recommendations import SUITE,create_fixture


class SnapshotCastDexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'catalog.sqlite3'
        create_fixture(self.path,json.loads(SUITE.read_text()))
        with closing(core.connect(self.path)) as db:
            # Literal source values include malformed numbers, zero padding,
            # BLOB digits and conflicting multiple Dex facets. Names are not
            # inferred from those values and these are synthetic only.
            values=(0,25,'025','25e0','25.9','25foo','foo','',25.9,b'25',-1,
                    '9223372036854775808','-9223372036854775809')
            for i,value in enumerate(values):
                for language in ('en','ja'):
                    cid=core.card_id(language,'TYPED',f'{i+1:03}/100','normal')
                    core.import_cards(db,[dict(language=language,set_code='TYPED',collector_number=f'{i+1:03}/100',
                        variant='normal',name='Synthetic Species',provenance='synthetic',rights_reference='synthetic',match_eligible=True)])
                    db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,'dex_id',value,'synthetic','synthetic'))
            # Same source card can declare multiple contradictory values. Native
            # CAST membership retains both; it does not choose a species/printing.
            self.conflicting='ja:TYPED:003/100:normal'
            db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(self.conflicting,'dex_id','26','synthetic','synthetic'))
            db.commit()
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with closing(core.connect(self.path,readonly=True)) as db:self.model=runtime.CatalogReadModel(db)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def native_rows(self,db,operands,languages=('ja','en'),relation='main.discovery_card_facet'):
        return discovery._rows(db,'c.language IN ('+','.join('?' for _ in languages)+
            ') AND EXISTS(SELECT 1 FROM '+relation+" f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ("+
            ','.join('?' for _ in operands)+'))',(*languages,*operands))

    def narrowed_rows(self,db,ids,languages=('ja','en')):
        return discovery._rows(db,'c.language IN ('+','.join('?' for _ in languages)+
            ') AND c.card_id IN ('+','.join('?' for _ in ids)+')',(*languages,*ids)) if ids else []

    def test_canonical_typed_source_values_keep_native_order_and_conflicting_membership(self):
        for operands in ((0,),(25,),(26,),(-1,),(2**63-1,),(-2**63,),(25,26),(0,25,0),(9999,)):
            for languages in (('ja',),('en',),('ja','en')):
                with self.subTest(operands=operands,languages=languages):
                    with closing(core.connect(self.path,readonly=True)) as db:
                        expected=[dict(row) for row in self.native_rows(db,operands,languages)]
                    with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
                        narrowed=runtime.snapshot_cast_dex_card_ids(db,operands)
                        self.assertIsInstance(narrowed,frozenset)
                        self.assertEqual([dict(row) for row in self.narrowed_rows(db,tuple(narrowed),languages)],expected)
        self.assertIn(self.conflicting,self.model._cast_dex_card_ids[25])
        self.assertIn(self.conflicting,self.model._cast_dex_card_ids[26])
        with self.assertRaises(TypeError):self.model._cast_dex_card_ids[25]=frozenset()

    def test_raw_sqlite_relation_probe_covers_null_int_real_blob_and_card_id_affinity(self):
        # Canonical seed Dex columns have TEXT affinity and reject NULL. This
        # extra typed relation probe tests the materializer's exact SQLite JOIN
        # semantics without weakening the production canonical-schema gate.
        with closing(core.connect(':memory:')) as db:
            core.init_db(db);db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
            db.execute('CREATE TABLE collector_snapshot.facets(card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)')
            cards=('25','025','25e0','UPPER','upper',b'25',b'025','null-value','float-value','missing')
            for i,cid in enumerate(cards):
                db.execute('INSERT INTO card VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (cid,'ja','RAW',str(i),'normal','Synthetic','', 'synthetic','synthetic',0,1,'{}'))
            for cid,value in [(25,25),('25',None),('025','025'),('25e0','25e0'),
                              (b'25',b'25'),(b'025',b'025'),('UPPER','25foo'),('upper','foo'),
                              ('null-value',None),('float-value',25.9),('float-value','26'),
                              ('25','25.9'),('025',-1),('UPPER','9223372036854775808'),
                              ('upper','-9223372036854775809'),('upper','')]:
                db.execute('INSERT INTO collector_snapshot.facets VALUES (?,?,?,?,?)',(cid,'dex_id',value,'synthetic','synthetic'))
            db.commit()
            index=runtime.CatalogReadModel._build_cast_dex_card_ids(db)
            for operands in ((0,),(25,),(26,),(-1,),(2**63-1,),(-2**63,),(25,26),(9999,)):
                expected=[tuple(row) for row in db.execute("SELECT c.card_id,typeof(c.card_id) FROM main.card c WHERE EXISTS(SELECT 1 FROM collector_snapshot.facets f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ("+
                    ','.join('?' for _ in operands)+')) ORDER BY c.card_id',operands)]
                ids=frozenset(cid for dex in operands for cid in index.get(dex,()))
                actual=[tuple(row) for row in db.execute('SELECT c.card_id,typeof(c.card_id) FROM main.card c WHERE c.card_id IN ('+
                    ','.join('?' for _ in ids)+') ORDER BY c.card_id',tuple(ids))] if ids else []
                self.assertEqual(actual,expected,operands)
            self.assertNotIn('null-value',index.get(0,()))
            self.assertNotIn('missing',index.get(0,()))
            self.assertIn('25',index[25]);self.assertIn(b'25',index[25])
            self.assertNotIn('025',index[0])

    def test_noninteger_or_large_operands_and_large_candidate_unions_retain_native_sql(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            for operands in ((),(None,),('25',),(25.0,),(True,),(2**63,),tuple(range(33))):
                self.assertIsNone(runtime.snapshot_cast_dex_card_ids(db,operands))
            with patch.object(runtime.CatalogReadModel,'MAX_DEX_QUERY_IDS',1):
                self.assertIsNone(runtime.snapshot_cast_dex_card_ids(db,(25,)))
                native=discovery.execute(db,'Japanese Pikachu cards',limit=100)
        with closing(core.connect(self.path,readonly=True)) as db:
            self.assertEqual(discovery.execute(db,'Japanese Pikachu cards',limit=100),native)
            self.assertIsNone(runtime.snapshot_cast_dex_card_ids(db,(25,)))

    def test_constructor_bound_failures_do_not_publish_partial_indexes(self):
        for field,limit in [('MAX_DEX_BINDINGS',1),('MAX_DEX_ID_BYTES',1),('MAX_DEX_KEYS',1)]:
            with self.subTest(field=field),closing(core.connect(self.path,readonly=True)) as db:
                with patch.object(runtime.CatalogReadModel,field,limit):
                    with self.assertRaisesRegex(ValueError,'CAST dex'):runtime.CatalogReadModel(db)
                self.assertIsNone(runtime._snapshot_scope.get())

    def test_text_in_and_artist_character_scope_do_not_use_cast_index(self):
        queries=['Japanese Pikachu cards by Alpha','Pikachu only by Alpha',
                 'Japanese Mew cards by Beta','English Pikachu cards by Alpha']
        with closing(core.connect(self.path,readonly=True)) as db:
            expected=[discovery.execute(db,q,limit=100) for q in queries]
            text_native=[tuple(r) for r in db.execute("SELECT card_id,value,typeof(value) FROM discovery_card_facet WHERE facet_type='dex_id' AND value IN ('25') ORDER BY card_id,value")]
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            with patch.object(runtime,'snapshot_cast_dex_card_ids',side_effect=AssertionError('text-IN changed')):
                self.assertEqual([discovery.execute(db,q,limit=100) for q in queries],expected)
            self.assertEqual([tuple(r) for r in db.execute("SELECT card_id,value,typeof(value) FROM "+runtime.facet_lookup_relation(db)+" WHERE facet_type='dex_id' AND value IN ('25') ORDER BY card_id,value")],text_native)

    def test_active_mutable_scope_rejects_every_static_reader_and_recovers_natively(self):
        readers=[lambda db:runtime.snapshot_cast_dex_card_ids(db,(25,)),
                 lambda db:runtime.facet_lookup_relation(db),lambda db:runtime.snapshot_affiliations(db),
                 lambda db:runtime.vocabulary(db,'artists',runtime.VOCABULARY_SQL['artists'])]
        for mutation in ('query_only','transaction','temp_table','temp_view','rollback'):
            for reader in readers:
                with self.subTest(mutation=mutation,reader=reader),closing(core.connect(self.path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
                    db.execute('PRAGMA query_only=OFF')
                    if mutation in ('transaction','rollback'):
                        db.execute("UPDATE card_facet SET provenance='changed'")
                        if mutation=='rollback':db.rollback();db.execute('PRAGMA query_only=ON')
                    elif mutation.startswith('temp_'):
                        db.execute('CREATE TEMP '+('TABLE synthetic(x)' if mutation=='temp_table' else 'VIEW synthetic AS SELECT 1 x'))
                        db.commit();db.execute('PRAGMA query_only=ON')
                    with self.assertRaises(runtime.CatalogSnapshotChanged):reader(db)
                    db.rollback()
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertIsNotNone(runtime.snapshot_cast_dex_card_ids(db,(25,)))
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE card_facet SET value='26' WHERE value='25'")
            self.assertIsNone(runtime.snapshot_cast_dex_card_ids(db,(25,)))
            self.assertEqual(runtime.facet_lookup_relation(db),'discovery_card_facet');db.rollback()

    def test_exact_coordinates_keep_native_parameter_equality_and_name_or_logic(self):
        queries=['Pikachu FIX 001/100','Japanese Pikachu FIX 001/100',
                 'Mew FIX 001/100','Pikachu family cards','ピカチュウ','Pikachu EX','Pikachu ex']
        with closing(core.connect(self.path,readonly=True)) as db:
            expected=[discovery.execute(db,q,limit=100) for q in queries]
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertEqual([discovery.execute(db,q,limit=100) for q in queries],expected)


if __name__=='__main__':unittest.main()
