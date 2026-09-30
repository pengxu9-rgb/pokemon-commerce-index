import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from pokemon_index import core, ingestion_worker as worker

NOW='2026-10-01T00:00:00Z'
SOURCE='synthetic_worker_fixture'


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite3'
        self.db=core.connect(self.path);core.init_db(self.db);worker.initialize(self.db)
        self.policy(True)
        core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',
            variant='normal',name='Synthetic',provenance='synthetic',rights_reference='fixture',
            match_eligible=True)])

    def tearDown(self):self.db.close();self.tmp.cleanup()

    def policy(self,allow):
        core.register_source(self.db,dict(source=SOURCE,rights_reference='synthetic',
            ingest_allowed=allow,retention_days=1,listing_ttl_hours=1))

    def row(self,**changes):
        return dict(dict(source=SOURCE,native_id='one',title='Synthetic FIX 001/100',
            url='https://example.invalid/one',observed_at=NOW,status='on_sale',price_minor=100,
            currency='JPY',language='ja',evidence_ref='synthetic:v1'),**changes)

    def queue(self,job='one',now=NOW):
        worker.enqueue(self.db,job,SOURCE,{'query':'FIX 001/100'},now=now)

    def test_restart_after_crash_recovers_lease_and_charges_each_call(self):
        self.queue()
        def crash(_):raise RuntimeError('simulated process crash')
        with self.assertRaises(RuntimeError):
            worker.run_next(self.db,crash,source=SOURCE,now=NOW,lease_seconds=60)
        self.db.close();self.db=core.connect(self.path)
        idle=worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now='2026-10-01T00:00:59Z')
        self.assertEqual(idle['status'],'idle')
        done=worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now='2026-10-01T00:01:00Z')
        self.assertEqual(done['status'],'done');self.assertEqual(done['attempt'],2)
        self.assertEqual(self.db.execute('SELECT used FROM feed_budget').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM observation').fetchone()[0],1)

    def test_transient_backoff_quota_and_attempt_limit_are_durable(self):
        self.queue()
        def transient(_):raise worker.RetryableFeedError()
        first=worker.run_next(self.db,transient,source=SOURCE,now=NOW,calls_per_day=1,max_attempts=2)
        self.assertEqual(first['status'],'retry')
        self.assertEqual(worker.run_next(self.db,transient,source=SOURCE,now='2026-10-01T00:01:00Z',calls_per_day=1)['status'],'quota_blocked')
        final=worker.run_next(self.db,transient,source=SOURCE,now='2026-10-02T00:00:00Z',calls_per_day=1,max_attempts=2)
        self.assertEqual(final['status'],'failed')
        self.assertEqual(worker.run_next(self.db,transient,source=SOURCE,now='2026-10-03T00:00:00Z')['status'],'idle')

    def test_atomic_conflicts_preserve_history_and_listing(self):
        self.queue();worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now=NOW)
        self.queue('replay');result=worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now=NOW)
        self.assertEqual(result['duplicates'],1)
        self.queue('conflict')
        result=worker.run_next(self.db,lambda _:[self.row(native_id='two'),self.row(price_minor=999)],source=SOURCE,now=NOW)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM observation').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT current_price_minor FROM listing').fetchone()[0],100)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM ingest_receipt').fetchone()[0],1)

    def test_call_reservation_visible_to_second_process_before_fetch(self):
        self.queue('first');self.queue('second')
        seen=[]
        def callback(_):
            with closing(core.connect(self.path)) as other:
                seen.append(worker.run_next(other,lambda _:[self.row()],source=SOURCE,now=NOW,calls_per_day=1)['status'])
            return [self.row()]
        self.assertEqual(worker.run_next(self.db,callback,source=SOURCE,now=NOW,calls_per_day=1)['status'],'done')
        self.assertEqual(seen,['quota_blocked'])

    def test_retention_deletes_payload_journal_and_prevents_resurrection(self):
        self.queue();worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now=NOW)
        removed=worker.purge(self.db,now='2026-10-03T00:00:00Z')
        self.assertEqual(removed['feed_job'],1);self.assertEqual(removed['ingest_receipt'],1)
        self.queue('old',now='2026-10-03T00:00:00Z')
        result=worker.run_next(self.db,lambda _:[self.row()],source=SOURCE,now='2026-10-03T00:00:00Z')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM observation').fetchone()[0],0)

    def test_revoked_permission_and_unknown_request_fields_prevent_call(self):
        self.queue();self.policy(False);called=[]
        with self.assertRaises(ValueError):
            worker.run_next(self.db,lambda _:called.append(True),source=SOURCE,now=NOW)
        self.assertEqual(called,[])
        self.policy(True)
        with self.assertRaises(ValueError):
            worker.enqueue(self.db,'secret',SOURCE,{'access_token':'never-store'},now=NOW)
        with self.assertRaisesRegex(ValueError,'different request'):
            worker.enqueue(self.db,'one',SOURCE,{'query':'another'},now=NOW)

    def test_source_batch_and_future_time_are_checked_before_commit(self):
        for number,rows in enumerate([[self.row(source='another')],
              [self.row(observed_at='2026-10-02T00:00:00Z')],
              [self.row(native_id='one'),self.row(native_id='two')]]):
            self.queue(str(number))
            result=worker.run_next(self.db,lambda _:rows,source=SOURCE,now=NOW,max_batch=1)
            self.assertEqual(result['status'],'failed')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM observation').fetchone()[0],0)


if __name__=='__main__':unittest.main()
