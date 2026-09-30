"""Fill missing pinned-source rarities only after exact official-page checks.

The candidate list is frozen before fetching. A checkpoint permits resuming an
interrupted batch without repeating completed requests. No images are stored.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import sqlite3
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from pokemon_index.card_rarity import OFFICIAL_ICON_RARITIES
from scripts.audit_jp_source_conflicts import compact, official_record
from scripts.public_question_sandbox import read_jsonl, sha_file, write_jsonl


def select_candidates(db: sqlite3.Connection, references: list[dict]) -> list[dict]:
    refs = defaultdict(list)
    for row in references:
        if row.get("rarity") and row.get("set_code") and row.get("collector_number"):
            refs[(row["set_code"], row["collector_number"])].append(row)
    candidates = []
    for card in db.execute("""SELECT card_id,set_code,collector_number,name,rarity,provenance
        FROM card WHERE language='ja' AND (rarity IS NULL OR rarity='')
        AND match_eligible=1 AND provenance LIKE 'tcgdex:%' ORDER BY card_id"""):
        records = refs[(card["set_code"], card["collector_number"])]
        if len(records) != 1:
            continue
        ref = records[0]
        icon = f'ic_{ref["rarity"]}.gif'
        if icon not in OFFICIAL_ICON_RARITIES or compact(ref["name"]) != compact(card["name"]):
            continue
        if not ref["provenance"].startswith("ptcg-database:"):
            continue
        candidates.append({"card_id": card["card_id"], "set_code": card["set_code"],
                           "collector_number": card["collector_number"],
                           "original_name": card["name"], "original_rarity": card["rarity"],
                           "source_provenance": card["provenance"],
                           "reference_provenance": ref["provenance"],
                           "reference_name": ref["name"],
                           "official_url": f'https://www.pokemon-card.com/card-search/details.php/card/{ref["source_jp_id"]}',
                           "expected_icon": icon,
                           "corrected_rarity": OFFICIAL_ICON_RARITIES[icon]})
    return candidates


def check(candidate: dict) -> dict:
    result = {"card_id": candidate["card_id"],
              "candidate_sha256": hashlib.sha256(json.dumps(candidate, ensure_ascii=False,
                  sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for attempt in range(3):
        try:
            official = official_record(candidate["official_url"], candidate["set_code"],
                                       candidate["collector_number"])
            break
        except (OSError, http.client.HTTPException) as exc:
            if attempt == 2:
                return {**result, "status": "fetch_failed", "error_type": type(exc).__name__}
            time.sleep(attempt + 1)
        except ValueError as exc:
            return {**result, "status": "rejected", "reason": str(exc)}
    result["official"] = official
    if (compact(official["name"]) != compact(candidate["original_name"])
            or official["rarity_icons"] != [candidate["expected_icon"]]):
        return {**result, "status": "rejected", "reason": "official name or rarity disagrees"}
    return {**result, "status": "verified"}


def run(db_path: Path, reference_path: Path, out_dir: Path) -> dict:
    inputs = {"schema": "pokemon.missing-rarity-audit.v1",
              "catalog_sha256": sha_file(db_path), "reference_sha256": sha_file(reference_path)}
    if out_dir.exists():
        manifest = json.loads((out_dir / "manifest.json").read_text())
        if any(manifest.get(key) != value for key, value in inputs.items()):
            raise ValueError("rarity audit inputs changed")
        candidates = read_jsonl(out_dir / "candidates.jsonl")
        if sha_file(out_dir / "candidates.jsonl") != manifest["candidates_sha256"]:
            raise ValueError("frozen rarity candidates changed")
    else:
        with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            candidates = select_candidates(db, read_jsonl(reference_path))
        out_dir.mkdir(parents=True)
        write_jsonl(out_dir / "candidates.jsonl", candidates)
        manifest = {**inputs, "candidates": len(candidates),
                    "candidates_sha256": sha_file(out_dir / "candidates.jsonl"),
                    "scope": "internal rarity metadata only; exact official set/number/name/icon; no images or prices"}
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    checkpoint = out_dir / "official_audit.jsonl"
    reviewed = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["card_id"]: row for row in reviewed}
    frozen = {row["card_id"]: row for row in candidates}
    if len(by_id) != len(reviewed) or set(by_id) - set(frozen):
        raise ValueError("rarity checkpoint IDs differ from candidates")
    for card_id, row in by_id.items():
        expected = hashlib.sha256(json.dumps(frozen[card_id], ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if row["candidate_sha256"] != expected:
            raise ValueError("rarity checkpoint candidate changed")
    pending = [row for row in candidates if row["card_id"] not in by_id]
    with checkpoint.open("a", encoding="utf-8") as output:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in as_completed([pool.submit(check, row) for row in pending]):
                row = future.result()
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                by_id[row["card_id"]] = row
                if len(by_id) % 25 == 0:
                    print(json.dumps({"checked": len(by_id), "total": len(candidates)}), flush=True)
    corrections = []
    for candidate in candidates:
        review = by_id[candidate["card_id"]]
        if review["status"] == "verified":
            fields = ("card_id", "original_name", "original_rarity", "source_provenance",
                      "corrected_rarity", "reference_provenance", "official_url")
            corrections.append({**{key: candidate[key] for key in fields},
                                "official_page_sha256": review["official"]["page_sha256"],
                                "official_rarity_icon": candidate["expected_icon"]})
    summary = {"candidates": len(candidates), "statuses": dict(Counter(r["status"] for r in by_id.values())),
               "corrections": len(corrections),
               "by_rarity": dict(sorted(Counter(r["corrected_rarity"] for r in corrections).items())),
               "by_set": dict(sorted(Counter(frozen[r["card_id"]]["set_code"] for r in corrections).items()))}
    write_jsonl(out_dir / "corrections.jsonl", corrections)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("catalog/ptcg-jp-reference.jsonl"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.reference, args.out_dir), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
