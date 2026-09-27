"""Compare official Japanese multi-record card images without resolving printings.

Every record and image is bound to a pinned source and a prior image hash.
Images are used in memory only. AI labels describe visible artwork relationships,
not foil, edition, physical identity, or offer-match eligibility.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import io
import json
import os
import subprocess
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from scripts.audit_jp_source_conflicts import PTCG_REVISION
from scripts.audit_jp_variant_images import _valid_image_url
from scripts.relationship_pilot import read_jsonl, write_jsonl
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "jp-official-artwork-lineage-v1"
LABELS = {"exact_artwork", "derived_artwork", "different_artwork", "uncertain"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def model_image(raw: bytes) -> tuple[bytes, str, str]:
    """Convert a validated official GIF's first frame in memory for Vertex."""
    if raw.startswith(b"\xff\xd8\xff"):
        return raw, "image/jpeg", "original_jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("official GIF exceeds pixel limit")
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
        return output.getvalue(), "image/png", "gif_first_frame_to_png"
    raise ValueError("unsupported official image type")


def source_images(group: dict, evidence: dict, repo: Path) -> tuple[list[bytes], list[dict]]:
    """Fetch each official image only if source metadata and bytes still match."""
    if group["card_id"] != evidence["card_id"] or group["source_record_sha256"] != evidence["source_record_sha256"]:
        raise ValueError("group and image evidence disagree")
    prior = {int(r["source_jp_id"]): r for r in evidence["records"]}
    if set(prior) != set(group["source_jp_ids"]):
        raise ValueError("prior image records differ from group")
    images, details = [], []
    for source_id, expected_record, page in zip(
        group["source_jp_ids"], group["source_record_sha256"],
        group["official_page_urls"], strict=True
    ):
        matches = list((repo / "data_jp").glob(f"*/{source_id}.json"))
        if len(matches) != 1:
            raise ValueError(f"official source record missing or ambiguous: {source_id}")
        raw = matches[0].read_bytes()
        if sha(raw) != expected_record:
            raise ValueError(f"official source record changed: {source_id}")
        record = json.loads(raw)
        if (record.get("url") != page or record.get("name") != group["name"]
                or str(record.get("set_name", "")).upper() != group["set_code"]
                or f"{str(record.get('number', '')).zfill(3)}/{record.get('set_total')}" != group["collector_number"]):
            raise ValueError(f"official source identity changed: {source_id}")
        url = str(record.get("img", ""))
        if not _valid_image_url(url):
            raise ValueError(f"official image URL outside allowlist: {source_id}")
        detail = {"source_jp_id": source_id, "image_url_sha256": sha(url.encode()),
                  "expected_image_sha256": prior[source_id].get("sha256")}
        if prior[source_id].get("status") != "included":
            detail["status"] = "prior_image_unavailable"
            images.append(b"")
        else:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "pokemon-commerce-internal-review/1"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    image = response.read(7_000_001)
                if len(image) > 7_000_000:
                    detail["status"] = "unsupported_image"
                    images.append(b"")
                elif sha(image) != prior[source_id]["sha256"]:
                    detail["status"] = "image_hash_changed"
                    detail["current_image_sha256"] = sha(image)
                    images.append(b"")
                else:
                    try:
                        converted, mime, conversion = model_image(image)
                    except ValueError:
                        detail["status"] = "unsupported_image"
                        images.append(b"")
                    else:
                        detail.update({"status": "included", "model_image_mime": mime,
                                       "conversion": conversion,
                                       "model_image_sha256": sha(converted)})
                        images.append(converted)
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                detail["status"] = "fetch_failed"
                detail["error_type"] = type(exc).__name__
                images.append(b"")
        details.append(detail)
    return images, details


def model_request(group: dict, images: list[bytes]) -> dict:
    ids = group["source_jp_ids"]
    prompt = f"""Internal Japanese Pokémon card catalog artwork review. Images are official
card scans for the SAME set, collector number and name, but separate official
record IDs. Compare each image after the first (reference image A) with A.
Use exact_artwork when depicted composition, objects and linework match despite
scan color or surface effects; derived_artwork for recolored or altered art
with shared composition; different_artwork for materially different scenes;
uncertain when the illustration area cannot support the distinction.
Report visible differences such as a stamp or foil-like scan effect in a note,
but do NOT infer physical foil, edition, printing identity or market equivalence.
Do not treat translated text or card frame as artwork. Return JSON only:
{{"comparisons":[{{"source_jp_id":integer,"label":one of the four labels,
"visible_reason":string,"possible_surface_or_stamp_difference":boolean}}]}}.
Exactly one comparison for each ID after A, in this order: {ids[1:]}.
"""
    parts = [{"text": prompt}]
    for letter, source_id, image in zip("ABCDEFGH"[:len(ids)], ids, images, strict=True):
        parts.extend([{"text": f"Image {letter}, official record {source_id}:"},
                      {"inlineData": {"mimeType": "image/png" if image.startswith(b"\x89PNG") else "image/jpeg",
                                      "data": base64.b64encode(image).decode()}}])
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 2048}}


def parse_response(response: dict, ids: list[int]) -> tuple[list[dict], str]:
    if response.get("modelVersion") != MODEL:
        raise ValueError("unexpected Vertex model version")
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("incomplete Vertex response")
    body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    items = json.loads(body)["comparisons"]
    if (len(items) != len(ids) - 1 or
            [int(x["source_jp_id"]) for x in items] != ids[1:]):
        raise ValueError("comparison IDs do not match pinned group")
    for item in items:
        if (item.get("label") not in LABELS or not str(item.get("visible_reason", "")).strip()
                or not isinstance(item.get("possible_surface_or_stamp_difference"), bool)):
            raise ValueError("invalid visual comparison")
    return items, sha(body.encode())


def review_one(group: dict, evidence: dict, repo: Path, project: str,
               location: str, token: str) -> dict:
    images, image_details = source_images(group, evidence, repo)
    row = {"card_id": group["card_id"], "source_jp_ids": group["source_jp_ids"],
           "source_record_sha256": group["source_record_sha256"],
           "prior_image_hashes": [r.get("sha256") for r in evidence["records"]],
           "image_evidence": image_details, "model": MODEL,
           "prompt_version": PROMPT_VERSION, "comparisons": [],
           "printing_verified": False, "match_eligible_changed": False}
    if not all(images):
        row["review_status"] = "image_unavailable"
        return row
    request = model_request(group, images)
    row["request_sha256"] = sha(json.dumps(request, sort_keys=True).encode())
    for attempt in range(3):
        try:
            response = _call_model(project, location, token, request)
            row["comparisons"], row["response_sha256"] = parse_response(
                response, group["source_jp_ids"])
            row["review_status"] = "ai_visual_candidate"
            row["usage"] = response.get("usageMetadata", {})
            break
        except (RuntimeError, ValueError, OSError, TimeoutError,
                http.client.HTTPException) as exc:
            row["review_status"] = "model_error"
            row["model_error_type"] = type(exc).__name__
            row["model_attempts"] = attempt + 1
            if attempt < 2:
                time.sleep(attempt + 1)
    return row


def run(queue: list[dict], evidence: list[dict], repo: Path, project: str,
        location: str, checkpoint: Path, workers: int) -> list[dict]:
    if workers < 1:
        raise ValueError("workers must be positive")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() != PTCG_REVISION:
        raise ValueError("Japanese source checkout differs from pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "data_jp"], cwd=repo, text=True).strip():
        raise ValueError("Japanese source data is dirty")
    by_id = {x["card_id"]: x for x in evidence}
    if set(by_id) != {x["card_id"] for x in queue}:
        raise ValueError("queue and prior image evidence differ")
    completed = {x["card_id"]: x for x in read_jsonl(checkpoint)} if checkpoint.exists() else {}
    if set(completed) - set(by_id):
        raise ValueError("checkpoint includes unknown group")
    if checkpoint.exists() and len(completed) != len(read_jsonl(checkpoint)):
        raise ValueError("checkpoint contains duplicate groups")
    for group in queue:
        prior = completed.get(group["card_id"])
        if prior and (prior.get("source_jp_ids") != group["source_jp_ids"]
                      or prior.get("source_record_sha256") != group["source_record_sha256"]
                      or prior.get("prior_image_hashes") != [
                          x.get("sha256") for x in by_id[group["card_id"]]["records"]]
                      or prior.get("prompt_version") != PROMPT_VERSION):
            raise ValueError("checkpoint differs from pinned source or prompt")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    todo = [x for x in queue if x["card_id"] not in completed]
    with ThreadPoolExecutor(max_workers=workers) as pool, checkpoint.open("a", encoding="utf-8") as out:
        futures = {pool.submit(review_one, group, by_id[group["card_id"]], repo,
                               project, location, token): group["card_id"] for group in todo}
        for number, future in enumerate(as_completed(futures), 1):
            result = future.result()
            completed[result["card_id"]] = result
            out.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            out.flush()
            if number % 25 == 0:
                print(f"{number}/{len(todo)} variant groups reviewed", flush=True)
    return [completed[x["card_id"]] for x in queue]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--image-evidence", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("review outputs must be new")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or location not in {"global", "us", "eu"}:
        raise ValueError("Google Cloud project and supported location required")
    queue, image_evidence = read_jsonl(args.queue), read_jsonl(args.image_evidence)
    results = run(queue, image_evidence, args.repo.resolve(), project, location,
                  args.checkpoint, args.workers)
    audit = {"groups": len(results), "model": MODEL, "prompt_version": PROMPT_VERSION,
             "ptcg_revision": PTCG_REVISION,
             "queue_sha256": sha(args.queue.read_bytes()),
             "image_evidence_sha256": sha(args.image_evidence.read_bytes()),
             "statuses": dict(sorted(Counter(x["review_status"] for x in results).items())),
             "labels": dict(sorted(Counter(c["label"] for x in results
                                           for c in x["comparisons"]).items())),
             "physical_printings_verified": 0, "offer_match_eligibility_changed": 0,
             "scope": "official scan artwork lineage candidates only"}
    write_jsonl(args.output, results)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
