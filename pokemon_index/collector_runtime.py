"""Request-local catalog vocabulary and bounded HTTP computation admission.

Only bounded, immutable catalog facts are shared between HTTP requests.
Sessions, queries, rankings, inventories and authority remain request-local.
"""
from __future__ import annotations

from collections import deque
from contextlib import closing, contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import sqlite3
from types import MappingProxyType
import threading
import time


_catalog_scope = ContextVar('collector_catalog_scope', default=None)
_work_deadline = ContextVar('collector_work_deadline', default=None)
_sql_scopes = ContextVar('collector_sql_scopes', default=())
_snapshot_scope = ContextVar('collector_snapshot_scope', default=None)
VOCABULARY_SQL = {
    'artists': "SELECT DISTINCT value FROM discovery_card_facet WHERE facet_type='illustrator'",
    'release_codes': 'SELECT DISTINCT set_code FROM card',
    'character_aliases': "SELECT DISTINCT name,dex_id,current_evidence FROM (SELECT c.name,CAST(MIN(f.value) AS INTEGER) AS dex_id,\n        MAX(CASE WHEN (f.provenance=c.provenance AND f.rights_reference=c.rights_reference)\n            OR EXISTS(SELECT 1 FROM active_card_metadata_evidence metadata\n                      WHERE metadata.card_id=c.card_id AND metadata.evidence_id=f.provenance)\n            THEN 1 ELSE 0 END) AS current_evidence\n        FROM card c JOIN discovery_card_facet f ON f.card_id=c.card_id AND f.facet_type='dex_id'\n        GROUP BY c.card_id HAVING COUNT(DISTINCT f.value)=1)",
}
_VOCABULARY_KEYS = frozenset(VOCABULARY_SQL)



def checkpoint():
    """Cooperative Python checkpoint, scoped to the current HTTP computation.

    Direct in-process callers keep their existing behavior. This does not
    preempt an arbitrary blocking extension or a thread between checkpoints.
    """
    expires = _work_deadline.get()
    if expires is not None and time.monotonic() >= expires:
        raise CatalogDeadline()


def catalog_request(function):
    """Reuse fixed vocabularies only within one call and its nested operations."""
    @wraps(function)
    def wrapped(db, *args, **kwargs):
        checkpoint()
        active = _catalog_scope.get()
        if active is not None and active['db'] is db:
            result = function(db, *args, **kwargs)
            checkpoint()
            return result
        token = _catalog_scope.set({'db': db, 'version': None, 'rows': {}, 'mentions': {}})
        try:
            result = function(db, *args, **kwargs)
            checkpoint()
            return result
        finally:
            _catalog_scope.reset(token)
    return wrapped


def _request_cache(db):
    active = _catalog_scope.get()
    if active is None or active['db'] is not db:
        return None
    # Transactions can roll back without reducing total_changes. Never retain
    # transaction-local results, including rollback-to-savepoint results.
    if db.in_transaction:
        active['rows'].clear();active['mentions'].clear();active['version']=None
        return None
    version=(db.total_changes,db.execute('PRAGMA data_version').fetchone()[0],
             db.execute('PRAGMA schema_version').fetchone()[0],
             db.execute('PRAGMA temp.schema_version').fetchone()[0])
    if active['version']!=version:
        active['rows'].clear();active['mentions'].clear();active['version']=version
    return active


def vocabulary(db, key, sql):
    """Fixed immutable vocabularies, snapshot-bound on the read-only HTTP path."""
    checkpoint()
    if key not in _VOCABULARY_KEYS:
        raise ValueError('unsupported catalog vocabulary')
    snapshot=_snapshot_scope.get()
    if snapshot is not None and snapshot['db'] is db and sql==VOCABULARY_SQL[key]:
        return snapshot['model']._vocabularies[key]
    active=_request_cache(db)
    if active is None:return tuple(db.execute(sql))
    cache_key=(key,sql)
    if cache_key not in active['rows']:
        rows=tuple(db.execute(sql))
        if len(rows)<=100000 and len(active['rows'])<len(_VOCABULARY_KEYS):
            active['rows'][cache_key]=rows
        return rows
    return active['rows'][cache_key]


def request_mentions(db, key, build):
    """Bounded immutable parser matches; never retain user text across requests."""
    checkpoint();active=_request_cache(db)
    if active is None:return build()
    if key not in active['mentions']:
        result=build();checkpoint()
        if len(active['mentions'])<64:active['mentions'][key]=result
        return result
    return active['mentions'][key]


def snapshot_affiliations(db):
    snapshot=_snapshot_scope.get()
    if snapshot is None or snapshot['db'] is not db:return None
    checkpoint()
    # A fresh object prevents recommendation/response mutation from poisoning
    # the shared source proofs or a later session.
    return json.loads(snapshot['model']._affiliations_json)


def facet_lookup_relation(db):
    """Audited string equality/IN or explicit CAST lookups only.

    This materialized relation is NOT an arbitrary-SQL replacement for SQLite's
    compound effective view. Generic consumers retain the original view and its
    branch-specific comparison affinities/collations.
    """
    snapshot=_snapshot_scope.get()
    return 'collector_snapshot.facets' if snapshot is not None and snapshot['db'] is db else 'discovery_card_facet'


class CatalogReadModelUnsupported(Exception):
    pass


class CatalogReadModel:
    """Immutable, bounded effective-facet image; a fresh clone per admitted call.

    Built only by the immutable HTTP server after calculating its catalog
    revision. Main remains mode=ro. No shared SQLite connection, user text,
    session, ranking, result, or new catalog assertion is retained.
    """
    MAX_IMAGE_BYTES=64*1024*1024
    COLUMNS=('card_id','facet_type','value','provenance','rights_reference')
    SCHEMA='collector_snapshot'

    def __init__(self,db):
        from pathlib import Path
        main=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
        if not main:raise ValueError('catalog read model requires a file snapshot')
        self._path=Path(main).resolve(strict=True)
        self._identity=snapshot_identity(self._path)
        # Keep affinities as well as storage values. The effective view has no
        # declared affinity except TEXT provenance; do not coerce numeric artist
        # names, card IDs, or dex strings during materialization.
        expected=[(name,'TEXT' if name=='provenance' else 'BLOB') for name in self.COLUMNS]
        actual=[(r[1],r[2] or 'BLOB') for r in db.execute('PRAGMA main.table_info(discovery_card_facet)')]
        if actual!=expected or not callable(getattr(db,'serialize',None)) or not callable(getattr(db,'deserialize',None)):
            raise CatalogReadModelUnsupported()
        if db.in_transaction:raise ValueError('read model needs a committed snapshot')
        # Affinity labels alone do not capture collations, intermediate views or
        # compound-view comparison rules. Only the package's exact schema can
        # use the audited lookup optimization; other catalogs retain native SQL.
        from . import core, variant_dimension_hold, catalog_locale_indexes
        query='SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name,tbl_name'
        with closing(core.connect(':memory:')) as reference:
            core.init_db(reference)
            expected_schema=tuple(tuple(row) for row in reference.execute(query))
            expected_encoding=reference.execute('PRAGMA main.encoding').fetchone()[0]
            variant_dimension_hold.install_guards(reference)
            held_schema=tuple(tuple(row) for row in reference.execute(query))
        actual_schema=tuple(tuple(row) for row in db.execute(query))
        try:
            base_schema=catalog_locale_indexes.without_optional_indexes(actual_schema)
        except ValueError:
            raise CatalogReadModelUnsupported() from None
        if (base_schema not in (expected_schema,held_schema) or
                db.execute('PRAGMA main.encoding').fetchone()[0]!=expected_encoding):
            raise CatalogReadModelUnsupported()
        # The base schema remains supported before hold ingestion. Once hold
        # rows exist, only the exact complete index/trigger group is accepted.
        # Other schema objects, altered guards and partial groups fail above.
        if (base_schema==expected_schema and db.execute(
                "SELECT 1 FROM main.catalog_identity_quarantine WHERE quarantine_id GLOB 'variant-dimension-hold:*' LIMIT 1").fetchone()):
            raise CatalogReadModelUnsupported()
        checkpoint()
        db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
        db.execute('PRAGMA collector_snapshot.page_size=4096')
        db.execute('PRAGMA collector_snapshot.max_page_count='+str(self.MAX_IMAGE_BYTES//4096))
        db.execute('CREATE TABLE collector_snapshot.facets (card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)')
        db.execute('INSERT INTO collector_snapshot.facets SELECT * FROM main.discovery_card_facet')
        db.execute('CREATE INDEX collector_snapshot.facet_lookup ON facets(facet_type,value,card_id)')
        db.execute('CREATE INDEX collector_snapshot.card_lookup ON facets(card_id,facet_type,value)')
        db.commit()
        db.execute('PRAGMA query_only=ON')
        self._vocabularies=MappingProxyType({key:tuple(db.execute(sql).fetchmany(100001))
            for key,sql in VOCABULARY_SQL.items()})
        if any(len(rows)>100000 for rows in self._vocabularies.values()):
            raise ValueError('catalog vocabulary exceeds read model bound')
        from . import collector_character_affiliation
        affiliations=collector_character_affiliation.affiliations(db)
        if len(affiliations)>collector_character_affiliation.MAX_BINDINGS:
            raise ValueError('catalog affiliations exceed read model bound')
        self._affiliations_json=json.dumps(affiliations,ensure_ascii=False,separators=(',',':'))
        if len(self._affiliations_json.encode())>1024*1024:
            raise ValueError('catalog affiliation proofs exceed read model bound')
        self._image=db.serialize(name=self.SCHEMA)
        if len(self._image)>self.MAX_IMAGE_BYTES:
            raise ValueError('catalog read model exceeds memory bound')
        checkpoint()
        self._check_snapshot(db)

    def _check_snapshot(self,db):
        from pathlib import Path
        try:
            main=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
            if not main or Path(main).resolve(strict=True)!=self._path or snapshot_identity(self._path)!=self._identity:
                raise CatalogSnapshotChanged()
        except OSError as exc:
            raise CatalogSnapshotChanged() from exc

    def _attach(self,db):
        db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
        db.deserialize(self._image,name=self.SCHEMA)
        db.execute('PRAGMA query_only=ON')

    @contextmanager
    def request(self,db):
        checkpoint();self._check_snapshot(db)
        self._attach(db)
        checkpoint()
        token=_snapshot_scope.set({'db':db,'model':self})
        try:
            yield
            checkpoint();self._check_snapshot(db)
        finally:
            _snapshot_scope.reset(token)


class CatalogBusy(Exception):
    pass


class CatalogDeadline(Exception):
    pass


class CatalogSnapshotChanged(Exception):
    pass


def snapshot_identity(path):
    """Fail closed on ordinary replacement, writes or WAL commits while serving.

    The service serves an immutable built snapshot and needs a restart after a
    catalog change. This metadata guard is not adversarial file attestation.
    """
    from pathlib import Path
    path = Path(path).resolve(strict=True)
    result = []
    for file in (path, Path(str(path) + '-wal')):
        try:
            stat = file.stat()
        except FileNotFoundError:
            result.append(None)
        else:
            # A read-only WAL open may create/remove an empty sidecar. It has
            # no transactions and is equivalent to an absent WAL file.
            result.append(None if file != path and stat.st_size == 0 else
                          (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


class CatalogAdmission:
    """Small FIFO queue protects a CPU-bound worker from thread contention.

    Queue expiry and a full queue reject without running catalog work. Waiting
    callers cannot be overtaken by a new arrival. This is per-server, not a
    distributed rate limiter or a promise that all burst requests will succeed.
    """
    def __init__(self, *, workers=1, queue_size=4, queue_wait=0.25, deadline=8.0):
        if (type(workers) is not int or not 1 <= workers <= 16
                or type(queue_size) is not int or not 0 <= queue_size <= 64
                or not 0 <= queue_wait <= 1 or not 0 < deadline <= 8):
            raise ValueError('invalid catalog runtime limits')
        self.workers, self.queue_size = workers, queue_size
        self.queue_wait, self.deadline = queue_wait, deadline
        self._condition = threading.Condition()
        self._waiting = deque()
        self._active = 0

    @contextmanager
    def acquire(self, *, expires=None):
        started = time.monotonic()
        expires = min(started + self.deadline, expires) if expires is not None else started + self.deadline
        ticket = object()
        with self._condition:
            if time.monotonic() >= expires:
                raise CatalogDeadline()
            if self._active >= self.workers or self._waiting:
                if len(self._waiting) >= self.queue_size:
                    raise CatalogBusy()
                self._waiting.append(ticket)
                try:
                    while self._active >= self.workers or self._waiting[0] is not ticket:
                        now = time.monotonic()
                        if now >= expires:
                            raise CatalogDeadline()
                        remaining = min(started + self.queue_wait, expires) - now
                        if remaining <= 0:
                            raise CatalogBusy()
                        self._condition.wait(remaining)
                    if time.monotonic() >= expires:
                        raise CatalogDeadline()
                    if time.monotonic() - started >= self.queue_wait:
                        raise CatalogBusy()
                    self._waiting.popleft()
                except BaseException:
                    self._waiting.remove(ticket)
                    self._condition.notify_all()
                    raise
            self._active += 1
        try:
            yield expires
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()


@contextmanager
def sqlite_deadline(db, expires):
    """One cooperative budget shared by SQLite and Python checkpoints."""
    active = _work_deadline.get()
    expires = min(expires, active) if active is not None else expires
    token = _work_deadline.set(expires)
    scopes = _sql_scopes.get()
    prior = next((callback for connection, callback in reversed(scopes) if connection is db), None)
    def expired():
        return time.monotonic() >= expires
    scope_token = _sql_scopes.set((*scopes, (db, expired)))
    installed = False
    try:
        db.set_progress_handler(expired, 1000)
        installed = True
        if expired():
            raise CatalogDeadline()
        yield
        if expired():
            raise CatalogDeadline()
    except Exception as exc:
        if expired():
            raise CatalogDeadline() from exc
        raise
    finally:
        try:
            if installed:db.set_progress_handler(prior, 1000 if prior is not None else 0)
        finally:
            _sql_scopes.reset(scope_token)
            _work_deadline.reset(token)
