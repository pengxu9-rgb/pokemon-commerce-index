"""Find conservative number leads in two independent public merchant catalogs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pokemon_index import core
from scripts.audit_jp_source_conflicts import TCGDEX_REVISION
from scripts.relationship_pilot import read_jsonl, write_jsonl

SOURCES = {
    "hareruya": "https://www.hareruya2.com/en/pages/buying-list-sm",
    "fullcomp": "https://shopping.fullcomp.jp/collections/p_sm10b",
}


def _page(url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.geturl() != url or "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("merchant catalog redirected or changed content type")
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("merchant catalog page exceeds audit limit")
    rendered = re.sub(r"\s+", "", unicodedata.normalize(
        "NFKC", html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace")))))
    return rendered, hashlib.sha256(raw).hexdigest()


def audit(cards: list[dict], unresolved: list[dict], official_gap: dict,
          tcgdex_repo: Path) -> tuple[list[dict], dict]:
    if (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tcgdex_repo,
                                text=True).strip() != TCGDEX_REVISION
            or subprocess.check_output(["git", "status", "--porcelain", "--", "data-asia"],
                                       cwd=tcgdex_repo, text=True).strip()):
        raise ValueError("TCGdex source differs from pinned revision")
    if (not official_gap["pinned_source_ids_match_official_search"]
            or official_gap["official_search_results"] != 62
            or {x["card_id"] for x in official_gap["unresolved_catalog_cards"]}
               != {x["card_id"] for x in unresolved}):
        raise ValueError("official search-gap audit differs from unresolved cards")
    source_pages = {name: _page(url) for name, url in SOURCES.items()}
    catalog = {core.card_id(x["language"], x["set_code"], x["collector_number"],
                            x["variant"]): x for x in cards}
    output = []
    for missing in unresolved:
        card = catalog[missing["card_id"]]
        if (card["language"] != "ja" or card["set_code"].upper() != "SM10B"
                or not card["provenance"].startswith(f"tcgdex:{TCGDEX_REVISION}:")):
            raise ValueError("unresolved card is outside the pinned SM10b catalog")
        relative, expected = card["provenance"].split(f"tcgdex:{TCGDEX_REVISION}:", 1)[1].split(
            ":sha256:", 1)
        if not re.fullmatch(r"data-asia/SM/SM10b/[0-9]{3}\.ts", relative):
            raise ValueError("unexpected TCGdex source path")
        if hashlib.sha256((tcgdex_repo / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("TCGdex source file changed")
        number = card["collector_number"].split("/")[0] + "/054"
        rarity = "HR" if int(number[:3]) <= 66 else "UR"
        if card["rarity"] != ("Hyper rare" if rarity == "HR" else "Secret Rare"):
            raise ValueError("pinned catalog rarity differs from secondary card grouping")
        name = card["name"]
        patterns = {
            "hareruya": (re.escape(name) + r"\(" + rarity + r"\)\{[^}]{0,20}\}〈"
                         + re.escape(number) + r"〉\[SM10b\]"),
            "fullcomp": (r"\[SM10b\]" + re.escape(name) + r"【" + rarity + r"】"
                         + re.escape(number)),
        }
        evidence = []
        for source, pattern in patterns.items():
            rendered, page_sha = source_pages[source]
            if not re.search(pattern, rendered, re.I):
                raise ValueError(f"merchant {source} lacks exact name, rarity, set and number")
            evidence.append({"url": SOURCES[source], "page_sha256": page_sha,
                             "matched_name": name, "matched_number": number,
                             "rarity_label": rarity})
        output.append({"card_id": missing["card_id"], "rule_id": missing["rule_id"],
                       "catalog_number": card["collector_number"], "catalog_name": name,
                       "source_provenance": card["provenance"],
                       "candidate_number": number, "rarity_label": rarity,
                       "merchant_sources": evidence,
                       "official_search_gap_sha256": official_gap["_artifact_sha256"],
                       "evidence_class": "two_independent_merchant_catalog_text",
                       "physical_printing_status": "unverified",
                       "offer_matching_status": "blocked"})
    output.sort(key=lambda x: x["card_id"])
    return output, {"secondary_candidates": len(output), "sources": [
        {"url": SOURCES[name], "page_sha256": page_sha} for name, (_, page_sha)
        in source_pages.items()], "tcgdex_revision": TCGDEX_REVISION,
        "official_search_gap_sha256": official_gap["_artifact_sha256"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "scope": "two independent merchant catalog text assertions; official record and physical printing remain unverified",
        "offer_match_eligibility_changed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cards", "unresolved", "official-gap", "tcgdex-repo", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("secondary number outputs must be new")
    gap = json.loads(args.official_gap.read_text())
    gap["_artifact_sha256"] = hashlib.sha256(args.official_gap.read_bytes()).hexdigest()
    rows, report = audit(read_jsonl(args.cards), read_jsonl(args.unresolved),
                         gap, args.tcgdex_repo.resolve())
    report["catalog_sha256"] = hashlib.sha256(args.cards.read_bytes()).hexdigest()
    report["unresolved_sha256"] = hashlib.sha256(args.unresolved.read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
