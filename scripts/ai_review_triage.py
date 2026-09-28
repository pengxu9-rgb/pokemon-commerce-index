"""Route independent AI listing reviews to consensus, blind audit, or human review.

This script does not call a model or promote an offer into the commerce index.
Model outputs and listing material remain in a private work directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.blind_listing_eval import (SCHEMA as SAMPLE_SCHEMA, _gold_fields,
                                        _wilson_lower, digest, read_jsonl, write_jsonl)
from scripts.review_workbench import LABEL_FIELDS, validate_label

SCHEMA = "pokemon.ai-review-triage.v1"
ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("identity", "printing", "grade")


def listing_sha256(item: dict[str, Any]) -> str:
    payload = {key: item.get(key) for key in ("item_key", "source", "native_id", "title",
                                               "description", "url", "observed_at",
                                               "image_urls", "image_sha256")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _review(row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if row.get("item_key") != item["item_key"]:
        raise ValueError("AI review key does not match listing")
    family = row.get("model_family")
    if not isinstance(family, str) or len(family.strip()) < 2:
        raise ValueError("AI review needs a model family")
    if row.get("listing_sha256") != listing_sha256(item):
        raise ValueError("AI review is not bound to this listing snapshot")
    hashes = item.get("image_sha256", [])
    if row.get("image_sha256") != hashes:
        raise ValueError("AI review image hashes differ from frozen listing")
    confidence = row.get("confidence")
    if not isinstance(confidence, dict) or set(confidence) != set(FIELDS):
        raise ValueError("AI review needs confidence for identity, printing and grade")
    for value in confidence.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
                value) or not 0 <= value <= 1:
            raise ValueError("AI confidence must be finite numbers between 0 and 1")
    label = validate_label(row.get("label"))
    return {"model_family": family.strip(), "confidence": confidence, "label": label}


def _approvable(reviews: list[dict[str, Any]], item: dict[str, Any], minimum: float) -> bool:
    if len(reviews) < 2 or len({row["model_family"] for row in reviews}) != len(reviews):
        return False
    if not item.get("image_sha256") or any(not row["label"]["image_seen"] for row in reviews):
        return False
    first = reviews[0]["label"]
    if (first["single_card"] != "yes" or first["language"] not in {"ja", "en"} or
            not first["set_code"] or not first["number"] or first["variant"] == "unknown" or
            first["grade_status"] == "unknown"):
        return False
    return all(all(row["label"][field] == first[field] for field in LABEL_FIELDS) and
               min(row["confidence"].values()) >= minimum for row in reviews)


def triage(sample_dir: Path, ai_reviews: Path, out_dir: Path, *, min_confidence: float,
           audit_size: int, seed: int, media_ai_rights_ref: str) -> dict[str, Any]:
    if not 0 <= min_confidence <= 1:
        raise ValueError("minimum confidence must be between 0 and 1")
    if not media_ai_rights_ref.strip():
        raise ValueError("media AI rights reference is required")
    if out_dir.exists():
        raise FileExistsError("triage output already exists")
    if out_dir.resolve().is_relative_to(ROOT):
        raise ValueError("private AI review outputs must be outside the repository")
    sample_manifest_path = sample_dir / "manifest.json"
    sample = json.loads(sample_manifest_path.read_text(encoding="utf-8"))
    if sample.get("schema") != SAMPLE_SCHEMA:
        raise ValueError("unknown frozen sample schema")
    queue_path = sample_dir / "review_queue.jsonl"
    if digest(queue_path) != sample["review_queue_sha256"]:
        raise ValueError("frozen listing sample changed")
    items = read_jsonl(queue_path)
    by_key = {row["item_key"]: row for row in items}
    if len(by_key) != sample["sample_size"]:
        raise ValueError("sample has duplicate or missing listing keys")
    reviews_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(ai_reviews):
        key = row.get("item_key")
        if key not in by_key:
            raise ValueError("AI review refers to an item outside the frozen sample")
        reviews_by_key[key].append(_review(row, by_key[key]))
    accepted = []
    escalated = []
    reasons = Counter()
    for item in items:
        key = item["item_key"]
        reviews = reviews_by_key.get(key, [])
        families = [row["model_family"] for row in reviews]
        if len(families) != len(set(families)):
            raise ValueError("duplicate model family for one listing")
        if _approvable(reviews, item, min_confidence):
            label = reviews[0]["label"]
            accepted.append({"item_key": key, "listing_sha256": listing_sha256(item),
                             "label": {field: label[field] for field in LABEL_FIELDS},
                             "model_families": sorted(families),
                             "minimum_confidence": min(min(row["confidence"].values())
                                                       for row in reviews)})
        else:
            escalated.append(item)
            if len(reviews) < 2:
                reasons["missing_independent_review"] += 1
            elif not item.get("image_sha256"):
                reasons["missing_hashed_photo_evidence"] += 1
            elif any(row["label"][field] != reviews[0]["label"][field]
                     for row in reviews[1:] for field in LABEL_FIELDS):
                reasons["ai_disagreement"] += 1
            elif any(min(row["confidence"].values()) < min_confidence for row in reviews):
                reasons["low_confidence"] += 1
            else:
                reasons["incomplete_or_uncertain_identity"] += 1
    if accepted and not 1 <= audit_size <= len(accepted):
        raise ValueError("audit size must sample at least one and no more than AI approvals")
    if not accepted and audit_size != 0:
        raise ValueError("no AI approvals are available to audit")
    audit_keys = set(random.Random(seed).sample(sorted(row["item_key"] for row in accepted),
                                               audit_size))
    escalated_keys = {item["item_key"] for item in escalated}
    human_queue = [item for item in items if item["item_key"] in escalated_keys | audit_keys]
    out_dir.mkdir(parents=True)
    write_jsonl(out_dir / "ai_consensus.jsonl", accepted)
    write_jsonl(out_dir / "human_queue.jsonl", human_queue)
    triage_manifest = {"schema": SCHEMA, "sample_manifest_sha256": digest(sample_manifest_path),
                       "sample_queue_sha256": digest(queue_path),
                       "ai_reviews_sha256": digest(ai_reviews),
                       "ai_consensus_sha256": digest(out_dir / "ai_consensus.jsonl"),
                       "human_queue_sha256": digest(out_dir / "human_queue.jsonl"),
                       "media_ai_rights_ref": media_ai_rights_ref,
                       "minimum_confidence": min_confidence,
                       "audit_seed": seed, "audit_item_keys": sorted(audit_keys),
                       "ai_approved_pending_audit": len(accepted),
                       "human_escalation": len(escalated),
                       "human_audit": len(audit_keys),
                       "escalation_reasons": dict(sorted(reasons.items()))}
    (out_dir / "manifest.json").write_text(json.dumps(triage_manifest, ensure_ascii=False,
                                                  sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {key: triage_manifest[key] for key in ("ai_approved_pending_audit", "human_escalation",
                                                  "human_audit", "escalation_reasons")}


def audit(sample_dir: Path, triage_dir: Path, gold_path: Path) -> dict[str, Any]:
    manifest = json.loads((triage_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unknown AI triage schema")
    if digest(sample_dir / "manifest.json") != manifest["sample_manifest_sha256"] or digest(
            sample_dir / "review_queue.jsonl") != manifest["sample_queue_sha256"]:
        raise ValueError("frozen sample changed")
    if digest(triage_dir / "ai_consensus.jsonl") != manifest["ai_consensus_sha256"] or digest(
            triage_dir / "human_queue.jsonl") != manifest["human_queue_sha256"]:
        raise ValueError("frozen AI triage outputs changed")
    items = {row["item_key"]: row for row in read_jsonl(triage_dir / "human_queue.jsonl")}
    accepted = {row["item_key"]: row for row in read_jsonl(triage_dir / "ai_consensus.jsonl")}
    gold_rows = read_jsonl(gold_path)
    if len({row.get("item_key") for row in gold_rows}) != len(gold_rows):
        raise ValueError("duplicate human gold key")
    gold = {row["item_key"]: row for row in gold_rows}
    if any(key not in items for key in gold):
        raise ValueError("human gold contains a listing outside the review queue")
    audit_keys = manifest["audit_item_keys"]
    correct = 0
    incorrect = 0
    unknown = 0
    non_single = 0
    pending = 0
    for key in audit_keys:
        if key not in gold:
            pending += 1
            continue
        human = gold[key]
        item = items[key]
        if (human.get("source"), human.get("native_id"), human.get("title"), human.get("url")) != (
                item["source"], item["native_id"], item["title"], item["url"]):
            raise ValueError("human gold does not match audit listing")
        fields = _gold_fields(human)
        if fields["single_card"] == "no":
            non_single += 1
            incorrect += 1
            continue
        if not fields["card"] or not fields["grade"]:
            unknown += 1
            continue
        label = accepted[key]["label"]
        predicted_card = ":".join((label["language"], label["set_code"],
                                   label["number"], label["variant"]))
        predicted_grade = (("RAW", "raw") if label["grade_status"] == "raw" else
                           (label["grade_company"], label["grade_value"]))
        if (predicted_card, predicted_grade) == (fields["card"], fields["grade"]):
            correct += 1
        else:
            incorrect += 1
    measured = correct + incorrect
    lower = _wilson_lower(correct, measured)
    return {"schema": SCHEMA, "audit_sample_size": len(audit_keys),
            "review_pending": pending, "gold_unknown_joint": unknown,
            "non_single_false_accepts": non_single,
            "joint_correct": correct, "joint_incorrect": incorrect,
            "joint_precision": correct / measured if measured else None,
            "joint_wilson_95_lower": lower,
            "initial_auto_join_gate": ("pass" if pending == unknown == non_single == 0 and
                                       measured >= 300 and lower is not None and lower >= 0.98
                                       else "insufficient_or_failed"),
            "note": "No offer is promoted by this report; sampling-frame and rights checks remain external."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("triage")
    prep.add_argument("--sample-dir", type=Path, required=True)
    prep.add_argument("--ai-reviews", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True)
    prep.add_argument("--min-confidence", type=float, default=0.95)
    prep.add_argument("--audit-size", type=int, required=True)
    prep.add_argument("--seed", type=int, required=True)
    prep.add_argument("--media-ai-rights-ref", required=True)
    check = sub.add_parser("audit")
    check.add_argument("--sample-dir", type=Path, required=True)
    check.add_argument("--triage-dir", type=Path, required=True)
    check.add_argument("--human-gold", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "triage":
        result = triage(args.sample_dir, args.ai_reviews, args.out_dir,
                        min_confidence=args.min_confidence, audit_size=args.audit_size,
                        seed=args.seed, media_ai_rights_ref=args.media_ai_rights_ref)
    else:
        if args.output.exists():
            raise FileExistsError("audit report already exists")
        result = audit(args.sample_dir, args.triage_dir, args.human_gold)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
