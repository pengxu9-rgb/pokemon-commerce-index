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
_VOCABULARY_KEYS = frozenset({'character_aliases', 'artists', 'release_codes'})


def catalog_request(function):
    """Reuse fixed vocabularies only within one call and its nested operations."""
    @wraps(function)
    def wrapped(db, *args, **kwargs):
        active = _catalog_scope.get()
        if active is not None and active['db'] is db:
            return function(db, *args, **kwargs)
        token = _catalog_scope.set({'db': db, 'version': None, 'rows': {}})
        try:
            return function(db, *args, **kwargs)
        finally:
            _catalog_scope.reset(token)
    return wrapped


def vocabulary(db, key, sql):
    """Return immutable SQLite rows, invalidating on local or external writes.

    Only three fixed, non-user-specific parser vocabularies can be retained.
    A direct helper call outside a request never installs a persistent cache.
    """
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
    def acquire(self):
        started = time.monotonic()
        ticket = object()
        with self._condition:
            if self._active >= self.workers or self._waiting:
                if len(self._waiting) >= self.queue_size:
                    raise CatalogBusy()
                self._waiting.append(ticket)
                try:
                    while self._active >= self.workers or self._waiting[0] is not ticket:
                        remaining = self.queue_wait - (time.monotonic() - started)
                        if remaining <= 0:
                            raise CatalogBusy()
                        self._condition.wait(remaining)
                    if time.monotonic() - started >= self.queue_wait:
                        raise CatalogBusy()
                    self._waiting.popleft()
                except BaseException:
                    self._waiting.remove(ticket)
                    self._condition.notify_all()
                    raise
            self._active += 1
        try:
            yield started + self.deadline
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()


@contextmanager
def sqlite_deadline(db, expires):
    """Cooperative SQL deadline; bounded Python work is checked on completion."""
    def expired():
        return time.monotonic() >= expires
    db.set_progress_handler(expired, 1000)
    try:
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
        db.set_progress_handler(None, 0)
