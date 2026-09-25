"""Build a bounded review packet from high-ambiguity Trainer name pools.

Ranking uses only pinned source metadata: illustrator, Trainer subtype,
release dates, series era, and numerals in rule text. It never approves a
translation or asserts a physical printing relationship.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from pokemon_index import tcgdex_source
from scripts.build_discovery_facets import SOURCE_RE
from scripts.concept_review_packet import _classified_artist_cards, _source_card, write_sheet
from scripts.relationship_pilot import read_jsonl, write_jsonl

REVISION = "a211f11f3ba57d56c65c5ac33be35b77d3280757"
ERA_EN = {"Sun & Moon": "SM", "Sword & Shield": "S",
          "Scarlet & Violet": "SV", "Mega Evolution": "M"}


def _read_verified(repo: Path, path: str, expected_sha: str | None) -> tuple[str, str]:
    source = (repo / path).resolve()
    if not source.is_relative_to(repo.resolve()):
        raise ValueError("source path leaves pinned checkout")
    body = source.read_bytes()
    actual_sha = hashlib.sha256(body).hexdigest()
    if expected_sha and actual_sha != expected_sha:
        raise ValueError(f"source hash mismatch: {path}")
    return body.decode("utf-8"), actual_sha


def _features(db: sqlite3.Connection, repo: Path, row: sqlite3.Row,
              cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    provenance = row["provenance"]
    if provenance in cache:
        return cache[provenance]
    match = SOURCE_RE.fullmatch(provenance)
    if not match or match.group(1) != REVISION:
        raise ValueError(f"card is not from pinned source: {row['card_id']}")
    path, expected_sha = match.group(2), match.group(3)
    source, _ = _read_verified(repo, path, expected_sha)
    effect_body = tcgdex_source._object_field(source, "effect", "{", "}") or ""
    effect = tcgdex_source._string_field(effect_body, row["language"]) or ""
    numbers = sorted(set(re.findall(r"(?<![0-9])[0-9]{1,3}(?![0-9])", effect)))
    set_row = db.execute(
        "SELECT provenance FROM catalog_set_localized WHERE language=? AND set_code=?",
        (row["language"], row["set_code"]),
    ).fetchone()
    set_provenance = set_row["provenance"] if set_row else ""
    set_sha = ""
    release = None
    if set_provenance.startswith(f"tcgdex:{REVISION}:"):
        set_path = set_provenance.split(":", 2)[2]
        set_source, set_sha = _read_verified(repo, set_path, None)
        raw_date = tcgdex_source._string_field(set_source, "releaseDate")
        if raw_date:
            try:
                release = date.fromisoformat(raw_date)
            except ValueError:
                pass
    series = path.split("/")[1]
    era = ERA_EN.get(series) if row["language"] == "en" else series
    result = {"effect_numbers": numbers, "release_date": release,
              "source_path": path, "set_provenance": set_provenance,
              "set_source_sha256": set_sha, "era": era}
    cache[provenance] = result
    return result


def _score(ja: dict[str, Any], en: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    a, b = set(ja["effect_numbers"]), set(en["effect_numbers"])
    number_score = 0.0
    if a and b:
        common = a & b
        number_score = 2.0 * len(common) / len(a | b) if common else -0.5
    days = None
    date_score = 0.0
    if ja["release_date"] and en["release_date"]:
        days = abs((ja["release_date"] - en["release_date"]).days)
        date_score = 2.0 / (1.0 + days / 200.0)
    era_score = 0.5 if ja["era"] == en["era"] and ja["era"] in {
        "SM", "S", "SV", "M"} else 0.0
    parts = {"ja_effect_numbers": sorted(a), "en_effect_numbers": sorted(b),
             "release_gap_days": days, "number_score": round(number_score, 6),
             "date_score": round(date_score, 6), "era_score": era_score}
    return number_score + date_score + era_score, parts


def build(db: sqlite3.Connection, repo: Path, excluded_names: set[str],
          limit_names: int = 25, candidates_per_name: int = 5,
          seed: str = "concept-review-v4") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if limit_names < 1 or candidates_per_name < 1:
        raise ValueError("limits must be positive")
    english = _classified_artist_cards(db, "en", "Trainer")
    japanese = _classified_artist_cards(db, "ja", "Trainer")
    by_artist: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in english:
        by_artist[row["source_illustrator"].casefold()].append(row)
    for row in japanese:
        if row["name"] not in excluded_names:
            by_name[row["name"]].append(row)
    feature_cache: dict[str, dict[str, Any]] = {}
    eligible = []
    gaps = Counter()
    for name, anchors in by_name.items():
        candidate_pairs: dict[str, list[tuple[float, sqlite3.Row, sqlite3.Row, dict[str, Any]]]] = defaultdict(list)
        for anchor in anchors:
            for candidate in by_artist[anchor["source_illustrator"].casefold()]:
                if (anchor["source_subtype"] and candidate["source_subtype"] and
                        anchor["source_subtype"] != candidate["source_subtype"]):
                    continue
                ja_features = _features(db, repo, anchor, feature_cache)
                en_features = _features(db, repo, candidate, feature_cache)
                score, parts = _score(ja_features, en_features)
                parts.update({"ja_release_date": ja_features["release_date"].isoformat()
                              if ja_features["release_date"] else None,
                              "en_release_date": en_features["release_date"].isoformat()
                              if en_features["release_date"] else None,
                              "ja_set_provenance": ja_features["set_provenance"],
                              "en_set_provenance": en_features["set_provenance"],
                              "ja_set_source_sha256": ja_features["set_source_sha256"],
                              "en_set_source_sha256": en_features["set_source_sha256"]})
                candidate_pairs[candidate["name"]].append((score, anchor, candidate, parts))
        if len(candidate_pairs) <= 4:
            gaps["not_high_ambiguity"] += 1
            continue
        best = {}
        for english_name, pairs in candidate_pairs.items():
            best[english_name] = sorted(pairs, key=lambda item: (
                -item[0], -item[1]["match_eligible"], -item[2]["match_eligible"],
                item[1]["card_id"], item[2]["card_id"],
            ))[0]
        ranked = sorted(best, key=lambda item: (-best[item][0], item))
        if best[ranked[0]][0] < 3.0:
            gaps["weak_top_score"] += 1
            continue
        if len(ranked) > candidates_per_name and (
                best[ranked[candidates_per_name - 1]][0] -
                best[ranked[candidates_per_name]][0] < 0.3):
            gaps["no_cutoff_margin"] += 1
            continue
        eligible.append((name, ranked, best))
    eligible.sort(key=lambda item: hashlib.sha256(
        f"{seed}\0{item[0]}".encode()).hexdigest())
    packet = []
    for name, ranked, best in eligible[:limit_names]:
        for position, english_name in enumerate(ranked[:candidates_per_name], 1):
            score, anchor, candidate, parts = best[english_name]
            ja, en = _source_card(anchor), _source_card(candidate)
            frozen = {
                "category": "Trainer", "subtype": anchor["source_subtype"] or "",
                "proposal_signal": "ranked_artist_subtype_effect_numbers_release_era",
                "illustrator": anchor["source_illustrator"],
                "candidate_illustrator": candidate["source_illustrator"],
                "omitted_name_count": len(ranked) - min(len(ranked), candidates_per_name),
                "name_ja": name, "name_en": english_name,
                "ja_card_id": anchor["card_id"], "en_card_id": candidate["card_id"],
                "source_ja": ja["metadata_source_url"],
                "source_en": en["metadata_source_url"],
                "ja_match_eligible": anchor["match_eligible"],
                "en_match_eligible": candidate["match_eligible"],
            }
            frozen["proposal_id"] = hashlib.sha256((
                "concept-proposal-v1\0" + "\0".join(("Trainer", name, english_name))
            ).encode()).hexdigest()[:20]
            snapshot = {"frozen": frozen,
                        "ja_provenance": anchor["provenance"],
                        "en_provenance": candidate["provenance"],
                        "ja_classification": anchor["classification_provenance"],
                        "en_classification": candidate["classification_provenance"],
                        "ja_illustrator": anchor["illustrator_provenance"],
                        "en_illustrator": candidate["illustrator_provenance"],
                        "ja_rights": anchor["rights_reference"],
                        "en_rights": candidate["rights_reference"],
                        "rank": {"position": position, "score": round(score, 6), **parts}}
            digest = hashlib.sha256(json.dumps(
                snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            packet.append({**frozen, "source_snapshot_sha256": digest,
                           "source_snapshot": snapshot,
                           "ja_provenance": anchor["provenance"],
                           "en_provenance": candidate["provenance"],
                           "rights_reference": anchor["rights_reference"],
                           "retrieval_only": True})
    audit = {"seed": seed, "excluded_name_count": len(excluded_names),
             "source_ja_names_with_artist": len(by_name),
             "high_ambiguity_names": len(by_name) - gaps["not_high_ambiguity"],
             "eligible_names": len(eligible), "selected_names": min(len(eligible), limit_names),
             "proposal_rows": len(packet), "max_candidates_per_name": candidates_per_name,
             "minimum_top_score": 3.0, "minimum_cutoff_margin": 0.3,
             "gap_counts": dict(sorted(gaps.items())),
             "scope": "ranked review candidates only; no translation or printing verified"}
    return packet, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--exclude-anchors", type=Path, required=True)
    parser.add_argument("--limit-names", type=int, default=25)
    parser.add_argument("--candidates-per-name", type=int, default=5)
    parser.add_argument("--seed", default="concept-review-v4")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (args.queue, args.sheet, args.audit)):
        raise FileExistsError("packet output exists")
    repo = args.repo.resolve()
    import subprocess
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() != REVISION:
        raise ValueError("source checkout does not match pinned revision")
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        excluded = {row["name"] for item in read_jsonl(args.exclude_anchors)
                    if (row := db.execute("SELECT name FROM card WHERE card_id=?",
                                          (item["card_id"],)).fetchone())}
        packet, audit = build(db, repo, excluded, args.limit_names,
                              args.candidates_per_name, args.seed)
    write_jsonl(args.queue, packet)
    write_sheet(args.sheet, packet)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
