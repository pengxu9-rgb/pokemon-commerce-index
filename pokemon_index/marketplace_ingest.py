"""Atomic local capture ingestion for independent marketplace tracking.

No transport, credential handling or source-policy grants live here. Captures
must already have been obtained through a separately authorized collection route.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from . import core, ingestion_worker as worker

MAX_CAPTURE_BYTES = 2_000_000


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("capture JSON contains duplicate object keys")
        result[key] = value
    return result


def load_capture(path: Path) -> dict:
    """Read a bounded local JSON object, rejecting ambiguous/nonfinite values."""
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_CAPTURE_BYTES + 1)
    if len(raw) > MAX_CAPTURE_BYTES:
        raise ValueError("capture exceeds two-megabyte limit")
    def nonfinite(_value):
        raise ValueError("capture JSON must contain finite numbers")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise ValueError("capture must be a JSON object")
    return result


def initialize(db):
    """Explicit operator schema setup; never called inside an import transaction."""
    if db.in_transaction:
        raise ValueError("marketplace initialization requires no active transaction")
    if not all(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
               for name in ("source_policy", "observation")):
        raise ValueError("initialize the base operator database before preparing marketplace state")
    db.execute("PRAGMA foreign_keys=ON")
    worker.initialize(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS marketplace_capture (
          capture_sha256 TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES source_policy(source),
          observed_at TEXT NOT NULL, imported_at TEXT NOT NULL,
          request_json TEXT NOT NULL, coverage_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS marketplace_capture_source_time
          ON marketplace_capture(source, observed_at);
        CREATE TABLE IF NOT EXISTS marketplace_observation_quality (
          source TEXT NOT NULL, native_id TEXT NOT NULL, observed_at TEXT NOT NULL,
          quality_json TEXT NOT NULL, evidence_ref TEXT NOT NULL,
          PRIMARY KEY(source,native_id,observed_at),
          FOREIGN KEY(source,native_id,observed_at)
            REFERENCES observation(source,native_id,observed_at) ON DELETE CASCADE);
    """)


def _is_fixture(source, url):
    host = urlsplit(url).hostname or ""
    return source.endswith("_fixture") and host.endswith(".invalid")


def _check_isolation(db, fixture):
    for row in db.execute("SELECT source,url FROM listing"):
        if fixture != _is_fixture(row["source"], row["url"]):
            raise ValueError("synthetic captures require a database isolated from real inventory")


def import_capture(db, capture: dict, *, now: str | None = None) -> dict:
    """Commit observations, immutable receipts, claim evidence and coverage together."""
    from .marketplace_sources import normalize_capture

    if db.in_transaction:
        raise ValueError("capture import requires a connection without an active transaction")
    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ValueError("capture import requires foreign-key enforcement")
    raw = _encoded(capture)
    if len(raw.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ValueError("capture exceeds two-megabyte limit")
    batch = normalize_capture(capture)
    source = batch["source"]
    fixture = source.endswith("_fixture")
    if now is not None and not fixture:
        raise ValueError("real marketplace captures must use the current clock")
    instant = core.parse_time(now or core.utcnow())
    observed = core.parse_time(batch["observed_at"])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    try:
        policy = core._policy(db, source)
        if observed > instant or observed < instant - timedelta(days=policy["retention_days"]):
            raise ValueError("capture outside permitted time window")
        _check_isolation(db, fixture)
        review_rows = [row for row in batch["observations"]
                       if row.get("resolution_gate") == "photo_required" and not db.execute(
                           "SELECT 1 FROM observation WHERE source=? AND native_id=? AND observed_at=?",
                           (source, row["native_id"], core.parse_time(row["observed_at"]).isoformat())).fetchone()]
        counts = worker._ingest(db, batch["observations"], source, instant)
        for row in review_rows:
            listing = db.execute("SELECT unit_id,last_seen FROM listing WHERE source=? AND native_id=?",
                                 (source, row["native_id"])).fetchone()
            if listing["unit_id"] and core.parse_time(listing["last_seen"]) == core.parse_time(row["observed_at"]):
                # New evidence supersedes an older human binding; exact replay
                # must preserve review performed after the original import.
                db.execute("UPDATE listing SET unit_id=NULL,resolution_method='unresolved' WHERE source=? AND native_id=?",
                           (source, row["native_id"]))
                db.execute("""INSERT INTO resolution_record
                    (source,native_id,unit_id,method,rule_version,resolved_at,reason)
                    VALUES (?,?,NULL,'unresolved','marketplace-quality-v1',?,?)""",
                           (source, row["native_id"], core.parse_time(row["observed_at"]).isoformat(),
                            "new source observation requires identity/grade review"))
        for row in batch["observations"]:
            quality = row["marketplace_quality"]
            if quality.get("certificate_verified") is not False or quality.get("authenticity_verified") is not False:
                raise ValueError("marketplace claim metadata cannot assert verification")
            encoded = _encoded(quality)
            key = (source, row["native_id"], core.parse_time(row["observed_at"]).isoformat())
            existing = db.execute("""SELECT quality_json,evidence_ref FROM marketplace_observation_quality
                WHERE source=? AND native_id=? AND observed_at=?""", key).fetchone()
            if existing and (existing["quality_json"] != encoded or existing["evidence_ref"] != row["evidence_ref"]):
                raise ValueError("conflicting immutable marketplace quality evidence")
            db.execute("INSERT OR IGNORE INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                       (*key, encoded, row["evidence_ref"]))
        prior = db.execute("SELECT capture_sha256 FROM marketplace_capture WHERE capture_sha256=?", (digest,)).fetchone()
        db.execute("INSERT OR IGNORE INTO marketplace_capture VALUES (?,?,?,?,?,?)",
                   (digest, source, observed.isoformat(), instant.isoformat(),
                    _encoded(batch["request"]), _encoded(batch["coverage"])))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"schema": "pokemon.marketplace-import-receipt.v1", "source": source,
            "capture_sha256": digest, "observed_at": observed.isoformat(),
            "capture_replayed": prior is not None, **counts, "coverage": batch["coverage"],
            "network_calls": 0, "fixture": fixture}


def purge(db, *, now: str | None = None) -> dict:
    """Use existing retention; quality follows observations through cascade deletion."""
    if db.in_transaction:
        raise ValueError("purge requires no active transaction")
    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ValueError("marketplace purge requires foreign-key enforcement")
    instant = core.parse_time(now or core.utcnow())
    before = db.execute("SELECT COUNT(*) FROM marketplace_observation_quality").fetchone()[0]
    removed = worker.purge(db, now=instant.isoformat())
    removed["marketplace_observation_quality"] = before - db.execute(
        "SELECT COUNT(*) FROM marketplace_observation_quality").fetchone()[0]
    removed["marketplace_capture"] = 0
    with db:
        for policy in db.execute("SELECT source,retention_days FROM source_policy").fetchall():
            cutoff = (instant - timedelta(days=policy["retention_days"])).isoformat()
            removed["marketplace_capture"] += db.execute(
                "DELETE FROM marketplace_capture WHERE source=? AND observed_at<?",
                (policy["source"], cutoff)).rowcount
    return removed
