"""Release one ranked concept candidate per name at a time for dual-AI review.

The full ranked packet remains an immutable retrieval audit. An agreed reject
advances to the next candidate; agreement on approve or any uncertainty stops
that name. This script schedules review only. It never imports an alias or edge.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.concept_review_packet import write_sheet
from scripts.relationship_pilot import read_jsonl, write_jsonl

DECISIONS = {"approve", "reject", "uncertain"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _groups(queue: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for row in queue:
        pid = row["proposal_id"]
        if pid in seen or row["source_snapshot_sha256"] != _digest(row["source_snapshot"]):
            raise ValueError(f"duplicate proposal or changed snapshot: {pid}")
        if any(row.get(key) != value for key, value in
               row["source_snapshot"]["frozen"].items()):
            raise ValueError(f"frozen proposal field changed: {pid}")
        seen.add(pid)
        grouped[(row["category"], row["name_ja"])].append(row)
    if not grouped:
        raise ValueError("ranked queue is empty")
    for key, rows in grouped.items():
        rows.sort(key=lambda item: item["source_snapshot"]["rank"]["position"])
        positions = [row["source_snapshot"]["rank"]["position"] for row in rows]
        if positions != list(range(1, len(rows) + 1)):
            raise ValueError(f"noncontiguous rank for {key}")
    return dict(grouped)


def _review_rows(path: Path, queue: dict[str, dict[str, Any]]) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        pid = row.get("proposal_id", "")
        if pid in result or pid not in queue:
            raise ValueError(f"duplicate or unknown reviewed proposal: {pid}")
        if row.get("source_snapshot_sha256") != queue[pid]["source_snapshot_sha256"]:
            raise ValueError(f"review source snapshot mismatch: {pid}")
        decision = row.get("suggested_decision")
        if decision not in DECISIONS or not (row.get("rationale") or "").strip():
            raise ValueError(f"invalid or unexplained review: {pid}")
        result[pid] = decision
    return result


def read_dual_reviews(queue: list[dict[str, Any]], astra: Path | None,
                      sol: Path | None) -> dict[str, tuple[str, str]]:
    if (astra is None) != (sol is None):
        raise ValueError("both independent review files are required")
    if astra is None:
        return {}
    by_id = {row["proposal_id"]: row for row in queue}
    first, second = _review_rows(astra, by_id), _review_rows(sol, by_id)
    if set(first) != set(second):
        raise ValueError("AI review files cover different proposals")
    return {pid: (first[pid], second[pid]) for pid in first}


def read_triple_reviews(queue: list[dict[str, Any]], astra: Path, sol: Path,
                        gemini: Path, gemini_audit: Path
                        ) -> tuple[dict[str, tuple[str, str, str]], set[str]]:
    dual = read_dual_reviews(queue, astra, sol)
    third = _review_rows(gemini, {row["proposal_id"]: row for row in queue})
    if set(dual) != set(third):
        raise ValueError("three AI review files cover different proposals")
    audit = json.loads(gemini_audit.read_text(encoding="utf-8"))
    if audit.get("model") != "gemini-3.8-flash":
        raise ValueError("Gemini model audit is missing")
    evidence = {row["proposal_id"]: row for row in audit.get("rows", [])}
    if len(evidence) != len(third) or set(evidence) != set(third):
        raise ValueError("Gemini image audit does not cover reviewed proposals")
    image_holds = {pid for pid, decision in third.items()
                   if decision == "approve" and any(
                       evidence[pid].get(f"{side}_image", {}).get("status") != "included"
                       for side in ("ja", "en"))}
    return {pid: (*dual[pid], third[pid]) for pid in dual}, image_holds


def select_next(queue: list[dict[str, Any]],
                reviews: dict[str, tuple[str, ...]], *, replay_full: bool = False,
                held_ids: set[str] | None = None
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = _groups(queue)
    if set(reviews) - {row["proposal_id"] for row in queue}:
        raise ValueError("review references an unknown proposal")
    held_ids = held_ids or set()
    if held_ids - set(reviews):
        raise ValueError("image hold references an unreviewed proposal")
    selected: list[dict[str, Any]] = []
    outcomes: Counter[str] = Counter()
    scheduled_count = 0
    for rows in groups.values():
        stopped = False
        for index, row in enumerate(rows):
            pid = row["proposal_id"]
            if stopped:
                if pid in reviews and not replay_full:
                    raise ValueError(f"review exists after name was stopped: {pid}")
                continue
            scheduled_count += 1
            if pid not in reviews:
                if any(later["proposal_id"] in reviews for later in rows[index + 1:]):
                    raise ValueError(f"review skipped a prior rank: {pid}")
                selected.append(row)
                outcomes["needs_review"] += 1
                stopped = True
                continue
            decisions = reviews[pid]
            if len(decisions) not in {2, 3} or any(item not in DECISIONS for item in decisions):
                raise ValueError(f"invalid independent decisions for {pid}")
            if pid not in held_ids and all(item == "reject" for item in decisions):
                continue
            if pid not in held_ids and all(item == "approve" for item in decisions):
                outcomes["approved_by_ai"] += 1
            else:
                outcomes["deferred"] += 1
            stopped = True
        if not stopped:
            outcomes["exhausted"] += 1
    audit = {"ranked_names": len(groups), "ranked_proposals": len(queue),
             "reviewed_proposals": len(reviews), "sequential_review_slots": scheduled_count,
             "next_review_rows": len(selected), "outcomes": dict(sorted(outcomes.items())),
             "scope": "review scheduling only; no alias, edge, or human verification"}
    if replay_full:
        if len(reviews) != len(queue):
            raise ValueError("full replay requires independent reviews for every proposal")
        audit["avoided_review_rows"] = len(queue) - scheduled_count
        audit["review_row_reduction"] = round(
            (len(queue) - scheduled_count) / len(queue), 4)
        audit["ai_approval_per_sequential_review"] = round(
            outcomes["approved_by_ai"] / scheduled_count, 4)
    return selected, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--astra", type=Path)
    parser.add_argument("--sol", type=Path)
    parser.add_argument("--gemini", type=Path)
    parser.add_argument("--gemini-audit", type=Path)
    parser.add_argument("--require-image-pair", action="store_true")
    parser.add_argument("--replay-full", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sheet", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.replay_full and (args.output or args.sheet):
        raise ValueError("a full replay only produces an audit")
    if not args.replay_full and (args.output is None or args.sheet is None):
        raise ValueError("a review stage requires output queue and sheet")
    if args.audit and args.audit.exists():
        raise FileExistsError(args.audit)
    queue = read_jsonl(args.queue)
    if args.gemini or args.gemini_audit:
        if not (args.astra and args.sol and args.gemini and args.gemini_audit):
            raise ValueError("triple review needs all three files and Gemini audit")
        reviews, image_gaps = read_triple_reviews(
            queue, args.astra, args.sol, args.gemini, args.gemini_audit)
        held_ids = image_gaps if args.require_image_pair else set()
    else:
        if args.require_image_pair:
            raise ValueError("image-pair gate requires Gemini audit")
        reviews, held_ids, image_gaps = read_dual_reviews(queue, args.astra, args.sol), set(), set()
    selected, audit = select_next(queue, reviews, replay_full=args.replay_full,
                                  held_ids=held_ids)
    if args.gemini:
        audit["reviewer_count"] = 3
        audit["missing_image_pair_rows"] = len(image_gaps)
        audit["image_evidence_holds"] = len(held_ids)
    if args.output:
        write_jsonl(args.output, selected)
    if args.sheet:
        write_sheet(args.sheet, selected)
    if args.audit:
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
