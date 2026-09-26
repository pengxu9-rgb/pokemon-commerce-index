"""Build a source-bound internal queue for duplicate Japanese official card records.

The queue contains factual identifiers and page links, never image bytes or
image URLs. Two records at one set/number do not by themselves prove variants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from scripts.audit_jp_source_conflicts import PTCG_REVISION


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def build(reference_path: Path, candidates_path: Path, repo: Path,
          set_code: str) -> tuple[list[dict], dict]:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != PTCG_REVISION:
        raise ValueError("Japanese source checkout differs from pinned revision")
    set_code = set_code.upper()
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in read_jsonl(reference_path):
        if row.get("set_code") == set_code and row.get("collector_number"):
            grouped[(set_code, row["collector_number"])].append(row)
    candidate_keys = {(r["set_code"].upper(), r["collector_number"]): r
                      for r in read_jsonl(candidates_path)
                      if r["set_code"].upper() == set_code}
    queue = []
    for key, group in sorted(grouped.items()):
        if len(group) < 2 or key not in candidate_keys:
            continue
        if len({r["name"] for r in group}) != 1 or len({r["rarity"] for r in group}) != 1:
            continue
        official_urls, image_urls, authors, source_hashes = [], set(), set(), []
        ordered_group = sorted(group, key=lambda item: int(item["source_jp_id"]))
        for row in ordered_group:
            prefix = f"ptcg-database:{PTCG_REVISION}:"
            provenance = row["provenance"]
            if not provenance.startswith(prefix) or ":sha256:" not in provenance:
                raise ValueError("reference does not bind pinned PTCG source")
            relative, expected = provenance[len(prefix):].rsplit(":sha256:", 1)
            if not re.fullmatch(r"data_jp/[A-Za-z0-9-]+/[A-Za-z0-9-]+\.json", relative):
                raise ValueError("source path is not allowlisted")
            raw = (repo / relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("source record hash differs from pinned reference")
            source = json.loads(raw)
            url = source.get("url", "")
            if not re.fullmatch(r"https://www\.pokemon-card\.com/card-search/details\.php/card/\d+", url):
                raise ValueError("source lacks exact official card page")
            official_urls.append(url)
            image_urls.add(source.get("img"))
            authors.add(tuple(source.get("author") or []))
            source_hashes.append(expected)
        if len(authors) != 1:
            continue
        if len(set(official_urls)) != len(group):
            raise ValueError("duplicate source IDs share an official page")
        candidate = candidate_keys[key]
        queue.append({"card_id": f"ja:{set_code}:{key[1]}:{candidate['variant']}",
                      "set_code": set_code, "collector_number": key[1],
                      "name": group[0]["name"], "source_rarity": group[0]["rarity"],
                      "source_jp_ids": [row["source_jp_id"] for row in ordered_group],
                      "official_page_urls": official_urls,
                      "source_record_sha256": source_hashes,
                      "distinct_source_image_urls": len(image_urls),
                      "review_status": "candidate_only",
                      "review_question": "Do the official records represent distinct physical printings or duplicate records?",
                      "evidence_limit": "Distinct pages or image URLs do not establish foil, finish, edition or price equivalence."})
    audit = {"set_code": set_code, "ptcg_revision": PTCG_REVISION,
             "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
             "candidate_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
             "groups_queued": len(queue),
             "same_name_rarity_groups": len(queue),
             "same_illustrator_groups": len(queue),
             "distinct_image_url_groups": sum(r["distinct_source_image_urls"] > 1 for r in queue),
             "scope": "internal variant review queue; no verified printing or offer match"}
    return queue, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--set-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("variant queue output already exists")
    queue, audit = build(args.reference, args.candidates, args.repo.resolve(), args.set_code)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                   for row in queue), encoding="utf-8")
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
