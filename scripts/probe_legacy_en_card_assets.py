"""Probe a narrow, source-bound legacy English image gap for internal review.

The Pokémon TCG API image CDN is a temporary comparison source, not a
production catalog feed. Its card images are never persisted by this script.
The later visual model must verify printed name and collector number.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from scripts.concept_review_ranked import REVISION
from scripts.relationship_pilot import read_jsonl, write_jsonl
from scripts.vertex_concept_review import _source

SET_MAP = {"SM3.5": "sm35", "SWSHP": "swshp", "SWSH12.5GG": "swsh12pt5gg"}


def candidate_url(card: dict) -> str:
    parts = card["card_id"].split(":")
    if len(parts) != 4 or parts[0] != "en" or parts[1] not in SET_MAP:
        raise ValueError("unsupported legacy English source")
    relative = card["provenance"].split(":sha256:", 1)[0].split(":", 2)[-1]
    stem = Path(relative).stem
    printed = parts[2].split("/", 1)[0]
    same_number = (stem.casefold() == printed.casefold()
                   or (stem.isdigit() and printed.isdigit()
                       and int(stem) == int(printed)))
    if not same_number or not re.fullmatch(r"[A-Za-z0-9]+", stem):
        raise ValueError("pinned source filename differs from collector number")
    return f"https://images.pokemontcg.io/{SET_MAP[parts[1]]}/{stem}_hires.png"


def probe(queue: list[dict], previous: list[dict], repo: Path) -> tuple[list[dict], dict]:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != REVISION:
        raise ValueError("TCGdex checkout differs from pinned revision")
    by_id = {row["candidate_id"]: row for row in queue}
    if len(by_id) != len(queue):
        raise ValueError("duplicate relationship candidate")
    targets = []
    for result in previous:
        if (result["artwork_decision"] != "insufficient_images"
                or result["ja_image_status"] != "included"
                or result["en_image_status"] == "included"):
            continue
        card = by_id[result["candidate_id"]]["candidate"]
        if card["set_code"] in SET_MAP:
            targets.append((by_id[result["candidate_id"]], card))
    cache, outputs = {}, []
    for row, card in targets:
        _source(repo, card["provenance"])
        url = candidate_url(card)
        if url not in cache:
            try:
                request = urllib.request.Request(url, headers={
                    "User-Agent": "pokemon-commerce-internal-review/1"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(7_000_001)
                if len(raw) > 7_000_000 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    cache[url] = {"status": "unsupported_image"}
                else:
                    cache[url] = {"status": "included",
                                  "image_sha256": hashlib.sha256(raw).hexdigest(),
                                  "image_bytes": len(raw)}
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                    OSError) as exc:
                cache[url] = {"status": "fetch_failed", "error_type": type(exc).__name__}
        evidence = cache[url]
        if evidence["status"] == "included":
            outputs.append({"candidate_id": row["candidate_id"],
                            "source_snapshot_sha256": row["source_snapshot_sha256"],
                            "en_card_id": card["card_id"], "en_name": card["name"],
                            "image_url": url,
                            "image_sha256": evidence["image_sha256"],
                            "image_bytes": evidence["image_bytes"],
                            "asset_source": "pokemon_tcg_api_image_candidate",
                            "source_note": "Legacy public image CDN; exact printed identity requires model check; internal comparison only; no runtime dependency or image display"})
    report = {"target_pairs": len(targets), "unique_urls": len(cache),
              "asset_status": dict(sorted(Counter(v["status"] for v in cache.values()).items())),
              "source_bound_image_candidates": len(outputs),
              "printing_verified": 0, "price_comparable": 0,
              "scope": "temporary public image evidence, not a licensed production feed"}
    return outputs, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("legacy asset outputs must be new")
    with args.previous.open(encoding="utf-8", newline="") as handle:
        previous = list(csv.DictReader(handle))
    results, report = probe(read_jsonl(args.queue), previous, args.repo.resolve())
    report["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    report["previous_sha256"] = hashlib.sha256(args.previous.read_bytes()).hexdigest()
    write_jsonl(args.output, results)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
