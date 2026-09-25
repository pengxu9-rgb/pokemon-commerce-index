"""Prepare source-bound review proposals for names exhausted by ranked search.

Seed pairs are editorial retrieval hints. Every card name, class, subtype and
source hash is checked against the local catalog and pinned TCGdex checkout.
The packet is review input only; no alias or relationship is imported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from scripts.build_discovery_facets import SOURCE_RE
from scripts.concept_review_packet import _source_card, write_sheet
from scripts.concept_review_ranked import REVISION, _read_verified
from scripts.relationship_pilot import read_jsonl, write_jsonl


def _card(db: sqlite3.Connection, repo: Path, card_id: str, name: str,
          language: str) -> sqlite3.Row:
    row = db.execute("""SELECT c.*, cl.category AS source_category,
        cl.subtype AS source_subtype, cl.provenance AS classification_provenance,
        COALESCE(f.value, '') AS source_illustrator,
        COALESCE(f.provenance, '') AS illustrator_provenance
        FROM card c JOIN card_classification cl ON cl.card_id=c.card_id
        LEFT JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='illustrator'
        WHERE c.card_id=? AND c.language=? AND cl.provenance=c.provenance
        AND c.provenance LIKE 'tcgdex:%'""", (card_id, language)).fetchone()
    if row is None or row["name"] != name:
        raise ValueError(f"card identity or name missing: {card_id}")
    match = SOURCE_RE.fullmatch(row["provenance"])
    if not match or match.group(1) != REVISION:
        raise ValueError(f"card is not from pinned revision: {card_id}")
    source, _ = _read_verified(repo, match.group(2), match.group(3))
    if name not in source:
        raise ValueError(f"pinned source does not contain card name: {card_id}")
    return row


def build(db: sqlite3.Connection, repo: Path, seeds: list[dict[str, str]],
          excluded_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packet = []
    names: set[tuple[str, str]] = set()
    for seed in seeds:
        ja = _card(db, repo, seed["ja_card_id"], seed["name_ja"], "ja")
        en = _card(db, repo, seed["en_card_id"], seed["name_en"], "en")
        if ja["source_category"] != en["source_category"] or (
                ja["source_subtype"] and en["source_subtype"] and
                ja["source_subtype"] != en["source_subtype"]):
            raise ValueError(f"card class mismatch: {seed['name_ja']}")
        key = (ja["source_category"], ja["name"])
        if key in names:
            raise ValueError(f"duplicate Japanese name: {key}")
        names.add(key)
        ja_source, en_source = _source_card(ja), _source_card(en)
        frozen = {
            "category": ja["source_category"], "subtype": ja["source_subtype"] or "",
            "proposal_signal": "editorial_gap_search_title_and_effect_candidate",
            "illustrator": ja["source_illustrator"],
            "candidate_illustrator": en["source_illustrator"],
            "omitted_name_count": 0,
            "name_ja": ja["name"], "name_en": en["name"],
            "ja_card_id": ja["card_id"], "en_card_id": en["card_id"],
            "source_ja": ja_source["metadata_source_url"],
            "source_en": en_source["metadata_source_url"],
            "ja_match_eligible": ja["match_eligible"],
            "en_match_eligible": en["match_eligible"],
        }
        frozen["proposal_id"] = hashlib.sha256((
            "concept-proposal-v1\0" + "\0".join((
                frozen["category"], ja["name"], en["name"])))
            .encode()).hexdigest()[:20]
        if frozen["proposal_id"] in excluded_ids:
            raise ValueError(f"candidate was already reviewed: {frozen['proposal_id']}")
        snapshot = {
            "frozen": frozen, "ja_provenance": ja["provenance"],
            "en_provenance": en["provenance"],
            "ja_classification": ja["classification_provenance"],
            "en_classification": en["classification_provenance"],
            "ja_illustrator": ja["illustrator_provenance"],
            "en_illustrator": en["illustrator_provenance"],
            "ja_rights": ja["rights_reference"],
            "en_rights": en["rights_reference"],
            "rescue_context": {"prior_pool": "concept-review-v6-full-queue",
                               "candidate_source": "editorial title and rule-text search",
                               "seed_note": seed.get("seed_note", "")},
        }
        digest = hashlib.sha256(json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        packet.append({**frozen, "source_snapshot_sha256": digest,
                       "source_snapshot": snapshot,
                       "ja_provenance": ja["provenance"],
                       "en_provenance": en["provenance"],
                       "rights_reference": ja["rights_reference"],
                       "retrieval_only": True})
    return packet, {"proposal_rows": len(packet), "unique_ja_names": len(names),
                    "source_revision": REVISION,
                    "scope": "editorial retrieval hints for independent review only; no translation or physical printing verified"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--exclude-queue", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (args.queue, args.sheet, args.audit)):
        raise FileExistsError("gap review outputs must be new files")
    repo = args.repo.resolve()
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != REVISION:
        raise ValueError("source checkout does not match pinned revision")
    excluded = {row["proposal_id"] for row in read_jsonl(args.exclude_queue)}
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        packet, audit = build(db, repo, read_jsonl(args.seeds), excluded)
    write_jsonl(args.queue, packet)
    write_sheet(args.sheet, packet)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
