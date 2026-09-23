"""Audit every data-asia set in a pinned local TCGdex metadata checkout.

The output contains text identity metadata only. Missing Japanese names and
unrepresentable variants are recorded as gaps instead of inferred.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from pokemon_index.tcgdex_source import parse_card_source, parse_set_metadata


def build(repo: Path, revision: str, output: Path, report_path: Path,
          gaps_path: Path, sets_path: Path) -> dict:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision:
        raise ValueError(f"checkout revision {actual} differs from requested {revision}")
    if not (repo / "LICENSE").is_file() or not (repo / "data-asia").is_dir():
        raise ValueError("checkout lacks LICENSE or data-asia")
    for path in (output, report_path, gaps_path, sets_path):
        if path.exists():
            raise FileExistsError(f"output exists: {path}")

    rows: list[dict] = []
    gaps: list[dict] = []
    set_reports: list[dict] = []
    set_metadata: list[dict] = []
    identities: set[tuple[str, str, str, str]] = set()
    for directory in sorted((repo / "data-asia").glob("*/*")):
        if not directory.is_dir():
            continue
        relative = directory.relative_to(repo).as_posix()
        header = directory.with_suffix(".ts")
        files = sorted(directory.glob("*.ts"))
        set_report = {"set_path": relative, "set_id": directory.name,
                      "source_files": len(files), "parsed_files": 0,
                      "printings": 0, "gaps": 0}
        if not header.is_file():
            gaps.append({"path": header.relative_to(repo).as_posix(),
                         "reason": "set header missing"})
            gaps.extend({"path": file.relative_to(repo).as_posix(),
                         "reason": "set header missing"} for file in files)
            set_report["gaps"] = len(files) + 1
            set_reports.append(set_report)
            continue
        try:
            metadata = parse_set_metadata(header.read_text(encoding="utf-8"))
            set_id, official_count = metadata["set_code"], metadata["official_card_count"]
            if set_id != directory.name:
                raise ValueError("set id in source differs from directory")
        except ValueError as exc:
            gaps.append({"path": header.relative_to(repo).as_posix(),
                         "reason": str(exc)})
            gaps.extend({"path": file.relative_to(repo).as_posix(),
                         "reason": "set header could not be parsed"} for file in files)
            set_report["gaps"] = len(files) + 1
            set_reports.append(set_report)
            continue
        set_report["official_card_count"] = official_count
        set_report["name_ja"] = metadata["name_ja"]
        set_report["release_date_ja"] = metadata["release_date_ja"]
        for file in files:
            path = file.relative_to(repo).as_posix()
            try:
                parsed = parse_card_source(file.read_text(encoding="utf-8"),
                                           set_id=set_id, official_count=official_count,
                                           path=path, revision=revision)
                local_identities = set()
                for row in parsed:
                    identity = (row["language"], row["set_code"].upper(),
                                row["collector_number"], row["variant"])
                    if identity in identities or identity in local_identities:
                        raise ValueError("duplicate normalized identity across source files")
                    local_identities.add(identity)
                identities.update(local_identities)
                rows.extend(parsed)
                set_report["parsed_files"] += 1
                set_report["printings"] += len(parsed)
            except ValueError as exc:
                gaps.append({"path": path, "reason": str(exc)})
                set_report["gaps"] += 1
        if metadata["name_ja"] or set_report["printings"]:
            set_metadata.append({**metadata, "provenance":
                                 f"tcgdex:{revision}:{header.relative_to(repo).as_posix()}",
                                 "rights_reference":
                                 f"https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE",
                                 "display_allowed": False})
        set_reports.append(set_report)

    rows.sort(key=lambda row: (row["set_code"].upper(), row["collector_number"], row["variant"]))
    reasons = Counter(gap["reason"] for gap in gaps)
    report = {"source": f"https://github.com/tcgdex/cards-database/tree/{revision}/data-asia",
              "revision": revision,
              "license": f"https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE",
              "scope": "all data-asia sets with representable Japanese text metadata at this revision",
              "display_approved": False,
              "sets_scanned": len(set_reports),
              "sets_with_japanese_name": sum(bool(item.get("name_ja")) for item in set_reports),
              "sets_with_printings": sum(item["printings"] > 0 for item in set_reports),
              "japanese_named_set_missing_card_names": sum(
                  item["source_files"] - item["parsed_files"]
                  for item in set_reports if item.get("name_ja")),
              "source_card_files": sum(item["source_files"] for item in set_reports),
              "parsed_card_files": sum(item["parsed_files"] for item in set_reports),
              "priceable_printings": len(rows),
              "gap_count": len(gaps),
              "gap_reasons": dict(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
              "set_coverage": set_reports}
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with gaps_path.open("x", encoding="utf-8") as handle:
        for gap in gaps:
            handle.write(json.dumps(gap, ensure_ascii=False) + "\n")
    with sets_path.open("x", encoding="utf-8") as handle:
        for item in set_metadata:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build audited Japanese card metadata from a local TCGdex checkout")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--sets", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.repo.resolve(), args.revision, args.output, args.report, args.gaps, args.sets)
    print(json.dumps({key: value for key, value in report.items() if key != "set_coverage"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
