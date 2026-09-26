"""Independently review pinned bilingual name proposals with Vertex Gemini.

The prompt includes source TS metadata and source-matched public card images
when available. Image bytes stay in memory; only URLs, hashes and decisions
are retained. This review does not import aliases or printing relationships.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import http.client
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.concept_review_ranked import REVISION, _read_verified
from scripts.relationship_pilot import read_jsonl

MODEL = "gemini-3.8-flash"
PROMPT_VERSION = "vertex-concept-name-review-v1"
CSV_FIELDS = ("proposal_id", "source_snapshot_sha256", "suggested_decision",
              "rationale", "evidence_limits", "image_evidence")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_json(url: str, *, token: str | None = None,
              body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"User-Agent": "pokemon-commerce-internal-review/1"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = "Bearer " + str(token)
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def _source(repo: Path, provenance: str) -> tuple[str, str]:
    prefix = f"tcgdex:{REVISION}:"
    if not provenance.startswith(prefix) or ":sha256:" not in provenance:
        raise ValueError("proposal source is not pinned to the expected revision")
    path, expected = provenance[len(prefix):].rsplit(":sha256:", 1)
    body, actual = _read_verified(repo, path, expected)
    return body, path


def _image(row: dict[str, Any], side: str) -> tuple[bytes | None, dict[str, Any]]:
    language = "ja" if side == "ja" else "en"
    card_id = row[f"{side}_card_id"]
    source_path = row[f"{side}_provenance"].split(":sha256:", 1)[0].split(":", 2)[2]
    local_id = Path(source_path).stem
    set_code = card_id.split(":")[1]
    api_url = (f"https://api.tcgdex.net/v2/{language}/cards/"
               + urllib.parse.quote(f"{set_code}-{local_id}"))
    evidence: dict[str, Any] = {"api_url": api_url, "status": "unavailable"}
    try:
        detail = _get_json(api_url)
        if detail.get("name") != row[f"name_{side}"]:
            evidence["status"] = "api_name_mismatch"
            evidence["api_name"] = detail.get("name")
            return None, evidence
        image_base = detail.get("image")
        if not image_base or urllib.parse.urlparse(image_base).hostname != "assets.tcgdex.net":
            evidence["status"] = "image_missing"
            return None, evidence
        image_url = image_base.rstrip("/") + "/high.webp"
        request = urllib.request.Request(image_url, headers={
            "User-Agent": "pokemon-commerce-internal-review/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            image = response.read(7_000_001)
        if len(image) > 7_000_000 or not (image[:4] == b"RIFF" and image[8:12] == b"WEBP"):
            evidence["status"] = "unsupported_image"
            return None, evidence
        evidence.update({"status": "included", "image_url": image_url,
                         "image_sha256": _sha(image), "image_bytes": len(image)})
        return image, evidence
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            http.client.HTTPException, OSError, ValueError) as exc:
        evidence["status"] = "fetch_failed"
        evidence["error_type"] = type(exc).__name__
        return None, evidence


def _request(row: dict[str, Any], ja_source: str, en_source: str,
             ja_image: bytes | None, en_image: bytes | None) -> dict[str, Any]:
    prompt = f"""You are an independent third reviewer for an internal Pokémon TCG catalog.
Decide whether the two source cards use the same bilingual NAME CONCEPT.
Use the Japanese and English card title, card category/subtype, and distinctive
effect/rule text. Compare both attached card scans where supplied; a scan may
show printing-specific art or finish and does not by itself prove identity.
Do not infer a match from shared illustrator, dates, numeric effects, set era,
or marketplace identifiers alone. Some source text omits type symbols or rules;
if decisive evidence is absent or conflicting, answer uncertain. A generic
English name may correspond to a Japanese title with a character qualifier;
state that limitation explicitly. Never claim matching physical printing,
artwork, finish, condition, or price equivalence.

Proposal ID: {row['proposal_id']}
Japanese name: {row['name_ja']}
English name: {row['name_en']}
Japanese pinned source file follows:\n{ja_source}
English pinned source file follows:\n{en_source}

Return ONLY a JSON object with these string fields:
suggested_decision (approve, reject, or uncertain), rationale (specific
card evidence), evidence_limits (missing/conflicting evidence), image_evidence
(what the images actually show, or explicitly state image missing).
"""
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, image in (("Japanese card scan", ja_image), ("English card scan", en_image)):
        if image is not None:
            parts.append({"text": label + ":"})
            parts.append({"inlineData": {"mimeType": "image/webp",
                                          "data": base64.b64encode(image).decode()}})
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 1200}}


def _call_model(project: str, location: str, token: str,
                request: dict[str, Any]) -> dict[str, Any]:
    url = ("https://aiplatform.googleapis.com/v1/projects/"
           f"{project}/locations/{location}/publishers/google/models/{MODEL}:generateContent")
    for attempt in range(3):
        try:
            return _get_json(url, token=token, body=request)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 503} or attempt == 2:
                raise RuntimeError(f"Vertex returned HTTP {exc.code}") from exc
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _parse_response(response: dict[str, Any]) -> tuple[dict[str, str], str]:
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("Vertex returned no complete candidate")
    text = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    verdict = json.loads(text)
    if verdict.get("suggested_decision") not in {"approve", "reject", "uncertain"}:
        raise ValueError("Vertex returned an invalid decision")
    if not str(verdict.get("rationale", "")).strip():
        raise ValueError("Vertex returned no evidence rationale")
    return {key: str(verdict.get(key, "")) for key in CSV_FIELDS[2:]}, text


def run(queue: list[dict[str, Any]], repo: Path, project: str, location: str,
        checkpoint: Path, *, limit: int | None = None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    actual_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if actual_revision != REVISION:
        raise ValueError("source checkout does not match pinned revision")
    seen = {}
    if checkpoint.exists():
        for item in read_jsonl(checkpoint):
            if item["proposal_id"] in seen:
                raise ValueError("duplicate checkpoint proposal")
            seen[item["proposal_id"]] = item
    selected = queue if limit is None else queue[:limit]
    if set(seen) - {row["proposal_id"] for row in selected}:
        raise ValueError("checkpoint contains an unexpected proposal")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                    text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    all_rows = []
    audit_rows = []
    for index, row in enumerate(selected, 1):
        pid = row["proposal_id"]
        snapshot = json.dumps(row["source_snapshot"], ensure_ascii=False,
                              sort_keys=True).encode()
        if _sha(snapshot) != row["source_snapshot_sha256"]:
            raise ValueError(f"source snapshot mismatch: {pid}")
        prior = seen.get(pid)
        if prior:
            if prior["source_snapshot_sha256"] != row["source_snapshot_sha256"]:
                raise ValueError(f"checkpoint source changed: {pid}")
            result = prior
        else:
            ja_source, ja_path = _source(repo, row["ja_provenance"])
            en_source, en_path = _source(repo, row["en_provenance"])
            ja_image, ja_evidence = _image(row, "ja")
            en_image, en_evidence = _image(row, "en")
            request = _request(row, ja_source, en_source, ja_image, en_image)
            response = _call_model(project, location, token, request)
            if response.get("modelVersion") != MODEL:
                raise ValueError(f"Vertex response model differs from {MODEL}")
            verdict, raw_text = _parse_response(response)
            result = {"proposal_id": pid,
                      "source_snapshot_sha256": row["source_snapshot_sha256"],
                      **verdict,
                      "audit": {"model_version": response["modelVersion"],
                                "prompt_version": PROMPT_VERSION,
                                "request_sha256": _sha(json.dumps(
                                    request, ensure_ascii=False, sort_keys=True).encode()),
                                "response_sha256": _sha(raw_text.encode()),
                                "usage": response.get("usageMetadata", {}),
                                "ja_source_path": ja_path, "en_source_path": en_path,
                                "ja_image": ja_evidence, "en_image": en_evidence}}
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        all_rows.append({key: result[key] for key in CSV_FIELDS})
        audit_rows.append({"proposal_id": pid, **result["audit"]})
        print(f"{index}/{len(selected)} {pid} {result['suggested_decision']}", flush=True)
    audit = {"model": MODEL, "project": project, "location": location,
             "prompt_version": PROMPT_VERSION, "pinned_revision": REVISION,
             "review_rows": len(all_rows),
             "decisions": dict(sorted(Counter(
                 row["suggested_decision"] for row in all_rows).items())),
             "images_included": sum(side["status"] == "included"
                                    for item in audit_rows
                                    for side in (item["ja_image"], item["en_image"])),
             "image_sides_total": len(all_rows) * 2,
             "rows": audit_rows,
             "scope": "independent AI name-concept review; no physical printing verified"}
    return all_rows, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("final Vertex review outputs already exist")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or not project.replace("-", "").isalnum():
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    if location not in {"global", "us", "eu"}:
        raise ValueError("unsupported Gemini 3.8 Flash location")
    rows, audit = run(read_jsonl(args.queue), args.repo.resolve(), project,
                      location, args.checkpoint, limit=args.limit)
    with args.output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps({key: audit[key] for key in
                      ("review_rows", "decisions", "images_included", "image_sides_total")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
