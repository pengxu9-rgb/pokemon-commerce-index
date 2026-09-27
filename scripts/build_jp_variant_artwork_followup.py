"""Make a source-bound queue for unresolved Japanese multi-record printings."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def build(queue: list[dict], results: list[dict]) -> tuple[list[dict], dict]:
    by_id = {row["card_id"]: row for row in results}
    if len(by_id) != len(results) or set(by_id) != {row["card_id"] for row in queue}:
        raise ValueError("visual results differ from frozen variant queue")
    followup = []
    for group in queue:
        result = by_id[group["card_id"]]
        if (result["source_jp_ids"] != group["source_jp_ids"]
                or result["source_record_sha256"] != group["source_record_sha256"]):
            raise ValueError("visual result source differs from frozen group")
        surface = [c for c in result["comparisons"]
                   if c["possible_surface_or_stamp_difference"]]
        if result["review_status"] == "ai_visual_candidate" and not surface:
            continue
        reason = (result["review_status"] if result["review_status"] != "ai_visual_candidate"
                  else "visible_surface_or_stamp_question")
        followup.append({"card_id": group["card_id"], "source_jp_ids": group["source_jp_ids"],
                         "official_page_urls": group["official_page_urls"],
                         "source_record_sha256": group["source_record_sha256"],
                         "reason": reason,
                         "visual_labels": [c["label"] for c in result["comparisons"]],
                         "flagged_source_jp_ids": [c["source_jp_id"] for c in surface],
                         "review_status": "pending_physical_variant_evidence",
                         "printing_verified": False,
                         "offer_match_eligibility_changed": False})
    audit = {"groups": len(queue), "visual_candidate_groups": sum(
        r["review_status"] == "ai_visual_candidate" for r in results),
             "followup_groups": len(followup),
             "reasons": dict(sorted(Counter(r["reason"] for r in followup).items())),
             "physical_printings_verified": 0, "offer_match_eligibility_changed": 0}
    return followup, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--visual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("followup output already exists")
    rows, audit = build(read_jsonl(args.queue), read_jsonl(args.visual))
    audit["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    audit["visual_sha256"] = hashlib.sha256(args.visual.read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
