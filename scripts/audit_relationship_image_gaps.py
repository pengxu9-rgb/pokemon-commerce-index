"""Explain why the frozen JP/EN artwork queue lacks exact source images.

This is a read-only catalog/source audit. Possible official records are leads,
not substituted images or verified printing relationships.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.official_jp_image_evidence import OfficialJPImageIndex, _valid_official_url
from scripts.relationship_pilot import read_jsonl, write_jsonl


def classify_jp(card_id: str, name: str, source: OfficialJPImageIndex) -> dict:
    _, set_code, number_total, _ = card_id.split(":", 3)
    number, total = number_total.split("/", 1)
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in source.paths.get((set_code.upper(), number.zfill(3)), [])]
    same_total = [r for r in records if str(r.get("set_total", "")).zfill(3) == total.zfill(3)]
    exact = [r for r in same_total if r.get("name") == name]
    valid = [r for r in exact if _valid_official_url(str(r.get("url", "")), image=False)
             and _valid_official_url(str(r.get("img", "")), image=True)]
    if not records:
        cause = "no_official_set_number_record"
    elif not same_total:
        cause = "official_set_total_conflict"
    elif not exact:
        cause = "official_name_conflict"
    elif len(valid) > 1:
        cause = "multiple_exact_official_records"
    elif not valid:
        cause = "exact_record_without_supported_image"
    else:
        cause = "exact_official_record_present"
    return {"cause": cause, "set_number_records": len(records),
            "same_total_records": len(same_total), "exact_name_records": len(exact),
            "usable_exact_records": len(valid),
            "official_pages": [r["url"] for r in exact if _valid_official_url(
                str(r.get("url", "")), image=False)]}


def audit(queue: list[dict], followup: list[dict],
          source: OfficialJPImageIndex) -> tuple[list[dict], dict]:
    by_id = {r["candidate_id"]: r for r in queue}
    if len(by_id) != len(queue):
        raise ValueError("duplicate relationship candidate")
    results = []
    for item in followup:
        if item["reason"] != "insufficient_images":
            continue
        cid = item["candidate_id"]
        row = by_id[cid]
        if (row["source_snapshot_sha256"] != item["source_snapshot_sha256"]
                or row["anchor"]["card_id"] != item["ja_card_id"]
                or row["candidate"]["card_id"] != item["en_card_id"]):
            raise ValueError("follow-up row differs from frozen queue")
        jp = classify_jp(item["ja_card_id"], row["anchor"]["name"], source)
        results.append({"candidate_id": cid, "ja_card_id": item["ja_card_id"],
                        "en_card_id": item["en_card_id"],
                        "ja_previous_status": item["ja_image_status"],
                        "en_previous_status": item["en_image_status"],
                        "ja_source_gap": jp,
                        "review_status": "pending_exact_images",
                        "offer_match_eligibility_changed": False})
    report = {"pairs": len(results), "ptcg_revision": source.revision,
              "jp_gap_causes": dict(sorted(Counter(
                  x["ja_source_gap"]["cause"] for x in results
                  if x["ja_previous_status"] != "included").items())),
              "en_prior_status": dict(sorted(Counter(
                  x["en_previous_status"] for x in results).items())),
              "source_gaps_resolved_by_inference": 0,
              "scope": "source diagnosis only; candidate records are not image substitutions"}
    return results, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--followup", type=Path, required=True)
    parser.add_argument("--official-jp-repo", type=Path, required=True)
    parser.add_argument("--official-jp-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("gap audit outputs must be new")
    source = OfficialJPImageIndex(args.official_jp_repo.resolve(),
                                  args.official_jp_revision)
    rows, report = audit(read_jsonl(args.queue), read_jsonl(args.followup), source)
    report["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    report["followup_sha256"] = hashlib.sha256(args.followup.read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
