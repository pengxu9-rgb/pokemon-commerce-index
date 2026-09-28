"""Independently route frozen public questions with Vertex Gemini 3.8 Flash.

The model sees only the short question and media-availability flag, not source
replies, strata, Astra labels, a catalog ID, or the target system's prediction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.public_question_sandbox import (ACTORS, EVIDENCE, FORBIDDEN,
                                             IDENTITY_STATES, INTENTS, NEXT_ACTIONS,
                                             SCHEMA, read_jsonl, sha_file,
                                             validate_label)
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-routing-gemini-v1"


def _request(question: dict) -> tuple[dict, str]:
    prompt = f"""Classify one real-world Pokémon card buyer or seller question for an
internal evidence-routing study. You see only a short source-condensed question,
not the original post's replies or images. Do not answer the question. Never
invent an exact card, current price, sold price, physical condition, authenticity,
grade, or JP/EN artwork relationship. A missing photo is missing evidence.
Select one primary intent and one safe next action. Seller questions may be
outside the current card-index product. Return a JSON object with exactly these
fields: actor, primary_intent, identity_state, next_action, required_evidence
(array), forbidden_claims (array), rationale (one short sentence).

actor: {sorted(ACTORS)}
primary_intent: {sorted(INTENTS)}
identity_state: {sorted(IDENTITY_STATES)}
next_action: {sorted(NEXT_ACTIONS)}
required_evidence items: {sorted(EVIDENCE)}
forbidden_claims items: {sorted(FORBIDDEN)}

Question language: {question['language']}
Media state: {question['media_state']}
Question: {question['question']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 1200}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def _parse(response: dict) -> tuple[dict, str, str]:
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in ("STOP", None):
        raise ValueError("Gemini returned no complete candidate")
    content = candidates[0].get("content") or {}
    raw = "".join(part.get("text", "") for part in content.get("parts", []))
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Gemini did not return an object")
    rationale = value.pop("rationale", None)
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Gemini rationale is missing")
    label = validate_label(value)
    return label, rationale.strip(), hashlib.sha256(raw.encode()).hexdigest()


def run(frozen_dir: Path, checkpoint: Path, project: str, location: str,
        limit: int | None = None) -> dict:
    if location not in {"global", "us", "eu"} or not project.replace("-", "").isalnum():
        raise ValueError("unsupported Vertex project or location")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"]):
        raise ValueError("frozen questions differ from manifest")
    questions = read_jsonl(frozen_dir / "blind_questions.jsonl")
    selected = questions if limit is None else questions[:limit]
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["id"]: row for row in existing}
    if len(by_id) != len(existing) or set(by_id) - {q["id"] for q in selected}:
        raise ValueError("checkpoint has duplicate or unexpected question IDs")
    for q in selected:
        prior = by_id.get(q["id"])
        if prior and (prior.get("question_sha256") != q["question_sha256"] or
                      prior.get("model_family") != "google"):
            raise ValueError("checkpoint review differs from frozen question")
    pending = [q for q in selected if q["id"] not in by_id]
    token = None
    if pending:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                        text=True, stderr=subprocess.DEVNULL).strip()
        if not token:
            raise ValueError("gcloud returned no access token")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("a", encoding="utf-8") as handle:
        for q in pending:
            request, prompt_sha = _request(q)
            row = {"id": q["id"], "question_sha256": q["question_sha256"],
                   "model_family": "google", "requested_model": MODEL,
                   "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha}
            try:
                response = _call_model(project, location, token, request)
                label, rationale, response_sha = _parse(response)
                row.update(status="ok", label=label, rationale=rationale,
                           model_version=response.get("modelVersion"),
                           response_sha256=response_sha,
                           usage_metadata=response.get("usageMetadata"))
            except Exception as exc:
                row.update(status="error", label=None, error_type=type(exc).__name__)
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    rows = read_jsonl(checkpoint)
    return {"selected": len(selected), "completed": len(rows),
            "ok": sum(row["status"] == "ok" for row in rows),
            "errors": sum(row["status"] == "error" for row in rows),
            "model": MODEL, "checkpoint_sha256": sha_file(checkpoint)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="global")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.frozen_dir, args.checkpoint, args.project,
                         args.location, args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
