"""Use Vertex Gemini to triage artwork on source-bound card pairs.

This is visual research for a human review queue. It cannot establish finish,
edition, condition, exact printing equivalence, or a verified graph edge.
Images remain in memory; the output retains image provenance and limitations.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
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

from scripts.concept_review_ranked import REVISION
from scripts.official_jp_image_evidence import OfficialJPImageIndex
from scripts.tcgdex_asset_discovery import fetch as discover_tcgdex_asset
from scripts.relationship_pilot import read_jsonl
from scripts.vertex_concept_review import MODEL, _call_model, _image, _source

FIELDS = ("candidate_id", "source_snapshot_sha256", "artwork_decision",
          "rationale", "evidence_limits", "ja_image_status", "en_image_status",
          "en_image_identity")
PROMPT_VERSION = "vertex-card-artwork-triage-v1"
STANDARD_LIMIT = ("Visual artwork comparison does not verify foil, variant, "
                  "edition, exact printing, condition or price equivalence.")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _limits(value: str) -> str:
    limits = value.strip()
    if limits.casefold() in {"", "none", "n/a"}:
        return STANDARD_LIMIT
    if STANDARD_LIMIT not in limits:
        return limits + " " + STANDARD_LIMIT
    return limits


def _adapt(row: dict[str, Any]) -> dict[str, str]:
    return {"ja_card_id": row["anchor"]["card_id"],
            "en_card_id": row["candidate"]["card_id"],
            "ja_provenance": row["anchor"]["provenance"],
            "en_provenance": row["candidate"]["provenance"],
            "name_ja": row["anchor"]["name"],
            "name_en": row["candidate"]["name"]}


def _request(row: dict[str, Any], ja_source: str, en_source: str,
             ja_image: bytes, en_image: bytes) -> dict[str, Any]:
    prompt = f"""You are reviewing a candidate pair in an internal Pokémon card catalog.
Compare only the illustrated ARTWORK area on the Japanese and English card
images. Decide same, different, or uncertain. Ignore translated card text,
language-specific card frames and set symbols. If the art is obscured, cropped,
or ambiguous, choose uncertain. Identical characters or similar composition
are not enough unless details of the depicted scene agree.

The images may represent a default card from the set and collector number;
they do not prove the listed foil, promo, reverse or other variant. Do NOT
claim identical printing, finish, edition, condition, rarity, value or market
equivalence. Also read the English card name and collector number on its image;
if either visibly conflicts with the supplied identity, choose uncertain.
The source text is for card identity and provenance, not visual proof. Return
JSON only with artwork_decision (same/different/uncertain), rationale (specific
visible details), evidence_limits, and en_image_identity (match/mismatch/uncertain).

Pair ID: {row['candidate_id']}
Japanese card ID and variant: {row['anchor']['card_id']} / {row['anchor']['variant']}
English card ID and variant: {row['candidate']['card_id']} / {row['candidate']['variant']}
Japanese pinned source:\n{ja_source}
English pinned source:\n{en_source}
"""
    return {"contents": [{"role": "user", "parts": [
        {"text": prompt}, {"text": "Japanese card image:"},
        {"inlineData": {"mimeType": _mime(ja_image),
                        "data": base64.b64encode(ja_image).decode()}},
        {"text": "English card image:"},
        {"inlineData": {"mimeType": _mime(en_image),
                        "data": base64.b64encode(en_image).decode()}},
    ]}], "generationConfig": {"responseMimeType": "application/json",
                              "maxOutputTokens": 2048}}


def _mime(image: bytes) -> str:
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("unsupported card image format")


def _prior_image(prior: dict[str, Any], snapshot_sha: str,
                 side: str) -> tuple[bytes | None, dict[str, Any]]:
    """Reuse a previously audited public asset only when its bytes still match."""
    evidence = prior.get(f"{side}_image", {})
    url = evidence.get("image_url", "")
    parsed = urllib.parse.urlparse(url)
    expected_sha = evidence.get("image_sha256", "")
    result: dict[str, Any] = {"status": "prior_asset_unavailable"}
    if (prior.get("source_snapshot_sha256") != snapshot_sha
            or evidence.get("status") != "included"
            or parsed.scheme != "https" or parsed.hostname != "assets.tcgdex.net"
            or parsed.query or parsed.fragment or not parsed.path.endswith("/high.webp")
            or len(expected_sha) != 64):
        return None, result
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-commerce-internal-review/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            image = response.read(7_000_001)
        if len(image) > 7_000_000 or _mime(image) != "image/webp":
            result["status"] = "unsupported_image"
        elif _sha(image) != expected_sha:
            result["status"] = "prior_asset_hash_changed"
        else:
            result.update({"status": "included", "image_url": url,
                           "image_sha256": expected_sha, "image_bytes": len(image),
                           "source": "prior_source_bound_audit"})
            return image, result
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        result.update({"status": "fetch_failed", "error_type": type(exc).__name__})
    return None, result


def _parse(response: dict[str, Any]) -> dict[str, str]:
    if response.get("modelVersion") != MODEL:
        raise ValueError("Vertex returned an unexpected model version")
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("Vertex returned no complete candidate")
    body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    verdict = json.loads(body)
    if verdict.get("artwork_decision") not in {"same", "different", "uncertain"}:
        raise ValueError("Vertex returned an invalid artwork decision")
    if not str(verdict.get("rationale", "")).strip():
        raise ValueError("Vertex returned no visual rationale")
    if verdict.get("en_image_identity") not in {"match", "mismatch", "uncertain"}:
        raise ValueError("Vertex returned no English image identity check")
    limits = _limits(str(verdict.get("evidence_limits", "")))
    return {"artwork_decision": verdict["artwork_decision"],
            "rationale": str(verdict["rationale"]),
            "evidence_limits": limits,
            "en_image_identity": verdict["en_image_identity"],
            "response_sha256": _sha(body.encode())}


def _curated_image(record: dict[str, Any], row: dict[str, Any]
                   ) -> tuple[bytes | None, dict[str, Any]]:
    result: dict[str, Any] = {"status": "curated_asset_unavailable"}
    if (record.get("candidate_id") != row["candidate_id"]
            or record.get("source_snapshot_sha256") != row["source_snapshot_sha256"]
            or record.get("en_card_id") != row["candidate"]["card_id"]
            or record.get("en_name") != row["candidate"]["name"]):
        return None, result
    url = record.get("image_url", "")
    parsed = urllib.parse.urlparse(url)
    expected = record.get("image_sha256", "")
    if (parsed.scheme != "https" or parsed.hostname != "assets.tcgdex.net"
            or parsed.query or parsed.fragment or not parsed.path.endswith("/high.webp")
            or not isinstance(expected, str) or len(expected) != 64):
        return None, result
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-commerce-internal-review/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            image = response.read(7_000_001)
        if len(image) > 7_000_000 or _mime(image) != "image/webp":
            result["status"] = "unsupported_image"
        elif _sha(image) != expected:
            result["status"] = "curated_asset_hash_changed"
        else:
            result.update({"status": "included", "image_url": url,
                           "image_sha256": expected, "image_bytes": len(image),
                           "source": "curated_hash_bound_asset",
                           "source_note": record.get("source_note", "")})
            return image, result
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        result.update({"status": "fetch_failed", "error_type": type(exc).__name__})
    return None, result


def run(queue: list[dict[str, Any]], repo: Path, project: str, location: str,
        checkpoint: Path, official_jp: OfficialJPImageIndex | None = None,
        prior_audit: dict[str, dict[str, Any]] | None = None,
        curated_assets: dict[str, dict[str, Any]] | None = None,
        discover_en_assets: bool = False
        ) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                               text=True).strip() != REVISION:
        raise ValueError("source checkout does not match pinned revision")
    seen: dict[str, dict[str, Any]] = {}
    if checkpoint.exists():
        for item in read_jsonl(checkpoint):
            if item["candidate_id"] in seen:
                raise ValueError("duplicate checkpoint candidate")
            seen[item["candidate_id"]] = item
    if set(seen) - {row["candidate_id"] for row in queue}:
        raise ValueError("checkpoint contains an unexpected candidate")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                    text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    output, audits = [], []
    for number, row in enumerate(queue, 1):
        cid = row["candidate_id"]
        if not row.get("retrieval_only") or row["review"]["decision"] != "pending":
            raise ValueError(f"relationship candidate is not pending: {cid}")
        pair = sorted((row["anchor"]["card_id"], row["candidate"]["card_id"]))
        expected_id = hashlib.sha256(("relationship-pilot-v1\0" + "\0".join(pair))
                                     .encode()).hexdigest()[:20]
        if cid != expected_id:
            raise ValueError(f"relationship candidate ID changed: {cid}")
        prior = seen.get(cid)
        if prior:
            if prior["source_snapshot_sha256"] != row["source_snapshot_sha256"]:
                raise ValueError(f"checkpoint snapshot changed: {cid}")
            result = dict(prior)
        else:
            item = _adapt(row)
            ja_source, ja_path = _source(repo, item["ja_provenance"])
            en_source, en_path = _source(repo, item["en_provenance"])
            ja_image, ja_evidence = _image(item, "ja")
            if ja_image is None and official_jp is not None:
                fallback_image, fallback_evidence = official_jp.get(
                    item["ja_card_id"], item["name_ja"])
                fallback_evidence["tcgdex_attempt"] = ja_evidence
                ja_image, ja_evidence = fallback_image, fallback_evidence
            en_image, en_evidence = _image(item, "en")
            if en_image is None and prior_audit and cid in prior_audit:
                fallback_image, fallback_evidence = _prior_image(
                    prior_audit[cid], row["source_snapshot_sha256"], "en")
                fallback_evidence["tcgdex_attempt"] = en_evidence
                en_image, en_evidence = fallback_image, fallback_evidence
            if en_image is None and curated_assets and cid in curated_assets:
                fallback_image, fallback_evidence = _curated_image(
                    curated_assets[cid], row)
                fallback_evidence["tcgdex_attempt"] = en_evidence
                en_image, en_evidence = fallback_image, fallback_evidence
            if en_image is None and discover_en_assets:
                fallback_image, fallback_evidence = discover_tcgdex_asset(
                    item["en_card_id"], item["en_provenance"])
                fallback_evidence["tcgdex_attempt"] = en_evidence
                en_image, en_evidence = fallback_image, fallback_evidence
            evidence: dict[str, Any] = {
                "model_version": None, "prompt_version": PROMPT_VERSION,
                "ja_source_path": ja_path, "en_source_path": en_path,
                "ja_image": ja_evidence, "en_image": en_evidence,
                "variant_image_verified": False,
            }
            if ja_image is None or en_image is None:
                verdict = {"artwork_decision": "insufficient_images",
                           "rationale": "Both source-matched card images are required for visual comparison.",
                           "evidence_limits": "Missing image side is recorded; no visual verdict.",
                           "en_image_identity": "not_checked",
                           "response_sha256": None}
            else:
                request = _request(row, ja_source, en_source, ja_image, en_image)
                verdict, response = None, None
                for attempt in range(3):
                    try:
                        response = _call_model(project, location, token, request)
                        verdict = _parse(response)
                        break
                    except ValueError as exc:
                        if "no complete candidate" in str(exc):
                            request["generationConfig"]["maxOutputTokens"] = 4096
                        evidence["model_error_type"] = type(exc).__name__
                    except RuntimeError as exc:
                        if not any(f"HTTP {code}" in str(exc) for code in
                                   (400, 408, 429, 500, 502, 503, 504)):
                            raise
                        evidence["model_error_type"] = str(exc)
                    except (urllib.error.URLError, TimeoutError) as exc:
                        evidence["model_error_type"] = type(exc).__name__
                    if attempt < 2:
                        time.sleep(attempt + 1)
                if verdict is None:
                    verdict = {"artwork_decision": "model_error",
                               "rationale": "Vertex did not return a usable artwork decision after three attempts.",
                               "evidence_limits": "No visual verdict; this candidate remains pending.",
                               "en_image_identity": "not_checked",
                               "response_sha256": None}
                else:
                    if (en_evidence.get("source") in {
                            "curated_hash_bound_asset", "convention_asset_discovery"}
                            and verdict["en_image_identity"] != "match"):
                        verdict["artwork_decision"] = "uncertain"
                        verdict["evidence_limits"] = _limits(
                            "Curated English image identity was not confirmed by visual review.")
                    evidence.update({"model_version": response["modelVersion"],
                                     "request_sha256": _sha(json.dumps(
                                         request, ensure_ascii=False, sort_keys=True).encode()),
                                     "usage": response.get("usageMetadata", {})})
            result = {"candidate_id": cid,
                      "source_snapshot_sha256": row["source_snapshot_sha256"],
                      **verdict,
                      "ja_image_status": ja_evidence["status"],
                      "en_image_status": en_evidence["status"],
                      "audit": evidence}
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        result["evidence_limits"] = _limits(result["evidence_limits"])
        output.append({key: result.get(key, "") for key in FIELDS})
        audits.append({"candidate_id": cid,
                       "source_snapshot_sha256": result["source_snapshot_sha256"],
                       "response_sha256": result["response_sha256"],
                       "en_image_identity": result.get("en_image_identity", ""),
                       **result["audit"]})
        print(f"{number}/{len(queue)} {cid} {result['artwork_decision']}", flush=True)
    audit = {"model": MODEL, "project": project, "location": location,
             "prompt_version": PROMPT_VERSION, "pinned_revision": REVISION,
             "candidate_rows": len(queue),
             "decisions": dict(sorted(Counter(
                 item["artwork_decision"] for item in output).items())),
             "both_images_included": sum(item["ja_image_status"] == "included" and
                                          item["en_image_status"] == "included"
                                          for item in output),
             "rows": audits,
             "scope": "AI visual artwork triage only; no physical printing or finish verified"}
    return output, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--source-queues", type=Path, nargs="+", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--official-jp-repo", type=Path)
    parser.add_argument("--official-jp-revision")
    parser.add_argument("--prior-artwork-audit", type=Path)
    parser.add_argument("--curated-assets", type=Path)
    parser.add_argument("--discover-en-assets", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("final visual triage outputs already exist")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or not project.replace("-", "").isalnum():
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    if location not in {"global", "us", "eu"}:
        raise ValueError("unsupported model location")
    if bool(args.official_jp_repo) != bool(args.official_jp_revision):
        raise ValueError("official Japanese source needs both repository and revision")
    official_jp = (OfficialJPImageIndex(args.official_jp_repo.resolve(),
                                        args.official_jp_revision)
                   if args.official_jp_repo else None)
    prior_audit = None
    if args.prior_artwork_audit:
        prior_rows = json.loads(args.prior_artwork_audit.read_text(encoding="utf-8"))["rows"]
        prior_audit = {row["candidate_id"]: row for row in prior_rows}
        if len(prior_audit) != len(prior_rows):
            raise ValueError("duplicate candidates in prior artwork audit")
    curated_assets = None
    if args.curated_assets:
        asset_rows = read_jsonl(args.curated_assets)
        curated_assets = {row["candidate_id"]: row for row in asset_rows}
        if len(curated_assets) != len(asset_rows):
            raise ValueError("duplicate curated assets")
    queue = read_jsonl(args.queue)
    source = {item["candidate_id"]: item for path in args.source_queues
              for item in read_jsonl(path)}
    if len(source) != sum(len(read_jsonl(path)) for path in args.source_queues):
        raise ValueError("source relationship queues contain duplicate candidates")
    if any(source.get(item["candidate_id"]) != item for item in queue):
        raise ValueError("first-pass row differs from frozen source queue")
    rows, audit = run(queue, args.repo.resolve(), project,
                      location, args.checkpoint, official_jp, prior_audit,
                      curated_assets, args.discover_en_assets)
    with args.output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps({key: audit[key] for key in (
        "candidate_rows", "decisions", "both_images_included")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
