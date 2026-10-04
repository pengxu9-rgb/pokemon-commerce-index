"""Request-local catalog vocabulary and bounded HTTP computation admission.

No sessions, rankings, inventories or authority are shared between requests.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading
import time


_catalog_scope = ContextVar('collector_catalog_scope', default=None)
_work_deadline = ContextVar('collector_work_deadline', default=None)
_sql_scopes = ContextVar('collector_sql_scopes', default=())
_VOCABULARY_KEYS = frozenset({'character_aliases', 'artists', 'release_codes'})


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
        token = _catalog_scope.set({'db': db, 'version': None, 'rows': {}})
        try:
            result = function(db, *args, **kwargs)
            checkpoint()
            return result
        finally:
            _catalog_scope.reset(token)
    return wrapped


def vocabulary(db, key, sql):
    """Return immutable SQLite rows, invalidating on local or external writes.

    Only three fixed, non-user-specific parser vocabularies can be retained.
    A direct helper call outside a request never installs a persistent cache.
    """
    checkpoint()
    if key not in _VOCABULARY_KEYS:
        raise ValueError('unsupported catalog vocabulary')
    active = _catalog_scope.get()
    if active is None or active['db'] is not db:
        return tuple(db.execute(sql))
    # SQLite total_changes cannot reveal a rollback or rollback-to-savepoint.
    # Direct write-capable callers therefore never retain transaction-local
    # rows. HTTP opens fresh read-only connections without explicit transactions.
    if db.in_transaction:
        active['rows'].clear()
        active['version'] = None
        return tuple(db.execute(sql))
    version = (db.total_changes, db.execute('PRAGMA data_version').fetchone()[0],
               db.execute('PRAGMA schema_version').fetchone()[0],
               db.execute('PRAGMA temp.schema_version').fetchone()[0])
    if active['version'] != version:
        active['rows'].clear()
        active['version'] = version
    if key not in active['rows']:
        rows = tuple(db.execute(sql))
        # Retention is bounded even for an unexpectedly malformed catalog.
        if len(rows) <= 100000:
            active['rows'][key] = rows
        return rows
    return active['rows'][key]


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
