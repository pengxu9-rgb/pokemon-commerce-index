"""Compile AI visual evidence into scoped cross-region card comparison advice.

Card-level evidence can support discovery and contextual comparison. It never
merges Japanese and English price series or certifies an individual listing's
condition, foil pattern, or paid price.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from scripts.relationship_pilot import read_jsonl


def _rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {row["candidate_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate artwork candidate")
    return result


def compile_pair(pair: dict[str, Any], art: dict[str, str],
                 audit: dict[str, Any]) -> dict[str, Any]:
    cid = pair["candidate_id"]
    if (art["candidate_id"] != cid
            or art["source_snapshot_sha256"] != pair["source_snapshot_sha256"]
            or audit["candidate_id"] != cid
            or audit["source_snapshot_sha256"] != pair["source_snapshot_sha256"]):
        raise ValueError(f"artwork evidence does not bind to candidate {cid}")
    image_complete = (art["ja_image_status"] == "included"
                      and art["en_image_status"] == "included"
                      and audit["ja_image"].get("image_sha256")
                      and audit["en_image"].get("image_sha256"))
    if art["artwork_decision"] == "same" and not image_complete:
        raise ValueError(f"same-artwork verdict lacks two hashed images: {cid}")
    if (audit["en_image"].get("source") == "curated_hash_bound_asset"
            and art["artwork_decision"] == "same"
            and art.get("en_image_identity") != "match"):
        raise ValueError(f"curated English image identity was not confirmed: {cid}")
    same_art = art["artwork_decision"] == "same"
    variants_match = pair["anchor"]["variant"] == pair["candidate"]["variant"]
    rarity_match = pair["anchor"]["rarity"] == pair["candidate"]["rarity"]
    if not image_complete:
        scope, next_action = "await_image_evidence", "fetch_exact_missing_card_image"
    elif art["artwork_decision"] == "different":
        scope, next_action = "separate_artwork", "retain_separate_price_series"
    elif not same_art:
        scope, next_action = "artwork_uncertain", "ai_second_visual_pass"
    elif variants_match and rarity_match:
        scope, next_action = "nominal_variant_peer", "listing_condition_and_finish_check"
    else:
        scope, next_action = "artwork_peer_only", "retain_variant_and_rarity_separation"
    return {
        "candidate_id": cid,
        "source_snapshot_sha256": pair["source_snapshot_sha256"],
        "ja_card_id": pair["anchor"]["card_id"],
        "en_card_id": pair["candidate"]["card_id"],
        "artwork_decision": art["artwork_decision"],
        "artwork_model": audit.get("model_version"),
        "artwork_rationale": art.get("rationale", ""),
        "model_response_sha256": audit.get("response_sha256"),
        "en_image_identity": art.get("en_image_identity", ""),
        "ja_image_sha256": audit["ja_image"].get("image_sha256"),
        "en_image_sha256": audit["en_image"].get("image_sha256"),
        "ja_image_ref": audit["ja_image"].get("card_url") or audit["ja_image"].get("image_url"),
        "en_image_ref": audit["en_image"].get("image_url"),
        "ja_variant": pair["anchor"]["variant"],
        "en_variant": pair["candidate"]["variant"],
        "ja_rarity": pair["anchor"]["rarity"],
        "en_rarity": pair["candidate"]["rarity"],
        "variant_metadata_match": variants_match,
        "rarity_metadata_match": rarity_match,
        "comparison_scope": scope,
        "next_action": next_action,
        "price_series_merge_allowed": False,
        "numeric_cross_region_spread_allowed": False,
        "reason": "Card images and catalog labels do not establish physical finish, listing condition, or paid price.",
    }


def compile_all(queue: list[dict[str, Any]], passes: list[tuple[Path, Path]],
                ignored_candidate_ids: set[str] | None = None
                ) -> list[dict[str, Any]]:
    art_by_id: dict[str, dict[str, str]] = {}
    audit_by_id: dict[str, dict[str, Any]] = {}
    for sheet, audit_path in passes:
        artwork = _rows(sheet)
        audit_file = json.loads(audit_path.read_text(encoding="utf-8"))
        audits = {row["candidate_id"]: row for row in audit_file["rows"]}
        if set(artwork) != set(audits) or len(audits) != len(audit_file["rows"]):
            raise ValueError("artwork sheet and audit disagree")
        art_by_id.update(artwork)
        audit_by_id.update(audits)
    expected = {row["candidate_id"] for row in queue}
    ignored = ignored_candidate_ids or set()
    if ((set(art_by_id) - expected) != ignored or (expected - set(art_by_id))
            or len(expected) != len(queue)):
        raise ValueError("artwork passes do not cover the candidate queue exactly")
    return [compile_pair(row, art_by_id[row["candidate_id"]],
                         audit_by_id[row["candidate_id"]]) for row in queue]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--pass", dest="passes", type=Path, nargs=2,
                        action="append", required=True, metavar=("SHEET", "AUDIT"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ignore-superseded-candidate", action="append", default=[])
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        raise FileExistsError("comparison outputs already exist")
    rows = compile_all(read_jsonl(args.queue), [tuple(p) for p in args.passes],
                       set(args.ignore_superseded_candidate))
    with args.output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    from collections import Counter
    report = {"candidate_pairs": len(rows),
              "comparison_scope": dict(sorted(Counter(
                  row["comparison_scope"] for row in rows).items())),
              "price_series_merge_allowed": 0,
              "numeric_cross_region_spread_allowed": 0,
              "scope": "AI card-level evidence only; listing condition and finish need listing evidence"}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
