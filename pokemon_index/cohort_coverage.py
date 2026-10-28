"""Offline exact-printing coverage report. Never fetches images or listings.

Consumes a hash-bound export of the catalog primary-image and source-scan decisions. A reference is
not image delivery, an exact physical-card match, or permission to ingest an
offer. Missing offer input stays unknown rather than becoming zero inventory.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .coverage_snapshot import IDENTITY_FIELDS, load_snapshot, strict_json, validate_catalog


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def pointer(value, path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("exact evidence JSON pointer required")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def evidence_check(entry, workspace):
    if not entry.get("selection_evidence"):
        raise ValueError("selection evidence required")
    receipts = []
    for evidence in entry["selection_evidence"]:
        name = evidence["path"]
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("evidence path must stay within workspace")
        source = (workspace / name).resolve(strict=True)
        if not source.is_relative_to(workspace):
            raise ValueError("evidence path escapes workspace")
        with source.open('rb') as stream:
            body = stream.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise ValueError('selection evidence size limit')
        actual_hash = hashlib.sha256(body).hexdigest()
        if actual_hash != evidence["sha256"]:
            raise ValueError("selection evidence checksum changed")
        actual = pointer(strict_json(body), evidence["json_pointer"])
        if actual != evidence["expected_value"]:
            raise ValueError("selection evidence assertion changed")
        receipts.append({k: evidence[k] for k in ("path", "sha256", "json_pointer")})
    return receipts


def check_identity(db, entry):
    row = db.execute("SELECT * FROM card WHERE card_id=?", (entry["card_id"],)).fetchone()
    if row is None:
        raise ValueError("selected exact printing is missing from pinned catalog")
    for field in IDENTITY_FIELDS:
        if row[field] != entry["identity"][field]:
            raise ValueError("selected exact printing identity changed: " + field)
    if hashlib.sha256(row["provenance"].encode()).hexdigest() != entry["catalog_provenance_sha256"]:
        raise ValueError("selected printing provenance changed")
    return dict(row)


def card_report(db, entry, primary_reader, scan_reader):
    row = check_identity(db, entry)
    primary = primary_reader(db, entry["card_id"])
    scan = scan_reader(db, entry["card_id"])
    primary_fields = ("status", "basis", "event_id", "image_sha256", "current_endpoint", "source_ref", "reason")
    primary_out = {key: primary.get(key) for key in primary_fields}
    scan_fields = ("status", "evidence_basis", "source_scan_event_id", "image_sha256", "current_endpoint", "inspection_tier")
    gaps = []
    if primary.get("status") != "current" or primary.get("current_endpoint") is not True:
        gaps.append("primary_image_" + str(primary.get("status", "unknown")))
    if scan.get("status") != "current_source_scan_evidence":
        gaps.append("source_scan_" + str(scan.get("status", "unknown")))
    gaps.extend(["image_delivery_not_audited", "actual_listing_evidence_not_supplied", "actual_seller_photos_not_supplied", "trusted_offer_target_not_established"])
    return {
        "card_id": entry["card_id"], "identity": entry["identity"],
        "catalog_status": "exact_record_present", "catalog_provenance_sha256": entry["catalog_provenance_sha256"],
        "primary_image": primary_out, "source_scan": {key: scan.get(key) for key in scan_fields},
        "catalog_gates": {"match_eligible": bool(row["match_eligible"]), "display_allowed": bool(row["display_allowed"])},
        "offers": {"input_status": "not_supplied", "active_listing_count": None, "distinct_seller_count": None,
                   "comparable_offer_count": None, "listings_with_actual_copy_photos": None},
        "gaps": gaps,
        "claims": {"image_delivery_verified": False, "exact_variant_visually_verified": False,
                   "physical_copy_verified": False, "certificate_verified": False,
                   "approved_offer_target": False, "ready_for_live_comparison": False},
    }


def next_wave(db, path):
    if path is None:
        return {"input_status": "not_supplied", "entries": []}
    rows = [strict_json(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [row["card_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate next-wave exact printing")
    out = []
    for row in rows:
        # Keep the original unresolved states; an audit cannot promote them.
        if row.get("selection_status") != "provisional_coverage_sample" or row.get("search_query_status") != "not_ready_marketplace_alias_required" or row.get("offer_matching_status") != "photo_review_required":
            raise ValueError("unreviewed next-wave status transition")
        entry = {"card_id": row["card_id"], "identity": {field: row[field] for field in IDENTITY_FIELDS}, "catalog_provenance_sha256": row["catalog_provenance_sha256"]}
        check_identity(db, entry)
        out.append({**entry, "selection_status": row["selection_status"], "search_query_status": row["search_query_status"],
                    "offer_matching_status": row["offer_matching_status"], "marketplace": row.get("marketplace"),
                    "ready_for_live_comparison": False})
    return {"input_status": "retained_provisional_samples", "sha256": sha256(path), "entries": out,
            "scope": "Retained coverage samples; not a popularity ranking, approved search aliases, or authorized inventory."}


def generate(*, database, expected_database_sha256, cohort_path, workspace, primary_reader, scan_reader, next_wave_path=None):
    database = Path(database).resolve(strict=True)
    workspace = Path(workspace).resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_database_sha256) or sha256(database) != expected_database_sha256:
        raise ValueError("catalog checksum mismatch")
    cohort = strict_json(Path(cohort_path).read_text())
    if cohort.get("schema") != "pot.focused-card-cohort.v1" or not cohort.get("entries"):
        raise ValueError("nonempty versioned exact-printing cohort required")
    ids = [entry["card_id"] for entry in cohort["entries"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate cohort printing")
    selected_evidence = {entry["card_id"]: evidence_check(entry, workspace) for entry in cohort["entries"]}
    db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        rows = [card_report(db, entry, primary_reader, scan_reader) for entry in cohort["entries"]]
        waves = next_wave(db, Path(next_wave_path) if next_wave_path else None)
        catalog = {"sha256": expected_database_sha256,
                   "records": db.execute("SELECT count(*) FROM card").fetchone()[0],
                   "by_language": dict(db.execute("SELECT language,count(*) FROM card GROUP BY language"))}
    finally:
        db.close()
    if sha256(database) != expected_database_sha256:
        raise ValueError("catalog changed during audit")
    summary = {"cohort_cards": len(rows), "primary_images_current": sum(r["primary_image"]["status"] == "current" and r["primary_image"]["current_endpoint"] is True for r in rows),
               "missing_primary_images": sum(r["primary_image"]["status"] == "missing" for r in rows),
               "source_scans_current": sum(r["source_scan"]["status"] == "current_source_scan_evidence" for r in rows),
               "identity_held": sum(r["source_scan"]["status"] == "identity_hold" or r["primary_image"]["status"] == "held" for r in rows),
               "live_offer_evidence": "not_supplied", "seller_photo_evidence": "not_supplied", "ready_for_live_comparison": 0,
               "gap_counts": dict(Counter(g for r in rows for g in r["gaps"]))}
    return {"schema": "pot.focused-card-coverage.v1", "catalog": catalog,
            "cohort": {"id": cohort["id"], "basis": cohort["basis"], "selection_evidence": selected_evidence,
                       "scope": "Acceptance priorities from retained signed-in/API tests; no demand or popularity claim."},
            "rows": rows, "summary": summary, "next_wave": waves,
            "safeguards": {"catalog_read_only": True, "network_calls": 0, "marketplace_calls": 0, "orders": 0, "payments": 0,
                           "permissions_added": 0, "inventory_inferred_from_missing_input": False},
            "next_actions": ["Audit cached image delivery for each exact primary reference.",
                             "Review trusted revision-bound offer target evidence before joining seller listings.",
                             "After separate source approval, collect current exact-listing inventory and authorized actual-copy photos.",
                             "Keep native-currency product prices and later destination quotes as separate comparison layers."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("database", "cohort", "workspace", "snapshot", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-database-sha256", required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--next-wave", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve prior evidence")
    snapshot, decisions = load_snapshot(args.snapshot, args.expected_snapshot_sha256, args.expected_database_sha256)
    with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        validate_catalog(db, snapshot, decisions)
    result = generate(database=args.database, expected_database_sha256=args.expected_database_sha256,
                      cohort_path=args.cohort, workspace=args.workspace,
                      primary_reader=lambda db, cid: decisions[cid]["primary_image"],
                      scan_reader=lambda db, cid: decisions[cid]["source_scan"], next_wave_path=args.next_wave)
    result["reader_snapshot"] = {"sha256": args.expected_snapshot_sha256, "producer": snapshot["producer"],
        "native_reader_decisions_revalidated": False,
        "scope": "Supplied hash-bound decisions, not independent proof of native reader correctness, image delivery or source rights"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
