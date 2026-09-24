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
    "proposal_id", "source_snapshot_sha256", "category", "subtype", "proposal_signal",
    "illustrator", "candidate_illustrator", "omitted_name_count",
    "name_ja", "name_en", "ja_card_id", "en_card_id", "source_ja", "source_en",
    "ja_match_eligible", "en_match_eligible",
)
REVIEW_FIELDS = ("review_revision", "decision", "reviewer", "reviewed_at",
                 "ja_identity_checked", "en_identity_checked", "translation_checked",
                 "evidence_note", "extra_source_ja", "extra_source_en")
SHEET_FIELDS = (*FROZEN_FIELDS, *REVIEW_FIELDS)
DECISIONS = {"pending", "approve", "reject", "uncertain"}

# These are retrieval hints for the specific v1 gaps, not reviewed aliases.
TRAINER_NAME_HINTS = {
    "ルリナ": "Nessa",
    "ツツジ": "Roxanne",
    "マスタード れんげきのかた": "Rapid Strike Style Mustard",
    "マグマ団のしたっぱ": "Team Magma Grunt",
}

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
        WHERE c.language=? AND cl.category=? AND c.provenance LIKE 'tcgdex:%'
        AND cl.provenance=c.provenance AND f.provenance=c.provenance
        ORDER BY c.card_id""",
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
            AND cl.provenance=c.provenance AND c.provenance LIKE 'tcgdex:%'
            ORDER BY c.card_id LIMIT 1""", (name_ja,)).fetchone()
        en = db.execute("""SELECT c.*, cl.category AS source_category,
            cl.subtype AS source_subtype, cl.provenance AS classification_provenance,
            COALESCE(f.value, '') AS source_illustrator,
            COALESCE(f.provenance, '') AS illustrator_provenance
            FROM card c JOIN card_classification cl ON cl.card_id=c.card_id
            LEFT JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='illustrator'
            WHERE c.language='en' AND c.name=? AND cl.category='Energy'
            AND cl.provenance=c.provenance AND c.provenance LIKE 'tcgdex:%'
            ORDER BY c.card_id LIMIT 1""", (name_en,)).fetchone()
        if ja and en and (ja["source_subtype"] == en["source_subtype"]
                          or ja["source_subtype"] is None or en["source_subtype"] is None):
            pairs.append((ja, [en]))
    return pairs


def build(db: sqlite3.Connection, excluded_anchor_ids: set[str],
          trainer_limit: int = 16, energy_limit: int = 8,
          max_names_per_anchor: int = 5, seed: str = "concept-review-v2",
          include_names: set[str] | None = None,
          preserve_pairs: set[tuple[str, str, str]] | None = None,
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
            if row["name"] not in excluded_names and (include_names is None or row["name"] in include_names):
                by_name[row["name"]].append(row)
        eligible: list[tuple[list[tuple[sqlite3.Row, sqlite3.Row, str]], int]] = []
        gap_counts = Counter()
        missing_hint_names = []
        for name, anchors in by_name.items():
            evidence: dict[str, list[tuple[sqlite3.Row, sqlite3.Row, str]]] = defaultdict(list)
            for anchor in anchors:
                matching = [row for row in by_artist.get(anchor["source_illustrator"].casefold(), [])
                            if (row["source_subtype"] is None or anchor["source_subtype"] is None
                                or row["source_subtype"] == anchor["source_subtype"])]
                for row in matching:
                    evidence[row["name"]].append((anchor, row, "same_illustrator_and_class"))
            hint = TRAINER_NAME_HINTS.get(name) if category == "Trainer" else None
            if hint:
                hinted = [row for row in english if row["name"] == hint and (
                    row["source_subtype"] is None or anchors[0]["source_subtype"] is None
                    or row["source_subtype"] == anchors[0]["source_subtype"])]
                if hinted:
                    for candidate in hinted:
                        anchor = next((row for row in anchors if row["source_illustrator"].casefold()
                                       == candidate["source_illustrator"].casefold()), anchors[0])
                        signal = ("editorial_name_hint_and_illustrator" if anchor[
                            "source_illustrator"].casefold() == candidate["source_illustrator"].casefold()
                                  else "editorial_name_hint")
                        evidence[hint].append((anchor, candidate, signal))
                else:
                    gap_counts["hint_without_pinned_english_source"] += 1
                    missing_hint_names.append(name)
            if not evidence:
                gap_counts["no_source_backed_candidate"] += 1
                continue
            ranked = sorted(evidence, key=lambda english_name: (
                english_name != hint,
                -len({pair[0]["source_illustrator"].casefold() for pair in evidence[english_name]}),
                -max(pair[1]["match_eligible"] for pair in evidence[english_name]),
                english_name,
            ))
            if preserve_pairs is not None and category == "Trainer":
                keep = {english_name for english_name in ranked
                        if (category, name, english_name) in preserve_pairs or english_name == hint}
                missing = {english_name for cat, ja_name, english_name in preserve_pairs
                           if cat == category and ja_name == name and english_name not in evidence}
                if missing:
                    raise ValueError(f"previous candidate evidence missing for {name}: {sorted(missing)}")
                ranked_selected = [english_name for english_name in ranked if english_name in keep]
            else:
                ranked_selected = ranked[:max_names_per_anchor]
            if len(ranked) > max_names_per_anchor and preserve_pairs is None:
                if include_names is None:
                    gap_counts["too_many_candidate_names"] += 1
                    continue
                gap_counts["candidate_names_truncated"] += 1
            selected = []
            for english_name in ranked_selected:
                choices = sorted(evidence[english_name], key=lambda pair: (
                    pair[2] != "editorial_name_hint_and_illustrator",
                    pair[2] != "same_illustrator_and_class",
                    -pair[0]["match_eligible"], -pair[1]["match_eligible"],
                    pair[0]["card_id"], pair[1]["card_id"],
                ))
                selected.append(choices[0])
            eligible.append((selected, len(ranked) - len(selected)))
        if category == "Energy":
            eligible = [([(anchor, candidate, "editorial_name_hint")], 0)
                        for anchor, candidates in _energy_hint_candidates(db, excluded_names)
                        if include_names is None or anchor["name"] in include_names
                        for candidate in candidates]
            gap_counts = Counter()
        eligible.sort(key=lambda item: hashlib.sha256(
            f"{seed}\0{category}\0{item[0][0][0]['name']}".encode()).hexdigest())
        chosen = eligible[:limit]
        for candidate_pairs, omitted_count in chosen:
            for anchor, candidate, signal in candidate_pairs:
                ja = _source_card(anchor)
                en = _source_card(candidate)
                frozen = {
                    "category": category, "subtype": anchor["source_subtype"] or "",
                    "proposal_signal": signal,
                    "illustrator": anchor["source_illustrator"],
                    "candidate_illustrator": candidate["source_illustrator"],
                    "omitted_name_count": omitted_count,
                    "name_ja": anchor["name"], "name_en": candidate["name"],
                    "ja_card_id": anchor["card_id"], "en_card_id": candidate["card_id"],
                    "source_ja": ja["metadata_source_url"],
                    "source_en": en["metadata_source_url"],
                    "ja_match_eligible": anchor["match_eligible"],
                    "en_match_eligible": candidate["match_eligible"],
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
                               "source_snapshot": snapshot,
                               "ja_provenance": anchor["provenance"],
                               "en_provenance": candidate["provenance"],
                               "rights_reference": anchor["rights_reference"],
                               "retrieval_only": True})
        audit["by_category"][category] = {
            "proposal_strategy": ("editorial_name_hint" if category == "Energy"
                                  else "pooled_illustrators_with_editorial_hints"),
            "source_ja_names_with_artist": len(by_name),
            "eligible_ja_names": len(eligible), "selected_ja_names": len(chosen),
            "candidate_rows": sum(len(pairs) for pairs, _ in chosen),
            "truncated_selected_names": sum(omitted > 0 for _, omitted in chosen),
            "hint_without_pinned_english_source": sorted(missing_hint_names),
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
                             "review_revision": "1", "decision": "pending"})


def compile_sheet(packet: list[dict[str, Any]], path: Path
                  ) -> tuple[dict[str, Any], dict[str, Any]]:
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
    events = []
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
        reviewed_at = parse_time(review["reviewed_at"]).isoformat()
        if not review["review_revision"].isdigit() or int(review["review_revision"]) < 1:
            raise ValueError("review decision needs positive review_revision")
        attestations = {field: review[field].strip().lower() in {"yes", "true", "1"} for field in (
            "ja_identity_checked", "en_identity_checked", "translation_checked")}
        if decision == "approve" and not all(attestations.values()):
            raise ValueError("approval requires both card identities and translation checked")
        for field in ("extra_source_ja", "extra_source_en"):
            if review[field].strip() and not review[field].strip().startswith(("https://", "http://")):
                raise ValueError("additional card evidence must be an HTTP(S) URL")
        reviewed = {
            "review_revision": int(review["review_revision"]), "decision": decision,
            "reviewer": review["reviewer"].strip(), "reviewed_at": reviewed_at,
            **attestations, "evidence_note": review["evidence_note"].strip(),
            "extra_source_ja": review["extra_source_ja"].strip(),
            "extra_source_en": review["extra_source_en"].strip(),
        }
        event = {"schema": "pokemon.concept_review.v1", "proposal": proposal,
                 "review": reviewed}
        event["event_id"] = hashlib.sha256(json.dumps(
            event, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        events.append(event)
        if decision != "approve":
            continue
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
            "reviewed_at": reviewed_at,
            "status": "approved", "review_event_id": event["event_id"],
        })
    audit = {"proposal_rows": len(packet), "decisions": dict(sorted(counts.items())),
             "retained_review_events": len(events), "approved_import_rows": len(imports),
             "scope": "reviewed concept names only; no printing relationship verified"}
    return {"schema": "pokemon.concept_review_bundle.v1", "review_events": events,
            "concept_revisions": imports, "audit": audit}, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--db", type=Path, required=True)
    build_cmd.add_argument("--exclude-anchors", type=Path, action="append", default=[])
    build_cmd.add_argument("--include-names-from", type=Path,
                           help="keep the Japanese names in an earlier proposal queue")
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
        earlier = read_jsonl(args.include_names_from) if args.include_names_from else None
        include_names = {row["name_ja"] for row in earlier} if earlier is not None else None
        preserve_pairs = ({(row["category"], row["name_ja"], row["name_en"])
                           for row in earlier} if earlier is not None else None)
        with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            packet, audit = build(db, exclude, args.trainer_limit, args.energy_limit,
                                  args.max_names_per_anchor, include_names=include_names,
                                  preserve_pairs=preserve_pairs)
        write_jsonl(args.queue, packet)
        write_sheet(args.sheet, packet)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(audit, ensure_ascii=False))
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        bundle, audit = compile_sheet(read_jsonl(args.queue), args.sheet)
        args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
