"""Extract minimal identity metadata from a pinned public PTCG-database checkout.

Supplemental cards are internal, unverified candidates. They cannot resolve
offers until their printing identity has been independently checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from pokemon_index.core import normalize_collector_number


def _identity(row: dict) -> tuple[str, str] | None:
    set_code = str(row.get("set_name") or "")
    number = str(row.get("number") or "")
    total = str(row.get("set_total") or "")
    if (not re.fullmatch(r"[A-Za-z0-9-]{1,20}", set_code)
            or not re.fullmatch(r"[A-Za-z0-9]{1,5}", number)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,20}", total)):
        return None
    collector_number = normalize_collector_number(f"{number.upper().zfill(3)}/{total.upper()}")
    return set_code.upper(), collector_number


def _attributes(row: dict) -> dict:
    return {key: value for key, value in {
        "source_jp_id": row.get("jp_id"),
        "card_type": row.get("card_type"),
        "hp": row.get("hp"),
        "types": row.get("types"),
        "illustrator": row.get("author"),
    }.items() if value is not None}


def build(repo: Path, revision: str, base_path: Path, reference_path: Path,
          candidates_path: Path, report_path: Path, gaps_path: Path) -> dict:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual != revision:
        raise ValueError(f"checkout revision {actual} differs from requested {revision}")
    if not (repo / "LICENSE").is_file() or not (repo / "data_jp").is_dir():
        raise ValueError("checkout lacks LICENSE or data_jp")
    for path in (reference_path, candidates_path, report_path, gaps_path):
        if path.exists():
            raise FileExistsError(f"output exists: {path}")

    base: dict[tuple[str, str], set[str]] = defaultdict(set)
    for line in base_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        base[(row["set_code"].upper(), row["collector_number"])].add(row["name"])

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    reference = []
    gaps = []
    rights = f"https://github.com/type-null/PTCG-database/blob/{revision}/LICENSE"
    for path in sorted((repo / "data_jp").glob("*/*.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        if not isinstance(row.get("name"), str) or not row["name"].strip():
            gaps.append({"path": path.relative_to(repo).as_posix(), "reason": "missing Japanese name"})
            continue
        key = _identity(row)
        item = {"source": "ptcg-database", "source_jp_id": row.get("jp_id"),
                "set_code": key[0] if key else None,
                "collector_number": key[1] if key else None, "name": row["name"],
                "rarity": row.get("rarity"), "attributes": _attributes(row),
                "provenance": f"ptcg-database:{revision}:{path.relative_to(repo).as_posix()}:sha256:{hashlib.sha256(raw).hexdigest()}",
                "rights_reference": rights, "display_allowed": False,
                "match_eligible": False}
        reference.append(item)
        if key:
            grouped[key].append(item)
        else:
            gaps.append({"path": path.relative_to(repo).as_posix(),
                         "reason": "set code or collector number is absent or unsupported"})

    candidates = []
    counts = Counter()
    for key, items in sorted(grouped.items()):
        if key in base:
            counts["overlap_groups"] += 1
            counts["overlap_rows"] += len(items)
            if not any(item["name"] in base[key] for item in items):
                counts["overlap_name_conflicts"] += 1
                gaps.append({"set_code": key[0], "collector_number": key[1],
                             "reason": "source names disagree at same set and number",
                             "source_jp_ids": [item["source_jp_id"] for item in items]})
        elif len(items) == 1:
            item = items[0]
            candidates.append({"language": "ja", "set_code": key[0],
                               "collector_number": key[1], "variant": "unverified",
                               "name": item["name"], "rarity": item["rarity"],
                               "attributes": item["attributes"],
                               "provenance": item["provenance"],
                               "rights_reference": rights, "display_allowed": False,
                               "match_eligible": False})
        else:
            counts["ambiguous_new_groups"] += 1
            counts["ambiguous_new_rows"] += len(items)
            gaps.append({"set_code": key[0], "collector_number": key[1],
                         "reason": "multiple source records share set and number",
                         "source_jp_ids": [item["source_jp_id"] for item in items]})

    report = {"source": f"https://github.com/type-null/PTCG-database/tree/{revision}/data_jp",
              "revision": revision, "source_files": len(reference),
              "scope": "internal reference and unverified candidate identities; images and rules text omitted",
              "display_approved": False, "candidate_match_eligible": False,
              "reference_rows": len(reference), "valid_identity_groups": len(grouped),
              "new_unique_candidates": len(candidates),
              "candidate_sets": len({row["set_code"] for row in candidates}),
              "invalid_identity_rows": len(reference) - sum(len(items) for items in grouped.values()),
              **dict(counts), "gap_rows": len(gaps)}
    for path, rows in ((reference_path, reference), (candidates_path, candidates), (gaps_path, gaps)):
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build internal Japanese card reference candidates")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.repo.resolve(), args.revision, args.base,
                   args.reference, args.candidates, args.report, args.gaps)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
