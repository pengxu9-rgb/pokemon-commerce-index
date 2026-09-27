"""Merge a hash-rebased retry into the frozen Japanese artwork review batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def merge(queue: list[dict], first: list[dict], retry: list[dict]) -> tuple[list[dict], dict]:
    source = {r["card_id"]: r for r in first}
    second = {r["card_id"]: r for r in retry}
    expected = {r["card_id"] for r in queue}
    if (len(source) != len(first) or len(second) != len(retry)
            or set(source) != expected or not set(second) <= expected):
        raise ValueError("review results differ from frozen queue")
    output, promoted = [], 0
    for group in queue:
        cid = group["card_id"]
        old = source[cid]
        new = second.get(cid)
        for row in (old, new) if new else (old,):
            if (row["source_jp_ids"] != group["source_jp_ids"]
                    or row["source_record_sha256"] != group["source_record_sha256"]
                    or row["printing_verified"] or row["match_eligible_changed"]):
                raise ValueError(f"review row changed source or printing status: {cid}")
        if new and new["review_status"] == "ai_visual_candidate":
            if old["review_status"] == "ai_visual_candidate":
                raise ValueError("retry would replace a completed visual result")
            chosen = dict(new)
            chosen["prior_review_status"] = old["review_status"]
            chosen["image_rebase_used"] = True
            promoted += 1
        else:
            chosen = dict(old)
            chosen["image_rebase_used"] = False
        output.append(chosen)
    report = {"groups": len(output), "retry_rows": len(retry),
              "recovered_groups": promoted,
              "statuses": dict(sorted(Counter(x["review_status"] for x in output).items())),
              "labels": dict(sorted(Counter(c["label"] for x in output
                                            for c in x["comparisons"]).items())),
              "printing_verified": 0, "offer_match_eligibility_changed": 0,
              "scope": "AI visible artwork only; no physical printing or price equivalence"}
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("queue", "first", "retry", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("merged artwork outputs must be new")
    rows, report = merge(read_jsonl(args.queue), read_jsonl(args.first),
                         read_jsonl(args.retry))
    for name in ("queue", "first", "retry"):
        report[name + "_sha256"] = hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
