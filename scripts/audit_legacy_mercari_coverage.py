"""Audit old Mercari HTTP cassettes against the internal catalog without importing offers.

The output contains aggregate counts and card set/number gaps only. Listing
titles, IDs, photo URLs, seller information and historical prices stay in the
local cassette checkout and are never copied to the report or runtime index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from pokemon_index import buyship_mercari, core, listing_candidates

NUMBER = re.compile(r"(?<!\d)(\d{1,3}/\d{1,3})(?!\d)")
PROMO_NUMBER = re.compile(r"(?<!\d)\d{1,3}/(?:SV-P|S-P|SM-P|XY-P)(?![A-Za-z0-9])", re.I)
LEGACY_ALIASES = {
    "DP6": ("DPS-B",),
    "BW3": ("BW3-BH", "BW3-BP"),
    "BW4": ("BW4-B",),
    "BW6": ("BW6-BC", "BW6-BF"),
    "BW7": ("BW7-B",),
}


def _items(cassette: dict) -> list[dict]:
    found = []
    for interaction in cassette.get("interactions", []):
        request, response = interaction.get("request", {}), interaction.get("response", {})
        url = request.get("url", "")
        if "/tanosys/mercari/" not in url or response.get("status_code") != 200:
            continue
        try:
            payload = json.loads(response.get("body", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        endpoint = urlparse(url).path.rsplit("/", 1)[-1]
        try:
            rows = buyship_mercari.response_items(payload, endpoint)
        except ValueError:
            continue
        found.extend(row for row in rows if isinstance(row, dict) and row.get("id"))
    return found


def _candidate_codes(title: str, set_codes: set[str], code_pattern: re.Pattern[str]
                     ) -> tuple[set[str], str]:
    normalized = unicodedata.normalize("NFKC", title)
    codes = {match.group(0).upper() for match in code_pattern.finditer(normalized)}
    # MA and SA are often rarity/artwork shorthand, not the set identifier.
    if ("MEGAドリーム" in normalized.upper() or "メガドリーム" in normalized) and "M2A" in set_codes:
        return {"M2A"}, "set_name"
    if "M2A" in codes:
        codes.discard("MA")
    if "S6A" in codes:
        codes.discard("SA")
    if codes == {"MA"} or codes == {"SA"} and "/069" in normalized:
        return set(), "artwork_shorthand"
    aliases = {alias for alias in LEGACY_ALIASES if re.search(
        rf"(?<![A-Za-z0-9]){alias}(?![A-Za-z0-9])", normalized, re.I)}
    if len(aliases) == 1:
        alias = next(iter(aliases))
        return (set(LEGACY_ALIASES[alias]) & set_codes) | (codes - {alias}), "legacy_alias"
    if codes:
        return codes, "exact"
    return set(), "none"


def audit(db: sqlite3.Connection, cassette_dir: Path) -> dict:
    fingerprints = []
    items = {}
    for path in sorted(cassette_dir.rglob("*cassette.json")):
        data = path.read_bytes()
        try:
            rows = _items(json.loads(data))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if rows:
            fingerprints.append(hashlib.sha256(data).hexdigest())
            for item in rows:
                items[str(item["id"])] = item
    set_codes = {row[0] for row in db.execute("SELECT DISTINCT set_code FROM card")}
    code_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:" + "|".join(sorted(
            (re.escape(code) for code in set_codes), key=len, reverse=True))
        + r")(?![A-Za-z0-9])", re.I)
    counts = Counter()
    gaps = Counter()
    reference_only = Counter()
    db.execute("SAVEPOINT legacy_fixture_resolution_audit")
    try:
        for item in items.values():
            counts["unique_items"] += 1
            if item.get("status") != "on_sale":
                counts["non_on_sale"] += 1
            photos = item.get("photos")
            two_photos = isinstance(photos, list) and len(photos) >= 2
            if isinstance(photos, list):
                counts["with_photo_array"] += 1
                counts["with_two_or_more_photos"] += two_photos
            title = unicodedata.normalize("NFKC", str(item.get("name", "")))
            unit_id = None
            try:
                unit_id, _ = core.resolve(db, {"title": title})
                counts["resolver_auto_accepted" if unit_id else "resolver_abstained"] += 1
                if two_photos:
                    counts["auto_accepted_two_photo_candidates" if unit_id
                           else "abstained_two_photo_candidates"] += 1
            except ValueError:
                counts["resolver_error"] += 1
            try:
                retrieval = listing_candidates.retrieve(db, title)
            except ValueError:
                retrieval = {"status": "none"}
            if retrieval["status"] == "candidate_only":
                counts["review_candidate_items"] += 1
                counts["review_candidate_items_with_two_photos"] += two_photos
                if not unit_id and two_photos:
                    counts["abstained_two_photo_items_with_review_candidates"] += 1
                counts["single_candidate_items"] += retrieval["candidate_count"] == 1
            if core.BUNDLE_RE.search(title):
                counts["bundle_or_multi_card_title"] += 1
                counts["bundle_with_two_or_more_photos"] += two_photos
                continue
            numbers = {core.normalize_collector_number(n) for n in NUMBER.findall(title)}
            codes, code_method = _candidate_codes(title, set_codes, code_pattern)
            if len(numbers) != 1 or not codes or PROMO_NUMBER.search(title):
                counts["no_single_set_number"] += 1
                if code_method == "artwork_shorthand":
                    counts["artwork_shorthand_not_set"] += 1
                continue
            number = next(iter(numbers))
            matches = db.execute(
                "SELECT language,set_code,collector_number,match_eligible FROM card "
                "WHERE set_code IN (" + ",".join("?" for _ in codes) + ") "
                "AND collector_number=?", (*sorted(codes), number)).fetchall()
            counts["explicit_or_alias_set_number"] += 1
            counts[f"code_method_{code_method}"] += 1
            if matches:
                counts["catalog_identity_present"] += 1
                counts["catalog_match_eligible_present"] += any(row["match_eligible"] for row in matches)
                if len({(row["language"], row["set_code"]) for row in matches}) > 1:
                    counts["multiple_language_or_set_candidates"] += 1
            elif len(codes) == 1:
                code = next(iter(codes))
                references = db.execute(
                    "SELECT COUNT(*) FROM card_reference WHERE set_code=? AND collector_number=?",
                    (code, number)).fetchone()[0]
                if references:
                    counts["reference_only_no_printing"] += 1
                    reference_only[(code, number, references)] += 1
                else:
                    gaps[(code, number)] += 1
            else:
                counts["ambiguous_alias_gap"] += 1
    finally:
        db.execute("ROLLBACK TO SAVEPOINT legacy_fixture_resolution_audit")
        db.execute("RELEASE SAVEPOINT legacy_fixture_resolution_audit")
    return {
        "scope": "offline historical fixture coverage; no live offers, prices or photo bytes",
        "cassette_files_with_items": len(fingerprints),
        "cassette_snapshot_sha256": hashlib.sha256("\n".join(sorted(fingerprints)).encode()).hexdigest(),
        "counts": dict(sorted(counts.items())),
        "missing_set_number_groups": [
            {"set_code": code, "collector_number": number, "fixture_items": n}
            for (code, number), n in sorted(gaps.items(), key=lambda pair: (-pair[1], pair[0]))],
        "reference_only_groups": [
            {"set_code": code, "collector_number": number, "reference_records": references,
             "fixture_items": n}
            for (code, number, references), n in sorted(reference_only.items())],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cassettes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with core.connect(args.db) as db:
        report = audit(db, args.cassettes)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
