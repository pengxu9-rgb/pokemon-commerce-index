"""Build localized physical-card identities from a pinned TCGdex source checkout.

Only series explicitly named with --series are scanned. Pokémon TCG Pocket is
digital and is intentionally rejected. Card art, rules text and image URLs are
never copied into the catalog extract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from pokemon_index.tcgdex_source import parse_card_source, parse_set_metadata
from pokemon_index.languages import normalize_language


def verify_source(repo, revision, series, data_root):
    """Bind all selected files to the pinned Git tree, including the license."""
    remotes = subprocess.check_output(['git', 'remote'], cwd=repo, text=True).splitlines()
    if any(remote != 'origin' for remote in remotes):
        raise ValueError('unexpected source remote; offline build refused')
    requested = ['LICENSE'] + [f'{data_root}/{name}' for name in series]
    tree = subprocess.check_output(['git', '-c', 'remote.origin.url=/dev/null', '-c', 'remote.origin.promisor=false',
                                    'ls-tree', '-rz', revision, '--', *requested], cwd=repo,
                                   env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'})
    blobs = {}
    for entry in tree.split(b'\0'):
        if entry:
            metadata, path = entry.split(b'\t', 1)
            if metadata.split()[1] == b'blob':
                blobs[path.decode()] = metadata.split()[2].decode()
    local = {'LICENSE'}
    for name in series:
        local.update(p.relative_to(repo).as_posix() for p in (repo/data_root/name).rglob('*') if p.is_file())
    if local != set(blobs):
        raise ValueError('selected source files differ from pinned Git tree')
    for path, expected in blobs.items():
        source = (repo/path).resolve()
        if not source.is_relative_to(repo.resolve()):
            raise ValueError('source symlink escapes pinned checkout')
        raw = source.read_bytes()
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != expected:
            raise ValueError('source Git blob changed: '+path)


def build(repo: Path, revision: str, series: list[str], output: Path,
          sets_path: Path, report_path: Path, gaps_path: Path, language: str = "en",
          data_root: str = "data") -> dict:
    repo = repo.resolve()
    language = normalize_language(language)
    if data_root not in {"data", "data-asia"}:
        raise ValueError("unsupported physical data root")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision:
        raise ValueError(f"checkout revision {actual} differs from requested {revision}")
    if not (repo / "LICENSE").is_file() or not series or any("pocket" in name.casefold() for name in series):
        raise ValueError("missing source license/series or digital series requested")
    for path in (output, sets_path, report_path, gaps_path):
        if path.exists():
            raise FileExistsError(f"output exists: {path}")
    for name in series:
        series_path = (repo / data_root / name).resolve()
        if not series_path.is_relative_to((repo / data_root).resolve()):
            raise ValueError('series escapes physical data root')
    verify_source(repo, revision, series, data_root)
    rows, sets, gaps, reports = [], [], [], []
    identities = set()
    set_ids = set()
    rights = f"https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE"
    for name in sorted(set(series)):
        series_path = (repo / data_root / name).resolve()
        if not series_path.is_relative_to((repo / data_root).resolve()):
            raise ValueError("series escapes physical data root")
        if not series_path.is_dir():
            raise ValueError(f"series missing from checkout: {name}")
        for directory in sorted(series_path.iterdir()):
            if not directory.is_dir():
                continue
            header = directory.with_suffix(".ts")
            files = sorted(directory.glob("*.ts"))
            report = {"path": directory.relative_to(repo).as_posix(),
                      "source_files": len(files), "parsed_files": 0,
                      "identities": 0, "gaps": 0}
            if not header.is_file():
                gaps.append({"path": header.relative_to(repo).as_posix(),
                             "reason": "set header missing"})
                gaps.extend({"path": file.relative_to(repo).as_posix(),
                             "reason": "set header missing"} for file in files)
                report["gaps"] = len(files) + 1
                reports.append(report)
                continue
            try:
                source = header.read_text(encoding="utf-8")
                metadata = parse_set_metadata(source, language)
                set_id, official = metadata["set_code"], metadata["official_card_count"]
                english_name = metadata.get("name", metadata.get("name_ja"))
                if not english_name or set_id.upper() in set_ids:
                    raise ValueError("missing localized set name or duplicate set id")
                set_ids.add(set_id.upper())
            except ValueError as exc:
                gaps.append({"path": header.relative_to(repo).as_posix(), "reason": str(exc)})
                gaps.extend({"path": file.relative_to(repo).as_posix(),
                             "reason": "set header could not be parsed"} for file in files)
                report["gaps"] = len(files) + 1
                reports.append(report)
                continue
            sets.append({"language": language, "set_code": set_id, "name": english_name,
                         "release_date": metadata.get("release_date", metadata.get("release_date_ja")),
                         "official_card_count": official,
                         "provenance": f"tcgdex:{revision}:{header.relative_to(repo).as_posix()}",
                         "rights_reference": rights, "display_allowed": False})
            report.update({"set_id": set_id, "official_card_count": official,
                           "name_en": english_name})
            for file in files:
                path = file.relative_to(repo).as_posix()
                try:
                    parsed = parse_card_source(file.read_text(encoding="utf-8"),
                                               set_id=set_id, official_count=official,
                                               path=path, revision=revision, language=language,
                                               source_directory=directory.name,
                                               strict_variant_dimensions=True)
                    for row in parsed:
                        key = (row["set_code"].upper(), row["collector_number"], row["variant"])
                        if key in identities:
                            raise ValueError("duplicate normalized localized identity")
                    for row in parsed:
                        identities.add((row["set_code"].upper(), row["collector_number"], row["variant"]))
                        row["match_eligible"] = bool(language in {"en", "ja"} and row["match_eligible"] and official and re.fullmatch(r"\d+", file.stem))
                    rows.extend(parsed)
                    report["parsed_files"] += 1
                    report["identities"] += len(parsed)
                except ValueError as exc:
                    gaps.append({"path": path, "reason": str(exc)})
                    report["gaps"] += 1
            reports.append(report)
    rows.sort(key=lambda row: (row["set_code"].upper(), row["collector_number"], row["variant"]))
    sets.sort(key=lambda row: row["set_code"].upper())
    audit = {"source": f"https://github.com/tcgdex/cards-database/tree/{revision}/{data_root}",
             "revision": revision, "language": language, "series": sorted(set(series)),
             "scope": "Localized physical-card identity text only; no art, rules or prices",
             "display_approved": False, "sets": len(sets),
             "source_files": sum(item["source_files"] for item in reports),
             "parsed_files": sum(item["parsed_files"] for item in reports),
             "identities": len(rows),
             "match_eligible": sum(bool(row["match_eligible"]) for row in rows),
             "gap_count": len(gaps),
             "gap_reasons": dict(Counter(gap["reason"] for gap in gaps)),
             "set_coverage": reports}
    for path, items in ((output, rows), (sets_path, sets), (gaps_path, gaps)):
        with path.open("x", encoding="utf-8") as handle:
            for row in items:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return {key: value for key, value in audit.items() if key != "set_coverage"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--series", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sets", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--data-root", choices=["data", "data-asia"], default="data")
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.revision, args.series, args.output,
                           args.sets, args.report, args.gaps, args.language, args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
