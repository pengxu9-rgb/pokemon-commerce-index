"""Measure collector-number relationships inside a frozen visual-review cohort."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl


def _parts(number: str) -> tuple[str, str]:
    fields = number.upper().split("/", 1)
    if len(fields) != 2:
        return number.upper(), ""
    return tuple(field.lstrip("0") or "0" for field in fields)


def analyze(queue: list[dict], visual: list[dict]) -> dict:
    by_id = {row["candidate_id"]: row for row in visual}
    if len(by_id) != len(visual) or set(by_id) != {
            row["candidate_id"] for row in queue}:
        raise ValueError("number analysis requires one visual row per pair")
    by_decision: dict[str, Counter] = {}
    same_ja, same_en = Counter(), Counter()
    examples = {}
    for pair in queue:
        result = by_id[pair["candidate_id"]]
        if result["source_snapshot_sha256"] != pair["source_snapshot_sha256"]:
            raise ValueError("visual result does not bind source snapshot")
        decision = result["artwork_decision"]
        left, right = pair["anchor"], pair["candidate"]
        if (left["language"], right["language"]) != ("ja", "en"):
            raise ValueError("expected a Japanese and English card")
        ln, ld = _parts(left["collector_number"])
        rn, rd = _parts(right["collector_number"])
        pattern = ("same" if ln == rn else "different") + "_numerator__" + (
            "same" if ld == rd else "different") + "_denominator"
        counts = by_decision.setdefault(decision, Counter())
        counts["pairs"] += 1
        counts[pattern] += 1
        counts["same_set_code"] += left["set_code"] == right["set_code"]
        counts["same_variant_string"] += left["variant"] == right["variant"]
        if decision == "same":
            same_ja[left["card_id"]] += 1
            same_en[right["card_id"]] += 1
            examples.setdefault(pattern, {"ja_card_id": left["card_id"],
                                          "en_card_id": right["card_id"],
                                          "ja_name": left["name"],
                                          "en_name": right["name"],
                                          "ja_variant": left["variant"],
                                          "en_variant": right["variant"]})
    return {"scope": "number patterns in a biased retrieval cohort; same means one Gemini artwork verdict, not verified card or price equivalence",
            "pairs": len(queue),
            "by_visual_decision": {key: dict(sorted(value.items()))
                                   for key, value in sorted(by_decision.items())},
            "same_artwork_many_to_many": {
                "distinct_ja_cards": len(same_ja), "distinct_en_cards": len(same_en),
                "ja_cards_with_multiple_en_candidates": sum(n > 1 for n in same_ja.values()),
                "en_cards_with_multiple_ja_candidates": sum(n > 1 for n in same_en.values()),
                "maximum_en_candidates_per_ja": max(same_ja.values(), default=0),
                "maximum_ja_candidates_per_en": max(same_en.values(), default=0)},
            "examples_by_number_pattern": examples,
            "observation_prices_included": 0,
            "price_trend_inference_allowed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--visual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with args.visual.open(encoding="utf-8", newline="") as handle:
        visual = list(csv.DictReader(handle))
    report = analyze(read_jsonl(args.queue), visual)
    report["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    report["visual_sha256"] = hashlib.sha256(args.visual.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                      sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pairs": report["pairs"],
                      "same_artwork_number_patterns": report["by_visual_decision"]["same"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
