"""Same-version clone replacement, sticky failure and typed HTTP regressions."""
from contextlib import closing,contextmanager
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from pokemon_index import core,collector_runtime as runtime,collector_journey
from pokemon_index import catalog_read_model_artifact as artifact
from pokemon_index.cli import create_server
from scripts.rehearse_collector_recommendations import create_fixture,SUITE


class SnapshotCloneGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.path=self.base/'catalog.sqlite3'
        create_fixture(self.path,json.loads(SUITE.read_text()))
        self.manifest=self.base/'manifest.json';self.manifest.write_text('{"synthetic_test_only":true}')
        self.directory=self.base/'artifact'
        with closing(core.connect(self.path,readonly=True)) as db:
            receipt=artifact.write(db,self.manifest,self.directory)
        self.pin=receipt['seal_sha256']
        with closing(core.connect(self.path,readonly=True)) as db:
            native=runtime.CatalogReadModel(db)
        with closing(core.connect(self.path,readonly=True)) as db:
            loaded,_,_=artifact.load(db,self.directory,self.manifest,expected_seal_sha256=self.pin)
        self.models={'native':native,'loaded':loaded}
        self.replacement=self.base/'same-version-clone.sqlite3'
        self.replacement.write_bytes(native._image)
        with closing(sqlite3.connect(self.replacement)) as db:
            self.version=db.execute('PRAGMA schema_version').fetchone()[0]
            db.execute("UPDATE facets SET value='unqualified replacement fact' WHERE facet_type='illustrator'");db.commit()
            self.assertEqual(db.execute('PRAGMA schema_version').fetchone()[0],self.version)
        self.changed_image=self.replacement.read_bytes()
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def facets(self,db):
        return tuple(tuple(row) for row in db.execute('SELECT * FROM collector_snapshot.facets ORDER BY card_id,facet_type,value'))

    def mutations(self):
        return {
            'detach_attach':lambda db: (db.execute('DETACH DATABASE collector_snapshot'),
                db.execute('ATTACH DATABASE ? AS collector_snapshot',(str(self.replacement),))),
            'attach_other_alias':lambda db:db.execute("ATTACH DATABASE ':memory:' AS untracked_alias"),
            'bound_deserialize_clone':lambda db:db.deserialize(self.changed_image,name='collector_snapshot'),
            'base_deserialize_clone':lambda db:sqlite3.Connection.deserialize(db,self.changed_image,name='collector_snapshot'),
            'bound_deserialize_main':lambda db:db.deserialize(self.changed_image),
            'cursor_detach':lambda db:db.cursor().execute('DETACH DATABASE collector_snapshot'),
            'preexisting_cursor_detach':lambda db:db._test_cursor.execute('DETACH DATABASE collector_snapshot'),
            'executemany_detach':lambda db:db.executemany('DETACH DATABASE collector_snapshot',[()]),
            'cursor_executemany_detach':lambda db:db.cursor().executemany('DETACH DATABASE collector_snapshot',[()]),
            'executescript_restore':lambda db:db.executescript("DETACH DATABASE collector_snapshot; ATTACH DATABASE ':memory:' AS collector_snapshot;"),
            'cursor_executescript':lambda db:db.cursor().executescript('DETACH DATABASE collector_snapshot;'),
            'clear_authorizer':lambda db:db.set_authorizer(None),
            'replace_authorizer':lambda db:db.set_authorizer(lambda *arguments:sqlite3.SQLITE_OK),
        }

    def test_all_replacement_driver_and_cursor_paths_reject_and_preserve_clone(self):
        for label,model in self.models.items():
            for name,mutate in self.mutations().items():
                with self.subTest(model=label,mutation=name),closing(core.connect(self.path,readonly=True)) as db:
                    db._test_cursor=db.cursor()
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            self.assertEqual(db.execute('PRAGMA collector_snapshot.schema_version').fetchone()[0],self.version)
                            before=self.facets(db);changes=db.total_changes
                            try:mutate(db)
                            except (runtime.CatalogSnapshotChanged,sqlite3.DatabaseError):pass
                            else:self.fail('namespace replacement was accepted')
                            self.assertEqual(db.total_changes,changes)
                            self.assertEqual(self.facets(db),before)
                            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.facet_lookup_relation(db)
                    self.assertIsNone(db._catalog_clone_guard)

    def test_caught_attempt_and_restore_before_exit_never_publishes(self):
        for label,model in self.models.items():
            for mutation in ('deserialize','authorizer','detach'):
                with self.subTest(model=label,mutation=mutation),closing(core.connect(self.path,readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            before=self.facets(db)
                            try:
                                if mutation=='deserialize':db.deserialize(self.changed_image,name='collector_snapshot')
                                elif mutation=='authorizer':db.set_authorizer(None)
                                else:db.execute('DETACH DATABASE collector_snapshot')
                            except (runtime.CatalogSnapshotChanged,sqlite3.DatabaseError):pass
                            # Even restoration to the authorized bytes/callback
                            # remains a forbidden operation in this poisoned scope.
                            for restore in (lambda:db.deserialize(model._image,name='collector_snapshot'),
                                    lambda:db.set_authorizer(None)):
                                with self.assertRaises(runtime.CatalogSnapshotChanged):restore()
                            self.assertEqual(self.facets(db),before)
                    self.assertIsNone(runtime._snapshot_scope.get())

    def test_clone_writes_ddl_and_version_restore_cannot_change_facts(self):
        for label,model in self.models.items():
            for statement in ("UPDATE collector_snapshot.facets SET value='changed'",
                'DROP INDEX collector_snapshot.facet_lookup',
                'CREATE VIEW collector_snapshot.unreviewed AS SELECT * FROM facets',
                'PRAGMA collector_snapshot.schema_version=3'):
                with self.subTest(model=label,statement=statement),closing(core.connect(self.path,readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            db.execute('PRAGMA query_only=OFF')
                            db.execute(statement)
                    self.assertIsNone(db._catalog_clone_guard)

    def test_ordinary_reads_native_equivalence_and_fresh_scope_recover(self):
        for label,model in self.models.items():
            for fail in (False,True):
                with closing(core.connect(self.path,readonly=True)) as db:
                    try:
                        with model.request(db):
                            expected=self.facets(db)
                            self.assertIsNotNone(runtime.snapshot_character_names(db,False))
                            self.assertEqual(db.cursor().execute('SELECT count(*) FROM collector_snapshot.facets').fetchone()[0],len(expected))
                            if fail:db.deserialize(self.changed_image,name='collector_snapshot')
                    except runtime.CatalogSnapshotChanged:
                        self.assertTrue(fail)
                with closing(core.connect(self.path,readonly=True)) as fresh,model.request(fresh):
                    self.assertEqual(self.facets(fresh),expected)
                    self.assertIsNotNone(runtime.snapshot_character_names(fresh,False))

    def test_prior_authorizer_restored_and_offline_mutability_preserved(self):
        for label,model in self.models.items():
            for poison in (False,True):
                seen=[]
                def prior(*arguments):seen.append(arguments);return sqlite3.SQLITE_OK
                with closing(core.connect(self.path,readonly=True)) as db:
                    db.set_authorizer(prior)
                    try:
                        with model.request(db):
                            db.execute('SELECT count(*) FROM collector_snapshot.facets').fetchone()
                            if poison:db.set_authorizer(None)
                    except runtime.CatalogSnapshotChanged:self.assertTrue(poison)
                    self.assertIs(db._catalog_authorizer,prior)
                    old=len(seen)
                    db.execute("ATTACH ':memory:' AS offline")
                    self.assertGreater(len(seen),old)
                    db.execute('PRAGMA query_only=OFF');db.execute('CREATE TABLE offline.native_operator(v)')
                    db.execute("INSERT INTO offline.native_operator VALUES ('outside admitted scope')");db.commit()
                    db.execute('DETACH DATABASE offline')
                    db.set_authorizer(None)
                    db.deserialize(self.changed_image,name='collector_snapshot')
                    self.assertIn('unqualified replacement fact',{row[0] for row in db.execute("SELECT value FROM collector_snapshot.facets WHERE facet_type='illustrator'")})

    def test_guard_does_not_replace_sql_progress_deadline(self):
        for model in self.models.values():
            with closing(core.connect(self.path,readonly=True)) as db:
                with self.assertRaises(runtime.CatalogDeadline),runtime.sqlite_deadline(db,runtime.time.monotonic()+.02):
                    with model.request(db):
                        db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
                self.assertIsNone(db._catalog_clone_guard)
        self.assertIsNone(runtime._work_deadline.get());self.assertEqual(runtime._sql_scopes.get(),())

    @contextmanager
    def server(self, packaged):
        # Bind only synthetic package paths in the test. The actual HTTP
        # entrypoint retains its literal image paths and no caller path input.
        package=self.directory if packaged else self.base/'absent-package'
        with patch.object(artifact,'_PACKAGED_DIR',package),patch.object(artifact,'_PACKAGED_MANIFEST',self.manifest):
            with create_server(str(self.path),'127.0.0.1',0,True,require_catalog_read_model=packaged) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:yield server
                finally:server.shutdown();thread.join(timeout=5)

    def call(self,server):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        try:
            client.request('POST','/collector-journey',json.dumps({'turns':[{'type':'ask','question':'Japanese Pikachu cards'}]}),{'Content-Type':'application/json'})
            response=client.getresponse();return response.status,dict(response.getheaders()),json.loads(response.read())
        finally:client.close()

    def test_prior_authorizer_deny_policy_is_chained_and_preserved(self):
        def prior(action,first,second,database,source):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_FUNCTION and second=='abs' else sqlite3.SQLITE_OK
        for label,model in self.models.items():
            with self.subTest(model=label),closing(core.connect(self.path,readonly=True)) as db:
                db.set_authorizer(prior)
                with model.request(db):
                    with self.assertRaises(sqlite3.DatabaseError):db.execute('SELECT abs(-1)')
                    self.assertFalse(db._catalog_clone_guard['invalid'])
                    self.assertEqual(db.execute('SELECT count(*) FROM collector_snapshot.facets').fetchone()[0],len(self.facets(db)))
                self.assertIs(db._catalog_authorizer,prior)
                with self.assertRaises(sqlite3.DatabaseError):db.execute('SELECT abs(-1)')
                db.set_authorizer(None)
                self.assertEqual(db.execute('SELECT abs(-1)').fetchone()[0],1)

    def test_http_replacement_attempt_is_typed_503_and_next_admission_recovers(self):
        payload={'turns':[{'type':'ask','question':'Japanese Pikachu cards'}]}
        with closing(core.connect(self.path,readonly=True)) as db:
            native_expected=collector_journey.replay(db,payload)
        for packaged in (False,True):
            with self.server(packaged) as server:
                for mutation in ('detach_attach','bound_deserialize_clone','base_deserialize_clone','clear_authorizer','cursor_executescript'):
                    def poisoned(db,*arguments,**keywords):
                        try:self.mutations()[mutation](db)
                        except (runtime.CatalogSnapshotChanged,sqlite3.DatabaseError):pass
                        return {'unqualified_result':'must not publish'}
                    with self.subTest(packaged=packaged,mutation=mutation),patch.object(collector_journey,'replay',side_effect=poisoned):
                        status,headers,body=self.call(server)
                        self.assertEqual((status,body),(503,{'error':'catalog_snapshot_changed'}))
                        self.assertEqual(headers['X-Collector-Error'],'catalog_snapshot_changed')
                    status,headers,body=self.call(server)
                    self.assertEqual((status,body),(200,native_expected))
                    self.assertNotIn('X-Collector-Error',headers)

if __name__=='__main__':unittest.main()
