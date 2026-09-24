"""Build a text-only, provenance-checked discovery facet snapshot from pinned TCGdex.

This does not infer JP↔EN printing counterparts or copy artwork, rules text or prices.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path

from pokemon_index import core, tcgdex_source

SOURCE_RE = re.compile(r"^tcgdex:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})$")


def build(repo: Path, revision: str, card_paths: list[Path], output: Path,
          report_path: Path) -> dict:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision or not (repo / "LICENSE").is_file():
        raise ValueError("source checkout does not match the pinned revision and license")
    if output.exists() or report_path.exists():
        raise FileExistsError("facet output or report already exists")
    source_cache: dict[str, dict] = {}
    facets = []
    gaps = []
    card_count = 0
    cards_with_dex = set()
    cards_with_artist = set()
    for card_path in card_paths:
        with card_path.open(encoding="utf-8") as handle:
            for line in handle:
                card = json.loads(line)
                card_count += 1
                match = SOURCE_RE.fullmatch(card["provenance"])
                if not match or match.group(1) != revision:
                    raise ValueError(f"unexpected card provenance in {card_path}: {card['provenance']}")
                source_path, expected_sha = match.group(2), match.group(3)
                if source_path not in source_cache:
                    source_file = (repo / source_path).resolve()
                    if not source_file.is_relative_to(repo.resolve()):
                        raise ValueError("source path leaves pinned checkout")
                    body = source_file.read_bytes()
                    if hashlib.sha256(body).hexdigest() != expected_sha:
                        raise ValueError(f"source hash mismatch: {source_path}")
                    try:
                        parsed = tcgdex_source.parse_discovery_facets(body.decode("utf-8"))
                    except ValueError as exc:
                        parsed = {}
                        gaps.append({"source_path": source_path, "reason": str(exc)})
                    source_cache[source_path] = parsed
                parsed = source_cache[source_path]
                card_id = core.card_id(card["language"], card["set_code"],
                                       card["collector_number"], card["variant"])
                for dex_id in parsed.get("dex_ids", []):
                    facets.append({"card_id": card_id, "facet_type": "dex_id",
                                   "value": str(dex_id), "provenance": card["provenance"],
                                   "rights_reference": card["rights_reference"]})
                    cards_with_dex.add(card_id)
                if parsed.get("illustrator"):
                    facets.append({"card_id": card_id, "facet_type": "illustrator",
                                   "value": parsed["illustrator"], "provenance": card["provenance"],
                                   "rights_reference": card["rights_reference"]})
                    cards_with_artist.add(card_id)
    facets.sort(key=lambda row: (row["card_id"], row["facet_type"], row["value"]))
    if output.suffix == ".gz":
        with output.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as handle:
                for row in facets:
                    handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    else:
        with output.open("x", encoding="utf-8") as handle:
            for row in facets:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"revision": revision, "source_cards": card_count,
              "source_files": len(source_cache), "facet_rows": len(facets),
              "cards_with_dex_id": len(cards_with_dex),
              "cards_with_illustrator": len(cards_with_artist),
              "facet_parse_gaps": gaps,
              "scope": "internal character and artist discovery only; no printing equivalence"}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cards", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.repo.resolve(), args.revision, args.cards, args.output, args.report)
    print(json.dumps({key: value for key, value in report.items() if key != "facet_parse_gaps"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
