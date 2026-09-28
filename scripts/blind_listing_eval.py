"""Freeze a matcher-blind listing sample and evaluate independent human gold.

All files produced here contain private marketplace data except the aggregate
evaluation report. Keep the preparation directory outside the source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import subprocess
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from pokemon_index.core import connect, normalize_collector_number, resolve

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pokemon.blind-listing-eval.v1"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("JSONL rows must be objects")
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            for row in rows), encoding="utf-8")


def _frame_item(row: dict[str, Any]) -> dict[str, Any]:
    for field in ("source", "native_id", "title", "url", "observed_at"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"frame item requires {field}")
    if not row["url"].startswith("https://"):
        raise ValueError("listing URL must use HTTPS")
    try:
        observed = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid observed_at") from exc
    if observed.tzinfo is None:
        raise ValueError("observed_at must carry a timezone")
    images = row.get("image_urls", [])
    if not isinstance(images, list) or any(not isinstance(url, str) or
                                            not url.startswith("https://") for url in images):
        raise ValueError("image_urls must be HTTPS URLs")
    image_hashes = row.get("image_sha256", [])
    if (not isinstance(image_hashes, list) or
            (image_hashes and len(image_hashes) != len(images)) or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in image_hashes)):
        raise ValueError("image_sha256 must align with image_urls and contain SHA-256 hashes")
    if any(key in row for key in ("card_id", "unit_id", "proposed_set", "proposed_variant",
                                  "matcher_prediction", "gold_label")):
        raise ValueError("sampling frame must not contain matcher predictions or labels")
    key = f"{row['source']}:{row['native_id']}"
    if row.get("item_key", key) != key:
        raise ValueError("item_key must equal source:native_id")
    return {"item_key": key, "source": row["source"], "native_id": row["native_id"],
            "title": row["title"], "url": row["url"],
            "observed_at": row["observed_at"],
            "description": str(row.get("description") or ""),
            "image_urls": images, "image_sha256": image_hashes,
            "stratum": str(row.get("stratum") or "unspecified")}


def prepare(frame: Path, catalog_db: Path, catalog_manifest: Path, out_dir: Path,
            sample_size: int, seed: int, cohort: str, authorization_ref: str,
            frame_ref: str) -> dict[str, Any]:
    if cohort not in {"representative", "challenge"}:
        raise ValueError("cohort must be representative or challenge")
    if not authorization_ref.strip() or not frame_ref.strip():
        raise ValueError("authorization and sampling-frame references are required")
    if out_dir.exists():
        raise FileExistsError(f"sample output already exists: {out_dir}")
    if out_dir.resolve().is_relative_to(ROOT):
        raise ValueError("private benchmark sample must be stored outside the repository")
    if not catalog_db.is_file() or not catalog_manifest.is_file():
        raise ValueError("frozen catalog database and build manifest are required")
    rows = [_frame_item(row) for row in read_jsonl(frame)]
    if not rows or len({row["item_key"] for row in rows}) != len(rows):
        raise ValueError("sampling frame must be nonempty with one snapshot per listing")
    if sample_size < 1 or sample_size > len(rows):
        raise ValueError("sample size must be between 1 and frame size")
    selected = random.Random(seed).sample(rows, sample_size)
    selected.sort(key=lambda row: row["item_key"])

    # A read-only source is copied to memory because resolve() creates unit rows.
    source = sqlite3.connect(f"file:{catalog_db.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    db = connect(":memory:")
    try:
        expected = json.loads(catalog_manifest.read_text(encoding="utf-8")).get("expected", {})
        for key, sql in (("printings", "SELECT COUNT(*) FROM card"),
                         ("match_eligible", "SELECT COUNT(*) FROM card WHERE match_eligible=1")):
            if expected.get(key) != source.execute(sql).fetchone()[0]:
                raise ValueError(f"catalog snapshot differs from build manifest: {key}")
        if source.execute("SELECT COUNT(*) FROM listing").fetchone()[0] or source.execute(
                "SELECT COUNT(*) FROM observation").fetchone()[0]:
            raise ValueError("benchmark catalog must not contain marketplace listings")
        source.backup(db)
        predictions = []
        for row in selected:
            unit, method = resolve(db, {"title": row["title"]})
            predictions.append({"item_key": row["item_key"],
                                "title_sha256": hashlib.sha256(row["title"].encode()).hexdigest(),
                                "unit_id": unit, "method": method})
    finally:
        db.close()
        source.close()

    out_dir.mkdir(parents=True)
    queue = out_dir / "review_queue.jsonl"
    prediction_path = out_dir / "predictions.jsonl"
    write_jsonl(queue, selected)
    write_jsonl(prediction_path, predictions)
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    manifest = {"schema": SCHEMA, "cohort": cohort, "frame_ref": frame_ref,
                "authorization_ref": authorization_ref, "frame_size": len(rows),
                "sample_size": len(selected), "seed": seed,
                "frame_sha256": digest(frame), "catalog_db_sha256": digest(catalog_db),
                "catalog_manifest_sha256": digest(catalog_manifest),
                "matcher_sha256": digest(ROOT / "pokemon_index/core.py"),
                "git_head": git_head, "review_queue_sha256": digest(queue),
                "predictions_sha256": digest(prediction_path),
                "frame_strata": dict(sorted(Counter(row["stratum"] for row in rows).items())),
                "sample_strata": dict(sorted(Counter(row["stratum"] for row in selected).items()))}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
                                                  indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"sample_size": len(selected), "frame_size": len(rows),
            "cohort": cohort, "output": str(out_dir)}


def _wilson_lower(correct: int, total: int) -> float | None:
    if not total:
        return None
    z = 1.959963984540054
    p = correct / total
    denominator = 1 + z * z / total
    return max(0.0, (p + z * z / (2 * total) -
                     z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)) /
               denominator)


def _gold_fields(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("human_reviewed") is not True:
        raise ValueError("gold row is not human reviewed")
    reviewers = row.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) != 2 or len(set(reviewers)) != 2:
        raise ValueError("gold requires two distinct reviewers")
    evidence = row.get("review_evidence")
    if (not isinstance(evidence, list) or len(evidence) != 2 or
            any(not isinstance(entry, dict) for entry in evidence) or
            {entry.get("reviewer") for entry in evidence} != set(reviewers)):
        raise ValueError("gold requires both independent review records")
    if row.get("adjudicator") in reviewers:
        raise ValueError("adjudicator must be independent")
    single = row.get("single_card")
    if single not in {"yes", "no", "uncertain"}:
        raise ValueError("gold needs explicit single_card status")
    if row.get("language") not in {"ja", "en", "ko", "zh", "unknown"}:
        raise ValueError("gold has invalid language")
    grade_status = row.get("grade_status")
    if grade_status not in {"unknown", "raw", "graded"}:
        raise ValueError("gold needs explicit grade status")
    if single != "yes" and (row.get("proposed_set") or row.get("proposed_number") or
                             row.get("proposed_variant") or grade_status != "unknown"):
        raise ValueError("non-single gold cannot claim one unit")
    if grade_status == "graded" and not (row.get("grade_company") and row.get("grade_value")):
        raise ValueError("graded gold requires company and value")
    if grade_status != "graded" and (row.get("grade_company") or row.get("grade_value")):
        raise ValueError("raw/unknown gold cannot contain grading fields")
    if (row.get("proposed_variant") or grade_status != "unknown") and not row.get("image_seen"):
        raise ValueError("known finish or grading status requires reviewed photo")
    if (row.get("proposed_set") or row.get("proposed_number") or row.get("proposed_variant")
            or grade_status != "unknown") and not row.get("evidence_notes"):
        raise ValueError("known identity, finish or grading status requires evidence notes")
    identity = None
    if (single == "yes" and row.get("language") in {"ja", "en", "ko", "zh"}
            and row.get("proposed_set") and row.get("proposed_number")):
        identity = ":".join((row["language"], row["proposed_set"].upper(),
                             normalize_collector_number(row["proposed_number"])))
    card = identity + ":" + row["proposed_variant"].lower() if identity and row.get(
        "proposed_variant") else None
    grade = (("RAW", "raw") if grade_status == "raw" else
             (str(row["grade_company"]).upper(), str(row["grade_value"]))
             if grade_status == "graded" else None)
    return {"single_card": single, "identity": identity, "card": card,
            "grade": grade, "grade_status": grade_status}


def _metric(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    evaluable = 0
    accepted = 0
    correct = 0
    unverifiable_accepts = 0
    for row in rows:
        gold = row["gold"]
        prediction = row["prediction"]
        known = gold["single_card"] == "no" and field in {"identity", "printing", "joint"}
        known = known or (gold["single_card"] == "yes" and (
            gold["identity"] if field == "identity" else gold["card"] if field == "printing"
            else gold["grade"] if field == "grade" else gold["card"] and gold["grade"]))
        if not known:
            unverifiable_accepts += prediction is not None
            continue
        evaluable += 1
        if prediction is None:
            continue
        accepted += 1
        if gold["single_card"] == "no":
            continue
        if field == "identity":
            matches = prediction["identity"] == gold["identity"]
        elif field == "printing":
            matches = prediction["card"] == gold["card"]
        elif field == "grade":
            matches = prediction["grade"] == gold["grade"]
        else:
            matches = prediction["card"] == gold["card"] and prediction["grade"] == gold["grade"]
        correct += matches
    return {"gold_evaluable": evaluable, "accepted_evaluable": accepted,
            "correct": correct, "incorrect": accepted - correct,
            "accepted_unverifiable": unverifiable_accepts,
            "precision": correct / accepted if accepted else None,
            "precision_wilson_95_lower": _wilson_lower(correct, accepted),
            "accepted_coverage_of_evaluable": accepted / evaluable if evaluable else None}


def evaluate(sample_dir: Path, gold_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unknown blind sample schema")
    queue_path = sample_dir / "review_queue.jsonl"
    predictions_path = sample_dir / "predictions.jsonl"
    if digest(queue_path) != manifest["review_queue_sha256"] or digest(
            predictions_path) != manifest["predictions_sha256"]:
        raise ValueError("frozen queue or predictions changed")
    queue = {row["item_key"]: row for row in read_jsonl(queue_path)}
    predictions = {row["item_key"]: row for row in read_jsonl(predictions_path)}
    if len(queue) != manifest["sample_size"] or len(predictions) != len(queue) or set(queue) != set(predictions):
        raise ValueError("sample keys changed or duplicated")
    gold_rows = read_jsonl(gold_path)
    if len({row.get("item_key") for row in gold_rows}) != len(gold_rows):
        raise ValueError("duplicate gold item key")
    if any(row.get("item_key") not in queue for row in gold_rows):
        raise ValueError("gold item is outside frozen sample")
    compared = []
    for row in gold_rows:
        key = row["item_key"]
        item = queue[key]
        pred = predictions[key]
        if (row.get("source"), row.get("native_id"), row.get("title"), row.get("url")) != (
                item["source"], item["native_id"], item["title"], item["url"]):
            raise ValueError("gold does not match frozen review queue")
        if pred["title_sha256"] != hashlib.sha256(item["title"].encode()).hexdigest():
            raise ValueError("prediction title does not match frozen sample")
        parts = pred["unit_id"].split("|") if pred["unit_id"] else None
        if parts is not None and len(parts) != 4:
            raise ValueError("invalid predicted unit")
        prediction = ({"card": parts[0], "identity": parts[0].rsplit(":", 1)[0],
                       "grade": (parts[1], parts[2])} if parts else None)
        compared.append({"item_key": key, "stratum": item["stratum"],
                         "gold": _gold_fields(row), "prediction": prediction})
    accepted_all = sum(row["unit_id"] is not None for row in predictions.values())
    report = {"schema": SCHEMA, "report_type": "blind sample, independently reviewed fields",
              "cohort": manifest["cohort"], "frame_ref": manifest["frame_ref"],
              "authorization_ref": manifest["authorization_ref"],
              "freeze": {key: manifest[key] for key in ("git_head", "matcher_sha256",
                "catalog_db_sha256", "catalog_manifest_sha256", "frame_sha256", "seed")},
              "frame_size": manifest["frame_size"], "sample_size": manifest["sample_size"],
              "gold_reviewed": len(compared), "gold_pending": len(queue) - len(compared),
              "auto_accepted_all": accepted_all,
              "auto_acceptance_rate": accepted_all / len(queue),
              "non_single_auto_accepted": sum(row["gold"]["single_card"] == "no" and
                                               row["prediction"] is not None for row in compared),
              "unknown_grade_gold": sum(row["gold"]["grade_status"] == "unknown"
                                        for row in compared),
              "metrics": {name: _metric(compared, name) for name in
                          ("identity", "printing", "grade", "joint")},
              "by_stratum": {name: {"reviewed": sum(row["stratum"] == name for row in compared),
                                    "joint": _metric([row for row in compared if row["stratum"] == name],
                                                     "joint")}
                             for name in manifest["sample_strata"]},
              "measurement_complete": len(compared) == len(queue),
              "population_claim_eligible": (manifest["cohort"] == "representative" and
                                            len(compared) == len(queue) and
                                            _metric(compared, "joint")["accepted_evaluable"] >= 300),
              "interpretation": "Sample precision only; no production launch threshold is implied. "
                                "Unknown gold fields are excluded from field precision and counted separately. "
                                "The sampling frame and authorization must be independently verified."}
    details = [{"item_key": row["item_key"], "stratum": row["stratum"],
                "gold": row["gold"], "prediction": row["prediction"]} for row in compared]
    return report, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for flag in ("frame", "catalog-db", "catalog-manifest", "out-dir"):
        prep.add_argument("--" + flag, type=Path, required=True)
    prep.add_argument("--sample-size", type=int, required=True)
    prep.add_argument("--seed", type=int, required=True)
    prep.add_argument("--cohort", choices=("representative", "challenge"), required=True)
    prep.add_argument("--authorization-ref", required=True)
    prep.add_argument("--frame-ref", required=True)
    score = sub.add_parser("evaluate")
    score.add_argument("--sample-dir", type=Path, required=True)
    score.add_argument("--gold", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--details", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.frame, args.catalog_db, args.catalog_manifest, args.out_dir,
                         args.sample_size, args.seed, args.cohort,
                         args.authorization_ref, args.frame_ref)
    else:
        if args.output.exists() or args.details and args.details.exists():
            raise FileExistsError("evaluation output already exists")
        report, details = evaluate(args.sample_dir, args.gold)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.details:
            write_jsonl(args.details, details)
        result = report
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
