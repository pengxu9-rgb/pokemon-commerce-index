"""Make a read-only JP/EN relationship review queue from catalog facets.

Character and artist agreement retrieves candidates. It never proves shared art,
localization, or price comparability. Only completed human reviews can be
compiled into reviewed relationship assertions for a separate import step.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


DECISIONS = {
    "localization_counterpart", "same_artwork", "collecting_alternative",
    "no_relation", "identity_gap", "uncertain",
}
POSITIVE_DECISIONS = {
    "localization_counterpart", "same_artwork", "collecting_alternative",
}
REVIEW_FIELDS = (
    "decision", "reviewer", "anchor_evidence_ref", "candidate_evidence_ref",
    "artwork_note", "finish_note",
)
SHEET_FIELDS = (
    "candidate_id", "anchor_card_id", "anchor_name", "anchor_variant",
    "anchor_metadata_source_url", "anchor_match_eligible",
    "candidate_card_id", "candidate_name", "candidate_variant",
    "candidate_metadata_source_url", "candidate_match_eligible", "dex_id", "illustrator",
    "selection_reason", *REVIEW_FIELDS,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_review_sheet(path: Path, queue: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in queue:
            writer.writerow({
                "candidate_id": row["candidate_id"],
                "anchor_card_id": row["anchor"]["card_id"],
                "anchor_name": row["anchor"]["name"],
                "anchor_variant": row["anchor"]["variant"],
                "anchor_metadata_source_url": row["anchor"].get("metadata_source_url", ""),
                "anchor_match_eligible": row["anchor"]["match_eligible"],
                "candidate_card_id": row["candidate"]["card_id"],
                "candidate_name": row["candidate"]["name"],
                "candidate_variant": row["candidate"]["variant"],
                "candidate_metadata_source_url": row["candidate"].get("metadata_source_url", ""),
                "candidate_match_eligible": row["candidate"]["match_eligible"],
                "dex_id": row["shared_facets"]["dex_id"],
                "illustrator": row["shared_facets"]["illustrator"],
                "selection_reason": row.get("selection_reason", ""),
                **row["review"],
            })


def apply_review_sheet(queue: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or set(reader.fieldnames) != set(SHEET_FIELDS):
            raise ValueError("review sheet columns do not match the generated template")
        decisions = {}
        for row in reader:
            candidate_id = row["candidate_id"]
            if candidate_id in decisions:
                raise ValueError(f"duplicate candidate_id {candidate_id} in review sheet")
            decisions[candidate_id] = row
    if set(decisions) != {row["candidate_id"] for row in queue}:
        raise ValueError("review sheet must contain every generated candidate exactly once")
    for row in queue:
        sheet = decisions[row["candidate_id"]]
        if (sheet["anchor_card_id"] != row["anchor"]["card_id"]
                or sheet["candidate_card_id"] != row["candidate"]["card_id"]):
            raise ValueError(f"candidate identities changed for {row['candidate_id']}")
        row["review"] = {field: sheet[field].strip() for field in REVIEW_FIELDS}
    return queue


def _facets(db: sqlite3.Connection, card_id: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {"dex_id": [], "illustrator": []}
    for row in db.execute(
        """SELECT facet_type, value, provenance, rights_reference FROM card_facet
        WHERE card_id=? ORDER BY facet_type, value""", (card_id,)
    ):
        result[row["facet_type"]].append({key: row[key] for key in
                                          ("value", "provenance", "rights_reference")})
    return result


def _card(db: sqlite3.Connection, card_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown anchor {card_id!r}")
    return row


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    result = {key: row[key] for key in (
        "card_id", "language", "set_code", "collector_number", "variant",
        "name", "rarity", "provenance", "rights_reference", "match_eligible",
        "display_allowed",
    )}
    provenance = row["provenance"]
    if provenance.startswith("tcgdex:") and ":sha256:" in provenance:
        revision, source_path = provenance.split(":sha256:", 1)[0].split(":", 2)[1:]
        result["metadata_source_url"] = (
            f"https://github.com/tcgdex/cards-database/blob/{revision}/{quote(source_path, safe='/')}"
        )
    return result


def generate(db: sqlite3.Connection, anchors: list[dict[str, Any]],
             max_per_anchor: int = 12) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_per_anchor < 1:
        raise ValueError("max_per_anchor must be positive")
    queue: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor_input in anchors:
        card_id = anchor_input.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("each anchor needs card_id")
        if card_id in seen:
            raise ValueError(f"duplicate anchor {card_id}")
        seen.add(card_id)
        anchor = _card(db, card_id)
        if anchor["language"] not in {"ja", "en"}:
            raise ValueError(f"unsupported anchor language for {card_id}")
        facets = _facets(db, card_id)
        dex = facets["dex_id"]
        artist = facets["illustrator"]
        if len(dex) != 1 or len(artist) != 1:
            gaps.append({"card_id": card_id, "reason": "missing_or_ambiguous_facets",
                         "dex_count": len(dex), "illustrator_count": len(artist)})
            continue
        other_language = "en" if anchor["language"] == "ja" else "ja"
        matches = db.execute(
            """SELECT DISTINCT c.* FROM card c
            JOIN card_facet d ON d.card_id=c.card_id AND d.facet_type='dex_id' AND d.value=?
            JOIN card_facet i ON i.card_id=c.card_id AND i.facet_type='illustrator'
                AND i.value=? COLLATE NOCASE
            WHERE c.language=? ORDER BY c.card_id""",
            (dex[0]["value"], artist[0]["value"], other_language),
        ).fetchall()
        # Multi-character cards need their own review path; a shared one of
        # several characters is especially weak evidence of a counterpart.
        matches = [row for row in matches if len(_facets(db, row["card_id"])["dex_id"]) == 1]
        if not matches:
            gaps.append({"card_id": card_id, "reason": "no_candidate_with_character_and_artist",
                         "dex_id": dex[0]["value"], "illustrator": artist[0]["value"]})
            continue
        matches.sort(key=lambda row: (
            row["collector_number"] != anchor["collector_number"],
            row["rarity"] != anchor["rarity"], row["variant"] != anchor["variant"],
            row["card_id"],
        ))
        if len(matches) > max_per_anchor:
            gaps.append({"card_id": card_id, "reason": "candidate_list_truncated",
                         "total_candidates": len(matches), "shown": max_per_anchor})
        for candidate in matches[:max_per_anchor]:
            pair = sorted((card_id, candidate["card_id"]))
            pair_id = hashlib.sha256(("relationship-pilot-v1\0" + "\0".join(pair)).encode()).hexdigest()[:20]
            queue.append({
                "candidate_id": pair_id,
                "anchor": _summary(anchor), "candidate": _summary(candidate),
                "selection_reason": anchor_input.get("case", ""),
                "shared_facets": {
                    "dex_id": dex[0]["value"], "illustrator": artist[0]["value"],
                    "anchor_dex_provenance": dex[0]["provenance"],
                    "anchor_illustrator_provenance": artist[0]["provenance"],
                    "candidate_dex_provenance": _facets(db, candidate["card_id"])["dex_id"][0]["provenance"],
                    "candidate_illustrator_provenance": _facets(db, candidate["card_id"])["illustrator"][0]["provenance"],
                },
                "retrieval_only": True,
                "review": {
                    "decision": "pending", "reviewer": "", "anchor_evidence_ref": "",
                    "candidate_evidence_ref": "", "artwork_note": "", "finish_note": "",
                },
            })
    audit = {"anchors": len(anchors), "candidate_pairs": len(queue),
             "anchors_with_candidates": len({row["anchor"]["card_id"] for row in queue}),
             "pairs_with_offer_matching_disabled": sum(
                 not row["anchor"]["match_eligible"] or not row["candidate"]["match_eligible"]
                 for row in queue),
             "gaps": gaps, "scope": "internal retrieval queue; no relationship verified"}
    return queue, audit


def compile_reviews(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assertions = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in seen:
            raise ValueError("candidate_id missing or repeated")
        seen.add(candidate_id)
        review = row.get("review") or {}
        decision = review.get("decision")
        if decision not in DECISIONS and decision != "pending":
            raise ValueError(f"invalid review decision for {candidate_id}")
        counts[decision] = counts.get(decision, 0) + 1
        if decision in DECISIONS and (not isinstance(review.get("reviewer"), str)
                                      or not review["reviewer"].strip()):
            raise ValueError(f"review decision {candidate_id} needs a reviewer")
        if decision in {"uncertain", "identity_gap"} and not str(review.get("artwork_note") or "").strip():
            raise ValueError(f"review decision {candidate_id} needs an explanation")
        if decision == "no_relation" and any(
                not str(review.get(field) or "").strip() for field in
                ("anchor_evidence_ref", "candidate_evidence_ref", "artwork_note")):
            raise ValueError(f"negative review {candidate_id} needs two-sided evidence and an explanation")
        if decision not in POSITIVE_DECISIONS:
            continue
        fields = ("reviewer", "anchor_evidence_ref", "candidate_evidence_ref", "artwork_note", "finish_note")
        if any(not isinstance(review.get(field), str) or not review[field].strip() for field in fields):
            raise ValueError(f"positive review {candidate_id} needs reviewer and two-sided evidence, artwork and finish notes")
        if review["anchor_evidence_ref"] == review["candidate_evidence_ref"]:
            raise ValueError(f"positive review {candidate_id} needs distinct card evidence")
        if not row.get("retrieval_only") or row["anchor"]["language"] == row["candidate"]["language"]:
            raise ValueError(f"invalid cross-language candidate {candidate_id}")
        pair = sorted((row["anchor"]["card_id"], row["candidate"]["card_id"]))
        evidence = {key: review[key] for key in
                    ("anchor_evidence_ref", "candidate_evidence_ref", "artwork_note", "finish_note")}
        digest = hashlib.sha256(json.dumps(
            [candidate_id, decision, review["reviewer"], evidence],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        assertions.append({
            "assertion_id": f"relationship-pilot-{digest}",
            "left_card_id": pair[0], "right_card_id": pair[1],
            "relation_type": decision, "review_status": "verified",
            "evidence_ref": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "rights_reference": "internal-curation-only; card source rights remain separate",
            "asserted_by": "relationship-pilot-v1", "reviewer": review["reviewer"],
        })
    return assertions, {"candidate_pairs": len(rows),
                        "reviewed_candidates": len(rows) - counts.get("pending", 0),
                        "decisions": counts,
                        "verified_assertions_ready_for_import": len(assertions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("--db", type=Path, required=True)
    generate_parser.add_argument("--anchors", type=Path, required=True)
    generate_parser.add_argument("--output", type=Path, required=True)
    generate_parser.add_argument("--audit", type=Path, required=True)
    generate_parser.add_argument("--sheet", type=Path, required=True)
    generate_parser.add_argument("--max-per-anchor", type=int, default=12)
    compile_parser = sub.add_parser("compile-reviewed")
    compile_parser.add_argument("--queue", type=Path, required=True)
    compile_parser.add_argument("--reviews", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        if args.output.exists() or args.audit.exists() or args.sheet.exists():
            raise FileExistsError("output, audit, or review sheet already exists")
        uri = f"file:{args.db.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            queue, audit = generate(db, read_jsonl(args.anchors), args.max_per_anchor)
        write_jsonl(args.output, queue)
        write_review_sheet(args.sheet, queue)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False))
    else:
        queue = apply_review_sheet(read_jsonl(args.queue), args.reviews)
        assertions, audit = compile_reviews(queue)
        write_jsonl(args.output, assertions)
        print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
