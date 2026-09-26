"""Recheck changed source image hashes without storing or displaying images."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections import Counter
from pathlib import Path

from scripts.calibrate_relationship_artwork import _url_allowed
from scripts.relationship_pilot import read_jsonl, write_jsonl


def _fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": "pokemon-commerce-internal-calibration/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(7_000_001)
        if len(body) > 7_000_000:
            raise ValueError("image exceeds audit size limit")
        return {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                "content_type": response.headers.get("Content-Type"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified")}


def audit(sample: list[dict], second: list[dict]) -> tuple[list[dict], dict]:
    by_id = {row["candidate_id"]: row for row in sample}
    if len(by_id) != len(sample):
        raise ValueError("duplicate calibration sample ID")
    changed = [row for row in second if row["second_decision"] == "source_image_changed"]
    if len({row["candidate_id"] for row in changed}) != len(changed):
        raise ValueError("duplicate source drift result")
    output = []
    for result in changed:
        row = by_id[result["candidate_id"]]
        side = result.get("changed_side")
        if (side not in {"ja", "en"}
                or result["source_snapshot_sha256"] != row["source_snapshot_sha256"]
                or result[f"{side}_image_sha256"] != row[f"{side}_image"]["sha256"]):
            raise ValueError("source drift result does not bind sampled image")
        image = row[f"{side}_image"]
        if not _url_allowed(image["url"], side):
            raise ValueError("source drift URL is outside audited hosts")
        first, repeat = _fetch(image["url"]), _fetch(image["url"])
        output.append({"candidate_id": row["candidate_id"],
                       "first_decision": row["first_decision"],
                       "source_snapshot_sha256": row["source_snapshot_sha256"],
                       "side": side, "source_url": image["url"],
                       "audited_image_sha256": image["sha256"],
                       "current_first": first, "current_repeat": repeat,
                       "repeat_stable": first["sha256"] == repeat["sha256"],
                       "still_changed": first["sha256"] != image["sha256"] and
                                        repeat["sha256"] != image["sha256"],
                       "image_bytes_saved": False})
    counts = Counter((row["repeat_stable"], row["still_changed"]) for row in output)
    report = {"scope": "source image byte stability only; no artwork or printing verdict",
              "changed_candidates": len(output),
              "repeat_stable_and_changed": counts[(True, True)],
              "repeat_stable_and_audited": counts[(True, False)],
              "repeat_unstable": sum(not row["repeat_stable"] for row in output),
              "no_images_saved": True}
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    rows, report = audit(read_jsonl(args.sample), read_jsonl(args.second))
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
