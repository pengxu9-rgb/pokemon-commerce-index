"""Create tightly scoped rules for two verified Japanese set-denominator conflicts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pokemon_index.number_conflicts import _validate, rule_id_for_evidence
from scripts.audit_jp_source_conflicts import PTCG_REVISION, TCGDEX_REVISION, official_record
from scripts.relationship_pilot import read_jsonl, write_jsonl

CONFLICTS = (("SM10B", "056", "054"), ("SV11B", "174", "086"))


def audit(cards: list[dict], repo: Path) -> tuple[list[dict], dict]:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != PTCG_REVISION:
        raise ValueError("Japanese official-source checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data_jp"],
                               cwd=repo, text=True).strip():
        raise ValueError("Japanese official-source data is dirty")
    output, counts = [], {}
    for set_code, catalog_denominator, official_denominator in CONFLICTS:
        affected = [row for row in cards if row["language"] == "ja"
                    and row["set_code"].upper() == set_code
                    and row["collector_number"].split("/")[-1] == catalog_denominator]
        prefix = f"tcgdex:{TCGDEX_REVISION}:"
        if len(affected) < 2 or any(not row["provenance"].startswith(prefix)
                                    for row in affected):
            raise ValueError("catalog denominator group is absent or has unpinned sources")
        source_files = list((repo / "data_jp").glob("*/*.json"))
        official = []
        for path in source_files:
            raw = path.read_bytes()
            record = json.loads(raw)
            if str(record.get("set_name", "")).upper() == set_code:
                if str(record.get("set_total", "")).zfill(3) != official_denominator:
                    raise ValueError("official source denominator is not uniform")
                official.append((path, raw, record))
        if len(official) < 2:
            raise ValueError("official source has insufficient records")
        manifest = [{"path": str(path.relative_to(repo)),
                     "sha256": hashlib.sha256(raw).hexdigest(),
                     "number": str(record["number"]).zfill(3),
                     "total": official_denominator, "url": record["url"]}
                    for path, raw, record in official]
        manifest.sort(key=lambda x: x["path"])
        manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest()
        first = min(official, key=lambda item: int(item[2]["number"]))[2]
        last = max(official, key=lambda item: int(item[2]["number"]))[2]
        pages = []
        for record in (first, last):
            printed = f"{str(record['number']).zfill(3)}/{official_denominator}"
            page = official_record(record["url"], set_code, printed)
            pages.append({"url": page["url"], "page_sha256": page["page_sha256"],
                          "collector_number": page["collector_number"],
                          "name": page["name"]})
        row = {"language": "ja", "set_code": set_code,
               "catalog_denominator": catalog_denominator,
               "official_denominator": official_denominator,
               "catalog_source_prefix": prefix,
               "official_source_revision": PTCG_REVISION,
               "official_record_count": len(official),
               "official_record_manifest_sha256": manifest_sha,
               "official_pages": pages,
               "reason": "Pinned catalog denominator conflicts with the uniform official source denominator; exact offer matching is disabled pending identity correction."}
        row["rule_id"] = rule_id_for_evidence(row)
        _validate(row)
        output.append(row)
        counts[set_code] = {"catalog_cards_affected": len(affected),
                            "official_records_checked": len(official),
                            "catalog_denominator": catalog_denominator,
                            "official_denominator": official_denominator}
    report = {"rules": len(output), "sets": counts,
              "tcgdex_revision": TCGDEX_REVISION,
              "ptcg_revision": PTCG_REVISION,
              "scope": "disable unsafe exact offer matching; preserve catalog identities and graph proposals"}
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--official-jp-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("number conflict outputs must be new")
    rows, report = audit(read_jsonl(args.cards), args.official_jp_repo.resolve())
    report["cards_sha256"] = hashlib.sha256(args.cards.read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
