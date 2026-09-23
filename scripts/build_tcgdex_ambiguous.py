"""Retain TCGdex card identities whose duplicate variants cannot be resolved.

These rows are internal discovery candidates, never eligible for automatic
offer matching. The source declarations may represent different art/printings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pokemon_index.core import normalize_collector_number
from pokemon_index.tcgdex_source import _object_field, _string_field, parse_card_source, parse_set_metadata


REASON = "two source variants collapse to the same identity"


def build(repo: Path, revision: str, gaps_path: Path, existing_paths: list[Path],
          output: Path, report_path: Path, language: str = "ja") -> dict:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision:
        raise ValueError(f"checkout revision {actual} differs from requested {revision}")
    if language not in {"ja", "en"}:
        raise ValueError("unsupported card language")
    for path in (output, report_path):
        if path.exists():
            raise FileExistsError(path)
    existing = set()
    for path in existing_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            existing.add((row["set_code"].upper(), row["collector_number"]))
    rows = []
    for line in gaps_path.read_text(encoding="utf-8").splitlines():
        gap = json.loads(line)
        if gap["reason"] != REASON:
            continue
        source_path = gap["path"]
        file = repo / source_path
        source = file.read_text(encoding="utf-8")
        metadata = parse_set_metadata(file.parent.with_suffix(".ts").read_text(encoding="utf-8"))
        set_id = metadata["set_code"]
        count = metadata["official_card_count"]
        try:
            parse_card_source(source, set_id=set_id, official_count=count,
                              path=source_path, revision=revision, language=language,
                              source_directory=file.parent.name)
        except ValueError as exc:
            if str(exc) != REASON:
                raise ValueError(f"gap changed at {source_path}: {exc}") from exc
        else:
            raise ValueError(f"gap was resolved at {source_path}; rebuild the main extract")
        name = _string_field(_object_field(source, "name", "{", "}") or "", language)
        if not name:
            raise ValueError(f"{language} name missing at {source_path}")
        local_id = file.stem
        width = max(3, len(local_id), len(str(count)))
        denominator = str(count).zfill(width) if count else set_id
        number = normalize_collector_number(f"{local_id.upper().zfill(width)}/{denominator}")
        key = (set_id.upper(), number)
        if key in existing:
            raise ValueError(f"candidate collides with existing card: {key}")
        existing.add(key)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rows.append({
            "language": language, "set_code": set_id, "collector_number": number,
            "variant": "unverified_source_variants", "name": name,
            "rarity": _string_field(source, "rarity"),
            "provenance": f"tcgdex:{revision}:{source_path}:sha256:{digest}",
            "rights_reference": f"https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE",
            "display_allowed": False, "match_eligible": False,
            "attributes": {"source_variant_ambiguity": REASON},
        })
    rows.sort(key=lambda row: (row["set_code"], row["collector_number"]))
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"revision": revision, **({"language": language} if language != "ja" else {}),
              "source_gap_reason": REASON,
              "unverified_card_identities": len(rows),
              "sets": sorted({row["set_code"] for row in rows}),
              "display_approved": False, "match_eligible": False,
              "scope": "internal identity candidates only; duplicate source variants remain unresolved"}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--language", choices=["ja", "en"], default="ja")
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.revision, args.gaps,
                           args.existing, args.output, args.report, args.language), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
