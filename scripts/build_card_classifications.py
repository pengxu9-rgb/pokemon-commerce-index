"""Build a provenance-checked text-only category snapshot from pinned TCGdex."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from pokemon_index import core, tcgdex_source
from scripts.build_discovery_facets import SOURCE_RE


def build(repo: Path, revision: str, card_paths: list[Path], output: Path,
          report_path: Path) -> dict:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision or not (repo / "LICENSE").is_file():
        raise ValueError("source checkout does not match pinned revision and license")
    if output.exists() or report_path.exists():
        raise FileExistsError("classification output or report already exists")
    cache = {}
    rows = []
    gaps = []
    counts = Counter()
    total = 0
    for path in card_paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                card = json.loads(line)
                total += 1
                match = SOURCE_RE.fullmatch(card["provenance"])
                if not match or match.group(1) != revision:
                    raise ValueError(f"unexpected provenance: {card['provenance']}")
                source_path, expected_sha = match.group(2), match.group(3)
                if source_path not in cache:
                    source_file = (repo / source_path).resolve()
                    if not source_file.is_relative_to(repo.resolve()):
                        raise ValueError("source path leaves pinned checkout")
                    body = source_file.read_bytes()
                    if hashlib.sha256(body).hexdigest() != expected_sha:
                        raise ValueError(f"source hash mismatch: {source_path}")
                    try:
                        cache[source_path] = tcgdex_source.parse_card_classification(body.decode("utf-8"))
                    except ValueError as exc:
                        cache[source_path] = None
                        gaps.append({"source_path": source_path, "reason": str(exc)})
                classification = cache[source_path]
                if classification is None:
                    continue
                category, subtype = classification
                rows.append({"card_id": core.card_id(card["language"], card["set_code"],
                                                   card["collector_number"], card["variant"]),
                             "category": category, "subtype": subtype,
                             "provenance": card["provenance"],
                             "rights_reference": card["rights_reference"]})
                counts[category] += 1
    rows.sort(key=lambda row: row["card_id"])
    if output.suffix == ".gz":
        with output.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as handle:
                for row in rows:
                    handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
    else:
        with output.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"revision": revision, "source_cards": total, "classified_cards": len(rows),
              "by_category": dict(sorted(counts.items())), "unclassified_cards": total-len(rows),
              "parse_gaps": gaps,
              "scope": "internal category retrieval only; no cross-region printing equivalence"}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cards", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.revision, args.cards, args.output,
                           args.report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
