"""Check every scaled relationship candidate against pinned local source bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

from scripts.concept_review_ranked import REVISION
from scripts.relationship_pilot import read_jsonl
from scripts.vertex_concept_review import _source


def audit(queue_path: Path, db_path: Path, repo: Path) -> dict:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != REVISION:
        raise ValueError("TCGdex checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data", "data-asia"],
                               cwd=repo, text=True).strip():
        raise ValueError("TCGdex source files differ from pinned revision")
    queue = read_jsonl(queue_path)
    source_cache = {}
    pairs = set()
    signals = Counter()
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
        for row in queue:
            if not row.get("retrieval_only") or row["review"]["decision"] != "pending":
                raise ValueError("candidate is incorrectly marked reviewed")
            left, right = row["anchor"], row["candidate"]
            if (left["language"], right["language"]) != ("ja", "en"):
                raise ValueError("expected JA/EN candidate")
            pair = (left["card_id"], right["card_id"])
            if pair in pairs:
                raise ValueError("duplicate card pair")
            pairs.add(pair)
            expected_id = hashlib.sha256(("relationship-pilot-v1\0" + "\0".join(
                sorted(pair))).encode()).hexdigest()[:20]
            if row["candidate_id"] != expected_id:
                raise ValueError("candidate ID differs from card pair")
            for card in (left, right):
                catalog = db.execute("SELECT language,set_code,collector_number,variant,name,provenance "
                                     "FROM card WHERE card_id=?", (card["card_id"],)).fetchone()
                if catalog is None or tuple(card[field] for field in (
                        "language", "set_code", "collector_number", "variant", "name",
                        "provenance")) != catalog:
                    raise ValueError(f"catalog identity drifted: {card['card_id']}")
                if card["provenance"] not in source_cache:
                    _, path = _source(repo, card["provenance"])
                    source_cache[card["provenance"]] = path
            signals[row["shared_facets"]["retrieval_signal"]] += 1
    return {"scope": "source and catalog identity validation only; no artwork, printing or relationship claim",
            "tcgdex_revision": REVISION,
            "queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
            "candidate_pairs": len(queue), "distinct_pairs": len(pairs),
            "unique_pinned_source_files_checked": len(source_cache),
            "signals": dict(sorted(signals.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = audit(args.queue, args.db, args.repo.resolve())
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                      indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
