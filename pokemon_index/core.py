from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from . import number_graph

STATUSES = {"on_sale", "trading", "sold_out", "gone"}
COMPONENTS = {"item", "domestic", "service", "international", "tax", "insurance", "fx_spread", "other"}
GRADE_RE = re.compile(r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)\s*(10|9(?:\.5)?|8(?:\.5)?|7(?:\.5)?|6(?:\.5)?|[1-5](?:\.5)?)(?![\d.])", re.I)
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3}/\d{1,3})(?!\d)")
CARD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9-]{0,11})\s+(\d{1,3}/\d{1,3})\b")
BUNDLE_RE = re.compile(r"(?<!\d)(?:[2-9]|[1-9]\d+)枚|まとめ売り|連番|\d+枚組|[&＆]")
LANGUAGE_RE = {
    "ja": re.compile(r"日版|日本語|日文|\bJapanese\b", re.I),
    "en": re.compile(r"英語版|英文|\bEnglish\b", re.I),
    "ko": re.compile(r"韓国語|韓版|韓文|\bKorean\b", re.I),
    "zh": re.compile(r"簡体字|繁体字|中国語|中文|\bChinese\b", re.I),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(db: sqlite3.Connection) -> None:
    db.executescript(Path(__file__).with_name("schema.sql").read_text())
    policy_columns = {row[1] for row in db.execute("PRAGMA table_info(source_policy)")}
    if "media_ai_allowed" not in policy_columns:
        db.execute("ALTER TABLE source_policy ADD COLUMN media_ai_allowed INTEGER NOT NULL DEFAULT 0")
    if "cross_region_use_allowed" not in policy_columns:
        db.execute("ALTER TABLE source_policy ADD COLUMN cross_region_use_allowed INTEGER NOT NULL DEFAULT 0")
    card_columns = {row[1] for row in db.execute("PRAGMA table_info(card)")}
    if "rights_reference" not in card_columns:
        db.execute("ALTER TABLE card ADD COLUMN rights_reference TEXT NOT NULL DEFAULT 'unreviewed legacy import'")
    if "display_allowed" not in card_columns:
        db.execute("ALTER TABLE card ADD COLUMN display_allowed INTEGER NOT NULL DEFAULT 0")
    if "match_eligible" not in card_columns:
        db.execute("ALTER TABLE card ADD COLUMN match_eligible INTEGER NOT NULL DEFAULT 1")
    if "attributes_json" not in card_columns:
        db.execute("ALTER TABLE card ADD COLUMN attributes_json TEXT NOT NULL DEFAULT '{}'")
    exception_columns = {row[1] for row in db.execute("PRAGMA table_info(card_identity_exception)")}
    if "source_provenance" not in exception_columns:
        db.execute("ALTER TABLE card_identity_exception ADD COLUMN source_provenance TEXT NOT NULL DEFAULT ''")
        db.execute("""UPDATE card_identity_exception SET source_provenance =
                   (SELECT provenance FROM card WHERE card.card_id=card_identity_exception.card_id)""")
    if "official_printing_type" not in exception_columns:
        db.execute("ALTER TABLE card_identity_exception ADD COLUMN official_printing_type TEXT")
        db.execute("""UPDATE card_identity_exception SET official_printing_type='prism_star'
                   WHERE corrected_rarity='Prism Star'""")
    # A prior positional insert into an upgraded table shifted these fields.
    # Repair only the exact, recognizable shape; fail closed on anything else.
    for broken in db.execute("""SELECT * FROM card_identity_exception
        WHERE official_url='Prism Star' AND corrected_name LIKE 'tcgdex:%'""").fetchall():
        if (not re.fullmatch(r"https://www\.pokemon-card\.com/card-search/details\.php/card/\d+",
                             broken["official_page_sha256"])
                or not re.fullmatch(r"[0-9a-f]{64}", broken["reason"])):
            raise ValueError("unrecognized shifted card exception; manual repair required")
        db.execute("""UPDATE card_identity_exception SET
            source_provenance=?, corrected_name=?, corrected_rarity='Prism Star',
            official_url=?, official_page_sha256=?, reason=?, applied_at=?,
            official_printing_type='prism_star' WHERE card_id=?""",
            (broken["corrected_name"], broken["corrected_rarity"],
             broken["official_page_sha256"], broken["reason"], broken["applied_at"],
             broken["source_provenance"], broken["card_id"]))
        db.execute("UPDATE card SET name=?, rarity='Prism Star' WHERE card_id=?",
                   (broken["corrected_rarity"], broken["card_id"]))
    observation_columns = {row[1] for row in db.execute("PRAGMA table_info(observation)")}
    if "native_created" not in observation_columns:
        db.execute("ALTER TABLE observation ADD COLUMN native_created TEXT")
    if "native_updated" not in observation_columns:
        db.execute("ALTER TABLE observation ADD COLUMN native_updated TEXT")
    relationship_columns = {row[1] for row in db.execute("PRAGMA table_info(card_relationship_assertion)")}
    if "reviewer" not in relationship_columns:
        db.execute("ALTER TABLE card_relationship_assertion ADD COLUMN reviewer TEXT")
    concept_columns = {row[1] for row in db.execute("PRAGMA table_info(bilingual_concept_revision)")}
    if "review_event_id" not in concept_columns:
        db.execute("ALTER TABLE bilingual_concept_revision ADD COLUMN review_event_id TEXT REFERENCES concept_review_event(event_id)")
    db.execute(
        """INSERT OR IGNORE INTO catalog_set_localized
        SELECT 'ja', set_code, name_ja, release_date_ja, official_card_count,
        provenance, rights_reference, display_allowed FROM catalog_set"""
    )
    number_graph.backfill_number_context(db)
    db.commit()


def _required(row: dict[str, Any], *names: str) -> None:
    for name in names:
        if row.get(name) in (None, ""):
            raise ValueError(f"missing {name}")


def _policy(db: sqlite3.Connection, source: str, display: bool = False) -> sqlite3.Row:
    policy = db.execute("SELECT * FROM source_policy WHERE source=?", (source,)).fetchone()
    if not policy or not policy["ingest_allowed"]:
        raise ValueError(f"source {source!r} lacks an enabled ingest policy")
    if policy["expires_at"] and parse_time(policy["expires_at"]) <= datetime.now(timezone.utc):
        raise ValueError(f"source {source!r} permission has expired")
    if display and not policy["display_allowed"]:
        raise ValueError(f"source {source!r} cannot be displayed")
    return policy


def register_source(db: sqlite3.Connection, row: dict[str, Any]) -> None:
    _required(row, "source", "rights_reference", "retention_days")
    if row["source"].lower() == "snkrdunk" and row["rights_reference"] == "public_site":
        raise ValueError("SNKRDUNK public pages are not an ingest permission")
    if row.get("expires_at"):
        parse_time(row["expires_at"])
    db.execute(
        """INSERT INTO source_policy
        (source, rights_reference, ingest_allowed, display_allowed,
         cross_source_use_allowed, seller_analytics_allowed, retention_days,
         listing_ttl_hours, expires_at, media_ai_allowed, cross_region_use_allowed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET rights_reference=excluded.rights_reference,
        ingest_allowed=excluded.ingest_allowed, display_allowed=excluded.display_allowed,
        cross_source_use_allowed=excluded.cross_source_use_allowed,
        seller_analytics_allowed=excluded.seller_analytics_allowed,
        media_ai_allowed=excluded.media_ai_allowed,
        cross_region_use_allowed=excluded.cross_region_use_allowed,
        retention_days=excluded.retention_days, listing_ttl_hours=excluded.listing_ttl_hours,
        expires_at=excluded.expires_at""",
        (row["source"], row["rights_reference"], int(bool(row.get("ingest_allowed", False))),
         int(bool(row.get("display_allowed", False))), int(bool(row.get("cross_source_use_allowed", False))),
         int(bool(row.get("seller_analytics_allowed", False))), int(row["retention_days"]),
         int(row.get("listing_ttl_hours", 6)), row.get("expires_at"),
         int(bool(row.get("media_ai_allowed", False))),
         int(bool(row.get("cross_region_use_allowed", False)))),
    )
    db.commit()


def card_id(language: str, set_code: str, number: str, variant: str) -> str:
    return ":".join((language.lower(), set_code.upper(), normalize_collector_number(number), variant.lower()))


def normalize_collector_number(number: str) -> str:
    match = re.fullmatch(r"(\d+)/(\d+)", str(number))
    if not match:
        return str(number)
    width = max(3, len(match.group(1)), len(match.group(2)))
    return f"{match.group(1).zfill(width)}/{match.group(2).zfill(width)}"


def _compact_identity_text(value: str) -> str:
    """Allow listing spacing/punctuation differences without changing card letters."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def import_cards(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        _required(row, "language", "set_code", "collector_number", "name", "provenance",
                  "rights_reference")
        variant = str(row.get("variant") or "standard").lower()
        number = normalize_collector_number(row["collector_number"])
        cid = card_id(row["language"], row["set_code"], number, variant)
        exception = db.execute("SELECT source_provenance FROM card_identity_exception WHERE card_id=?",
                               (cid,)).fetchone()
        if exception and exception["source_provenance"] != row["provenance"]:
            raise ValueError("re-imported card source differs from its identity exception")
        db.execute(
            """INSERT INTO card
            (card_id, language, set_code, collector_number, variant, name, rarity,
             provenance, rights_reference, display_allowed, match_eligible, attributes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id) DO UPDATE SET
            name=COALESCE((SELECT corrected_name FROM card_identity_exception
                           WHERE card_id=excluded.card_id), excluded.name),
            rarity=COALESCE((SELECT corrected_rarity FROM card_identity_exception
                             WHERE card_id=excluded.card_id), excluded.rarity),
            provenance=excluded.provenance,
            rights_reference=excluded.rights_reference,
            display_allowed=CASE WHEN EXISTS(SELECT 1 FROM card_identity_exception
                 WHERE card_id=excluded.card_id) THEN 0 ELSE excluded.display_allowed END,
            match_eligible=CASE WHEN EXISTS(SELECT 1 FROM card_identity_exception
                 WHERE card_id=excluded.card_id) THEN 0 ELSE excluded.match_eligible END,
            attributes_json=excluded.attributes_json""",
            (cid, row["language"].lower(), row["set_code"].upper(),
             number, variant, row["name"], row.get("rarity"), row["provenance"],
             row["rights_reference"], int(bool(row.get("display_allowed", False))),
             int(bool(row.get("match_eligible", True))),
             json.dumps(row.get("attributes", {}), ensure_ascii=False, sort_keys=True)),
        )
        number_graph.upsert_number_context(db, {
            "card_id": cid, "language": row["language"].lower(),
            "set_code": row["set_code"].upper(), "collector_number": number,
            "variant": variant,
        })
        count += 1
    db.commit()
    return count


def apply_card_identity_exceptions(db: sqlite3.Connection,
                                   rows: Iterable[dict[str, Any]]) -> int:
    """Apply source-bound corrections and keep corrected cards out of offer matching."""
    count = 0
    with db:
        for row in rows:
            _required(row, "card_id", "original_name", "source_provenance", "corrected_name", "official_url",
                      "official_page_sha256", "reason")
            if (not re.fullmatch(r"https://www\.pokemon-card\.com/card-search/details\.php/card/\d+",
                                 row["official_url"])
                    or not re.fullmatch(r"[0-9a-f]{64}", row["official_page_sha256"])):
                raise ValueError("identity exception lacks a valid official page reference")
            printing_type = row.get("official_printing_type")
            if printing_type not in {None, "prism_star"}:
                raise ValueError("unsupported official printing type")
            if printing_type == "prism_star" and row.get("corrected_rarity") != "Prism Star":
                raise ValueError("Prism Star printing type requires official rarity evidence")
            card = db.execute("SELECT name,provenance FROM card WHERE card_id=?",
                              (row["card_id"],)).fetchone()
            if (not card or card["name"] not in {row["original_name"], row["corrected_name"]}
                    or card["provenance"] != row["source_provenance"]
                    or not card["provenance"].startswith("tcgdex:")):
                raise ValueError("identity exception does not bind the pinned card")
            existing = db.execute("SELECT * FROM card_identity_exception WHERE card_id=?",
                                  (row["card_id"],)).fetchone()
            expected = (row["original_name"], row["source_provenance"],
                        row["corrected_name"], row.get("corrected_rarity"), printing_type,
                        row["official_url"], row["official_page_sha256"], row["reason"])
            if existing:
                actual = tuple(existing[key] for key in
                               ("original_name", "source_provenance", "corrected_name", "corrected_rarity",
                                "official_printing_type",
                                "official_url", "official_page_sha256", "reason"))
                if actual != expected:
                    raise ValueError("existing identity exception differs")
            else:
                db.execute("""INSERT INTO card_identity_exception
                    (card_id, original_name, source_provenance, corrected_name,
                     corrected_rarity, official_printing_type, official_url,
                     official_page_sha256, reason, applied_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (row["card_id"], *expected, utcnow()))
            db.execute("""UPDATE card SET name=?, rarity=COALESCE(?,rarity),
                       match_eligible=0, display_allowed=0 WHERE card_id=?""",
                       (row["corrected_name"], row.get("corrected_rarity"), row["card_id"]))
            count += 1
    return count


def import_sets(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        _required(row, "set_code", "provenance", "rights_reference")
        official = int(row.get("official_card_count", 0))
        if official < 0:
            raise ValueError("official card count cannot be negative")
        language = str(row.get("language") or "ja").lower()
        if language not in {"ja", "en"}:
            raise ValueError("unsupported set language")
        set_code = str(row["set_code"]).upper()
        name = row.get("name") if language == "en" else row.get("name_ja")
        release_date = row.get("release_date") if language == "en" else row.get("release_date_ja")
        values = (set_code, name, release_date, official, row["provenance"],
                  row["rights_reference"], int(bool(row.get("display_allowed", False))))
        db.execute(
            """INSERT INTO catalog_set_localized VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(language, set_code) DO UPDATE SET name=excluded.name,
            release_date=excluded.release_date,
            official_card_count=excluded.official_card_count,
            provenance=excluded.provenance, rights_reference=excluded.rights_reference,
            display_allowed=excluded.display_allowed""",
            (language, *values),
        )
        if language == "ja":
            db.execute(
                """INSERT INTO catalog_set VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(set_code) DO UPDATE SET name_ja=excluded.name_ja,
                release_date_ja=excluded.release_date_ja,
                official_card_count=excluded.official_card_count,
                provenance=excluded.provenance, rights_reference=excluded.rights_reference,
                display_allowed=excluded.display_allowed""",
                values,
            )
        count += 1
    db.commit()
    return count


def import_card_references(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        _required(row, "source", "source_jp_id", "name", "provenance", "rights_reference")
        db.execute(
            """INSERT INTO card_reference VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, native_id) DO UPDATE SET set_code=excluded.set_code,
            collector_number=excluded.collector_number, name=excluded.name,
            rarity=excluded.rarity, attributes_json=excluded.attributes_json,
            provenance=excluded.provenance, rights_reference=excluded.rights_reference,
            display_allowed=excluded.display_allowed""",
            (row["source"], str(row["source_jp_id"]), row.get("set_code"),
             row.get("collector_number"), row["name"], row.get("rarity"),
             json.dumps(row.get("attributes", {}), ensure_ascii=False, sort_keys=True),
             row["provenance"], row["rights_reference"],
             int(bool(row.get("display_allowed", False)))),
        )
        count += 1
    db.commit()
    return count


def import_card_facets(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Load internal character/artist facts with per-row source provenance."""
    count = 0
    with db:
        for row in rows:
            _required(row, "card_id", "facet_type", "value", "provenance", "rights_reference")
            facet_type, value = row["facet_type"], str(row["value"]).strip()
            if facet_type == "dex_id":
                if not re.fullmatch(r"[1-9]\d{0,3}", value):
                    raise ValueError("dex_id must be a positive integer below 10000")
            elif facet_type == "illustrator":
                if not value or len(value) > 160:
                    raise ValueError("invalid illustrator")
            else:
                raise ValueError("unsupported card facet")
            db.execute(
                """INSERT INTO card_facet VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(card_id, facet_type, value) DO UPDATE SET
                provenance=excluded.provenance, rights_reference=excluded.rights_reference""",
                (row["card_id"], facet_type, value, row["provenance"], row["rights_reference"]),
            )
            count += 1
    return count


def import_card_classifications(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Import category and subtype from a card-specific, pinned source."""
    allowed = {
        "Pokemon": {None},
        "Trainer": {None, "Item", "Stadium", "Supporter", "Tool"},
        "Energy": {None, "Normal", "Special"},
    }
    count = 0
    with db:
        for row in rows:
            _required(row, "card_id", "category", "provenance", "rights_reference")
            category, subtype = row["category"], row.get("subtype")
            if category not in allowed or subtype not in allowed[category]:
                raise ValueError("invalid card classification")
            current = db.execute(
                "SELECT category, subtype, provenance FROM card_classification WHERE card_id=?",
                (row["card_id"],),
            ).fetchone()
            if current and (current["category"], current["subtype"], current["provenance"]) != (
                    category, subtype, row["provenance"]):
                raise ValueError("conflicting card classification; review source before replacing")
            db.execute(
                """INSERT INTO card_classification VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO NOTHING""",
                (row["card_id"], category, subtype, row["provenance"], row["rights_reference"]),
            )
            count += 1
    return count


def import_bilingual_concepts(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Low-level concept import for fixtures and migrations; use review bundles in production."""
    count = 0
    fields = ("concept_id", "revision", "category", "name_ja", "name_en",
              "source_ja", "source_en", "rights_reference", "reviewer", "reviewed_at", "status")
    with db:
        for row in rows:
            _required(row, *fields)
            if row["category"] not in {"Pokemon", "Trainer", "Energy"}:
                raise ValueError("invalid concept category")
            if row["status"] not in {"approved", "withdrawn"}:
                raise ValueError("invalid concept status")
            if type(row["revision"]) is not int or row["revision"] < 1:
                raise ValueError("concept revision must be a positive integer")
            if any(not isinstance(row[field], str) or row[field] != row[field].strip()
                   or len(row[field]) > 500 for field in fields if field != "revision"):
                raise ValueError("invalid concept text")
            parse_time(row["reviewed_at"])
            values = tuple(row[field] for field in fields) + (row.get("review_event_id"),)
            latest = db.execute(
                "SELECT * FROM bilingual_concept_revision WHERE concept_id=? ORDER BY revision DESC LIMIT 1",
                (row["concept_id"],),
            ).fetchone()
            if latest and row["revision"] <= latest["revision"]:
                if row["revision"] == latest["revision"] and values == tuple(latest[field] for field in (*fields, "review_event_id")):
                    continue
                raise ValueError("stale or conflicting concept revision")
            db.execute(
                "INSERT INTO bilingual_concept_revision VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values,
            )
            count += 1
    return count


def import_concept_review_bundle(db: sqlite3.Connection, bundle: dict[str, Any]) -> dict[str, int]:
    """Atomically retain attributed decisions and their approved name aliases."""
    if bundle.get("schema") != "pokemon.concept_review_bundle.v1":
        raise ValueError("unsupported concept review bundle")
    events = bundle.get("review_events")
    concepts = bundle.get("concept_revisions")
    if not isinstance(events, list) or not isinstance(concepts, list):
        raise ValueError("bundle needs review_events and concept_revisions lists")
    prepared = {}
    for event in events:
        if not isinstance(event, dict) or event.get("schema") != "pokemon.concept_review.v1":
            raise ValueError("invalid concept review event")
        payload = {key: value for key, value in event.items() if key != "event_id"}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if event.get("event_id") != digest:
            raise ValueError("concept review event digest mismatch")
        proposal, review = event.get("proposal"), event.get("review")
        if not isinstance(proposal, dict) or not isinstance(review, dict):
            raise ValueError("concept review needs proposal and decision evidence")
        _required(proposal, "proposal_id", "source_snapshot_sha256", "category", "name_ja",
                  "name_en", "source_ja", "source_en", "ja_provenance", "en_provenance",
                  "rights_reference")
        snapshot = proposal.get("source_snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("frozen"), dict):
            raise ValueError("concept review lacks complete source snapshot")
        snapshot_digest = hashlib.sha256(json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if snapshot_digest != proposal["source_snapshot_sha256"] or any(
                proposal.get(key) != value for key, value in snapshot["frozen"].items()):
            raise ValueError("concept source snapshot mismatch")
        for side in ("ja", "en"):
            if proposal[f"{side}_provenance"] != snapshot[f"{side}_provenance"]:
                raise ValueError("concept card provenance mismatch")
        _required(review, "decision", "reviewer", "reviewed_at", "evidence_note")
        if review["decision"] not in {"approve", "reject", "uncertain"}:
            raise ValueError("invalid concept review decision")
        revision = review.get("review_revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("concept review needs positive review_revision")
        parse_time(review["reviewed_at"])
        if (not isinstance(review["reviewer"], str) or not review["reviewer"].strip()
                or review["reviewer"] != review["reviewer"].strip()
                or not isinstance(review["evidence_note"], str)
                or not review["evidence_note"].strip()):
            raise ValueError("concept review needs attributed evidence")
        if review["decision"] == "approve" and any(
                review.get(field) is not True for field in
                ("ja_identity_checked", "en_identity_checked", "translation_checked")):
            raise ValueError("approved concept needs three identity attestations")
        if event["event_id"] in prepared:
            raise ValueError("duplicate concept review event")
        prepared[event["event_id"]] = event
    approved_ids = {event_id for event_id, event in prepared.items()
                    if event["review"]["decision"] == "approve"}
    if {row.get("review_event_id") for row in concepts} != approved_ids:
        raise ValueError("every approval must map to exactly one concept revision")
    if len(concepts) != len(approved_ids):
        raise ValueError("duplicate concept revision for one approval")
    count_events = count_concepts = 0
    with db:
        for event_id, event in prepared.items():
            proposal, review = event["proposal"], event["review"]
            record = json.dumps(event, ensure_ascii=False, sort_keys=True)
            existing = db.execute(
                "SELECT record_json FROM concept_review_event WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing:
                if existing["record_json"] != record:
                    raise ValueError("conflicting concept review event")
                continue
            latest = db.execute(
                "SELECT MAX(review_revision) FROM concept_review_event WHERE proposal_id=?",
                (proposal["proposal_id"],),
            ).fetchone()[0]
            if latest is not None and review["review_revision"] <= latest:
                raise ValueError("stale concept review revision")
            db.execute("""INSERT INTO concept_review_event VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                       (event_id, proposal["proposal_id"], review["review_revision"],
                        proposal["source_snapshot_sha256"], review["decision"],
                        review["reviewer"], review["reviewed_at"], record))
            count_events += 1
        for row in concepts:
            event = prepared[row["review_event_id"]]
            proposal, review = event["proposal"], event["review"]
            expected = {
                "category": proposal["category"], "name_ja": proposal["name_ja"],
                "name_en": proposal["name_en"], "source_ja": proposal["source_ja"],
                "source_en": proposal["source_en"],
                "rights_reference": proposal["rights_reference"],
                "reviewer": review["reviewer"], "reviewed_at": review["reviewed_at"],
                "status": "approved",
            }
            if any(row.get(key) != value for key, value in expected.items()):
                raise ValueError("alias does not match retained review evidence")
            _required(row, "concept_id", "revision")
            if type(row["revision"]) is not int or row["revision"] < 1:
                raise ValueError("invalid concept revision")
            values = tuple(row[key] for key in (
                "concept_id", "revision", "category", "name_ja", "name_en",
                "source_ja", "source_en", "rights_reference", "reviewer",
                "reviewed_at", "status", "review_event_id"))
            existing = db.execute(
                "SELECT * FROM bilingual_concept_revision WHERE concept_id=? ORDER BY revision DESC LIMIT 1",
                (row["concept_id"],),
            ).fetchone()
            if existing and row["revision"] <= existing["revision"]:
                if row["revision"] == existing["revision"] and values == tuple(
                        existing[key] for key in (
                            "concept_id", "revision", "category", "name_ja", "name_en",
                            "source_ja", "source_en", "rights_reference", "reviewer",
                            "reviewed_at", "status", "review_event_id")):
                    continue
                raise ValueError("stale or conflicting concept revision")
            db.execute("INSERT INTO bilingual_concept_revision VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            count_concepts += 1
    return {"review_events": count_events, "concept_revisions": count_concepts}


def catalog_status(db: sqlite3.Connection) -> dict[str, Any]:
    """Inventory of the internal identity seed, including its display gate."""
    totals = db.execute(
        """SELECT COUNT(*) AS printings, COUNT(DISTINCT language || ':' || set_code) AS sets,
        SUM(CASE WHEN display_allowed=1 THEN 1 ELSE 0 END) AS display_approved,
        SUM(CASE WHEN match_eligible=1 THEN 1 ELSE 0 END) AS match_eligible
        FROM card"""
    ).fetchone()
    sets = [dict(row) for row in db.execute(
        """SELECT c.language, c.set_code, MAX(s.name) AS name,
        MAX(s.release_date) AS release_date,
        MAX(CASE WHEN c.language='ja' THEN s.name END) AS name_ja,
        MAX(CASE WHEN c.language='ja' THEN s.release_date END) AS release_date_ja,
        COUNT(*) AS printings, COUNT(DISTINCT c.collector_number) AS collector_numbers,
        SUM(CASE WHEN c.display_allowed=1 THEN 1 ELSE 0 END) AS display_approved,
        SUM(CASE WHEN c.match_eligible=1 THEN 1 ELSE 0 END) AS match_eligible
        FROM card c LEFT JOIN catalog_set_localized s
        ON s.language=c.language AND s.set_code=c.set_code
        GROUP BY c.language, c.set_code ORDER BY c.language, c.set_code"""
    )]
    references = db.execute("SELECT COUNT(*) FROM card_reference").fetchone()[0]
    facet_coverage = {row["facet_type"]: row["cards"] for row in db.execute(
        "SELECT facet_type, COUNT(DISTINCT card_id) AS cards FROM card_facet GROUP BY facet_type"
    )}
    printing_type_coverage = {row["official_printing_type"]: row["cards"] for row in db.execute(
        """SELECT official_printing_type, COUNT(*) AS cards FROM card_identity_exception
           WHERE official_printing_type IS NOT NULL GROUP BY official_printing_type""")}
    return {"printings": totals["printings"], "sets": totals["sets"],
            "reference_records": references,
            "facet_coverage": facet_coverage,
            "official_printing_type_coverage": printing_type_coverage,
            "display_approved": totals["display_approved"] or 0,
            "match_eligible": totals["match_eligible"] or 0, "set_coverage": sets,
            "scope": "internal catalog inventory; not a public display authorization"}


def _catalog_card_dict(row: sqlite3.Row) -> dict[str, Any]:
    card = dict(row)
    card["attributes"] = json.loads(card.pop("attributes_json"))
    return card


def catalog_search_internal(db: sqlite3.Connection, query: str, *,
                            set_code: str | None = None, variant: str | None = None,
                            printing_type: str | None = None,
                            dex_id: int | None = None, illustrator: str | None = None,
                            limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Search internal card metadata without weakening public display controls."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1–100 and offset cannot be negative")
    normalized = unicodedata.normalize("NFKC", query).strip()
    if dex_id is not None and (type(dex_id) is not int or not 1 <= dex_id <= 9999):
        raise ValueError("dex_id must be a positive integer below 10000")
    if printing_type not in {None, "prism_star"}:
        raise ValueError("unsupported official printing type")
    if not normalized and not (set_code or printing_type or dex_id or illustrator):
        raise ValueError("a query, set code, printing type, dex ID or illustrator is required")
    terms = [normalize_collector_number(term) for term in normalized.casefold().split()]
    candidates = db.execute(
        """SELECT c.*, s.name AS set_name, e.official_printing_type,
        CASE WHEN c.language='ja' THEN s.name END AS set_name_ja FROM card c
        LEFT JOIN catalog_set_localized s
        ON s.language=c.language AND s.set_code=c.set_code
        LEFT JOIN card_identity_exception e ON e.card_id=c.card_id
        WHERE (? IS NULL OR c.set_code=?) AND (? IS NULL OR c.variant=?)
        AND (? IS NULL OR e.official_printing_type=?)
        AND (? IS NULL OR EXISTS (SELECT 1 FROM card_facet f WHERE f.card_id=c.card_id
            AND f.facet_type='dex_id' AND f.value=?))
        AND (? IS NULL OR EXISTS (SELECT 1 FROM card_facet f WHERE f.card_id=c.card_id
            AND f.facet_type='illustrator' AND lower(f.value)=lower(?)))
        ORDER BY c.set_code, c.collector_number, c.variant""",
        (set_code.upper() if set_code else None, set_code.upper() if set_code else None,
         variant.lower() if variant else None, variant.lower() if variant else None,
         printing_type, printing_type,
         dex_id, str(dex_id) if dex_id is not None else None,
         illustrator, illustrator),
    )
    def matches(row: sqlite3.Row) -> bool:
        text = unicodedata.normalize(
            "NFKC", f"{row['name']} {row['set_name'] or ''} {row['set_code']} {row['collector_number']} "
            f"{row['language']} {row['variant']} {row['official_printing_type'] or ''} "
            f"{'プリズムスター Prism Star' if row['official_printing_type'] == 'prism_star' else ''}"
        ).casefold()
        return all(term in text for term in terms)
    found = [_catalog_card_dict(row) for row in candidates if matches(row)]
    return {"query": query, "set_code": set_code.upper() if set_code else None,
            "variant": variant.lower() if variant else None,
            "printing_type": printing_type, "dex_id": dex_id,
            "illustrator": illustrator, "total": len(found),
            "offset": offset, "cards": found[offset:offset + limit],
            "scope": "internal metadata only; display_allowed controls public APIs"}


def catalog_card_internal(db: sqlite3.Connection, cid: str) -> dict[str, Any]:
    row = db.execute("""SELECT c.*,e.official_printing_type FROM card c
                      LEFT JOIN card_identity_exception e ON e.card_id=c.card_id
                      WHERE c.card_id=?""", (cid,)).fetchone()
    if not row:
        raise ValueError("unknown card")
    units = [dict(unit) for unit in db.execute(
        """SELECT * FROM priceable_unit WHERE card_id=?
        ORDER BY grade_company, grade_value, condition_bucket""", (cid,)
    )]
    siblings = [dict(card) for card in db.execute(
        """SELECT card_id, variant FROM card WHERE language=? AND set_code=?
        AND collector_number=? ORDER BY variant""",
        (row["language"], row["set_code"], row["collector_number"]),
    )]
    references = []
    for reference in db.execute(
        """SELECT * FROM card_reference WHERE set_code=? AND collector_number=?
        ORDER BY source, native_id LIMIT 20""",
        (row["set_code"] if row["language"] == "ja" else "", row["collector_number"]),
    ):
        item = dict(reference)
        item["attributes"] = json.loads(item.pop("attributes_json"))
        references.append(item)
    facets = [dict(facet) for facet in db.execute(
        """SELECT facet_type, value, provenance, rights_reference FROM card_facet
        WHERE card_id=? ORDER BY facet_type, value""", (cid,)
    )]
    exception = db.execute("SELECT * FROM card_identity_exception WHERE card_id=?", (cid,)).fetchone()
    return {"card": _catalog_card_dict(row),
            "number_context": number_graph.card_number_context(db, cid),
            "identity_exception": dict(exception) if exception else None,
            "variants_at_number": siblings,
            "set": ({**dict(set_row),
                     "name_ja": set_row["name"] if row["language"] == "ja" else None,
                     "release_date_ja": set_row["release_date"] if row["language"] == "ja" else None}
                    if (set_row := db.execute(
                "SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?",
                (row["language"], row["set_code"])
            ).fetchone()) else None),
            "reference_records": references,
            "discovery_facets": facets,
            "observed_priceable_units": units,
            "scope": "internal metadata only; public APIs still enforce display permission"}


def _unit(db: sqlite3.Connection, cid: str, company: str, grade: str, condition: str) -> str:
    unit_id = "|".join((cid, company, grade, condition))
    db.execute("INSERT OR IGNORE INTO priceable_unit VALUES (?, ?, ?, ?, ?)",
               (unit_id, cid, company, grade, condition))
    return unit_id


def resolve(db: sqlite3.Connection, row: dict[str, Any]) -> tuple[str | None, str]:
    title = unicodedata.normalize("NFKC", str(row["title"]))
    if row.get("card_id"):
        cid = str(row["card_id"])
        method = "explicit"
    else:
        if BUNDLE_RE.search(title):
            return None, "unresolved"
        title_languages = {language for language, pattern in LANGUAGE_RE.items()
                           if pattern.search(title)}
        requested_language = str(row["language"]).lower() if row.get("language") else None
        if len(title_languages) > 1 or (requested_language and title_languages
                                        and requested_language not in title_languages):
            return None, "unresolved"
        requested_language = requested_language or next(iter(title_languages), None)
        numbers = {normalize_collector_number(number) for number in NUMBER_RE.findall(title)}
        if len(numbers) != 1:
            return None, "unresolved"
        set_codes = [value[0] for value in db.execute("SELECT DISTINCT set_code FROM card")]
        mentioned_sets = {code for code in set_codes if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", title, re.I)}
        # Marketplace "MA" can mean the artwork rarity. The printed set name
        # is stronger evidence for M2a than that short token.
        if ("MEGAドリーム" in title.upper() or "メガドリーム" in title) and "M2A" in set_codes:
            mentioned_sets = {"M2A"}
        elif "M2A" in mentioned_sets:
            mentioned_sets.discard("MA")
        if not mentioned_sets:
            return None, "unresolved"
        number_marks = ",".join("?" for _ in numbers)
        set_marks = ",".join("?" for _ in mentioned_sets)
        choices = db.execute(
            f"""SELECT card_id, language, variant, name FROM card
                WHERE set_code IN ({set_marks}) AND collector_number IN ({number_marks})
                AND match_eligible=1 AND (? IS NULL OR language=?)""",
            (*sorted(mentioned_sets), *sorted(numbers), requested_language, requested_language),
        ).fetchall()
        if not choices or len({choice["language"] for choice in choices}) != 1:
            return None, "unresolved"
        if len({choice["card_id"].rsplit(":", 1)[0] for choice in choices}) != 1:
            return None, "unresolved"
        lower = title.lower()
        if row.get("variant"):
            variant = str(row["variant"]).lower()
        elif "マスターボール" in title or "masterball" in lower or "master ball" in lower:
            variant = "reverse_masterball"
        elif "モンスターボール" in title or "pokeball" in lower or "poke ball" in lower:
            variant = "reverse_pokeball"
        elif "ミラー" in title or "reverse" in lower:
            reverse = [choice["variant"] for choice in choices
                       if choice["variant"].startswith("reverse")]
            variant = reverse[0] if len(reverse) == 1 else None
        elif "ホロ" in title or "holo" in lower:
            variant = "holo"
        elif len(choices) == 1:
            variant = choices[0]["variant"]
        else:
            variant = None
        selected = [choice for choice in choices if choice["variant"] == variant]
        if len(selected) != 1:
            return None, "unresolved"
        if _compact_identity_text(selected[0]["name"]) not in _compact_identity_text(title):
            return None, "unresolved"
        cid = selected[0]["card_id"]
        method = "exact"
    if not db.execute("SELECT 1 FROM card WHERE card_id=? AND match_eligible=1", (cid,)).fetchone():
        return None, "unresolved"
    grade_match = GRADE_RE.search(title)
    if grade_match and re.match(r"\s*(?:レベル|相当|級)", title[grade_match.end():]):
        grade_match = None
    company = grade_match.group(1).upper() if grade_match else "RAW"
    grade = grade_match.group(2) if grade_match else "raw"
    condition = str(row.get("condition_bucket") or ("graded" if grade_match else "unknown")).lower()
    if company == "RAW" and condition == "graded":
        raise ValueError("raw listing cannot have graded condition")
    return _unit(db, cid, company, grade, condition), method


def import_observations(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"imported": 0, "unresolved": 0}
    for row in rows:
        _required(row, "source", "native_id", "title", "url", "observed_at", "status", "currency", "evidence_ref")
        _policy(db, row["source"])
        observed_at = parse_time(row["observed_at"]).isoformat()
        if row["status"] not in STATUSES:
            raise ValueError(f"invalid status: {row['status']}")
        poll_reason = row.get("poll_reason", "discovery")
        if poll_reason not in {"discovery", "tracking", "panel", "auction_end"}:
            raise ValueError(f"invalid poll reason: {poll_reason}")
        price = row.get("price_minor")
        if price is not None and int(price) < 0:
            raise ValueError("negative price")
        unit_id, method = resolve(db, row)
        existing = db.execute("SELECT unit_id, resolution_method FROM listing WHERE source=? AND native_id=?",
                              (row["source"], row["native_id"])).fetchone()
        if existing and existing["resolution_method"] == "human":
            unit_id, method = existing["unit_id"], "human"
        if existing and existing["unit_id"] and unit_id and existing["unit_id"] != unit_id:
            raise ValueError(f"listing {row['source']}:{row['native_id']} changed priceable unit; review required")
        db.execute(
            """INSERT INTO listing VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, native_id) DO UPDATE SET
              title=excluded.title, url=excluded.url, seller_native_id=excluded.seller_native_id,
              unit_id=COALESCE(excluded.unit_id, listing.unit_id),
              resolution_method=CASE WHEN excluded.unit_id IS NULL THEN listing.resolution_method ELSE excluded.resolution_method END,
              last_seen=CASE WHEN excluded.last_seen > listing.last_seen THEN excluded.last_seen ELSE listing.last_seen END,
              current_status=CASE WHEN excluded.last_seen >= listing.last_seen THEN excluded.current_status ELSE listing.current_status END,
              current_price_minor=CASE WHEN excluded.last_seen >= listing.last_seen THEN excluded.current_price_minor ELSE listing.current_price_minor END""",
            (row["source"], row["native_id"], row["title"], row["url"], row.get("seller_native_id"),
             unit_id, method, observed_at, observed_at, row["status"],
             int(price) if price is not None else None, row["currency"]),
        )
        db.execute("""INSERT OR IGNORE INTO observation
                   (source, native_id, observed_at, title, url, seller_native_id,
                    status, price_minor, currency, evidence_ref, poll_reason,
                    native_created, native_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (row["source"], row["native_id"], observed_at, row["title"], row["url"],
                    row.get("seller_native_id"), row["status"], int(price) if price is not None else None,
                    row["currency"], row["evidence_ref"], poll_reason,
                    str(row["native_created"]) if row.get("native_created") is not None else None,
                    str(row["native_updated"]) if row.get("native_updated") is not None else None))
        if not existing or (existing["unit_id"] is None and unit_id is not None):
            db.execute("""INSERT INTO resolution_record
                (source, native_id, unit_id, method, rule_version, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (row["source"], row["native_id"], unit_id, method, "deterministic-v1", observed_at))
        counts["imported"] += 1
        counts["unresolved"] += unit_id is None
    db.commit()
    return counts


def archive_raw_item(db: sqlite3.Connection, row: dict[str, Any], raw_item: dict[str, Any],
                     endpoint: str) -> None:
    """Keep the exact item payload until its source's retention limit expires."""
    _policy(db, row["source"])
    payload = json.dumps(raw_item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if row["evidence_ref"] != f"mercari-gateway:sha256:{digest}":
        raise ValueError("raw item does not match observation evidence hash")
    db.execute(
        """INSERT OR IGNORE INTO raw_item_blob
           (source, native_id, observed_at, endpoint, sha256, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (row["source"], row["native_id"], row["observed_at"], endpoint, digest, payload),
    )


def override_resolution(db: sqlite3.Connection, source: str, native_id: str, unit_id: str,
                        reviewer: str, reason: str) -> None:
    _required({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    _policy(db, source)
    if not db.execute("SELECT 1 FROM listing WHERE source=? AND native_id=?", (source, native_id)).fetchone():
        raise ValueError("unknown listing")
    if not db.execute("SELECT 1 FROM priceable_unit WHERE unit_id=?", (unit_id,)).fetchone():
        raise ValueError("unknown priceable unit")
    db.execute("UPDATE listing SET unit_id=?, resolution_method='human' WHERE source=? AND native_id=?",
               (unit_id, source, native_id))
    db.execute("""INSERT INTO resolution_record
        (source, native_id, unit_id, method, rule_version, resolved_at, reviewer, reason)
        VALUES (?, ?, ?, 'human', 'manual-v1', ?, ?, ?)""",
        (source, native_id, unit_id, utcnow(), reviewer, reason))
    db.commit()


def import_quotes(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with db:
        for row in rows:
            _required(row, "source", "native_id", "destination", "currency", "components", "quoted_at", "expires_at", "evidence_ref")
            _policy(db, row["source"])
            quoted_at = parse_time(row["quoted_at"]).isoformat()
            expires_at = parse_time(row["expires_at"]).isoformat()
            if expires_at <= quoted_at:
                raise ValueError("quote expires before it was issued")
            components = row["components"]
            if not isinstance(components, dict) or set(components) != COMPONENTS:
                raise ValueError("quote requires every landed-cost component; use explicit zero when not applicable")
            if any(type(value) is not int or value < 0 for value in components.values()):
                raise ValueError("quote components must be nonnegative minor currency units")
            total = sum(components.values())
            values = (row["source"], row["native_id"], row["destination"], row["currency"],
                      json.dumps(components, sort_keys=True), total, quoted_at, expires_at,
                      row["evidence_ref"], json.dumps(row.get("assumptions", {}), sort_keys=True))
            existing = db.execute(
                """SELECT source,native_id,destination,currency,components_json,total_minor,
                quoted_at,expires_at,evidence_ref,assumptions_json FROM landed_quote
                WHERE source=? AND native_id=? AND destination=? AND quoted_at=?""",
                (row["source"], row["native_id"], row["destination"], quoted_at)).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise ValueError("quote evidence changed at the same quoted_at timestamp")
                continue
            db.execute("INSERT INTO landed_quote VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            count += 1
    return count


def import_verified_sales(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        _required(row, "source", "native_id", "settled_at", "paid_minor", "currency", "evidence_ref")
        _policy(db, row["source"])
        settled_at = parse_time(row["settled_at"]).isoformat()
        if int(row["paid_minor"]) < 0:
            raise ValueError("negative paid amount")
        db.execute("INSERT OR IGNORE INTO verified_sale VALUES (?, ?, ?, ?, ?, ?)",
                   (row["source"], row["native_id"], settled_at, int(row["paid_minor"]),
                    row["currency"], row["evidence_ref"]))
        count += 1
    db.commit()
    return count


def discover(db: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().split() if term]
    rows = db.execute("SELECT * FROM card WHERE display_allowed=1 ORDER BY set_code, collector_number").fetchall()
    matches = []
    for row in rows:
        text = f"{row['name']} {row['set_code']} {row['collector_number']} {row['language']} {row['variant']}".lower()
        if all(term in text for term in terms):
            matches.append(dict(row))
        if len(matches) >= limit:
            break
    return matches


def discover_intent(db: sqlite3.Connection, query: str, limit: int = 20) -> dict[str, Any]:
    """Conservative structured discovery. An LLM can later produce the same constraints."""
    grade = GRADE_RE.search(query)
    numbered = CARD_RE.search(query)
    language = None
    lower = query.lower()
    if re.search(r"\b(jp|japanese)\b|日版|日文", lower):
        language = "ja"
    elif re.search(r"\b(en|english)\b|英版|英文", lower):
        language = "en"
    if numbered:
        rows = db.execute(
            """SELECT * FROM card WHERE display_allowed=1 AND set_code=? AND collector_number=?
            AND (? IS NULL OR language=?) ORDER BY language, variant LIMIT ?""",
            (numbered.group(1).upper(), normalize_collector_number(numbered.group(2)), language, language, limit),
        ).fetchall()
        reason = "exact set code and collector number"
    else:
        cleaned = GRADE_RE.sub(" ", query)
        cleaned = re.sub(r"\b(jp|japanese|en|english)\b|日版|日文|英版|英文", " ", cleaned, flags=re.I)
        terms = [part for part in cleaned.lower().split() if part]
        rows = [row for row in db.execute("SELECT * FROM card WHERE display_allowed=1 ORDER BY set_code, collector_number")
                if (not language or row["language"] == language)
                and all(term in f"{row['name']} {row['set_code']} {row['collector_number']}".lower()
                        for term in terms)][:limit]
        reason = "name and metadata tokens"
    candidates = []
    for row in rows:
        units = units_for_card(db, row["card_id"])
        if grade:
            units = [unit for unit in units if unit["grade_company"] == grade.group(1).upper()
                     and unit["grade_value"] == grade.group(2)]
        candidates.append({"card": dict(row), "matching_units": units, "match_reason": reason})
    return {"query": query, "constraints": {"language": language,
            "set_code": numbered.group(1).upper() if numbered else None,
            "collector_number": numbered.group(2) if numbered else None,
            "grade_company": grade.group(1).upper() if grade else None,
            "grade_value": grade.group(2) if grade else None},
            "candidates": candidates, "abstained": not bool(candidates)}


def _displayable(db: sqlite3.Connection, source: str) -> bool:
    try:
        _policy(db, source, display=True)
        return True
    except ValueError:
        return False


def _require_card_display(db: sqlite3.Connection, cid: str) -> None:
    card = db.execute("SELECT display_allowed FROM card WHERE card_id=?", (cid,)).fetchone()
    if not card:
        raise ValueError("unknown card")
    if not card["display_allowed"]:
        raise ValueError("catalog source is not approved for display")


def units_for_card(db: sqlite3.Connection, card: str) -> list[dict[str, Any]]:
    _require_card_display(db, card)
    return [dict(row) for row in db.execute(
        "SELECT * FROM priceable_unit WHERE card_id=? ORDER BY grade_company, grade_value, condition_bucket",
        (card,),
    ).fetchall()]


def offers(db: sqlite3.Connection, card: str, destination: str | None = None,
           now: str | None = None, unit_id: str | None = None) -> list[dict[str, Any]]:
    _require_card_display(db, card)
    now = parse_time(now or utcnow()).isoformat()
    rows = db.execute(
        """SELECT l.*, u.grade_company, u.grade_value, u.condition_bucket
        FROM listing l JOIN priceable_unit u ON u.unit_id=l.unit_id
        WHERE u.card_id=? AND (? IS NULL OR l.unit_id=?)
        ORDER BY l.last_seen DESC""", (card, unit_id, unit_id)
    ).fetchall()
    result = []
    for row in rows:
        if not _displayable(db, row["source"]):
            continue
        snapshot = db.execute(
            """SELECT title, url, seller_native_id, status, price_minor, currency, observed_at FROM observation
            WHERE source=? AND native_id=? AND observed_at<=?
            ORDER BY observed_at DESC LIMIT 1""",
            (row["source"], row["native_id"], now),
        ).fetchone()
        if not snapshot or snapshot["status"] != "on_sale":
            continue
        policy = _policy(db, row["source"], display=True)
        if parse_time(snapshot["observed_at"]) < parse_time(now) - timedelta(hours=policy["listing_ttl_hours"]):
            continue
        item = dict(row)
        item["title"] = snapshot["title"]
        item["url"] = snapshot["url"]
        item["seller_native_id"] = snapshot["seller_native_id"]
        item["current_status"] = snapshot["status"]
        item["current_price_minor"] = snapshot["price_minor"]
        item["currency"] = snapshot["currency"]
        item["last_seen"] = snapshot["observed_at"]
        item["quote"] = None
        if destination:
            quote = db.execute(
                """SELECT * FROM landed_quote WHERE source=? AND native_id=? AND destination=?
                AND expires_at>? AND quoted_at<=? AND quoted_at>=?
                ORDER BY quoted_at DESC LIMIT 1""",
                (row["source"], row["native_id"], destination, now, now, snapshot["observed_at"]),
            ).fetchone()
            if quote:
                item["quote"] = dict(quote)
                item["quote"]["components"] = json.loads(item["quote"].pop("components_json"))
                item["quote"]["assumptions"] = json.loads(item["quote"].pop("assumptions_json"))
        result.append(item)
    sources = {item["source"] for item in result}
    if len(sources) > 1 and any(not _policy(db, source)["cross_source_use_allowed"] for source in sources):
        raise ValueError("cross-source offer display or comparison lacks permission")
    return result


def seller_overlap(db: sqlite3.Connection, source: str, unit_ids: list[str],
                   now: str | None = None) -> dict[str, Any]:
    policy = _policy(db, source, display=True)
    if not policy["seller_analytics_allowed"]:
        raise ValueError("seller analytics lacks permission")
    if not unit_ids:
        raise ValueError("at least one priceable unit is required")
    for unit_id in set(unit_ids):
        unit = db.execute("SELECT card_id FROM priceable_unit WHERE unit_id=?", (unit_id,)).fetchone()
        if not unit:
            raise ValueError("unknown priceable unit")
        _require_card_display(db, unit["card_id"])
    instant = parse_time(now or utcnow())
    placeholders = ",".join("?" for _ in unit_ids)
    rows = db.execute(
        f"""SELECT seller_native_id, unit_id, native_id FROM listing
        WHERE source=? AND seller_native_id IS NOT NULL
        AND unit_id IN ({placeholders})""", (source, *unit_ids)
    ).fetchall()
    sellers: dict[str, set[str]] = {}
    for row in rows:
        snapshot = db.execute(
            """SELECT status, observed_at FROM observation WHERE source=? AND native_id=?
            AND observed_at<=? ORDER BY observed_at DESC LIMIT 1""",
            (source, row["native_id"], instant.isoformat()),
        ).fetchone()
        if (snapshot and snapshot["status"] == "on_sale"
                and parse_time(snapshot["observed_at"]) >= instant - timedelta(hours=policy["listing_ttl_hours"])):
            sellers.setdefault(row["seller_native_id"], set()).add(row["unit_id"])
    ranking = [{"seller_native_id": seller, "matched_units": sorted(units),
                "coverage": len(units) / len(set(unit_ids))}
               for seller, units in sellers.items()]
    ranking.sort(key=lambda item: (-item["coverage"], item["seller_native_id"]))
    return {"source": source, "requested_units": unit_ids, "sellers": ranking,
            "meaning": "inventory overlap only; not a trust or fulfilment score"}


def recommend(db: sqlite3.Connection, unit_id: str, destination: str, now: str | None = None) -> dict[str, Any]:
    unit = db.execute("SELECT * FROM priceable_unit WHERE unit_id=?", (unit_id,)).fetchone()
    if not unit:
        raise ValueError("unknown priceable unit")
    _require_card_display(db, unit["card_id"])
    active = offers(db, unit["card_id"], destination, now, unit_id)
    quoted = [item for item in active if item["quote"] is not None]
    currencies = {item["quote"]["currency"] for item in quoted}
    if len(currencies) > 1:
        return {"unit_id": unit_id, "destination": destination, "recommendation": None,
                "recommendation_type": "none",
                "reason": "quotes have different destination currencies", "offers": active}
    quoted.sort(key=lambda item: (item["quote"]["total_minor"], item["last_seen"]))
    return {"unit_id": unit_id, "destination": destination,
            "recommendation": quoted[0] if quoted else None,
            "recommendation_type": "price_only" if quoted else "none",
            "reason": "lowest current complete landed quote" if quoted else "no current landed quote",
            "offers": active}


def index_for_unit(db: sqlite3.Connection, unit_id: str, date: str) -> dict[str, Any]:
    unit = db.execute("SELECT card_id FROM priceable_unit WHERE unit_id=?", (unit_id,)).fetchone()
    if not unit:
        raise ValueError("unknown priceable unit")
    _require_card_display(db, unit["card_id"])
    start = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    by_currency: dict[str, list[int]] = {}
    transition_prices: dict[str, list[int]] = {}
    actual: dict[str, list[int]] = {}
    listing_ids = db.execute("SELECT source, native_id FROM listing WHERE unit_id=?", (unit_id,)).fetchall()
    visible_sources = {item["source"] for item in listing_ids if _displayable(db, item["source"])}
    if len(visible_sources) > 1 and any(not _policy(db, source)["cross_source_use_allowed"]
                                        for source in visible_sources):
        raise ValueError("cross-source index lacks permission")
    for listing in listing_ids:
        if not _displayable(db, listing["source"]):
            continue
        history = db.execute("SELECT * FROM observation WHERE source=? AND native_id=? ORDER BY observed_at",
                             (listing["source"], listing["native_id"])).fetchall()
        eligible = [row for row in history if parse_time(row["observed_at"]) < end]
        if eligible:
            latest = eligible[-1]
            policy = _policy(db, listing["source"], display=True)
            if (latest["status"] == "on_sale" and latest["price_minor"] is not None
                    and parse_time(latest["observed_at"]) >= end - timedelta(hours=policy["listing_ttl_hours"])):
                by_currency.setdefault(latest["currency"], []).append(latest["price_minor"])
        for offset, (prev, current) in enumerate(zip(history, history[1:])):
            if prev["status"] == "on_sale" and current["status"] in ("trading", "sold_out"):
                timestamp = parse_time(current["observed_at"])
                reverted = any(later["status"] == "on_sale" for later in history[offset + 2:])
                if start <= timestamp < end and prev["price_minor"] is not None and not reverted:
                    transition_prices.setdefault(prev["currency"], []).append(prev["price_minor"])
        sales = db.execute(
            """SELECT paid_minor, currency FROM verified_sale
            WHERE source=? AND native_id=? AND settled_at>=? AND settled_at<?""",
            (listing["source"], listing["native_id"], start.isoformat(), end.isoformat()),
        ).fetchall()
        for row in sales:
            actual.setdefault(row["currency"], []).append(row["paid_minor"])
    series = {}
    for name, groups in (("ask", by_currency), ("last_list_at_transition", transition_prices),
                         ("verified_paid", actual)):
        series[name] = {currency: {"median_minor": median(values), "n": len(values)}
                        for currency, values in groups.items()}
    return {"unit_id": unit_id, "date": date, "series": series,
            "definitions": {"ask": "current active listing prices",
                            "last_list_at_transition": "last observed list price before trading or sold_out; not a paid price",
                            "verified_paid": "payment or settlement evidence supplied by an authorized source"}}


def purge_expired(db: sqlite3.Connection, now: str | None = None) -> dict[str, int]:
    instant = parse_time(now or utcnow())
    removed = {"observation": 0, "raw_item_blob": 0, "verified_sale": 0, "landed_quote": 0,
               "offer_visual_review": 0, "offer_media_snapshot": 0,
               "resolution_record": 0, "listing": 0}
    for policy in db.execute("SELECT * FROM source_policy").fetchall():
        cutoff = (instant - timedelta(days=policy["retention_days"])).isoformat()
        for table in ("offer_visual_review", "offer_media_snapshot"):
            cursor = db.execute(f"DELETE FROM {table} WHERE source=? AND observed_at<?",
                                (policy["source"], cutoff))
            removed[table] += cursor.rowcount
        for table, column in (("observation", "observed_at"), ("raw_item_blob", "observed_at"),
                              ("verified_sale", "settled_at"),
                              ("landed_quote", "quoted_at")):
            cursor = db.execute(f"DELETE FROM {table} WHERE source=? AND {column}<?", (policy["source"], cutoff))
            removed[table] += cursor.rowcount
        eligible = """l.source=? AND l.last_seen<?
            AND NOT EXISTS (SELECT 1 FROM observation o
                            WHERE o.source=l.source AND o.native_id=l.native_id)
            AND NOT EXISTS (SELECT 1 FROM landed_quote q
                            WHERE q.source=l.source AND q.native_id=l.native_id)
            AND NOT EXISTS (SELECT 1 FROM verified_sale s
                            WHERE s.source=l.source AND s.native_id=l.native_id)"""
        cursor = db.execute(
            f"""DELETE FROM resolution_record WHERE source=? AND native_id IN
                (SELECT l.native_id FROM listing l WHERE {eligible})""",
            (policy["source"], policy["source"], cutoff),
        )
        removed["resolution_record"] += cursor.rowcount
        cursor = db.execute(
            f"""DELETE FROM listing WHERE source=? AND last_seen<?
                AND NOT EXISTS (SELECT 1 FROM observation o
                                WHERE o.source=listing.source AND o.native_id=listing.native_id)
                AND NOT EXISTS (SELECT 1 FROM landed_quote q
                                WHERE q.source=listing.source AND q.native_id=listing.native_id)
                AND NOT EXISTS (SELECT 1 FROM verified_sale s
                                WHERE s.source=listing.source AND s.native_id=listing.native_id)""",
            (policy["source"], cutoff),
        )
        removed["listing"] += cursor.rowcount
    db.commit()
    return removed
