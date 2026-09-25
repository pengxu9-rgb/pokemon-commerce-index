"""Schedule one card-specific relationship candidate per Japanese anchor.

Distinctive rarity, variant agreement and release proximity order review work only. They are not
evidence of shared artwork, finish, printing identity, or price equivalence.
All input candidates remain in the full queues for later review.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from scripts.relationship_pilot import read_jsonl, write_jsonl, write_review_sheet


def _release(db: sqlite3.Connection, language: str, set_code: str) -> date | None:
    row = db.execute("""SELECT release_date FROM catalog_set_localized
        WHERE language=? AND set_code=?""", (language, set_code)).fetchone()
    try:
        return date.fromisoformat(row[0]) if row and row[0] else None
    except ValueError:
        return None


def _variant_rank(anchor: str, candidate: str) -> int:
    if anchor == candidate:
        return 0
    if candidate in {"normal", "holo", "standard"}:
        return 1
    if candidate == "reverse":
        return 2
    return 3


def _rarity_rank(anchor: str | None, candidate: str | None) -> int:
    """Prefer matching distinctive rarity families; other rarities are neutral."""
    left, right = (anchor or "").casefold(), (candidate or "").casefold()
    for family in ("hyper", "ultra", "illustration", "shiny"):
        if family in left:
            return 0 if family in right else 1
    return 0


def prioritize(db: sqlite3.Connection, queues: list[list[dict[str, Any]]]
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = [row for queue in queues for row in queue]
    if len({row["candidate_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate relationship candidate")
    groups: dict[str, list[tuple[tuple[int, int, int, str], dict[str, Any], int | None]]] = defaultdict(list)
    missing_dates = 0
    for row in rows:
        anchor, candidate = row["anchor"], row["candidate"]
        if anchor["language"] != "ja" or candidate["language"] != "en":
            raise ValueError("expected Japanese to English card candidates")
        ja_date = _release(db, "ja", anchor["set_code"])
        en_date = _release(db, "en", candidate["set_code"])
        gap = abs((ja_date - en_date).days) if ja_date and en_date else None
        missing_dates += gap is None
        rank = (_rarity_rank(anchor.get("rarity"), candidate.get("rarity")),
                _variant_rank(anchor["variant"], candidate["variant"]),
                gap if gap is not None else 10**7, candidate["card_id"])
        groups[anchor["card_id"]].append((rank, row, gap))
    first = []
    rank_rows = []
    for anchor_id in sorted(groups):
        ranked = sorted(groups[anchor_id], key=lambda item: item[0])
        first.append(ranked[0][1])
        for position, (rank, row, gap) in enumerate(ranked, 1):
            rank_rows.append({
                "candidate_id": row["candidate_id"],
                "anchor_card_id": anchor_id,
                "anchor_name": row["anchor"]["name"],
                "candidate_card_id": row["candidate"]["card_id"],
                "candidate_name": row["candidate"]["name"],
                "within_anchor_rank": position,
                "anchor_variant": row["anchor"]["variant"],
                "candidate_variant": row["candidate"]["variant"],
                "anchor_rarity": row["anchor"].get("rarity"),
                "candidate_rarity": row["candidate"].get("rarity"),
                "rarity_rank": rank[0],
                "variant_rank": rank[1],
                "release_gap_days": gap,
                "review_status": "pending",
            })
    audit = {"input_pairs": len(rows), "japanese_anchors": len(groups),
             "first_pass_pairs": len(first), "remaining_pairs": len(rows)-len(first),
             "missing_release_gap_pairs": missing_dates,
             "first_pass_distinctive_rarity_mismatches": sum(
                 _rarity_rank(row["anchor"].get("rarity"), row["candidate"].get("rarity"))
                 for row in first),
             "first_pass_variant_ranks": dict(sorted(Counter(
                 _variant_rank(row["anchor"]["variant"], row["candidate"]["variant"])
                 for row in first).items())),
             "scope": "review scheduling only; no physical relationship verified"}
    return first, rank_rows, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--queues", type=Path, nargs="+", required=True)
    parser.add_argument("--first-pass", type=Path, required=True)
    parser.add_argument("--ranked", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (args.first_pass, args.ranked, args.sheet, args.audit)):
        raise FileExistsError("priority outputs must be new")
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
        first, ranked, audit = prioritize(db, [read_jsonl(path) for path in args.queues])
    write_jsonl(args.first_pass, first)
    with args.ranked.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ranked[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(ranked)
    write_review_sheet(args.sheet, first)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
