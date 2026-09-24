"""Prepare a blind relationship-coverage sample and evaluate independently reviewed answers.

Sampling never labels a counterpart. Candidate generation is measured only after
two reviewers have supplied card-specific answers in a separate gold file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pokemon_index.core import parse_time
from scripts import relationship_pilot

STRATA = (
    "multi_character", "trainer", "energy", "missing_facet",
    "same_number_finish", "promo", "name_reprint", "supplemental_pokemon",
    "current_era", "control",
)
FACTUAL_TYPES = {"localization_counterpart", "same_artwork"}


def _identity_hash(card: sqlite3.Row | dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({key: card[key] for key in (
        "card_id", "name", "language", "set_code", "collector_number", "variant",
        "provenance", "match_eligible",
    )}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _catalog_pool(db: sqlite3.Connection) -> list[dict[str, Any]]:
    facet_counts = defaultdict(lambda: {"dex_id": 0, "illustrator": 0})
    for row in db.execute(
        "SELECT card_id, facet_type, COUNT(*) AS n FROM card_facet GROUP BY card_id, facet_type"
    ):
        facet_counts[row["card_id"]][row["facet_type"]] = row["n"]
    family_counts = Counter()
    name_sets = defaultdict(set)
    cards = []
    for row in db.execute("SELECT * FROM card WHERE language='ja' ORDER BY card_id"):
        card = dict(row)
        card["dex_count"] = facet_counts[card["card_id"]]["dex_id"]
        card["illustrator_count"] = facet_counts[card["card_id"]]["illustrator"]
        card["card_type"] = json.loads(card["attributes_json"]).get("card_type")
        card["identity_sha256"] = _identity_hash(card)
        cards.append(card)
        family_counts[(card["set_code"], card["collector_number"])] += 1
        if card["provenance"].startswith("tcgdex:"):
            name_sets[card["name"]].add(card["set_code"])
    for card in cards:
        card["family_count"] = family_counts[(card["set_code"], card["collector_number"])]
        card["name_set_count"] = len(name_sets[card["name"]])
    return cards


def _in_stratum(card: dict[str, Any], stratum: str) -> bool:
    tcgdex = card["provenance"].startswith("tcgdex:")
    supplemental = card["provenance"].startswith("ptcg-database:")
    kind = card["card_type"] or ""
    return {
        "multi_character": tcgdex and card["dex_count"] > 1,
        "trainer": supplemental and kind in {"グッズ", "サポート", "ポケモンのどうぐ", "スタジアム", "ワザマシン"},
        "energy": supplemental and "エネルギー" in kind,
        "missing_facet": tcgdex and (card["dex_count"] == 0 or card["illustrator_count"] == 0),
        "same_number_finish": tcgdex and card["family_count"] > 1 and (
            "reverse" in card["variant"] or "edition" in card["variant"]),
        "promo": tcgdex and (card["set_code"] == "S-P" or card["rarity"] == "Promo"),
        "name_reprint": tcgdex and card["name_set_count"] > 1 and card["dex_count"] == 1
                        and card["illustrator_count"] == 1,
        "supplemental_pokemon": supplemental and kind == "Pokémon" and card["match_eligible"] == 0,
        "current_era": tcgdex and card["set_code"].startswith("M") and card["dex_count"] == 1
                       and card["illustrator_count"] == 1,
        "control": tcgdex and card["match_eligible"] == 1 and card["dex_count"] == 1
                   and card["illustrator_count"] == 1 and card["family_count"] == 1,
    }[stratum]


def sample(db: sqlite3.Connection, exclude_ids: set[str], per_stratum: int = 3,
           seed: str = "relationship-coverage-v1") -> tuple[list[dict[str, Any]],
                                                               list[dict[str, Any]], dict[str, Any]]:
    if per_stratum < 1:
        raise ValueError("per_stratum must be positive")
    pool = _catalog_pool(db)
    selected = set(exclude_ids)
    anchors = []
    gold = []
    populations = {}
    for stratum in STRATA:
        eligible = [card for card in pool if _in_stratum(card, stratum)]
        populations[stratum] = len(eligible)
        eligible.sort(key=lambda card: (hashlib.sha256(
            f"{seed}\0{stratum}\0{card['card_id']}".encode()).hexdigest(), card["card_id"]))
        for card in eligible:
            if card["card_id"] in selected:
                continue
            selected.add(card["card_id"])
            anchors.append({"card_id": card["card_id"], "case": stratum,
                            "identity_sha256": card["identity_sha256"]})
            gold.append({"anchor_card_id": card["card_id"], "stratum": stratum,
                         "identity_sha256": card["identity_sha256"],
                         "review_status": "pending", "reviewers": [],
                         "anchor_evidence_ref": "", "expected": [], "rationale": ""})
            if sum(item["case"] == stratum for item in anchors) == per_stratum:
                break
    queue, probe = relationship_pilot.generate(db, anchors)
    by_anchor = Counter(row["anchor"]["card_id"] for row in queue)
    gap_by_anchor = defaultdict(list)
    for gap in probe["gaps"]:
        gap_by_anchor[gap["card_id"]].append(gap["reason"])
    audit = {
        "scope": "blind anchor selection and unlabeled candidate probe; no recall measurement",
        "seed": seed, "per_stratum": per_stratum, "catalog_ja_cards": len(pool),
        "excluded_anchor_count": len(exclude_ids), "selected_anchors": len(anchors),
        "strata": {stratum: {"population": populations[stratum],
                              "selected": sum(row["case"] == stratum for row in anchors),
                              "anchors_with_candidates": sum(bool(by_anchor[row["card_id"]])
                                  for row in anchors if row["case"] == stratum),
                              "candidate_pairs": sum(by_anchor[row["card_id"]]
                                  for row in anchors if row["case"] == stratum),
                              "gap_reasons": dict(Counter(reason
                                  for row in anchors if row["case"] == stratum
                                  for reason in gap_by_anchor[row["card_id"]]))}
                   for stratum in STRATA},
        "candidate_probe": probe,
    }
    return anchors, gold, audit


def _reviewed_gold(db: sqlite3.Connection, anchors: list[dict[str, Any]],
                   gold: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchor_by_id = {row["card_id"]: row for row in anchors}
    if len(anchor_by_id) != len(anchors) or len({row.get("anchor_card_id") for row in gold}) != len(gold):
        raise ValueError("anchor or gold rows are duplicated")
    if set(anchor_by_id) != {row.get("anchor_card_id") for row in gold}:
        raise ValueError("gold must contain every blind anchor exactly once")
    reviewed = []
    for row in gold:
        card_id = row["anchor_card_id"]
        anchor = anchor_by_id[card_id]
        card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
        if (card is None or row.get("stratum") != anchor["case"]
                or row.get("identity_sha256") != anchor["identity_sha256"]
                or row["identity_sha256"] != _identity_hash(card)):
            raise ValueError(f"stale or changed anchor identity {card_id}")
        status = row.get("review_status")
        if status == "pending":
            continue
        if status in {"identity_gap", "uncertain"}:
            if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
                raise ValueError(f"unresolved anchor needs rationale: {card_id}")
            if row.get("expected"):
                raise ValueError(f"unresolved anchor cannot assert gold targets: {card_id}")
            continue
        if status != "adjudicated":
            raise ValueError(f"unsupported review status for {card_id}")
        reviewers = row.get("reviewers")
        if (not isinstance(reviewers, list) or len(reviewers) != 2
                or any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
                       or not item["id"].strip() or item["id"] != item["id"].strip()
                       or not isinstance(item.get("reviewed_at"), str)
                       or not isinstance(item.get("answers"), list) for item in reviewers)
                or reviewers[0]["id"].casefold() == reviewers[1]["id"].casefold()):
            raise ValueError(f"adjudicated anchor needs two distinct reviewers: {card_id}")
        for reviewer in reviewers:
            parse_time(reviewer["reviewed_at"])
        if (not isinstance(row.get("anchor_evidence_ref"), str)
                or not row["anchor_evidence_ref"].strip()
                or not isinstance(row.get("rationale"), str) or not row["rationale"].strip()
                or not isinstance(row.get("expected"), list)):
            raise ValueError(f"adjudicated anchor needs evidence and rationale: {card_id}")
        seen = set()
        target_refs = {}
        for target in row["expected"]:
            if not isinstance(target, dict) or target.get("relation_type") not in FACTUAL_TYPES:
                raise ValueError(f"invalid gold relation for {card_id}")
            target_id = target.get("card_id")
            target_card = db.execute("SELECT language FROM card WHERE card_id=?", (target_id,)).fetchone()
            if (not isinstance(target_id, str) or target_card is None
                    or target_card["language"] == card["language"]
                    or not isinstance(target.get("evidence_ref"), str)
                    or not target["evidence_ref"].strip()
                    or target["evidence_ref"] == row["anchor_evidence_ref"]
                    or (target["evidence_ref"] in target_refs
                        and target_refs[target["evidence_ref"]] != target_id)
                    or (target_id, target["relation_type"]) in seen):
                raise ValueError(f"invalid gold target for {card_id}")
            seen.add((target_id, target["relation_type"]))
            target_refs[target["evidence_ref"]] = target_id
        for reviewer in reviewers:
            answers = reviewer["answers"]
            if (any(not isinstance(answer, dict) or set(answer) != {"card_id", "relation_type"}
                    or not isinstance(answer["card_id"], str)
                    or answer["relation_type"] not in FACTUAL_TYPES
                    for answer in answers)
                    or len(answers) != len(seen)
                    or {(answer["card_id"], answer["relation_type"]) for answer in answers} != seen):
                raise ValueError(f"two reviewers must agree on gold targets: {card_id}")
        reviewed.append(row)
    return reviewed


def evaluate(db: sqlite3.Connection, anchors: list[dict[str, Any]],
             gold: list[dict[str, Any]], max_per_anchor: int = 12) -> dict[str, Any]:
    reviewed = _reviewed_gold(db, anchors, gold)
    queue, probe = relationship_pilot.generate(db, anchors, max_per_anchor)
    found = defaultdict(set)
    for row in queue:
        found[row["anchor"]["card_id"]].add(row["candidate"]["card_id"])
    hits = Counter()
    totals = Counter()
    stratum_hits = Counter()
    stratum_totals = Counter()
    reviewed_by_stratum = Counter(row["stratum"] for row in reviewed)
    misses = []
    for row in reviewed:
        for target in row["expected"]:
            kind = target["relation_type"]
            totals[kind] += 1
            totals["all"] += 1
            stratum_totals[row["stratum"]] += 1
            if target["card_id"] in found[row["anchor_card_id"]]:
                hits[kind] += 1
                hits["all"] += 1
                stratum_hits[row["stratum"]] += 1
            else:
                misses.append({"anchor_card_id": row["anchor_card_id"], "stratum": row["stratum"],
                               "target_card_id": target["card_id"], "relation_type": kind,
                               "generator_gaps": [gap["reason"] for gap in probe["gaps"]
                                                  if gap["card_id"] == row["anchor_card_id"]]})
    return {
        "scope": "recall of the facet candidate generator against independently adjudicated card pairs",
        "reviewed_anchors": len(reviewed), "pending_or_excluded_anchors": len(anchors) - len(reviewed),
        "max_per_anchor": max_per_anchor,
        "pair_recall": {kind: {"gold_pairs": totals[kind], "retrieved_pairs": hits[kind],
                               "recall": hits[kind] / totals[kind] if totals[kind] else None}
                        for kind in ("localization_counterpart", "same_artwork", "all")},
        "pair_recall_by_stratum": {stratum: {
            "reviewed_anchors": reviewed_by_stratum[stratum],
            "gold_pairs": stratum_totals[stratum], "retrieved_pairs": stratum_hits[stratum],
            "recall": stratum_hits[stratum] / stratum_totals[stratum]
                      if stratum_totals[stratum] else None,
        } for stratum in STRATA},
        "misses": misses,
        "note": "Empty gold pairs do not enter the denominator; labels are supplied by reviewers, not this script",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sample_cmd = sub.add_parser("sample")
    sample_cmd.add_argument("--db", type=Path, required=True)
    sample_cmd.add_argument("--exclude-anchors", type=Path)
    sample_cmd.add_argument("--per-stratum", type=int, default=3)
    sample_cmd.add_argument("--seed", default="relationship-coverage-v1")
    sample_cmd.add_argument("--anchors", type=Path, required=True)
    sample_cmd.add_argument("--gold-template", type=Path, required=True)
    sample_cmd.add_argument("--audit", type=Path, required=True)
    eval_cmd = sub.add_parser("evaluate")
    eval_cmd.add_argument("--db", type=Path, required=True)
    eval_cmd.add_argument("--anchors", type=Path, required=True)
    eval_cmd.add_argument("--gold", type=Path, required=True)
    eval_cmd.add_argument("--max-per-anchor", type=int, default=12)
    eval_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.anchors, args.gold_template, args.audit) if args.command == "sample" else (args.output,)
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite an output")
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        if args.command == "sample":
            exclude = (set(row["card_id"] for row in relationship_pilot.read_jsonl(args.exclude_anchors))
                       if args.exclude_anchors else set())
            anchors, gold, report = sample(db, exclude, args.per_stratum, args.seed)
            relationship_pilot.write_jsonl(args.anchors, anchors)
            relationship_pilot.write_jsonl(args.gold_template, gold)
            args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        else:
            report = evaluate(db, relationship_pilot.read_jsonl(args.anchors),
                              relationship_pilot.read_jsonl(args.gold), args.max_per_anchor)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        ("selected_anchors", "strata") if args.command == "sample" else ("reviewed_anchors", "pair_recall"))},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
