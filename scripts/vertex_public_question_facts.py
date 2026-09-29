"""Extract structured question facts from a frozen public-question cohort.

The model sees the blind text and media flag, not original posts, replies,
marketplace data or another reviewer's labels. Facts are proposals; the
deterministic question planner applies the actual capability gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pokemon_index.question_routing import FOCUSES, PRODUCT_SCOPES, validate_facts
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-facts-gemini-v1"


def _request(question: dict) -> tuple[dict, str]:
    prompt = f"""Extract the question facts for an internal Pokémon commerce
evidence planner. Return JSON with exactly product_scope, focus, named_card,
exact_printing, specific_copy, photos_available, language_scope, rationale.
Do not answer the question. Do not browse. Do not use forum replies or infer
what an absent card or listing photo would show. Do not assert a current price.

product_scope: {sorted(PRODUCT_SCOPES)}.
Choose marketplace_process when the MAIN request is about transaction,
buyer protection, listing disclosure or platform obligations, even if a
Pokémon card is involved. sealed_tcg and non_tcg_card are outside the current
physical Pokémon TCG singles/collections index.
focus: {sorted(FOCUSES)}. Choose the single main goal. `marketplace_policy`
concerns platform protections or obligations; `merchant_reliability` concerns
seller/merchant trust or performance; `channel_choice` concerns where to sell
or buy; `seller_pricing` concerns a seller's price/value decision.
named_card: true only if a particular card is named in the question.
exact_printing: true only if the text uniquely fixes its language, release,
number and relevant printing; it requires named_card=true. A grade is not a
printing identity. A broad set or species name is not exact.
specific_copy: true if the user asks about an actual owned or listed physical
copy or collection, rather than a general category or hypothetical.
photos_available: true only if the actual images are included in this review.
A post mentioning or linking photos does NOT make them available here.
language_scope: ja_en if the requested comparison is within Japanese/English
physical cards, other if it explicitly includes another language, and
unspecified otherwise.
rationale: one concise sentence describing the decisive text evidence.

Question language: {question['language']}
Media state: {question['media_state']}
Question: {question['question']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 2000}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def run(frozen_dir: Path, checkpoint: Path, project: str, location: str) -> dict:
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    if sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"]:
        raise ValueError("frozen blind questions changed")
    questions = read_jsonl(frozen_dir / "blind_questions.jsonl")
    ids = {row["id"] for row in questions}
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["id"]: row for row in existing}
    if len(by_id) != len(existing) or set(by_id) - ids:
        raise ValueError("invalid checkpoint IDs")
    for q in questions:
        if q["id"] in by_id and (by_id[q["id"]].get("question_sha256") != q["question_sha256"]
                                 or by_id[q["id"]].get("model_family") != "google"):
            raise ValueError("checkpoint question or model changed")
    pending = [q for q in questions if q["id"] not in by_id]
    token = (subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                     text=True, stderr=subprocess.DEVNULL).strip()
             if pending else None)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("a", encoding="utf-8") as handle:
        for q in pending:
            request, prompt_sha = _request(q)
            row = {"id": q["id"], "question_sha256": q["question_sha256"],
                   "model_family": "google", "requested_model": MODEL,
                   "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha}
            for attempt in (1, 2):
                try:
                    response = _call_model(project, location, token, request)
                    candidates = response.get("candidates") or []
                    if not candidates or candidates[0].get("finishReason") != "STOP":
                        raise ValueError("incomplete Gemini candidate")
                    raw = "".join(part.get("text", "") for part in
                                  candidates[0].get("content", {}).get("parts", []))
                    answer = json.loads(raw)
                    if not isinstance(answer, dict) or set(answer) != {
                            "product_scope", "focus", "named_card", "exact_printing",
                            "specific_copy", "photos_available", "language_scope",
                            "rationale"}:
                        raise ValueError("unexpected Gemini fact fields")
                    rationale = answer.pop("rationale")
                    if not isinstance(rationale, str) or not rationale.strip():
                        raise ValueError("missing Gemini rationale")
                    validate_facts(answer)
                    row.update(status="ok", facts=answer, rationale=rationale,
                               attempts=attempt, model_version=response.get("modelVersion"),
                               response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                               usage_metadata=response.get("usageMetadata"))
                    break
                except Exception as exc:
                    row.update(status="error", facts=None, attempts=attempt,
                               error_type=type(exc).__name__)
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    rows = read_jsonl(checkpoint)
    return {"questions": len(questions), "reviewed": len(rows),
            "ok": sum(row["status"] == "ok" for row in rows),
            "errors": sum(row["status"] == "error" for row in rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="global")
    args = parser.parse_args()
    print(json.dumps(run(args.frozen_dir, args.checkpoint,
                         args.project, args.location), ensure_ascii=False))


if __name__ == "__main__":
    main()
