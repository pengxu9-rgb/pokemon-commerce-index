"""Audit pinned Japanese source files and emit conservative collector-number leads."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from pokemon_index import core
from pokemon_index.number_aliases import compact_name
from scripts.audit_jp_source_conflicts import PTCG_REVISION, TCGDEX_REVISION
from scripts.relationship_pilot import read_jsonl, write_jsonl


def _pinned_checkout(repo: Path, revision: str, scope: str) -> None:
    observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", scope],
                                    cwd=repo, text=True).strip()
    if observed != revision or dirty:
        raise ValueError(f"{scope} checkout differs from pinned clean revision")


def _source_hash(repo: Path, relative: str, expected: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or ".." in Path(relative).parts:
        raise ValueError("source path is not allowlisted")
    actual = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("source hash differs from pinned catalog provenance")


def build(cards: list[dict], rules: list[dict], tcgdex_repo: Path,
          official_repo: Path) -> tuple[list[dict], list[dict], dict]:
    _pinned_checkout(tcgdex_repo, TCGDEX_REVISION, "data-asia")
    _pinned_checkout(official_repo, PTCG_REVISION, "data_jp")
    candidates, unresolved, counts = [], [], Counter()
    for rule in rules:
        set_code = rule["set_code"]
        official = defaultdict(list)
        manifest = []
        for path in (official_repo / "data_jp").glob("*/*.json"):
            raw = path.read_bytes()
            data = json.loads(raw)
            if str(data.get("set_name", "")).upper() != set_code:
                continue
            number = str(data["number"]).zfill(3)
            if str(data["set_total"]).zfill(3) != rule["official_denominator"]:
                raise ValueError("official source denominator changed")
            relative = str(path.relative_to(official_repo))
            if not re.fullmatch(r"data_jp/[A-Za-z0-9-]+/[0-9]+\.json", relative):
                raise ValueError("unexpected official record path")
            if data.get("url") != f"https://www.pokemon-card.com/card-search/details.php/card/{path.stem}":
                raise ValueError("official record URL differs from path")
            source_sha = hashlib.sha256(raw).hexdigest()
            manifest.append({"path": relative, "sha256": source_sha, "number": number,
                             "total": rule["official_denominator"], "url": data["url"]})
            official[number].append({"path": relative, "sha256": source_sha,
                                     "url": data["url"], "collector_number":
                                     f"{number}/{rule['official_denominator']}", "name": data["name"]})
        if sum(map(len, official.values())) != rule["official_record_count"]:
            raise ValueError("official record count differs from conflict rule")
        manifest.sort(key=lambda record: record["path"])
        manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest()
        if manifest_sha != rule["official_record_manifest_sha256"]:
            raise ValueError("official record manifest differs from conflict rule")
        affected = [card for card in cards if card["language"] == "ja"
                    and card["set_code"].upper() == set_code
                    and card["collector_number"].split("/")[-1] == rule["catalog_denominator"]
                    and card["provenance"].startswith(rule["catalog_source_prefix"])]
        for card in sorted(affected, key=lambda item: (item["collector_number"], item["variant"])):
            relative_and_hash = card["provenance"][len(rule["catalog_source_prefix"]):]
            relative, expected = relative_and_hash.split(":sha256:", 1)
            if not re.fullmatch(r"data-asia/[A-Za-z0-9_./-]+\.ts", relative):
                raise ValueError("catalog source path is unexpected")
            _source_hash(tcgdex_repo, relative, expected)
            number = card["collector_number"].split("/")[0]
            records = sorted((record for record in official.get(number, [])
                              if compact_name(record["name"]) == compact_name(card["name"])),
                             key=lambda record: record["path"])
            card_id = core.card_id(card["language"], card["set_code"],
                                   card["collector_number"], card["variant"])
            if not records:
                reason = "official_numerator_absent" if number not in official else "name_disagrees"
                unresolved.append({"card_id": card_id, "catalog_number": card["collector_number"],
                                   "catalog_name": card["name"], "rule_id": rule["rule_id"],
                                   "reason": reason})
                counts[f"{set_code}_unresolved_{reason}"] += 1
                continue
            candidates.append({"card_id": card_id, "rule_id": rule["rule_id"],
                               "catalog_number": card["collector_number"],
                               "catalog_name": card["name"],
                               "source_provenance": card["provenance"],
                               "official_number_candidate":
                               f"{number}/{rule['official_denominator']}",
                               "official_source_revision": PTCG_REVISION,
                               "official_records": records,
                               "physical_printing_status": "unverified",
                               "offer_matching_status": "blocked"})
            counts[f"{set_code}_candidates"] += 1
            if len(records) > 1:
                counts[f"{set_code}_multiple_official_records"] += 1
    report = {"counts": dict(sorted(counts.items())), "candidates": len(candidates),
              "unresolved": len(unresolved),
              "tcgdex_revision": TCGDEX_REVISION, "official_source_revision": PTCG_REVISION,
              "scope": "internal number leads; no verified printing, offer match, or price equivalence"}
    return candidates, unresolved, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--tcgdex-repo", type=Path, required=True)
    parser.add_argument("--official-jp-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unresolved", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (args.output, args.unresolved, args.audit)):
        raise FileExistsError("number alias outputs must be new")
    cards = list(read_jsonl(args.cards))
    candidates, unresolved, report = build(
        cards, list(read_jsonl(args.rules)), args.tcgdex_repo.resolve(),
        args.official_jp_repo.resolve())
    report["catalog_cards_sha256"] = hashlib.sha256(args.cards.read_bytes()).hexdigest()
    report["number_conflict_rules_sha256"] = hashlib.sha256(args.rules.read_bytes()).hexdigest()
    write_jsonl(args.output, candidates)
    write_jsonl(args.unresolved, unresolved)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
