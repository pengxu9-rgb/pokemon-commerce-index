"""Check missing high-number SM10b cards against the official set search feed."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_jp_source_conflicts import PTCG_REVISION
from scripts.relationship_pilot import read_jsonl

BASE = "https://www.pokemon-card.com/card-search/resultAPI.php"


def audit(repo: Path, unresolved: list[dict]) -> dict:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != PTCG_REVISION:
        raise ValueError("official-source checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data_jp"],
                               cwd=repo, text=True).strip():
        raise ValueError("official-source data is dirty")
    source = {str(json.loads(path.read_bytes())["jp_id"]) for path in
              (repo / "data_jp/SM10b").glob("*.json")}
    if len(source) != 62:
        raise ValueError("pinned SM10b source is not the expected 62-record snapshot")
    if (len(unresolved) != 7 or {row["catalog_number"].split("/")[0]
                                for row in unresolved} != {str(n).zfill(3) for n in range(63, 70)}
            or any(not row["card_id"].startswith("ja:SM10B:") for row in unresolved)):
        raise ValueError("unresolved card list differs from the seven high-number cards")
    found, pages, page = set(), [], 1
    while True:
        url = f"{BASE}?mode=statuslist&pg=647&keyword=&illust=&page={page}"
        request = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-commerce-internal-review/1",
            "Referer": "https://www.pokemon-card.com/card-search/index.php?mode=statuslist&pg=647"})
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.geturl() != url:
                raise ValueError("official search feed redirected")
            raw = response.read(250_001)
        if len(raw) > 250_000:
            raise ValueError("official search response exceeds limit")
        payload = json.loads(raw)
        if (str(payload.get("result")) != "1" or int(payload["thisPage"]) != page
                or int(payload["maxPage"]) > 10 or int(payload["hitCnt"]) != 62):
            raise ValueError("official search response shape changed")
        ids = [str(card["cardID"]) for card in payload["cardList"]]
        if len(ids) != len(set(ids)) or found.intersection(ids):
            raise ValueError("official search has duplicate card IDs")
        found.update(ids)
        pages.append({"url": url, "response_sha256": hashlib.sha256(raw).hexdigest(),
                      "card_ids": ids})
        if page == int(payload["maxPage"]):
            break
        page += 1
    if len(found) != 62 or found != source:
        raise ValueError("official search IDs do not equal pinned source IDs")
    return {"fetched_at": datetime.now(timezone.utc).isoformat(),
            "official_set_page": "https://www.pokemon-card.com/products/sm/sm10b.html",
            "official_search_results": 62, "official_search_pages": pages,
            "pinned_source_revision": PTCG_REVISION,
            "pinned_source_ids_match_official_search": True,
            "unresolved_catalog_cards": unresolved,
            "interpretation": "Seven cards lack exact entries in this public official search feed; absence is not evidence that the cards do not exist. Their official collector numbers and physical finishes remain unverified in this audit.",
            "offer_match_eligibility_changed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-jp-repo", type=Path, required=True)
    parser.add_argument("--unresolved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = audit(args.official_jp_repo.resolve(), read_jsonl(args.unresolved))
    report["unresolved_sha256"] = hashlib.sha256(args.unresolved.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"official_search_results": report["official_search_results"],
                      "pages": len(report["official_search_pages"]),
                      "unresolved": len(report["unresolved_catalog_cards"])}))


if __name__ == "__main__":
    main()
