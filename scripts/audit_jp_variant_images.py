"""Hash official Japanese images for multi-record review without storing media."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.audit_jp_source_conflicts import PTCG_REVISION
from scripts.relationship_pilot import read_jsonl, write_jsonl


def _valid_image_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname == "www.pokemon-card.com"
            and not parsed.query and not parsed.fragment
            and re.fullmatch(
                r"/assets/images/card_images/large/[^/]+/[^/]+\.(?:jpg|gif)",
                parsed.path) is not None)


def _fetch(url: str) -> dict:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "pokemon-commerce-internal-review/1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(7_000_001)
            if (len(raw) > 7_000_000 or not (
                    raw.startswith(b"\xff\xd8\xff")
                    or raw.startswith((b"GIF87a", b"GIF89a")))):
                return {"status": "unsupported_image"}
            return {"status": "included", "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw)}
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                return {"status": "fetch_failed", "error_type": f"HTTP {exc.code}"}
            error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException,
                OSError) as exc:
            error = type(exc).__name__
        if attempt < 2:
            time.sleep(attempt + 1)
    return {"status": "fetch_failed", "error_type": error}


def audit(queue: list[dict], repo: Path, workers: int = 8,
          checkpoint: Path | None = None) -> tuple[list[dict], dict]:
    if workers < 1:
        raise ValueError("workers must be positive")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != PTCG_REVISION:
        raise ValueError("Japanese source checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data_jp"],
                               cwd=repo, text=True).strip():
        raise ValueError("Japanese source data differs from pinned revision")
    paths = {int(path.stem): path for path in (repo / "data_jp").glob("*/*.json")
             if path.stem.isdigit()}
    urls = {}
    for group in queue:
        if group["review_status"] != "candidate_only":
            raise ValueError("variant group is not pending")
        for source_id, expected, official_page in zip(
                group["source_jp_ids"], group["source_record_sha256"],
                group["official_page_urls"], strict=True):
            path = paths.get(int(source_id))
            if path is None:
                raise ValueError(f"missing pinned Japanese record {source_id}")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"Japanese record hash changed: {source_id}")
            record = json.loads(raw)
            number = f"{str(record.get('number', '')).zfill(3)}/{str(record.get('set_total', ''))}"
            if (record.get("url") != official_page
                    or str(record.get("set_name", "")).upper() != group["set_code"]
                    or number != group["collector_number"]
                    or record.get("name") != group["name"]):
                raise ValueError(f"Japanese record identity changed: {source_id}")
            url = str(record.get("img", ""))
            if not _valid_image_url(url):
                raise ValueError(f"Japanese record image URL is not allowlisted: {source_id}")
            urls[int(source_id)] = url
    fetched = {}
    if checkpoint and checkpoint.exists():
        for row in read_jsonl(checkpoint):
            source_id = int(row["source_jp_id"])
            if (source_id not in urls or row["url_sha256"] != hashlib.sha256(
                    urls[source_id].encode()).hexdigest()):
                raise ValueError("image checkpoint does not match pinned source")
            if row["status"] == "included":
                fetched[source_id] = {key: row[key] for key in ("status", "sha256", "bytes")}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch, url): source_id
                   for source_id, url in urls.items() if source_id not in fetched}
        for number, future in enumerate(as_completed(futures), 1):
            source_id = futures[future]
            result = future.result()
            fetched[source_id] = result
            if checkpoint:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                with checkpoint.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"source_jp_id": source_id,
                                             "url_sha256": hashlib.sha256(
                                                 urls[source_id].encode()).hexdigest(),
                                             **result}, sort_keys=True) + "\n")
            if number % 100 == 0:
                print(f"image hashes {len(fetched)}/{len(urls)}", flush=True)
    results = []
    for group in queue:
        records = [{"source_jp_id": source_id, **fetched[int(source_id)]}
                   for source_id in group["source_jp_ids"]]
        complete = all(record["status"] == "included" for record in records)
        hashes = {record["sha256"] for record in records if record["status"] == "included"}
        results.append({"card_id": group["card_id"], "set_code": group["set_code"],
                        "collector_number": group["collector_number"],
                        "source_record_sha256": group["source_record_sha256"],
                        "records": records,
                        "image_evidence_status": "complete" if complete else "incomplete",
                        "distinct_image_byte_hashes": len(hashes) if complete else None,
                        "identical_image_bytes": len(hashes) == 1 if complete else None,
                        "printing_verified": False, "match_eligible_changed": False})
    report = {"scope": "official image-byte comparison only; identical bytes do not prove identical physical finish",
              "ptcg_revision": PTCG_REVISION, "groups": len(results),
              "source_images": len(urls),
              "image_fetch_status": dict(sorted(Counter(
                  row["status"] for row in fetched.values()).items())),
              "groups_complete": sum(r["image_evidence_status"] == "complete" for r in results),
              "groups_identical_image_bytes": sum(r["identical_image_bytes"] is True
                                                  for r in results),
              "groups_distinct_image_bytes": sum(r["identical_image_bytes"] is False
                                                 for r in results),
              "no_printing_or_match_promotion": True}
    return results, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("image hash outputs must be new")
    rows, report = audit(read_jsonl(args.queue), args.repo.resolve(), args.workers,
                         args.checkpoint)
    report["queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                    indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
