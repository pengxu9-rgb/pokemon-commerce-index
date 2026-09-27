"""Join pinned number aliases to prior official-image AI reviews without inferring finish."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(aliases: list[dict], queue: list[dict], visual: list[dict],
          followup: list[dict], references: dict[str, str]) -> tuple[list[dict], dict]:
    groups = {row["card_id"]: row for row in queue}
    reviews = {row["card_id"]: row for row in visual}
    followups = {row["card_id"]: row for row in followup}
    if len(groups) != len(queue) or len(reviews) != len(visual):
        raise ValueError("prior variant review has duplicate groups")
    output, group_status, card_status = [], {}, Counter()
    for alias in aliases:
        if alias["card_id"].split(":")[1] != "SV11B" or len(alias["official_records"]) != 2:
            continue
        group_id = ("ja:SV11B:" + alias["official_number_candidate"]
                    + ":unverified_multi_record")
        group, review, pending = groups.get(group_id), reviews.get(group_id), followups.get(group_id)
        if not all((group, review, pending)):
            raise ValueError(f"number alias lacks prior image-review group: {group_id}")
        records = sorted(alias["official_records"],
                         key=lambda record: int(record["path"].rsplit("/", 1)[1][:-5]))
        ids = [int(record["path"].rsplit("/", 1)[1][:-5]) for record in records]
        hashes = [record["sha256"] for record in records]
        if (group["source_jp_ids"] != ids
                or group["source_record_sha256"] != hashes
                or review["source_jp_ids"] != ids
                or review["source_record_sha256"] != hashes
                or pending["source_jp_ids"] != ids
                or pending["source_record_sha256"] != hashes):
            raise ValueError(f"source records changed between alias and image review: {group_id}")
        if review["review_status"] == "ai_visual_candidate":
            if (pending["reason"] != "visible_surface_or_stamp_question"
                    or not review["comparisons"]
                    or any(c["label"] != "exact_artwork"
                           or not c["possible_surface_or_stamp_difference"]
                           for c in review["comparisons"])):
                raise ValueError("AI artwork result is not a surface-question group")
            status = "ai_exact_artwork_surface_question"
        elif review["review_status"] == "image_unavailable":
            if pending["reason"] != "image_unavailable" or review["comparisons"]:
                raise ValueError("missing-image result is inconsistent")
            status = "image_unavailable"
        else:
            raise ValueError("unsupported prior AI visual result")
        if (review["printing_verified"] or review["match_eligible_changed"]
                or pending["printing_verified"] or pending["offer_match_eligibility_changed"]):
            raise ValueError("prior review unexpectedly changed physical-printing or offer status")
        if group_id in group_status and group_status[group_id] != status:
            raise ValueError("one official group has inconsistent card projections")
        group_status[group_id] = status
        output.append({"card_id": alias["card_id"], "group_id": group_id,
                       "official_number_candidate": alias["official_number_candidate"],
                       "source_jp_ids": ids, "source_record_sha256": hashes,
                       "visual_status": status,
                       "visual_row_sha256": hashlib.sha256(json.dumps(
                           review, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()).hexdigest(),
                       "review_queue_sha256": references["queue"],
                       "visual_batch_sha256": references["visual"],
                       "followup_batch_sha256": references["followup"],
                       "physical_printing_status": "unverified",
                       "official_record_to_catalog_variant_assignment": "unestablished",
                       "offer_matching_status": "blocked"})
        card_status[status] += 1
    output.sort(key=lambda row: row["card_id"])
    report = {"cards": len(output), "groups": len(group_status),
              "card_status": dict(sorted(card_status.items())),
              "group_status": dict(sorted(Counter(group_status.values()).items())),
              "source_sha256": references,
              "physical_printings_verified": 0, "offer_match_eligibility_changed": 0,
              "scope": "prior AI artwork and visible surface signals only; no record-to-finish assignment"}
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--visual", type=Path, required=True)
    parser.add_argument("--followup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("visual crosswalk outputs must be new")
    references = {name: sha(getattr(args, name)) for name in
                  ("aliases", "queue", "visual", "followup")}
    rows, report = build(read_jsonl(args.aliases), read_jsonl(args.queue),
                         read_jsonl(args.visual), read_jsonl(args.followup), references)
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
