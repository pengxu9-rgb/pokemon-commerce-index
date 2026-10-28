"""Offline audit of native primary-image decisions and recorded beta copy evidence.

Never fetches images, changes catalog data, or equates a copy receipt with a
currently loadable browser image. Outputs a reconciliation work queue.
"""
import argparse
import collections
from contextlib import closing
import csv
import hashlib
import io
import json
import re
import sqlite3
from pathlib import Path

from .coverage_snapshot import load_snapshot, strict_json, validate_catalog


def copy_scope(source_bucket, destination_bucket, namespace):
    if (not all(isinstance(x, str) and re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,220}[a-z0-9]", x) for x in (source_bucket, destination_bucket))
            or source_bucket == destination_bucket or not isinstance(namespace, str)
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}", namespace)):
        raise ValueError("explicit valid copy scope required")
    return dict(prefix=namespace + "/catalog-media/", source="gs://" + source_bucket + "/", destination="gs://" + destination_bucket + "/")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def add_blob(blobs, name, size, receipt, scope):
    match = re.fullmatch(re.escape(scope["prefix"]) + r"([0-9a-f]{64})\.raw", name or "")
    if not match or not re.fullmatch(r"[1-9][0-9]*", str(size)):
        raise ValueError("invalid recorded blob")
    key = match[1]
    value = {"bytes": int(size), "receipt": receipt}
    if key in blobs:
        raise ValueError("duplicate recorded blob")
    blobs[key] = value


def copy_inventory(csv_path, generations_path, *, scope, input_hashes=None):
    blobs = {}
    def read(path):
        with path.open('rb') as stream:
            body = stream.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise ValueError('copy receipt size limit')
        if input_hashes is not None:
            input_hashes[str(path)] = hashlib.sha256(body).hexdigest()
        return body.decode('utf8')
    with io.StringIO(read(csv_path), newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("Result") != "OK":
                raise ValueError("non-successful copy receipt")
            destination = row.get("Destination", "")
            if not destination.startswith(scope["destination"]):
                raise ValueError("wrong destination bucket")
            source = row.get("Source", "")
            expected_source = scope["source"] + destination[len(scope["destination"]):] + "#"
            if not source.startswith(expected_source) or not re.fullmatch(r"[1-9][0-9]*", source[len(expected_source):]):
                raise ValueError("source generation or source/destination binding differs")
            if row.get("Source Size") != row.get("Bytes Transferred"):
                raise ValueError("incomplete copy receipt")
            add_blob(blobs, destination[len(scope["destination"]):], row["Source Size"], "copy_csv", scope)
    with io.StringIO(read(generations_path)) as stream:
        for line in stream:
            row = strict_json(line)
            if not all(re.fullmatch(r"[1-9][0-9]*", row.get(key, "")) for key in ("source_generation", "destination_generation")):
                raise ValueError("invalid generation receipt")
            add_blob(blobs, row.get("name"), row.get("size"), "generation_jsonl", scope)
    return blobs


def validate_copy_summary(verified, blobs, *, scope):
    if (verified.get("schema") != "pot.beta-media-copy.v1"
            or verified.get("source_bucket") != scope["source"][len("gs://"):].rstrip("/")
            or verified.get("destination_bucket") != scope["destination"][len("gs://"):].rstrip("/")
            or verified.get("source_generation_bound") is not True
            or verified.get("destination_create_only") is not True
            or verified.get("unexpected_destination_objects") != 0
            or verified.get("errors") != []
            or verified.get("passed") is not True or verified.get("objects") != len(blobs)
            or verified.get("matched") != len(blobs)
            or verified.get("bytes") != sum(x["bytes"] for x in blobs.values())):
        raise ValueError("copy summary does not reconcile with detailed receipts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path, help="reviewed native primary/scan decision export")
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--source-bucket", required=True)
    parser.add_argument("--destination-bucket", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--copy-csv", required=True, type=Path)
    parser.add_argument("--copy-generations", required=True, type=Path)
    parser.add_argument("--copy-verification", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    scope = copy_scope(args.source_bucket, args.destination_bucket, args.namespace)
    input_hashes = {}
    blobs = copy_inventory(args.copy_csv, args.copy_generations, scope=scope, input_hashes=input_hashes)
    with args.copy_verification.open('rb') as stream:
        summary_bytes = stream.read(1024 * 1024 + 1)
    if len(summary_bytes) > 1024 * 1024:
        raise ValueError('copy summary size limit')
    verified = strict_json(summary_bytes)
    input_hashes[str(args.copy_verification)] = hashlib.sha256(summary_bytes).hexdigest()
    validate_copy_summary(verified, blobs, scope=scope)
    db_path = args.database.resolve()
    initial_hash = digest(db_path)
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        snapshot, decisions = load_snapshot(args.snapshot, args.expected_snapshot_sha256, initial_hash)
        validate_catalog(db, snapshot, decisions)
        args.output.mkdir(parents=True, exist_ok=False)
        counts, by_language = collections.Counter(), {}
        referenced_blobs = set()
        with (args.output / "image-work-queue.jsonl").open("w") as queue:
            for card in db.execute("SELECT card_id,language,set_code,collector_number,variant,name FROM card ORDER BY card_id"):
                image = decisions[card["card_id"]]["primary_image"]
                current = image["status"] == "current"
                recorded = current and image.get("image_sha256") in blobs
                category = "current_primary_recorded_copy" if recorded else "current_primary_copy_unrecorded" if current else image["status"]
                counts[category] += 1
                by_language.setdefault(card["language"], collections.Counter())[category] += 1
                if recorded:
                    referenced_blobs.add(image["image_sha256"])
                else:
                    row = dict(card)
                    row.update(primary_status=image["status"], reason=image.get("reason"), image_sha256=image.get("image_sha256"),
                        action="reconcile_copy_evidence" if current else "find_supported_reference" if image["status"] == "missing" else "review_existing_identity_and_image_evidence")
                    queue.write(json.dumps(row, ensure_ascii=False) + "\n")
    if digest(db_path) != initial_hash:
        raise ValueError("catalog changed during read-only audit")
    result = {"schema": "pot.offline-reference-image-inventory.v1", "scope": "Supplied hash-bound native-reader decisions joined to historical copy receipts; producer decision correctness, current cloud bytes, browser loading and rights are not independently verified",
        "catalog_records": sum(counts.values()), "record_counts": dict(counts), "by_language": by_language,
        "recorded_media_blobs": len(blobs), "primary_image_hashes_with_recorded_copy": len(referenced_blobs),
        "recorded_blobs_not_selected_by_current_primary": len(set(blobs) - referenced_blobs), "browser_image_load_coverage": None,
        "actual_seller_photo_coverage": None, "live_calls": 0, "catalog_writes": 0,
        "input_sha256": {str(args.database): initial_hash, str(args.snapshot): args.expected_snapshot_sha256, **input_hashes},
        "producer": snapshot["producer"], "copy_scope": scope, "source_access_authorized": False, "native_reader_decisions_revalidated": False, "code_sha256": digest(Path(__file__))}
    (args.output / "image-inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"records": result["catalog_records"], "counts": result["record_counts"], "recorded_blobs": len(blobs)}))


if __name__ == "__main__":
    main()
