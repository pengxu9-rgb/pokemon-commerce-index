"""Project stable-image Gemini recoveries onto previously unresolved number aliases."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(prior: list[dict], first: list[dict], second: list[dict],
          review: list[dict], stable: dict, references: dict[str, str]) -> tuple[list[dict], dict]:
    first_by = {row["card_id"]: row for row in first}
    second_by = {row["card_id"]: row for row in second}
    reviews = {row["card_id"]: row for row in review}
    if (len(first_by) != len(first) or len(second_by) != len(second)
            or len(reviews) != len(review) or set(first_by) != set(second_by)
            or set(first_by) != set(reviews)):
        raise ValueError("recovery group snapshots differ or repeat")
    if (stable["stable_groups"] != len(reviews) or stable["unstable_groups"]
            or stable["first_sha256"] != references["first"]
            or stable["second_sha256"] != references["second"]):
        raise ValueError("stable image audit does not support the recovery batch")
    output, groups = [], Counter()
    for group_id, result in reviews.items():
        cards = [row for row in prior if row["group_id"] == group_id]
        if not cards or any(row["visual_status"] != "image_unavailable" for row in cards):
            raise ValueError("recovery does not correspond to a missing-image alias group")
        a, b = first_by[group_id], second_by[group_id]
        hashes_a = [record.get("sha256") for record in a["records"]]
        hashes_b = [record.get("sha256") for record in b["records"]]
        if (a["image_evidence_status"] != "complete"
                or b["image_evidence_status"] != "complete"
                or hashes_a != hashes_b
                or a["source_record_sha256"] != b["source_record_sha256"]
                or result["source_record_sha256"] != a["source_record_sha256"]
                or result["source_jp_ids"] != [r["source_jp_id"] for r in a["records"]]
                or [r.get("expected_image_sha256") for r in result["image_evidence"]]
                   != hashes_a
                or any(record["status"] != "included" for record in result["image_evidence"])):
            raise ValueError("recovery images differ from two stable official fetches")
        if (result["review_status"] != "ai_visual_candidate"
                or result["model"] != "gemini-3.8-flash"
                or result["printing_verified"] or result["match_eligible_changed"]
                or len(result["comparisons"]) != 1
                or result["comparisons"][0]["label"] != "exact_artwork"
                or not result["comparisons"][0]["possible_surface_or_stamp_difference"]):
            raise ValueError("recovery model result is not an exact-artwork surface lead")
        review_sha = hashlib.sha256(json.dumps(result, ensure_ascii=False,
                                                sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
        for card in cards:
            if (card["source_jp_ids"] != result["source_jp_ids"]
                    or sorted(card["source_record_sha256"])
                       != sorted(result["source_record_sha256"])):
                raise ValueError("prior alias visual source differs from recovery")
            output.append({"card_id": card["card_id"], "group_id": group_id,
                           "source_jp_ids": card["source_jp_ids"],
                           "source_record_sha256": card["source_record_sha256"],
                           "prior_visual_row_sha256": card["visual_row_sha256"],
                           "stable_audit_sha256": references["stable"],
                           "review_batch_sha256": references["review"],
                           "recovery_review_row_sha256": review_sha,
                           "model": result["model"],
                           "visual_status": "ai_exact_artwork_surface_question",
                           "physical_printing_status": "unverified",
                           "official_record_to_catalog_variant_assignment": "unestablished",
                           "offer_matching_status": "blocked"})
        groups["ai_exact_artwork_surface_question"] += 1
    output.sort(key=lambda row: row["card_id"])
    return output, {"recovered_groups": sum(groups.values()), "recovered_cards": len(output),
                    "group_status": dict(groups), "source_sha256": references,
                    "physical_printings_verified": 0, "offer_match_eligibility_changed": 0,
                    "scope": "stable official images plus Gemini artwork/surface lead; no finish assignment"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "first", "second", "review", "stable", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("recovery outputs must be new")
    refs = {name: sha(getattr(args, name)) for name in
            ("prior", "first", "second", "review", "stable")}
    rows, report = build(read_jsonl(args.prior), read_jsonl(args.first),
                         read_jsonl(args.second), read_jsonl(args.review),
                         json.loads(args.stable.read_text()), refs)
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
