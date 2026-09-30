"""Verify pinned M6 secret rarities against exact official card pages."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pokemon_index.core import card_id
from scripts.audit_jp_source_conflicts import compact, official_record

RARITIES = {"rare_ar": ("ic_rare_ar.gif", "AR"),
            "rare_sr_c": ("ic_rare_sr_c.gif", "SR"),
            "rare_sar": ("ic_rare_sar.gif", "SAR"),
            "rare_MUR": ("ic_rare_MUR.gif", "MUR")}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def audit(base_path: Path, reference_path: Path) -> tuple[list[dict], list[dict]]:
    base = {r["collector_number"]: r for r in read_jsonl(base_path)
            if r["set_code"] == "M6" and r["rarity"] == "Mega Hyper Rare"}
    refs = {r["collector_number"]: r for r in read_jsonl(reference_path)
            if r["set_code"] == "M6" and r["collector_number"] in base}
    if len(base) != 37 or len(refs) != 37:
        raise ValueError("M6 pinned secret-card scope changed")

    def check(number: str) -> tuple[dict, dict | None]:
        source, ref = base[number], refs[number]
        icon, rarity = RARITIES[ref["rarity"]]
        url = f'https://www.pokemon-card.com/card-search/details.php/card/{ref["source_jp_id"]}'
        for attempt in range(3):
            try:
                official = official_record(url, "M6", number)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        if official["rarity_icons"] != [icon] or compact(official["name"]) != compact(ref["name"]):
            raise ValueError(f"M6 {number} official page disagrees with reference")
        correction = None
        if compact(official["name"]) == compact(source["name"]):
            correction = {"card_id": card_id("ja", "M6", number, source["variant"]),
                          "original_name": source["name"],
                          "original_rarity": source["rarity"],
                          "source_provenance": source["provenance"],
                          "corrected_rarity": rarity,
                          "reference_provenance": ref["provenance"],
                          "official_url": url,
                          "official_page_sha256": official["page_sha256"],
                          "official_rarity_icon": icon}
        evidence = {"set_code": "M6", "collector_number": number,
                    "base_name": source["name"], "base_rarity": source["rarity"],
                    "reference_name": ref["name"], "reference_rarity": ref["rarity"],
                    "official": official,
                    "disposition": "rarity_correction" if correction else "existing_identity_exception"}
        return evidence, correction

    with ThreadPoolExecutor(max_workers=2) as pool:
        reviewed = list(pool.map(check, sorted(base)))
    audit_rows = [entry for entry, _ in reviewed]
    corrections = [row for _, row in reviewed if row is not None]
    if len(corrections) != 35:
        raise ValueError("M6 correction count changed; review identity exceptions")
    return audit_rows, corrections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path("catalog/ja-all-available.jsonl"))
    parser.add_argument("--reference", type=Path, default=Path("catalog/ptcg-jp-reference.jsonl"))
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    args = parser.parse_args()
    if args.audit.exists() or args.corrections.exists():
        raise FileExistsError("M6 audit outputs are immutable")
    reviewed, corrections = audit(args.base, args.reference)
    args.audit.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                  for row in reviewed), encoding="utf-8")
    args.corrections.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                        for row in corrections), encoding="utf-8")
    print(json.dumps({"official_pages": len(reviewed), "rarity_corrections": len(corrections),
                      "identity_exceptions": len(reviewed) - len(corrections)}))


if __name__ == "__main__":
    main()
