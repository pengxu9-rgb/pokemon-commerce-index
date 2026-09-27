"""Bind all Japanese multi-record artwork reviews to exact official records.

This is group-level visual evidence, not a physical printing or offer mapping.
It reuses existing image reviews and stores no image bytes or image URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from scripts.audit_jp_source_conflicts import PTCG_REVISION
from scripts.relationship_pilot import read_jsonl, write_jsonl


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(queue: list[dict], visual: list[dict], recovered: list[dict],
          repo: Path, snapshots: dict[str, str]) -> tuple[list[dict], dict]:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != PTCG_REVISION:
        raise ValueError("official-source checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data_jp"],
                               cwd=repo, text=True).strip():
        raise ValueError("official-source data is dirty")
    original = {row["card_id"]: row for row in visual}
    updates = {row["card_id"]: row for row in recovered}
    expected = {row["card_id"] for row in queue}
    if (len(queue) != len(expected) or len(visual) != len(original)
            or len(recovered) != len(updates) or set(original) != expected
            or not set(updates) <= expected):
        raise ValueError("review files differ from frozen 462-group queue")
    out, statuses, differences = [], Counter(), Counter()
    for group in queue:
        cid = group["card_id"]
        old = original[cid]
        review = updates.get(cid, old)
        if cid in updates and old["review_status"] != "image_unavailable":
            raise ValueError(f"recovery replaced a completed review: {cid}")
        ids, hashes = group["source_jp_ids"], group["source_record_sha256"]
        if (len(ids) < 2 or ids != sorted(ids) or len(ids) != len(hashes)
                or group["official_page_urls"] != [
                    f"https://www.pokemon-card.com/card-search/details.php/card/{x}" for x in ids]):
            raise ValueError(f"invalid official record group: {cid}")
        records = []
        for source_id, sha in zip(ids, hashes, strict=True):
            matches = list((repo / "data_jp").glob(f"*/{source_id}.json"))
            if len(matches) != 1:
                raise ValueError(f"official record missing or duplicated: {source_id}")
            raw = matches[0].read_bytes()
            source = json.loads(raw)
            if (digest(raw) != sha or source.get("url") !=
                    f"https://www.pokemon-card.com/card-search/details.php/card/{source_id}"
                    or str(source.get("set_name", "")).upper() != group["set_code"]
                    or f"{str(source.get('number', '')).zfill(3)}/{source.get('set_total')}" != group["collector_number"]):
                raise ValueError(f"official record identity changed: {source_id}")
            records.append({"source_jp_id": source_id,
                            "source_path": matches[0].relative_to(repo).as_posix(),
                            "source_record_sha256": sha})
        for result in (old, review):
            if (result["source_jp_ids"] != ids
                    or result["source_record_sha256"] != hashes
                    or result["printing_verified"]
                    or result["match_eligible_changed"]):
                raise ValueError(f"visual review changed source or printing: {cid}")
        status = review["review_status"]
        comparisons = review["comparisons"]
        if status == "ai_visual_candidate":
            if (len(comparisons) != len(ids)-1
                    or [x["source_jp_id"] for x in comparisons] != ids[1:]
                    or any(x["label"] != "exact_artwork"
                           or not isinstance(x["possible_surface_or_stamp_difference"], bool)
                           or not x["visible_reason"].strip() for x in comparisons)
                    or [x["source_jp_id"] for x in review["image_evidence"]] != ids
                    or any(x["status"] != "included" for x in review["image_evidence"])):
                raise ValueError(f"incomplete visual review: {cid}")
        elif status == "image_unavailable":
            if comparisons:
                raise ValueError(f"missing-image review has comparisons: {cid}")
        else:
            raise ValueError(f"unexpected visual review state: {cid}")
        for item in comparisons:
            differences[item["possible_surface_or_stamp_difference"]] += 1
        statuses[status] += 1
        out.append({"card_id": cid, "set_code": group["set_code"],
                    "collector_number": group["collector_number"],
                    "source_records": records,
                    "review_status": status,
                    "artwork_relation": "exact_artwork" if comparisons else "unresolved",
                    "comparisons_to_first_record": comparisons,
                    "model": review.get("model"),
                    "model_review_sha256": digest(json.dumps(review, ensure_ascii=False,
                                                               sort_keys=True,
                                                               separators=(",", ":")).encode()),
                    "image_sha256_by_source_id": [
                        {"source_jp_id": item["source_jp_id"],
                         "sha256": item.get("expected_image_sha256")}
                        for item in review["image_evidence"]],
                    "source_snapshots_sha256": snapshots,
                    "physical_printing_status": "unverified",
                    "offer_matching_status": "blocked",
                    "price_series_merge_allowed": False})
    out.sort(key=lambda x: x["card_id"])
    return out, {"groups": len(out), "sets": len({x["set_code"] for x in out}),
                 "official_records": sum(len(x["source_records"]) for x in out),
                 "review_status": dict(sorted(statuses.items())),
                 "comparisons_visible_difference": dict(sorted(
                     ((str(k).lower(), v) for k, v in differences.items()))),
                 "source_snapshots_sha256": snapshots,
                 "physical_printings_verified": 0,
                 "offer_match_eligibility_changed": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("queue", "visual", "recovered", "repo", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("multi-record scan outputs must be new")
    snapshots = {name: digest(getattr(args, name).read_bytes()) for name in
                 ("queue", "visual", "recovered")}
    rows, report = build(read_jsonl(args.queue), read_jsonl(args.visual),
                         read_jsonl(args.recovered), args.repo, snapshots)
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
