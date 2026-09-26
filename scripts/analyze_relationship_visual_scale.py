"""Summarize a complete, source-bound Gemini artwork triage batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl
from scripts.vertex_concept_review import MODEL


def analyze(queue: list[dict], artwork: list[dict], audit: dict
            ) -> tuple[dict, list[dict]]:
    by_id = {row["candidate_id"]: row for row in artwork}
    evidence = {row["candidate_id"]: row for row in audit["rows"]}
    expected = {row["candidate_id"] for row in queue}
    if (len(by_id) != len(artwork) or len(evidence) != len(audit["rows"])
            or set(by_id) != expected or set(evidence) != expected):
        raise ValueError("visual results do not cover frozen candidate queue")
    if audit["model"] != MODEL:
        raise ValueError("unexpected visual model")
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    by_signal: dict[str, Counter] = defaultdict(Counter)
    decisions = Counter()
    image_status = Counter()
    followup = []
    same_metadata = Counter()
    for candidate in queue:
        cid = candidate["candidate_id"]
        row, source = by_id[cid], evidence[cid]
        if (row["source_snapshot_sha256"] != candidate["source_snapshot_sha256"]
                or source["source_snapshot_sha256"] != candidate["source_snapshot_sha256"]):
            raise ValueError(f"visual source snapshot changed: {cid}")
        decision = row["artwork_decision"]
        if decision not in {"same", "different", "uncertain", "insufficient_images",
                            "model_error"}:
            raise ValueError(f"unknown visual decision: {decision}")
        both = row["ja_image_status"] == row["en_image_status"] == "included"
        if decision in {"same", "different"}:
            if (not both or row["en_image_identity"] != "match"
                    or source.get("model_version") != MODEL
                    or not source.get("response_sha256")
                    or not source["ja_image"].get("image_sha256")
                    or not source["en_image"].get("image_sha256")):
                raise ValueError(f"visual decision lacks complete evidence: {cid}")
        decisions[decision] += 1
        by_stratum[candidate["selection_reason"]][decision] += 1
        by_signal[candidate["shared_facets"]["retrieval_signal"]][decision] += 1
        image_status[(row["ja_image_status"], row["en_image_status"])] += 1
        if decision == "same":
            same_metadata["variant_string_equal"] += (
                candidate["anchor"]["variant"] == candidate["candidate"]["variant"])
            same_metadata["rarity_string_equal"] += (
                candidate["anchor"]["rarity"] == candidate["candidate"]["rarity"])
            same_metadata["any_offer_match_disabled"] += (
                not candidate["anchor"]["match_eligible"]
                or not candidate["candidate"]["match_eligible"])
        elif decision in {"uncertain", "insufficient_images", "model_error"}:
            followup.append({"candidate_id": cid,
                             "source_snapshot_sha256": row["source_snapshot_sha256"],
                             "ja_card_id": candidate["anchor"]["card_id"],
                             "en_card_id": candidate["candidate"]["card_id"],
                             "stratum": candidate["selection_reason"],
                             "reason": decision,
                             "ja_image_status": row["ja_image_status"],
                             "en_image_status": row["en_image_status"],
                             "review_status": "pending"})
    report = {
        "scope": "Gemini source-bound artwork triage; no verified graph edge, printing or price equivalence",
        "model": MODEL, "candidate_pairs": len(queue),
        "visual_decisions": dict(sorted(decisions.items())),
        "by_stratum": {key: dict(sorted(counts.items()))
                       for key, counts in sorted(by_stratum.items())},
        "by_retrieval_signal": {key: dict(sorted(counts.items()))
                                for key, counts in sorted(by_signal.items())},
        "image_status_pairs": {"|".join(pair): count
                               for pair, count in sorted(image_status.items())},
        "same_artwork_metadata": dict(sorted(same_metadata.items())),
        "pending_followup_pairs": len(followup),
        "price_series_merge_allowed": 0,
    }
    return report, followup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--visual", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--followup", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.followup.exists():
        raise FileExistsError("analysis outputs must be new")
    with args.visual.open(encoding="utf-8", newline="") as handle:
        artwork = list(csv.DictReader(handle))
    queue = read_jsonl(args.queue)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    report, followup = analyze(queue, artwork, audit)
    report["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    report["visual_sha256"] = hashlib.sha256(args.visual.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                      indent=2) + "\n", encoding="utf-8")
    write_jsonl(args.followup, followup)
    print(json.dumps({key: report[key] for key in (
        "candidate_pairs", "visual_decisions", "pending_followup_pairs")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
