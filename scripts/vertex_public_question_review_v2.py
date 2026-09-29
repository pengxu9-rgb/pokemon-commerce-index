"""Independently classify the new public question cohort with Vertex Gemini.

Only blind question text and missing-photo state are sent. This reviewer does
not retrieve forum replies, current listings, prices, source URLs or Astra labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.public_question_sandbox_v2 import (ACTORS, EVIDENCE, FIELDS,
                                                FORBIDDEN, IDENTITY_STATES,
                                                INTENTS, MISSING_CONTEXT,
                                                NEXT_ACTIONS, OBJECT_TYPES,
                                                SCHEMA, validate_label)
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-routing-gemini-v2"


def _request(question: dict) -> tuple[dict, str]:
    prompt = f"""Classify ONE source-condensed public Pokémon card question for an
internal evidence-routing sandbox. Do not answer the question or browse. You do
not see the original post, replies, images, live listings, or partner policies.
Never infer a current price, actual sale, card condition, authenticity, grade,
seller reliability or cross-language printing relationship from this excerpt.

Return a JSON object with exactly these fields plus rationale (one short sentence):
actor, object_type, primary_intent, identity_state, next_action,
missing_context (array), blocking_evidence (array), optional_evidence (array),
forbidden_claims (array), rationale.

Use these definitions precisely:
- next_action is the SINGLE first step that removes the immediate blocker.
- out_of_scope: the request concerns sealed packs/boxes or non-card products;
  this current index covers physical single cards and collections of singles.
- discuss_preferences: subjective collecting choice with no factual blocker.
- general_explanation: only asks a general concept, without a specific
  purchase/sale decision or request to check current evidence.
- ask_photos: the requested visual judgement cannot proceed because the actual
  front/back or listing photos are absent. References to photos are NOT photos.
- ask_context: essential card identity, destination, platform, goal or other
  context is missing; put ONLY that missing context in missing_context.
- retrieve_evidence: context is sufficient to search authorized catalog,
  official releases, policy, or live quote/sale sources. This is an action
  classification, NOT permission to invent or access an unapproved feed.
- blocking_evidence lists ONLY evidence absent now and indispensable for the
  immediate decision. optional_evidence lists later useful evidence. Do not
  duplicate an item in both arrays. Missing context belongs in missing_context,
  and is nonempty ONLY when next_action=ask_context.
- forbidden_claims lists ONLY question-relevant concrete assertions that
  would be unsupported now; the general no-hallucination rule is not repeated
  in every answer. Do not list unrelated risks. `price` means a current numeric
  valuation, not merely restating a number in the user question.
- identity_state=exact_in_text means enough literal card identity appears in
  the text; it does NOT mean a physical version, grade or authenticity is proven.
- When buyer/seller role is not explicit, choose unknown, not a guess.

actor: {sorted(ACTORS)}
object_type: {sorted(OBJECT_TYPES)}
primary_intent: {sorted(INTENTS)}
identity_state: {sorted(IDENTITY_STATES)}
next_action: {sorted(NEXT_ACTIONS)}
missing_context items: {sorted(MISSING_CONTEXT)}
blocking_evidence / optional_evidence items: {sorted(EVIDENCE)}
forbidden_claims items: {sorted(FORBIDDEN)}

Question language: {question['language']}
Media state: {question['media_state']}
Question: {question['question']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 4000}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def _parse(response: dict) -> tuple[dict, str, str]:
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in ("STOP", None):
        raise ValueError("Gemini returned no complete candidate")
    content = candidates[0].get("content") or {}
    raw = "".join(part.get("text", "") for part in content.get("parts", []))
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != set(FIELDS) | {"rationale"}:
        raise ValueError("Gemini returned unexpected fields")
    rationale = value.pop("rationale")
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
        raise ValueError("frozen v2 questions differ from manifest")
    questions = read_jsonl(frozen_dir / "blind_questions.jsonl")
    selected = questions if limit is None else questions[:limit]
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["id"]: row for row in existing}
    if len(by_id) != len(existing) or set(by_id) - {q["id"] for q in selected}:
        raise ValueError("checkpoint has duplicate or unexpected question IDs")
    for question in selected:
        prior = by_id.get(question["id"])
        if prior and (prior.get("question_sha256") != question["question_sha256"] or
                      prior.get("model_family") != "google"):
            raise ValueError("checkpoint review differs from frozen question")
    pending = [question for question in selected if question["id"] not in by_id]
    token = None
    if pending:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                        text=True, stderr=subprocess.DEVNULL).strip()
        if not token:
            raise ValueError("gcloud returned no access token")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("a", encoding="utf-8") as handle:
        for question in pending:
            request, prompt_sha = _request(question)
            row = {"id": question["id"],
                   "question_sha256": question["question_sha256"],
                   "model_family": "google", "requested_model": MODEL,
                   "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha,
                   "max_output_tokens": request["generationConfig"]["maxOutputTokens"],
                   "request_sha256": hashlib.sha256(json.dumps(
                       request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
            for attempt in (1, 2):
                try:
                    response = _call_model(project, location, token, request)
                    label, rationale, response_sha = _parse(response)
                    row.update(status="ok", label=label, rationale=rationale,
                               attempts=attempt, model_version=response.get("modelVersion"),
                               response_sha256=response_sha,
                               usage_metadata=response.get("usageMetadata"))
                    break
                except Exception as exc:
                    row.update(status="error", label=None, attempts=attempt,
                               error_type=type(exc).__name__)
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
