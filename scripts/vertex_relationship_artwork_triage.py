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
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.concept_review_ranked import REVISION
from scripts.relationship_pilot import read_jsonl
from scripts.vertex_concept_review import MODEL, _call_model, _image, _source

FIELDS = ("candidate_id", "source_snapshot_sha256", "artwork_decision",
          "rationale", "evidence_limits", "ja_image_status", "en_image_status")
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
equivalence. The source text is for card identity and provenance, not visual
proof. Return JSON only with artwork_decision (same/different/uncertain),
rationale (specific visible details), and evidence_limits.

Pair ID: {row['candidate_id']}
Japanese card ID and variant: {row['anchor']['card_id']} / {row['anchor']['variant']}
English card ID and variant: {row['candidate']['card_id']} / {row['candidate']['variant']}
Japanese pinned source:\n{ja_source}
English pinned source:\n{en_source}
"""
    return {"contents": [{"role": "user", "parts": [
        {"text": prompt}, {"text": "Japanese card image:"},
        {"inlineData": {"mimeType": "image/webp",
                        "data": base64.b64encode(ja_image).decode()}},
        {"text": "English card image:"},
        {"inlineData": {"mimeType": "image/webp",
                        "data": base64.b64encode(en_image).decode()}},
    ]}], "generationConfig": {"responseMimeType": "application/json",
                              "maxOutputTokens": 1200}}


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
    limits = _limits(str(verdict.get("evidence_limits", "")))
    return {"artwork_decision": verdict["artwork_decision"],
            "rationale": str(verdict["rationale"]),
            "evidence_limits": limits,
            "response_sha256": _sha(body.encode())}


def run(queue: list[dict[str, Any]], repo: Path, project: str, location: str,
        checkpoint: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
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
            en_image, en_evidence = _image(item, "en")
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
                           "response_sha256": None}
            else:
                request = _request(row, ja_source, en_source, ja_image, en_image)
                response = _call_model(project, location, token, request)
                verdict = _parse(response)
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
        output.append({key: result[key] for key in FIELDS})
        audits.append({"candidate_id": cid,
                       "source_snapshot_sha256": result["source_snapshot_sha256"],
                       "response_sha256": result["response_sha256"],
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
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("final visual triage outputs already exist")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    if not project or not project.replace("-", "").isalnum():
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    if location not in {"global", "us", "eu"}:
        raise ValueError("unsupported model location")
    queue = read_jsonl(args.queue)
    source = {item["candidate_id"]: item for path in args.source_queues
              for item in read_jsonl(path)}
    if len(source) != sum(len(read_jsonl(path)) for path in args.source_queues):
        raise ValueError("source relationship queues contain duplicate candidates")
    if any(source.get(item["candidate_id"]) != item for item in queue):
        raise ValueError("first-pass row differs from frozen source queue")
    rows, audit = run(queue, args.repo.resolve(), project,
                      location, args.checkpoint)
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
