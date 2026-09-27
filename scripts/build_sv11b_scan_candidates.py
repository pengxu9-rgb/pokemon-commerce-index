"""Project official scan motifs onto catalog variants as blocked candidates.

The prior visual crosswalk treated record hashes as an unordered set. This
addendum binds each hash to its official record ID and leaves the old artifact
intact for provenance. A scan motif does not prove a physical finish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(aliases: list[dict], queue: list[dict], original: list[dict],
          recovered: list[dict], crosswalk: list[dict], references: dict[str, str],
          ptcg_repo: Path, tcgdex_repo: Path) -> tuple[list[dict], dict]:
    groups = {row["card_id"]: row for row in queue}
    reviews = {row["card_id"]: row for row in original if row["card_id"] in groups}
    reviews.update({row["card_id"]: row for row in recovered})
    prior = {row["card_id"]: row for row in crosswalk}
    if len(groups) != 80 or len(reviews) != 80 or len(prior) != 232:
        raise ValueError("SV11B source snapshots are incomplete")
    output, variants, corrected_groups = [], Counter(), set()
    for alias in aliases:
        card_id = alias["card_id"]
        if card_id not in prior:
            continue
        old = prior[card_id]
        group = groups[old["group_id"]]
        review = reviews[group["card_id"]]
        records = sorted(alias["official_records"], key=lambda item: int(
            item["path"].rsplit("/", 1)[-1][:-5]))
        ids = [int(r["path"].rsplit("/", 1)[-1][:-5]) for r in records]
        hashes = [r["sha256"] for r in records]
        if (len(records) != 2 or ids != group["source_jp_ids"]
                or hashes != group["source_record_sha256"]
                or ids != review["source_jp_ids"]
                or hashes != review["source_record_sha256"]
                or ids != old["source_jp_ids"]
                or sorted(hashes) != sorted(old["source_record_sha256"])
                or review["review_status"] != "ai_visual_candidate"
                or review["printing_verified"] or review["match_eligible_changed"]
                or len(review["comparisons"]) != 1
                or review["comparisons"][0]["source_jp_id"] != ids[1]
                or review["comparisons"][0]["label"] != "exact_artwork"
                or not review["comparisons"][0]["possible_surface_or_stamp_difference"]
                or not re.search(r"pok[eé]\s*ball", review["comparisons"][0]["visible_reason"], re.I)
                or alias["offer_matching_status"] != "blocked"
                or old["offer_matching_status"] != "blocked"):
            raise ValueError(f"scan evidence mismatch: {card_id}")
        for record in records:
            if digest(ptcg_repo / record["path"]) != record["sha256"]:
                raise ValueError(f"official record hash changed: {card_id}")
        provenance = alias["source_provenance"]
        match = re.fullmatch(r"tcgdex:([0-9a-f]{40}):(data-asia/[A-Za-z0-9/_-]+\.ts):sha256:([0-9a-f]{64})", provenance)
        if not match or digest(tcgdex_repo / match[2]) != match[3]:
            raise ValueError(f"TCGdex variant metadata changed: {card_id}")
        variant = card_id.rsplit(":", 1)[-1]
        candidate_id = ids[0] if variant == "normal" else ids[1] if variant == "reverse_pokeball" else None
        candidate_strength = "metadata_plus_visible_scan_motif" if variant == "reverse_pokeball" else (
            "metadata_plus_contrasting_reference_scan" if variant == "normal" else "unassigned")
        if old["source_record_sha256"] != hashes:
            corrected_groups.add(group["card_id"])
        output.append({
            "card_id": card_id, "group_id": group["card_id"],
            "official_number_candidate": alias["official_number_candidate"],
            "official_scans": [
                {"source_jp_id": ids[0], "source_record_sha256": hashes[0],
                 "scan_role": "reference_image_no_motif_assertion"},
                {"source_jp_id": ids[1], "source_record_sha256": hashes[1],
                 "scan_role": "visible_pokeball_pattern_candidate"},
            ],
            "catalog_variant": variant, "candidate_official_scan_id": candidate_id,
            "candidate_strength": candidate_strength,
            "ai_visual_review_sha256": hashlib.sha256(json.dumps(
                review, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "source_snapshots_sha256": references,
            "physical_printing_status": "unverified",
            "offer_matching_status": "blocked",
            "price_series_merge_allowed": False,
        })
        variants[variant] += 1
    if len(output) != 232 or len(corrected_groups) != 37:
        raise ValueError("unexpected SV11B projection or legacy hash-order count")
    output.sort(key=lambda row: row["card_id"])
    return output, {"cards": len(output), "groups": len(groups),
                    "candidate_scan_assignments": sum(x["candidate_official_scan_id"] is not None for x in output),
                    "unassigned": sum(x["candidate_official_scan_id"] is None for x in output),
                    "variants": dict(sorted(variants.items())),
                    "legacy_crosswalk_hash_order_corrections": len(corrected_groups),
                    "source_snapshots_sha256": references,
                    "physical_printings_verified": 0,
                    "offer_match_eligibility_changed": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("aliases", "queue", "original", "recovered", "crosswalk", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--ptcg-repo", type=Path, required=True)
    parser.add_argument("--tcgdex-repo", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("scan candidate outputs must be new")
    names = ("aliases", "queue", "original", "recovered", "crosswalk")
    refs = {name: digest(getattr(args, name)) for name in names}
    rows, report = build(*(read_jsonl(getattr(args, name)) for name in names),
                         refs, args.ptcg_repo, args.tcgdex_repo)
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
