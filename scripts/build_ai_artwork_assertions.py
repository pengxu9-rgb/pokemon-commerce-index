"""Convert source-bound AI artwork decisions into scoped graph proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.relationship_pilot import read_jsonl


def build(rows: list[dict]) -> list[dict]:
    assertions = []
    for row in rows:
        if row["artwork_decision"] != "same":
            continue
        if not row.get("ja_image_sha256") or not row.get("en_image_sha256"):
            raise ValueError("same-artwork proposal needs both image hashes")
        if row.get("en_image_identity") != "match":
            raise ValueError("same-artwork proposal needs a confirmed English image identity")
        if not row.get("model_response_sha256") or not row.get("source_snapshot_sha256"):
            raise ValueError("same-artwork proposal needs model and source hashes")
        left, right = sorted((row["ja_card_id"], row["en_card_id"]))
        evidence = {
            "schema": "pokemon.ai_artwork_review.v1",
            "candidate_id": row["candidate_id"],
            "source_snapshot_sha256": row["source_snapshot_sha256"],
            "cards": [left, right],
            "model": row["artwork_model"],
            "artwork_decision": "same",
            "artwork_rationale": row["artwork_rationale"],
            "model_response_sha256": row["model_response_sha256"],
            "en_image_identity": row["en_image_identity"],
            "ja_image_sha256": row["ja_image_sha256"],
            "en_image_sha256": row["en_image_sha256"],
            "ja_image_ref": row["ja_image_ref"],
            "en_image_ref": row["en_image_ref"],
            "comparison_scope": row["comparison_scope"],
            "finish_checked": False,
            "condition_checked": False,
            "price_comparable": False,
        }
        digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False,
                                         sort_keys=True).encode()).hexdigest()[:24]
        assertions.append({
            "assertion_id": f"aiart-v1:{row['candidate_id']}:{digest}",
            "left_card_id": left, "right_card_id": right,
            "relation_type": "same_artwork", "review_status": "proposed",
            "evidence_ref": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "rights_reference": "internal image comparison only; source image rights remain separate",
            "asserted_by": "ai-artwork-review-v1", "reviewer": row["artwork_model"],
        })
    return assertions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = build(read_jsonl(args.input))
    with args.output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"same_artwork_proposals": len(rows)}))


if __name__ == "__main__":
    main()
