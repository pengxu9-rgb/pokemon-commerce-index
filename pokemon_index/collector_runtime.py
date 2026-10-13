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
        return _trusted_snapshot_model(db)._vocabularies[key]
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
    return json.loads(_trusted_snapshot_model(db)._affiliations_json)


def _static_snapshot_version(db):
    """Static facts require the unchanged committed main/temp namespace.

    Native and mutable callers keep validating their current rows. Temporary
    shadows, transactions or disabled query-only mode cannot use shared facts.
    """
    checkpoint()
    if (db.in_transaction or db.execute('PRAGMA query_only').fetchone()[0] != 1
            or db.execute('SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone()):
        return None
    return (db.total_changes, db.execute('PRAGMA main.data_version').fetchone()[0],
            db.execute('PRAGMA main.schema_version').fetchone()[0],
            db.execute('PRAGMA temp.schema_version').fetchone()[0],
            db.execute('PRAGMA collector_snapshot.schema_version').fetchone()[0])


def snapshot_media_ids(db):
    """Only exact already-validated static source-scan IDs, never permissions."""
    checkpoint()
    snapshot = _snapshot_scope.get()
    if snapshot is None or snapshot['db'] is not db:
        return None
    snapshot['model']._check_snapshot(db)
    version = _static_snapshot_version(db)
    if version is None or version != snapshot['static_version']:
        return None
    return snapshot['model']._media_ids


def _trusted_snapshot_model(db):
    """An active image never replaces native facts in a mutable namespace."""
    checkpoint()
    snapshot=_snapshot_scope.get()
    if snapshot is None or snapshot['db'] is not db:
        return None
    db._catalog_check_clone_guard(snapshot['clone_guard'])
    snapshot['model']._check_snapshot(db)
    version=_static_snapshot_version(db)
    if version is None or version!=snapshot['static_version']:
        raise CatalogSnapshotChanged()
    return snapshot['model']


def snapshot_cast_dex_card_ids(db, dex_ids):
    """Exact SQLite CAST membership for the audited explicit-CAST callers.

    This relation does not apply to string equality/IN, generic SQL or concept
    expansion. The native SQL join determined every typed card-ID membership;
    only a small union of those immutable catalog facts can narrow the main scan.
    """
    model=_trusted_snapshot_model(db)
    if model is None:return None
    operands=tuple(dex_ids)
    if (not operands or len(operands)>model.MAX_DEX_OPERANDS or
            any(type(value) is not int or not -(2**63)<=value<2**63 for value in operands)):
        return None
    result=set()
    for value in operands:
        checkpoint();result.update(model._cast_dex_card_ids.get(value,()))
        if len(result)>model.MAX_DEX_QUERY_IDS:return None
    checkpoint()
    return frozenset(result)


def snapshot_text_dex_card_ids(db, values):
    """Exact positive string-IN membership, separately derived from CAST facts."""
    model = _trusted_snapshot_model(db)
    if model is None:
        return None
    operands = tuple(values)
    if (not operands or len(operands) > model.MAX_DEX_OPERANDS or
            any(type(value) is not str for value in operands)):
        return None
    result = set()
    for value in operands:
        checkpoint()
        result.update(model._text_dex_card_ids.get(value, ()))
        if len(result) > model.MAX_DEX_QUERY_IDS:
            return None
    return frozenset(result)


def card_scan(db, *, narrow_ids=False):
    """Use the canonical primary key only for an audited bounded ID predicate."""
    if narrow_ids and _trusted_snapshot_model(db) is not None:
        return 'main.card AS c INDEXED BY sqlite_autoindex_card_1'
    return 'card c'


def snapshot_character_names(db, current_only):
    model = _trusted_snapshot_model(db)
    return None if model is None else model._character_names[current_only]


def snapshot_release_names(db, languages):
    model = _trusted_snapshot_model(db)
    if model is None:
        return None
    return frozenset((code, term) for language, code, term in model._release_names
                     if language in languages)


def snapshot_release_aliases(db, languages):
    model = _trusted_snapshot_model(db)
    if model is None:
        return None
    return [row for row in json.loads(model._release_aliases_json)
            if row['language'] in languages]


def facet_lookup_relation(db):
    """Audited string equality/IN or explicit CAST lookups only.

    This materialized relation is NOT an arbitrary-SQL replacement for SQLite's
    compound effective view. Generic consumers retain the original view and its
    branch-specific comparison affinities/collations.
    """
    return 'collector_snapshot.facets' if _trusted_snapshot_model(db) is not None else 'discovery_card_facet'


class CatalogReadModelUnsupported(Exception):
    pass


class CatalogReadModel:
    """Immutable, bounded effective-facet image; a fresh clone per admitted call.

    Built only by the immutable HTTP server after calculating its catalog
    revision. Main remains mode=ro. No shared SQLite connection, user text,
    session, ranking, result, or new catalog assertion is retained.
    """
    MAX_IMAGE_BYTES=64*1024*1024
    MAX_MEDIA_IDS=100000
    MAX_MEDIA_ID_BYTES=4*1024*1024
    MAX_DEX_BINDINGS=100000
    MAX_DEX_ID_BYTES=8*1024*1024
    MAX_DEX_KEYS=4096
    MAX_DEX_OPERANDS=32
    MAX_DEX_QUERY_IDS=512
    MAX_CHARACTER_NAME_ROWS=100000
    MAX_CHARACTER_NAME_BYTES=8*1024*1024
    MAX_RELEASE_NAME_ROWS=100000
    MAX_RELEASE_NAME_BYTES=8*1024*1024
    MAX_RELEASE_ALIAS_BYTES=1024*1024
    COLUMNS=('card_id','facet_type','value','provenance','rights_reference')
    SCHEMA='collector_snapshot'

    @classmethod
    def _validate_database(cls, db):
        from pathlib import Path
        main=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
        if not main:raise ValueError('catalog read model requires a file snapshot')
        path=Path(main).resolve(strict=True)
        identity=snapshot_identity(path)
        opened=getattr(db,'_catalog_open_file_identity',None)
        if opened is None:
            raise CatalogReadModelUnsupported()
        if opened!=(str(path),*identity[0][:2]):
            raise CatalogSnapshotChanged()
        # Keep affinities as well as storage values. The effective view has no
        # declared affinity except TEXT provenance; do not coerce numeric artist
        # names, card IDs, or dex strings during materialization.
        expected=[(name,'TEXT' if name=='provenance' else 'BLOB') for name in cls.COLUMNS]
        actual=[(r[1],r[2] or 'BLOB') for r in db.execute('PRAGMA main.table_info(discovery_card_facet)')]
        if actual!=expected or not callable(getattr(db,'serialize',None)) or not callable(getattr(db,'deserialize',None)):
            raise CatalogReadModelUnsupported()
        if db.in_transaction:raise ValueError('read model needs a committed snapshot')
        if (any(row[1]=='temp' for row in db.execute('PRAGMA database_list'))
                and db.execute('SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone()):
            raise CatalogReadModelUnsupported()
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
        return path, identity

    def __init__(self,db):
        self._path, self._identity = self._validate_database(db)
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
        from . import catalog_media
        # Execute the same complete source/identity/hold validation as native
        # requests once. Membership is an exact static metadata fact; response
        # contexts and all display/physical/trading authority remain native.
        media_ids = catalog_media.current_ids(db)
        if (len(media_ids)>self.MAX_MEDIA_IDS or
                sum(len(cid.encode('utf-8')) for cid in media_ids)>self.MAX_MEDIA_ID_BYTES):
            raise ValueError('catalog source-scan IDs exceed read model bound')
        self._media_ids = frozenset(media_ids)
        self._cast_dex_card_ids=self._build_cast_dex_card_ids(db)
        self._text_dex_card_ids = self._build_text_dex_card_ids(db)
        from . import collector_discovery, collector_release_alias
        self._release_alias_path = collector_release_alias.BINDINGS_PATH.resolve(strict=True)
        self._release_alias_identity = snapshot_identity(self._release_alias_path)
        self._character_names = MappingProxyType({current: tuple(
            collector_discovery._character_name_facts(db, current_only=current,
                aliases=self._vocabularies['character_aliases'])) for current in (False, True)})
        self._release_names = tuple(collector_discovery._release_name_facts(db))
        languages = {row[0] for row in self._release_names}
        # The native proof reader validates the exact localized release and its
        # evidence. Only those proofs are retained; every response gets a copy.
        payload = json.loads(collector_release_alias.BINDINGS_PATH.read_text())
        languages.update(row['language'] for row in payload['records'])
        release_aliases = collector_release_alias.aliases(db, languages)
        self._release_aliases_json = json.dumps(release_aliases, ensure_ascii=False,
                                               separators=(',', ':'))
        self._release_names += tuple((row['language'], row['set_code'],
            collector_discovery._norm(row['alias'])) for row in release_aliases)
        if (len(self._release_names) > self.MAX_RELEASE_NAME_ROWS or
                sum(sum(len(value.encode('utf-8')) for value in row)
                    for row in self._release_names) > self.MAX_RELEASE_NAME_BYTES or
                len(self._release_aliases_json.encode('utf-8')) > self.MAX_RELEASE_ALIAS_BYTES or
                any(len(rows) > self.MAX_CHARACTER_NAME_ROWS or
                    sum(len(name.encode('utf-8')) for name, _, _ in rows) > self.MAX_CHARACTER_NAME_BYTES
                    for rows in self._character_names.values())):
            raise ValueError('catalog matching facts exceed read model bound')
        self._image=db.serialize(name=self.SCHEMA)
        if len(self._image)>self.MAX_IMAGE_BYTES:
            raise ValueError('catalog read model exceeds memory bound')
        checkpoint()
        self._check_snapshot(db)

    @classmethod
    def _build_cast_dex_card_ids(cls,db):
        # Preserve SQLite's JOIN affinity, storage classes and CAST behavior.
        # Python string/int coercion would silently change malformed, numeric,
        # zero-padded or BLOB operands. NULL CASTs cannot satisfy native IN.
        pairs=db.execute("""SELECT DISTINCT c.card_id,CAST(f.value AS INTEGER) AS dex_id
            FROM main.card c JOIN collector_snapshot.facets f ON f.card_id=c.card_id
            WHERE f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IS NOT NULL""").fetchmany(cls.MAX_DEX_BINDINGS+1)
        if len(pairs)>cls.MAX_DEX_BINDINGS:
            raise ValueError('catalog CAST dex bindings exceed read model bound')
        cast_ids={};total_bytes=0
        for cid,dex_id in pairs:
            checkpoint()
            total_bytes+=len(cid.encode('utf-8') if isinstance(cid,str) else cid)
            cast_ids.setdefault(dex_id,set()).add(cid)
            if len(cast_ids)>cls.MAX_DEX_KEYS or total_bytes>cls.MAX_DEX_ID_BYTES:
                raise ValueError('catalog CAST dex IDs exceed read model bound')
        return MappingProxyType({key:frozenset(ids) for key,ids in cast_ids.items()})

    @classmethod
    def _build_text_dex_card_ids(cls, db):
        # The materialized value column has BLOB affinity. A string IN operand
        # matches only TEXT storage, using the canonical BINARY collation. The
        # SQL join applies main.card's exact ID affinity, rather than Python
        # conversions or parameter-equality semantics.
        pairs = db.execute("""SELECT DISTINCT c.card_id,f.value
            FROM main.card c JOIN collector_snapshot.facets f ON f.card_id=c.card_id
            WHERE f.facet_type='dex_id' AND typeof(f.value)='text'""").fetchmany(cls.MAX_DEX_BINDINGS+1)
        if len(pairs) > cls.MAX_DEX_BINDINGS:
            raise ValueError('catalog TEXT dex bindings exceed read model bound')
        text_ids = {}; total_bytes = 0
        for cid, value in pairs:
            checkpoint()
            total_bytes += len(cid.encode('utf-8') if isinstance(cid, str) else cid)
            text_ids.setdefault(value, set()).add(cid)
            if len(text_ids) > cls.MAX_DEX_KEYS or total_bytes > cls.MAX_DEX_ID_BYTES:
                raise ValueError('catalog TEXT dex IDs exceed read model bound')
        return MappingProxyType({key: frozenset(ids) for key, ids in text_ids.items()})

    def _check_snapshot(self,db):
        from pathlib import Path
        try:
            main=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
            if not main or Path(main).resolve(strict=True)!=self._path or snapshot_identity(self._path)!=self._identity:
                raise CatalogSnapshotChanged()
            if getattr(db,'_catalog_open_file_identity',None)!=(str(self._path),*self._identity[0][:2]):
                raise CatalogSnapshotChanged()
            if (hasattr(self, '_release_alias_path') and
                    snapshot_identity(self._release_alias_path) != self._release_alias_identity):
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
        if db.in_transaction or db.execute('SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone():
            raise CatalogSnapshotChanged()
        if hasattr(self, '_artifact_guard'):
            self._artifact_guard()
        self._attach(db)
        checkpoint()
        version=_static_snapshot_version(db)
        if version is None:
            raise CatalogSnapshotChanged()
        guard=db._catalog_protect_clone(self.SCHEMA)
        token=_snapshot_scope.set({'db':db,'model':self,'static_version':version,'clone_guard':guard})
        try:
            yield
            db._catalog_check_clone_guard(guard)
            checkpoint();self._check_snapshot(db)
            if _static_snapshot_version(db)!=version:
                raise CatalogSnapshotChanged()
            if hasattr(self, '_artifact_guard'):
                self._artifact_guard()
        except BaseException as exc:
            # A caller cannot catch the SQL/driver error and restore a replaced
            # namespace before success. Any forbidden attempt poisons this scope.
            try:
                db._catalog_check_clone_guard(guard)
            except CatalogSnapshotChanged as changed:
                raise changed from exc
            raise
        finally:
            try:
                db._catalog_release_clone_guard(guard)
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
