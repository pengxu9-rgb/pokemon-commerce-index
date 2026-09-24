"""Prepare and compile a human-review packet for bilingual card-name concepts.

Shared artist and card class only shortlist possible translations. They do not
approve an alias or assert a cross-region printing relationship.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pokemon_index.core import parse_time
from scripts.relationship_pilot import _summary, read_jsonl, write_jsonl

FROZEN_FIELDS = (
    "proposal_id", "source_snapshot_sha256", "category", "subtype", "proposal_signal", "illustrator",
    "name_ja", "name_en", "ja_card_id", "en_card_id", "source_ja", "source_en",
)
REVIEW_FIELDS = ("decision", "reviewer", "reviewed_at", "ja_identity_checked",
                 "en_identity_checked", "translation_checked", "evidence_note")
SHEET_FIELDS = (*FROZEN_FIELDS, *REVIEW_FIELDS)
DECISIONS = {"pending", "approve", "reject", "uncertain"}

# Editorial hints to find source records for review. These are NOT approved
# translations and must not be imported without a human checking both cards.
ENERGY_NAME_HINTS = {
    "ルミナスエネルギー": "Luminous Energy",
    "トリプル加速エネルギー": "Triple Acceleration Energy",
    "レガシーエネルギー": "Legacy Energy",
    "ダブルアクアエネルギー": "Double Aqua Energy",
    "ミストエネルギー": "Mist Energy",
    "メディカルエネルギー": "Medical Energy",
    "ブーメランエネルギー": "Boomerang Energy",
    "ダブルマグマエネルギー": "Double Magma Energy",
    "ダブルドラゴンエネルギー": "Double Dragon Energy",
}


def _source_card(row: sqlite3.Row) -> dict[str, Any]:
    summary = _summary(row)
    if not summary.get("metadata_source_url") or not row["provenance"].startswith("tcgdex:"):
        raise ValueError(f"card lacks pinned TCGdex source: {row['card_id']}")
    return summary


def _classified_artist_cards(db: sqlite3.Connection, language: str,
                             category: str) -> list[sqlite3.Row]:
    return db.execute("""SELECT c.*,
        cl.category AS source_category, cl.subtype AS source_subtype,
        cl.provenance AS classification_provenance,
        f.value AS source_illustrator, f.provenance AS illustrator_provenance
        FROM card c JOIN card_classification cl ON cl.card_id=c.card_id
        JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='illustrator'
        WHERE c.language=? AND cl.category=? AND c.match_eligible=1
        AND c.provenance LIKE 'tcgdex:%' ORDER BY c.card_id""",
        (language, category),
    ).fetchall()


def _energy_hint_candidates(db: sqlite3.Connection, excluded_names: set[str]
                            ) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
    pairs = []
    for name_ja, name_en in ENERGY_NAME_HINTS.items():
        if name_ja in excluded_names:
            continue
        ja = db.execute("""SELECT c.*, cl.category AS source_category,
            cl.subtype AS source_subtype, cl.provenance AS classification_provenance,
            COALESCE(f.value, '') AS source_illustrator,
            COALESCE(f.provenance, '') AS illustrator_provenance
            FROM card c JOIN card_classification cl ON cl.card_id=c.card_id
            LEFT JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='illustrator'
            WHERE c.language='ja' AND c.name=? AND cl.category='Energy'
            AND c.match_eligible=1 AND c.provenance LIKE 'tcgdex:%'
            ORDER BY c.card_id LIMIT 1""", (name_ja,)).fetchone()
        en = db.execute("""SELECT c.*, cl.category AS source_category,
            cl.subtype AS source_subtype, cl.provenance AS classification_provenance,
            COALESCE(f.value, '') AS source_illustrator,
            COALESCE(f.provenance, '') AS illustrator_provenance
            FROM card c JOIN card_classification cl ON cl.card_id=c.card_id
            LEFT JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='illustrator'
            WHERE c.language='en' AND c.name=? AND cl.category='Energy'
            AND c.match_eligible=1 AND c.provenance LIKE 'tcgdex:%'
            ORDER BY c.card_id LIMIT 1""", (name_en,)).fetchone()
        if ja and en and (ja["source_subtype"] == en["source_subtype"]
                          or ja["source_subtype"] is None or en["source_subtype"] is None):
            pairs.append((ja, [en]))
    return pairs


def build(db: sqlite3.Connection, excluded_anchor_ids: set[str],
          trainer_limit: int = 16, energy_limit: int = 8,
          max_names_per_anchor: int = 5, seed: str = "concept-review-v1"
          ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if min(trainer_limit, energy_limit) < 0 or max_names_per_anchor < 1:
        raise ValueError("limits must be nonnegative and candidate cap positive")
    excluded_names = {row["name"] for card_id in excluded_anchor_ids
                      if (row := db.execute("SELECT name FROM card WHERE card_id=?", (card_id,)).fetchone())}
    packet = []
    audit: dict[str, Any] = {"seed": seed, "excluded_card_ids": len(excluded_anchor_ids),
                             "excluded_name_count": len(excluded_names), "by_category": {}}
    for category, limit in (("Trainer", trainer_limit), ("Energy", energy_limit)):
        english = _classified_artist_cards(db, "en", category)
        by_artist: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in english:
            by_artist[row["source_illustrator"].casefold()].append(row)
        japanese = _classified_artist_cards(db, "ja", category)
        by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in japanese:
            if row["name"] not in excluded_names:
                by_name[row["name"]].append(row)
        eligible = []
        gap_counts = Counter()
        for name, anchors in by_name.items():
            options = []
            for anchor in anchors:
                matching = [row for row in by_artist.get(anchor["source_illustrator"].casefold(), [])
                            if (row["source_subtype"] is None or anchor["source_subtype"] is None
                                or row["source_subtype"] == anchor["source_subtype"])]
                by_english_name = {}
                for row in matching:
                    by_english_name.setdefault(row["name"], row)
                if by_english_name:
                    options.append((anchor, [by_english_name[key] for key in sorted(by_english_name)]))
            if not options:
                gap_counts["no_shared_artist_class_candidate"] += 1
                continue
            options.sort(key=lambda item: (len(item[1]), item[0]["card_id"]))
            anchor, candidates = options[0]
            if len(candidates) > max_names_per_anchor:
                gap_counts["too_many_candidate_names"] += 1
                continue
            eligible.append((anchor, candidates))
        if category == "Energy":
            eligible = _energy_hint_candidates(db, excluded_names)
            gap_counts = Counter()
        eligible.sort(key=lambda item: hashlib.sha256(
            f"{seed}\0{category}\0{item[0]['name']}".encode()).hexdigest())
        chosen = eligible[:limit]
        for anchor, candidates in chosen:
            ja = _source_card(anchor)
            for candidate in candidates:
                en = _source_card(candidate)
                frozen = {
                    "category": category, "subtype": anchor["source_subtype"] or "",
                    "proposal_signal": ("editorial_name_hint" if category == "Energy"
                                        else "same_illustrator_and_class"),
                    "illustrator": anchor["source_illustrator"],
                    "name_ja": anchor["name"], "name_en": candidate["name"],
                    "ja_card_id": anchor["card_id"], "en_card_id": candidate["card_id"],
                    "source_ja": ja["metadata_source_url"],
                    "source_en": en["metadata_source_url"],
                }
                frozen["proposal_id"] = hashlib.sha256((
                    "concept-proposal-v1\0" + "\0".join((category, anchor["name"], candidate["name"]))
                ).encode()).hexdigest()[:20]
                snapshot = {"frozen": frozen,
                            "ja_provenance": anchor["provenance"],
                            "en_provenance": candidate["provenance"],
                            "ja_classification": anchor["classification_provenance"],
                            "en_classification": candidate["classification_provenance"],
                            "ja_illustrator": anchor["illustrator_provenance"],
                            "en_illustrator": candidate["illustrator_provenance"],
                            "ja_rights": anchor["rights_reference"],
                            "en_rights": candidate["rights_reference"]}
                digest = hashlib.sha256(json.dumps(
                    snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                packet.append({**frozen, "source_snapshot_sha256": digest,
                               "ja_provenance": anchor["provenance"],
                               "en_provenance": candidate["provenance"],
                               "rights_reference": anchor["rights_reference"],
                               "retrieval_only": True})
        audit["by_category"][category] = {
            "proposal_strategy": ("editorial_name_hint" if category == "Energy"
                                  else "same_illustrator_and_class"),
            "source_ja_names_with_artist": len(by_name),
            "eligible_ja_names": len(eligible), "selected_ja_names": len(chosen),
            "candidate_rows": sum(len(candidates) for _, candidates in chosen),
            "gap_counts": dict(sorted(gap_counts.items())),
        }
    audit["proposal_rows"] = len(packet)
    audit["scope"] = "pending human translation review; no approved aliases or printing edges"
    return packet, audit


def write_sheet(path: Path, packet: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in packet:
            writer.writerow({**{key: row[key] for key in FROZEN_FIELDS},
                             **{key: "" for key in REVIEW_FIELDS},
                             "decision": "pending"})


def compile_sheet(packet: list[dict[str, Any]], path: Path
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(SHEET_FIELDS) or set(reader.fieldnames) != set(SHEET_FIELDS):
            raise ValueError("review sheet columns differ from template")
        decisions = {}
        for row in reader:
            proposal_id = row["proposal_id"]
            if proposal_id in decisions:
                raise ValueError("duplicate proposal_id in review sheet")
            decisions[proposal_id] = row
    if set(decisions) != {row["proposal_id"] for row in packet}:
        raise ValueError("review sheet must retain every proposal exactly once")
    imports = []
    selected_ja = set()
    selected_en = set()
    counts = Counter()
    for proposal in packet:
        review = decisions[proposal["proposal_id"]]
        if any(review[field] != str(proposal[field]) for field in FROZEN_FIELDS):
            raise ValueError(f"frozen evidence changed for {proposal['proposal_id']}")
        decision = review["decision"].strip().lower()
        if decision not in DECISIONS:
            raise ValueError(f"invalid decision for {proposal['proposal_id']}")
        counts[decision] += 1
        if decision == "pending":
            continue
        if not all(review[field].strip() for field in ("reviewer", "reviewed_at", "evidence_note")):
            raise ValueError("review decision requires reviewer, timestamp and evidence note")
        parse_time(review["reviewed_at"])
        if decision != "approve":
            continue
        if any(review[field].strip().lower() not in {"yes", "true", "1"} for field in (
                "ja_identity_checked", "en_identity_checked", "translation_checked")):
            raise ValueError("approval requires both card identities and translation checked")
        ja_key = (proposal["category"], proposal["name_ja"])
        en_key = (proposal["category"], proposal["name_en"])
        if ja_key in selected_ja or en_key in selected_en:
            raise ValueError("conflicting approved concept names in review sheet")
        selected_ja.add(ja_key)
        selected_en.add(en_key)
        if not proposal["source_ja"].startswith("https://github.com/tcgdex/cards-database/blob/") or not proposal[
                "source_en"].startswith("https://github.com/tcgdex/cards-database/blob/"):
            raise ValueError("approval requires pinned card-specific sources")
        imports.append({
            "concept_id": "concept-" + hashlib.sha256((
                proposal["category"] + "\0" + proposal["name_ja"]
            ).encode()).hexdigest()[:20],
            "revision": 1, "category": proposal["category"],
            "name_ja": proposal["name_ja"], "name_en": proposal["name_en"],
            "source_ja": proposal["source_ja"], "source_en": proposal["source_en"],
            "rights_reference": proposal["rights_reference"],
            "reviewer": review["reviewer"].strip(),
            "reviewed_at": parse_time(review["reviewed_at"]).isoformat(),
            "status": "approved",
        })
    return imports, {"proposal_rows": len(packet), "decisions": dict(sorted(counts.items())),
                     "approved_import_rows": len(imports),
                     "scope": "reviewed concept names only; no printing relationship verified"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--db", type=Path, required=True)
    build_cmd.add_argument("--exclude-anchors", type=Path, action="append", default=[])
    build_cmd.add_argument("--trainer-limit", type=int, default=16)
    build_cmd.add_argument("--energy-limit", type=int, default=8)
    build_cmd.add_argument("--max-names-per-anchor", type=int, default=5)
    build_cmd.add_argument("--queue", type=Path, required=True)
    build_cmd.add_argument("--sheet", type=Path, required=True)
    build_cmd.add_argument("--audit", type=Path, required=True)
    compile_cmd = sub.add_parser("compile-reviewed")
    compile_cmd.add_argument("--queue", type=Path, required=True)
    compile_cmd.add_argument("--sheet", type=Path, required=True)
    compile_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        if any(path.exists() for path in (args.queue, args.sheet, args.audit)):
            raise FileExistsError("packet output exists")
        exclude = {row["card_id"] for path in args.exclude_anchors for row in read_jsonl(path)}
        with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            packet, audit = build(db, exclude, args.trainer_limit, args.energy_limit,
                                  args.max_names_per_anchor)
        write_jsonl(args.queue, packet)
        write_sheet(args.sheet, packet)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(audit, ensure_ascii=False))
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        imports, audit = compile_sheet(read_jsonl(args.queue), args.sheet)
        write_jsonl(args.output, imports)
        print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
