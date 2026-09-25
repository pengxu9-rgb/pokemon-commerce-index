"""Classify authorized gateway photos as card front/back without assuming array order.

Input is a JSONL manifest of local, transient files supplied by an authorized
feed adapter. No photo is downloaded or committed here. Ambiguous sides abstain.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from pokemon_index import core
from pokemon_index.offer_comparison import _https_ref
from scripts.relationship_pilot import read_jsonl
from scripts.vertex_concept_review import MODEL, _call_model
from scripts.vertex_offer_visual_review import _load_image


def _request(item: dict[str, Any], photos: list[tuple[bytes, str]]) -> dict[str, Any]:
    prompt = ("Identify a single physical trading card's front and back among these "
              "numbered marketplace photos. Return JSON only with front_index and "
              "back_index (zero-based integers or null) and rationale. Select a side "
              "only if visibly clear. Packaging, collages, slabs, stock images, and "
              "multiple cards are not proof of either side. Never infer the back "
              "from photo order. If uncertain, use null. Listing ID: "
              f"{item['source']}/{item['native_id']}.")
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for index, (data, mime) in enumerate(photos):
        parts.extend([{"text": f"Photo index {index}:"},
                      {"inlineData": {"mimeType": mime,
                                      "data": base64.b64encode(data).decode()}}])
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 512}}


def _parse(response: dict[str, Any], count: int) -> dict[str, Any]:
    if response.get("modelVersion") != MODEL:
        raise ValueError("unexpected Vertex model version")
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("Vertex returned no complete photo-side finding")
    body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    result = json.loads(body)
    for side in ("front_index", "back_index"):
        index = result.get(side)
        if index is not None and (type(index) is not int or not 0 <= index < count):
            raise ValueError("photo-side index is invalid")
    if result.get("front_index") == result.get("back_index") and result.get("front_index") is not None:
        raise ValueError("one photo cannot prove both sides")
    if not isinstance(result.get("rationale"), str) or not result["rationale"].strip():
        raise ValueError("photo-side finding lacks rationale")
    return {key: result.get(key) for key in ("front_index", "back_index", "rationale")}


def run(db: sqlite3.Connection, manifest: list[dict[str, Any]], project: str,
        location: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                    text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    media_rows, review_rows, audit_rows = [], [], []
    for item in manifest:
        core._required(item, "source", "native_id", "observed_at", "card_id",
                       "rights_reference", "photos")
        if not core._policy(db, item["source"])["media_ai_allowed"]:
            raise ValueError("source has not authorized image AI analysis")
        at = core.parse_time(item["observed_at"]).isoformat()
        if not db.execute("SELECT 1 FROM observation WHERE source=? AND native_id=? AND observed_at=?",
                          (item["source"], item["native_id"], at)).fetchone():
            raise ValueError("photo-side manifest lacks imported observation")
        if not db.execute("SELECT 1 FROM card WHERE card_id=?", (item["card_id"],)).fetchone():
            raise ValueError("photo-side manifest references unknown card")
        entries = item["photos"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
            raise ValueError("photo-side pass accepts one to eight candidate photos")
        photos, references, hashes = [], [], []
        for entry in entries:
            if not isinstance(entry, dict) or not _https_ref(str(entry.get("ref", ""))):
                raise ValueError("candidate photo needs an HTTPS source ref")
            data = Path(entry["path"]).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if entry.get("sha256") and entry["sha256"] != digest:
                raise ValueError("candidate image hash changed")
            loaded, mime = _load_image(Path(entry["path"]), digest)
            photos.append((loaded, mime))
            references.append(entry["ref"])
            hashes.append(digest)
        if sum(len(data) for data, _ in photos) > 20_000_000:
            raise ValueError("candidate photos exceed total request size")
        response = _call_model(project, location, token, _request(item, photos))
        decision = _parse(response, len(photos))
        evidence = "vertex:response-sha256:" + hashlib.sha256(json.dumps(
            response, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        audit_rows.append({"source": item["source"], "native_id": item["native_id"],
                           "observed_at": at, "candidate_refs": references,
                           "candidate_sha256": hashes, "model": MODEL,
                           "evidence_ref": evidence, **decision})
        front = decision["front_index"]
        back = decision["back_index"]
        if front is None:
            continue
        media_rows.append({"source": item["source"], "native_id": item["native_id"],
                           "observed_at": at, "front_ref": references[front],
                           "front_sha256": hashes[front],
                           "back_ref": references[back] if back is not None else None,
                           "back_sha256": hashes[back] if back is not None else None,
                           "rights_reference": item["rights_reference"]})
        review_rows.append({"source": item["source"], "native_id": item["native_id"],
                            "observed_at": at, "card_id": item["card_id"],
                            "front_path": entries[front]["path"],
                            "back_path": entries[back]["path"] if back is not None else None})
    return media_rows, review_rows, audit_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--media-output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.media_output, args.review_output, args.audit_output)
    if len(set(outputs)) != 3 or any(path.exists() for path in outputs):
        raise FileExistsError("output paths must be unique and absent")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or not project.replace("-", "").isalnum():
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    if location not in {"global", "us", "eu"}:
        raise ValueError("unsupported Vertex location")
    with core.connect(args.db) as db:
        rows = run(db, read_jsonl(args.manifest), project, location)
    for path, values in zip(outputs, rows):
        with path.open("x", encoding="utf-8") as handle:
            for value in values:
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"media": len(rows[0]), "review_manifest": len(rows[1]),
                      "audit": len(rows[2])}))


if __name__ == "__main__":
    main()
