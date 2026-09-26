"""Build a reproducible, diverse JP/EN relationship candidate batch.

Every pair is retrieval-only. Shared characters, reviewed bilingual concepts,
and illustrators schedule review; they never establish shared artwork or prices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict, deque
from pathlib import Path

from scripts.relationship_coverage import _catalog_pool, _in_stratum
from scripts.relationship_pilot import generate, read_jsonl, write_jsonl, write_review_sheet

STRATA = ("multi_character", "same_number_finish", "promo", "name_reprint",
          "current_era", "control", "trainer", "energy", "missing_facet",
          "supplemental_pokemon")
SEED = "relationship-scale-batch-v1"


def _pair(row: dict) -> tuple[str, str]:
    return tuple(sorted((row["anchor"]["card_id"], row["candidate"]["card_id"])))


def _excluded(catalog: Path) -> tuple[set[tuple[str, str]], int]:
    pairs: set[tuple[str, str]] = set()
    files = 0
    for path in sorted(catalog.glob("*relationship-queue.jsonl")):
        files += 1
        for row in read_jsonl(path):
            pairs.add(_pair(row))
    return pairs, files


def _anchors(db: sqlite3.Connection, per_stratum: int) -> tuple[list[dict], dict]:
    pool = _catalog_pool(db)
    selected: set[str] = set()
    anchors: list[dict] = []
    populations = {}
    for stratum in STRATA:
        eligible = [card for card in pool if _in_stratum(card, stratum)]
        populations[stratum] = len(eligible)
        eligible.sort(key=lambda card: (
            hashlib.sha256(f"{SEED}\0{stratum}\0{card['card_id']}".encode()).hexdigest(),
            card["card_id"]))
        # Round-robin across sets before calling the existing evidence-bound
        # retriever; hot sets must not consume the whole review budget.
        by_set = defaultdict(deque)
        for card in eligible:
            if card["card_id"] not in selected:
                by_set[card["set_code"]].append(card)
        count = 0
        while by_set and count < per_stratum:
            for set_code in sorted(list(by_set)):
                card = by_set[set_code].popleft()
                if not by_set[set_code]:
                    del by_set[set_code]
                selected.add(card["card_id"])
                anchors.append({"card_id": card["card_id"], "case": stratum})
                count += 1
                if count == per_stratum:
                    break
    return anchors, populations


def select(rows: list[dict], excluded: set[tuple[str, str]], target: int,
           max_per_set: int = 80) -> tuple[list[dict], dict]:
    """Allocate first candidates across strata and anchors before second choices."""
    if target < 1 or max_per_set < 1:
        raise ValueError("target and per-set cap must be positive")
    groups = {stratum: defaultdict(deque) for stratum in STRATA}
    for row in rows:
        stratum = row["selection_reason"]
        if stratum not in groups:
            raise ValueError(f"unexpected stratum: {stratum}")
        if _pair(row) not in excluded:
            groups[stratum][row["anchor"]["card_id"]].append(row)
    selected, used, by_set = [], set(), Counter()
    active = {s: deque(sorted(anchors)) for s, anchors in groups.items() if anchors}
    while active and len(selected) < target:
        for stratum in STRATA:
            anchors = active.get(stratum)
            if not anchors:
                continue
            anchor_id = anchors.popleft()
            options = groups[stratum][anchor_id]
            while options:
                row = options.popleft()
                pair = _pair(row)
                set_code = row["anchor"]["set_code"]
                if pair in used or by_set[set_code] >= max_per_set:
                    continue
                selected.append(row)
                used.add(pair)
                by_set[set_code] += 1
                break
            if options:
                anchors.append(anchor_id)
            if not anchors:
                del active[stratum]
            if len(selected) >= target:
                break
    return selected, {"selected_pairs": len(selected),
                      "selected_by_stratum": dict(sorted(Counter(
                          r["selection_reason"] for r in selected).items())),
                      "selected_ja_sets": len(by_set),
                      "largest_ja_set_count": max(by_set.values(), default=0),
                      "selected_ja_anchors": len({r["anchor"]["card_id"] for r in selected}),
                      "offer_matching_disabled_pairs": sum(
                          not r["anchor"]["match_eligible"]
                          or not r["candidate"]["match_eligible"] for r in selected)}


def build(db: sqlite3.Connection, catalog: Path, target: int,
          per_stratum: int, max_per_set: int) -> tuple[list[dict], dict]:
    anchors, populations = _anchors(db, per_stratum)
    generated, probe = generate(db, anchors, max_per_anchor=8)
    excluded, excluded_files = _excluded(catalog)
    queue, selected = select(generated, excluded, target, max_per_set)
    if len(queue) < target:
        raise ValueError(f"only {len(queue)} distinct pairs available for target {target}")
    audit = {"scope": "internal cross-region retrieval candidates; no verified relationship, artwork, printing or price equivalence",
             "seed": SEED, "target_pairs": target,
             "per_stratum_anchor_budget": per_stratum,
             "max_pairs_per_ja_set": max_per_set,
             "source_database_cards": db.execute("SELECT COUNT(*) FROM card").fetchone()[0],
             "source_database_facets": db.execute("SELECT COUNT(*) FROM card_facet").fetchone()[0],
             "source_database_concept_revisions": db.execute("SELECT COUNT(*) FROM bilingual_concept_revision").fetchone()[0],
             "stratum_populations": populations,
             "sampled_anchors": len(anchors), "retrieved_pairs": len(generated),
             "retrieval_gap_reasons": dict(sorted(Counter(
                 gap["reason"] for gap in probe["gaps"]).items())),
             "prior_queue_files_excluded": excluded_files,
             "prior_distinct_pairs_excluded": len(excluded),
             **selected}
    return queue, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--per-stratum", type=int, default=300)
    parser.add_argument("--max-per-set", type=int, default=80)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if any(p.exists() for p in (args.output, args.sheet, args.audit)):
        raise FileExistsError("batch outputs must be new")
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        queue, audit = build(db, args.catalog, args.target, args.per_stratum,
                             args.max_per_set)
    write_jsonl(args.output, queue)
    write_review_sheet(args.sheet, queue)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, sort_keys=True,
                                    indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
