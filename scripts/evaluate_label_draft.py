"""Compare independent listing-label drafts with the title-only resolver.

This is a diagnostic agreement report, not a human-verified precision estimate.
Keep listing-level details in a private work directory; the summary omits titles
and marketplace identifiers so it can be shared with the catalog deliverable.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from pokemon_index.core import connect, import_cards, init_db, normalize_collector_number, resolve


def evaluate(labels_path: Path, catalog_path: Path) -> tuple[dict, list[dict]]:
    db = connect(":memory:")
    init_db(db)
    cards = [json.loads(line) for line in catalog_path.read_text(encoding="utf-8").splitlines()]
    import_cards(db, cards)
    labels = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines()]
    counts = Counter()
    for key in ("card_identity_candidates", "identity_candidates_in_catalog",
                "covered_identity_candidates", "covered_identity_auto_accepted",
                "covered_identity_agreement", "covered_identity_disagreement",
                "finish_labeled_candidates", "finish_labeled_in_catalog",
                "covered_finish_auto_accepted", "covered_finish_agreement",
                "covered_finish_disagreement", "abstain_label_auto_accepted",
                "grade_claim_candidates", "grade_claim_auto_accepted",
                "grade_claim_agreement", "grade_claim_disagreement"):
        counts[key] = 0
    per_set: dict[str, Counter] = defaultdict(Counter)
    details = []
    for label in labels:
        status = label["label_status"]
        counts[f"label_{status}"] += 1
        set_code = label.get("proposed_set") or "unknown"
        per_set[set_code]["samples"] += 1
        expected_identity = None
        if status != "abstain" and label.get("proposed_set") and label.get("proposed_number"):
            expected_identity = ":".join(("ja", label["proposed_set"].upper(),
                                          normalize_collector_number(label["proposed_number"])))
            counts["card_identity_candidates"] += 1
        expected_card = (expected_identity + ":" + label["proposed_variant"].lower()
                         if expected_identity and label.get("proposed_variant") else None)
        identity_covered = bool(expected_identity and db.execute(
            "SELECT 1 FROM card WHERE language='ja' AND set_code=? AND collector_number=?",
            (label["proposed_set"].upper(), normalize_collector_number(label["proposed_number"]))).fetchone())
        finish_covered = bool(expected_card and db.execute(
            "SELECT 1 FROM card WHERE card_id=?", (expected_card,)).fetchone())
        if expected_identity:
            if identity_covered:
                counts["identity_candidates_in_catalog"] += 1
                per_set[set_code]["in_catalog"] += 1
            else:
                counts["identity_candidates_outside_catalog"] += 1
        grade_claim = bool(label.get("grade_company") and label.get("grade_value"))
        if grade_claim:
            counts["grade_claim_candidates"] += 1
        if expected_card:
            counts["finish_labeled_candidates"] += 1
            if finish_covered:
                counts["finish_labeled_in_catalog"] += 1

        unit, method = resolve(db, {"title": label["title"]})
        actual_card = unit.split("|")[0] if unit else None
        actual_identity = actual_card.rsplit(":", 1)[0] if actual_card else None
        if unit:
            counts["resolver_auto_accepted"] += 1
            per_set[set_code]["auto_accepted"] += 1
        else:
            counts["resolver_abstained"] += 1
        if status == "abstain" and unit:
            counts["abstain_label_auto_accepted"] += 1
        if expected_identity and identity_covered:
            counts["covered_identity_candidates"] += 1
            if unit:
                counts["covered_identity_auto_accepted"] += 1
                if actual_identity == expected_identity:
                    counts["covered_identity_agreement"] += 1
                else:
                    counts["covered_identity_disagreement"] += 1
        if expected_card and finish_covered and unit:
            counts["covered_finish_auto_accepted"] += 1
            if actual_card == expected_card:
                counts["covered_finish_agreement"] += 1
            else:
                counts["covered_finish_disagreement"] += 1
        if expected_identity and unit:
            expected_company = label.get("grade_company") or "RAW"
            expected_grade = label.get("grade_value") or "raw"
            parts = unit.split("|")
            counts["resolved_grade_comparisons"] += 1
            if parts[1] == expected_company and parts[2] == str(expected_grade):
                counts["resolved_grade_agreement"] += 1
            else:
                counts["resolved_grade_disagreement"] += 1
        if grade_claim and unit:
            counts["grade_claim_auto_accepted"] += 1
            if unit.split("|")[1:3] == [label["grade_company"], str(label["grade_value"])]:
                counts["grade_claim_agreement"] += 1
            else:
                counts["grade_claim_disagreement"] += 1
        details.append({
            "source": label["source"], "native_id": label["native_id"],
            "label_status": status, "proposed_set": label.get("proposed_set"),
            "expected_identity": expected_identity, "expected_card": expected_card,
            "catalog_covered": identity_covered, "finish_covered": finish_covered,
            "resolved_card": actual_card, "resolved_unit": unit,
            "resolution_method": method,
        })
    human_reviewed = bool(labels) and all(row.get("human_reviewed") is True for row in labels)
    report = {
        "report_type": ("Human double-review comparison; verify sampling and blind design before a precision claim"
                        if human_reviewed else "AI draft agreement diagnostic; not human-verified accuracy"),
        "sample_count": len(labels), "catalog_cards": len(cards),
        "counts": dict(sorted(counts.items())),
        "by_proposed_set": {name: dict(sorted(values.items())) for name, values in sorted(per_set.items())},
        "interpretation": ([
            "Card identity means Japanese set code plus collector number, excluding finish.",
            "A specific finish is compared only when human reviewers verified a card photo.",
            "The resolver sees listing titles only; human reviewers may inspect descriptions and photos.",
            "Assess sample selection, catalog version, and matcher freeze before reporting population precision.",
        ] if human_reviewed else [
            "Card identity means Japanese set code plus collector number, excluding finish.",
            "The current draft has no independently evidenced set+number+finish labels, so finish precision is unmeasured.",
            "The resolver sees listing titles only; the draft annotator also inspected descriptions.",
            "Human adjudication and a held-out sample are required before reporting precision or recall.",
        ]),
    }
    return report, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--details", type=Path)
    args = parser.parse_args()
    report, details = evaluate(args.labels, args.catalog)
    args.summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.details:
        args.details.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in details),
                                encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
