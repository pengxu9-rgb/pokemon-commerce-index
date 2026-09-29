"""Extract v2 question facts from frozen text with Vertex Gemini.

The model sees the blind question and media flag only. It cannot decide catalog
uniqueness, enable marketplace capabilities, or answer the question.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pokemon_index import question_routing_v2 as routing
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-facts-gemini-v2"
MEDIA_FROM_BLIND = {"text_only": "none",
                    "referenced_not_collected": "referenced_not_collected"}


def _request(question: dict) -> tuple[dict, str]:
    prompt = f"""Extract only facts explicitly present in this Pokémon card
question for an internal evidence planner. Do not answer it, browse, use forum
replies, infer an unseen image, infer a current price, or decide that a catalog
printing is unique. Return one JSON object with exactly facts and rationale.

Facts must have exactly object_type, primary_goal, transaction_context,
identity_tokens, media_state, language_mentions, merchant_ref, destination.
object_type: {sorted(routing.OBJECT_TYPES)}. This says WHAT item is discussed;
a marketplace dispute about one card is still single_card.
primary_goal: {sorted(routing.FOCUSES)}. Choose one main question. Use
marketplace_policy for returns, authentication-service rules, account status,
or platform obligations; merchant_reliability for a seller's performance;
seller_pricing for a seller's payout; price_comparison for buyer price
differences; cross_language_relation for printing or artwork relationships.
transaction_context: {sorted(routing.TRANSACTION_CONTEXTS)}. none means a
general topic or hypothetical; prospective_buy means an actual proposed
purchase; owned means an item the user has; listed_for_sale means already
listed; completed_purchase means received or paid; seller_buyback means
considering or requesting a merchant buyback.
identity_tokens: exactly card_names (array of explicit card names, [] if none),
set_name, collector_number, language, finish, grade. Use null for absent
scalars. Do not infer number or language from a named promo or set. A broad
species name is still text evidence, not a unique printing. Keep two named
targets as two names.
media_state: use {MEDIA_FROM_BLIND[question['media_state']]}. Linked or
mentioned images are absent from this review.
language_mentions: array from {sorted(routing.LANGUAGES)}. Include only
languages explicitly named in the QUESTION, not the language in which it is
written. If it only says overseas or foreign without a specific language,
use unspecified_foreign; never assume English. Do not confuse purchase
location with the card's printed language.
merchant_ref: explicit seller/store identifier, or null. A platform name
is not a merchant. destination: explicit shipping destination, or null.
rationale: one short sentence using decisive question text only.

Question language: {question['language']}
Blind media flag: {question['media_state']}
Question: {question['question']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 3000}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def run(frozen_dir: Path, checkpoint: Path, project: str, location: str) -> dict:
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    if (sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            manifest.get("planner_sha256") != sha_file(Path(routing.__file__)) or
            manifest.get("v2_fact_extractor_sha256") != sha_file(Path(__file__))):
        raise ValueError("frozen questions, planner or extractor differ from manifest")
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
                    if not isinstance(answer, dict) or set(answer) != {"facts", "rationale"}:
                        raise ValueError("unexpected Gemini fields")
                    facts, rationale = answer["facts"], answer["rationale"]
                    routing.validate_facts(facts)
                    if facts["media_state"] != MEDIA_FROM_BLIND[q["media_state"]]:
                        raise ValueError("Gemini media claim differs from blind evidence")
                    if not isinstance(rationale, str) or not rationale.strip():
                        raise ValueError("missing Gemini rationale")
                    row.update(status="ok", facts=facts, rationale=rationale,
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
