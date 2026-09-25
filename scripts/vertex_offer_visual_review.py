"""Run a first, source-authorized Gemini pass on local listing photo files.

Input photos are supplied by an authorized feed adapter in a temporary folder.
They are read in memory, never copied to the repository. A second independent
model family must agree before a listing becomes price-comparison eligible.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from pokemon_index import core
from pokemon_index.offer_comparison import CONDITIONS
from scripts.relationship_pilot import read_jsonl
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "offer-visual-review-v1"


def _load_image(path: Path, expected_sha: str) -> tuple[bytes, str]:
    data = path.read_bytes()
    if len(data) > 7_000_000 or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("listing photo hash or size differs from media snapshot")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, "image/webp"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    raise ValueError("unsupported listing photo format")


def _request(card: sqlite3.Row, item: dict[str, Any], images: list[tuple[str, bytes, str]]
             ) -> dict[str, Any]:
    prompt = f"""You are auditing a marketplace listing for one physical Pokémon card.
Use ONLY visible evidence in the listing photos. The expected catalog printing is:
language={card['language']}; name={card['name']}; set={card['set_code']};
collector_number={card['collector_number']}; catalog_variant={card['variant']}.
Listing source/native id: {item['source']}/{item['native_id']}.

First check whether the visible printed name, language, set symbol/code and
collector number support this exact catalog card. A shared illustration or
seller title is insufficient. Then inspect the visible foil/texture/edition
marks. A flat photo often cannot prove a foil pattern; answer uncertain when
glare or resolution prevents it. Finally assess visible raw-card condition
from both front and back using only mint, near_mint, light_played,
moderate_played, heavy_played or damaged. Missing back, glare or obscured
corners means condition_decision=uncertain. Do not claim a PSA/BGS grade,
authenticity, hidden surface condition, paid price, or identical market value.

Return JSON only with identity_decision (match/mismatch/uncertain),
finish_decision (match/mismatch/uncertain), observed_finish (lowercase code or
null), condition_decision (assessed/uncertain), condition_bucket (one allowed
bucket or null), and rationale (specific visible evidence and limitations).
"""
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, data, mime in images:
        parts.extend([{"text": label + " listing photo:"},
                      {"inlineData": {"mimeType": mime,
                                      "data": base64.b64encode(data).decode()}}])
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 1400}}


def _parse(response: dict[str, Any], has_back: bool) -> dict[str, Any]:
    if response.get("modelVersion") != MODEL:
        raise ValueError("unexpected Vertex model version")
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("Vertex returned no complete visual finding")
    body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    result = json.loads(body)
    if result.get("identity_decision") not in {"match", "mismatch", "uncertain"}:
        raise ValueError("invalid identity decision")
    if result.get("finish_decision") not in {"match", "mismatch", "uncertain"}:
        raise ValueError("invalid finish decision")
    if result.get("condition_decision") not in {"assessed", "uncertain"}:
        raise ValueError("invalid condition decision")
    if (result["condition_decision"] == "assessed"
            and (not has_back or result.get("condition_bucket") not in CONDITIONS)):
        raise ValueError("condition finding lacks front/back support")
    if result["condition_decision"] == "uncertain":
        result["condition_bucket"] = None
    if result["finish_decision"] == "match" and not re.fullmatch(
            r"[a-z0-9_]{2,64}", str(result.get("observed_finish") or "")):
        raise ValueError("matched finish needs an observed finish code")
    if not isinstance(result.get("rationale"), str) or not result["rationale"].strip():
        raise ValueError("visual finding lacks rationale")
    return {key: result.get(key) for key in (
        "identity_decision", "finish_decision", "observed_finish",
        "condition_decision", "condition_bucket", "rationale")}


def run(db: sqlite3.Connection, manifest: list[dict[str, Any]], project: str,
        location: str) -> list[dict[str, Any]]:
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                    text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    output = []
    for item in manifest:
        core._required(item, "source", "native_id", "observed_at", "card_id", "front_path")
        policy = core._policy(db, item["source"])
        if not policy["media_ai_allowed"]:
            raise ValueError("source has not authorized image AI analysis")
        at = core.parse_time(item["observed_at"]).isoformat()
        media = db.execute(
            """SELECT * FROM offer_media_snapshot
            WHERE source=? AND native_id=? AND observed_at=?""",
            (item["source"], item["native_id"], at)).fetchone()
        card = db.execute("SELECT * FROM card WHERE card_id=?",
                          (item["card_id"],)).fetchone()
        if not media or not card:
            raise ValueError("manifest lacks imported media or catalog card")
        images = []
        for side in ("front", "back"):
            path = item.get(f"{side}_path")
            if bool(path) != bool(media[f"{side}_sha256"]):
                raise ValueError("manifest photo sides differ from media snapshot")
            if path:
                data, mime = _load_image(Path(path), media[f"{side}_sha256"])
                images.append((side, data, mime))
        request = _request(card, item, images)
        response = _call_model(project, location, token, request)
        decision = _parse(response, bool(media["back_sha256"]))
        reviewed_at = core.utcnow()
        fingerprint = hashlib.sha256(json.dumps({
            "source": item["source"], "native_id": item["native_id"],
            "observed_at": at, "card_id": item["card_id"],
            "front_sha256": media["front_sha256"],
            "back_sha256": media["back_sha256"],
            "model": MODEL, "prompt_version": PROMPT_VERSION,
            "reviewed_at": reviewed_at,
            "response": decision}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        output.append({"review_id": "vertex-offer-v1:" + fingerprint,
                       "source": item["source"], "native_id": item["native_id"],
                       "observed_at": at, "card_id": item["card_id"],
                       "model_family": "google", "model_version": MODEL,
                       "reviewed_at": reviewed_at,
                       "front_sha256": media["front_sha256"],
                       "back_sha256": media["back_sha256"],
                       "evidence_ref": "vertex:response-sha256:" + hashlib.sha256(
                           json.dumps(response, ensure_ascii=False,
                                      sort_keys=True).encode()).hexdigest(),
                       **decision})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or not project.replace("-", "").isalnum():
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    if location not in {"global", "us", "eu"}:
        raise ValueError("unsupported Vertex location")
    with core.connect(args.db) as db:
        rows = run(db, read_jsonl(args.manifest), project, location)
    with args.output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"reviews": len(rows), "model": MODEL}))


if __name__ == "__main__":
    main()
