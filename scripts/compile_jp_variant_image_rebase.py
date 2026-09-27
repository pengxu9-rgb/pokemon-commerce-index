"""Accept a new official image snapshot only after two independent matching fetches."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def compile_stable(queue: list[dict], original: list[dict], first: list[dict],
                   second: list[dict]) -> tuple[list[dict], list[dict], dict]:
    ids = {x["card_id"] for x in queue}
    maps = [{x["card_id"]: x for x in rows} for rows in (original, first, second)]
    if len(ids) != len(queue) or any(len(mapping) != len(rows) or not ids <= set(mapping)
                                     for mapping, rows in zip(maps, (original, first, second))):
        raise ValueError("duplicate or missing groups in image snapshots")
    selected_queue, selected_evidence = [], []
    changed, unstable = 0, 0
    for group in queue:
        key = group["card_id"]
        prior, a, b = [mapping[key] for mapping in maps]
        if any(row["source_record_sha256"] != group["source_record_sha256"]
               or [r["source_jp_id"] for r in row["records"]] != group["source_jp_ids"]
               for row in (prior, a, b)):
            raise ValueError(f"image snapshot source mismatch: {key}")
        a_hashes = [r.get("sha256") for r in a["records"]]
        b_hashes = [r.get("sha256") for r in b["records"]]
        if (a["image_evidence_status"] != "complete"
                or b["image_evidence_status"] != "complete"
                or a_hashes != b_hashes):
            unstable += 1
            continue
        changed += a_hashes != [r.get("sha256") for r in prior["records"]]
        selected_queue.append(group)
        selected_evidence.append(a)
    report = {"retry_groups": len(queue), "stable_groups": len(selected_queue),
              "unstable_groups": unstable, "stable_groups_changed_from_prior": changed,
              "printing_verified": 0, "offer_match_eligibility_changed": 0,
              "scope": "two-fetch stable official image bytes for internal AI retry only"}
    return selected_queue, selected_evidence, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("queue", "original", "first", "second", "output-queue",
                 "output-evidence", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output_queue.exists() or args.output_evidence.exists() or args.audit.exists():
        raise FileExistsError("stable image outputs must be new")
    queue, evidence, report = compile_stable(
        read_jsonl(args.queue), read_jsonl(args.original),
        read_jsonl(args.first), read_jsonl(args.second))
    for name in ("queue", "original", "first", "second"):
        report[name + "_sha256"] = hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
    write_jsonl(args.output_queue, queue)
    write_jsonl(args.output_evidence, evidence)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
