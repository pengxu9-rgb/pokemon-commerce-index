"""Extract v5 question facts from a future frozen cohort with Vertex Gemini.

This version records the validation stage for failures without persisting raw
model responses. It must be locked in a new cohort manifest before collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pokemon_index import question_routing_v5 as routing
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-facts-gemini-v5.0"
MEDIA_FROM_BLIND = {"text_only": "none",
                    "referenced_not_collected": "referenced_not_collected"}
EVIDENCE_KEYS = {"goal", "platform_refs", "merchant_ref", "rarity", "finish",
                 "time_window", "purchase_constraints", "sale_constraints"}


def _request(question: dict) -> tuple[dict, str]:
    prompt = f"""Extract only facts explicitly stated in this Pokémon-card
question. Do not answer it, browse, use replies, infer an unseen image,
invent a merchant, infer a unique printing or claim a current market price.
Return one JSON object with exactly facts, evidence_spans and rationale.

facts has exactly: object_type, primary_goal, transaction_context,
seller_channel, identity_tokens, media_state, language_mentions,
platform_refs, merchant_ref, destination, time_window, purchase_constraints,
sale_constraints.
object_type: {sorted(routing.OBJECT_TYPES)}. This is the item discussed, not
the question's task. A marketplace-policy dispute about one card is still
single_card. A non-TCG Pokémon collectible card is non_tcg_card.
card_market_segment is a question about a class of TCG cards, not a named
collection or individual printing (for example Japanese versus English set
cards generally).
primary_goal: {sorted(routing.FOCUSES)}. Choose one main request.
seller_pricing is about what the user can receive for selling their card,
including a store buyback quote. price_comparison is for a buyer comparing
purchase prices. marketplace_policy asks about authentication, return or
platform obligations.
price_trend asks whether or why a price moved over time, or about a future
price direction alone. purchase_timing asks whether the BUYER should buy now
or wait. seller_timing asks whether the OWNER should sell now or hold. A static
Japanese-versus-English value gap without change over time is
relative_value_explanation. Asking whether one offered price is high is
price_comparison, even if a future-price question is secondary. Asking which
card to choose for a collection is collecting_preference, even when the user
mentions a five-year horizon. Do not force these into price_trend. An old
forum quote is question context, not a current verified quote.
transaction_context: {sorted(routing.TRANSACTION_CONTEXTS)}.
sold_pending_fulfillment means the seller's listing has sold but the shipment,
authentication or buyer acceptance is pending. completed_sale means the
seller's sale has finished. completed_purchase is the buyer's purchase.
owned means the user possesses it without a stated active sale. A listing
mentioned for an authenticity opinion is observed_listing unless the user
explicitly proposes buying it. listed_for_sale means the USER's own listing,
not a third-party listing they are inspecting.
seller_channel: {sorted(routing.SELLER_CHANNELS)}. Use comparing_channels
when the seller explicitly compares marketplace sale and store buyback;
store_buyback for a store quote or intended store sale; marketplace_listing
for selling through a platform; none for buyers or unrelated topics.
identity_tokens has exactly card_names (explicit names, [] if none), set_name,
collector_number, language, rarity, finish, grade. Use null for absent
scalars. identity_tokens.language is null or one code from
{sorted(routing.LANGUAGES - {'unspecified_foreign'})}; convert a named Japanese
card language to ja, English to en, and so on. MUR, SAR, UR and similar
release rarity codes go in rarity, not
finish. Foil, reverse holo and texture go in finish only if explicitly
described as a physical finish. A card name is not a unique printing.
media_state must be {MEDIA_FROM_BLIND[question['media_state']]}; mentioned
or linked images are absent from this review.
language_mentions: array from {sorted(routing.LANGUAGES)}. Only languages
explicitly named in the QUESTION; the question's writing language alone is
not evidence. An unspecified overseas language is unspecified_foreign.
platform_refs: array of explicitly named platforms or proxy services, using
their exact surface text. A platform is never merchant_ref. merchant_ref is
one explicitly named seller or shop, or null. destination is an explicitly
named shipping destination, or null.
time_window is an explicitly stated past analysis interval or concrete future
decision horizon, copied as a short phrase, or null. Generic words such as
"future", "今後", "eventually" or "long term" alone are not a time window.
Do not invent one from the post date or old prices. purchase_constraints is an
explicitly stated BUYER budget, target condition, grade or risk preference
copied as a short phrase, or null. sale_constraints is an explicitly stated
SELLER cash need, target net proceeds, or willingness to wait, copied as a
short phrase, or null. A quoted old price alone is not a buyer or seller
constraint. Do not turn a time horizon into sale_constraints.

evidence_spans has exactly goal, platform_refs, merchant_ref, rarity, finish,
time_window, purchase_constraints, sale_constraints.
goal is a short exact substring of the question supporting primary_goal.
platform_refs is an array of short exact substrings from the question, in
the same order as facts.platform_refs. Other non-null fact values must have
short exact supporting substrings from the question; use null spans for
absent values.
Do not use surrounding forum context as evidence.
rationale is one brief sentence about the primary goal.

Question language: {question['language']}
Blind media flag: {question['media_state']}
Question: {question['question']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 8192}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def validate_answer(answer: dict, question: dict) -> tuple[dict, dict, str]:
    if not isinstance(answer, dict) or set(answer) != {"facts", "evidence_spans", "rationale"}:
        raise ValueError("unexpected answer fields")
    facts = routing.validate_facts(answer["facts"])
    if facts["media_state"] != MEDIA_FROM_BLIND[question["media_state"]]:
        raise ValueError("media differs from blind evidence")
    spans = answer["evidence_spans"]
    if not isinstance(spans, dict) or set(spans) != EVIDENCE_KEYS:
        raise ValueError("unexpected evidence span fields")
    goal_span = spans["goal"]
    if (not isinstance(goal_span, str) or not goal_span.strip() or
            goal_span not in question["question"] or len(goal_span) > 160):
        raise ValueError("goal evidence is absent from the question")
    platform_spans = spans["platform_refs"]
    if (not isinstance(platform_spans, list) or
            len(platform_spans) != len(facts["platform_refs"]) or
            any(not isinstance(span, str) or not span.strip() or
                span not in question["question"] or
                span.casefold() != platform.casefold()
                for span, platform in zip(platform_spans, facts["platform_refs"]))):
        raise ValueError("platform evidence is absent from the question")
    for field in ("merchant_ref", "rarity", "finish", "time_window",
                  "purchase_constraints", "sale_constraints"):
        fact_value = (facts["identity_tokens"][field] if field in {"rarity", "finish"}
                      else facts[field])
        span = spans[field]
        if ((fact_value is None and span is not None) or
                (fact_value is not None and
                 (not isinstance(span, str) or not span.strip() or
                  span not in question["question"] or
                  (fact_value.casefold() != span.strip().casefold() if field == "rarity"
                   else fact_value.casefold() not in span.casefold())))):
            raise ValueError(f"{field} evidence is absent from the question")
    rationale = answer["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("missing rationale")
    return facts, spans, rationale


def _extract_one(question: dict, project: str, location: str, token: str) -> dict:
    request, prompt_sha = _request(question)
    row = {"id": question["id"], "question_sha256": question["question_sha256"],
           "model_family": "google", "requested_model": MODEL,
           "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha}
    failures = []
    for attempt in (1, 2):
        stage, response, raw = "transport", None, None
        try:
            response = _call_model(project, location, token, request)
            stage = "candidate"
            candidates = response.get("candidates") or []
            if not candidates or candidates[0].get("finishReason") != "STOP":
                raise ValueError("incomplete model candidate")
            raw = "".join(part.get("text", "") for part in
                          candidates[0].get("content", {}).get("parts", []))
            stage = "json"
            answer = json.loads(raw)
            stage = "facts_and_evidence"
            facts, spans, rationale = validate_answer(answer, question)
            row.update(status="ok", facts=facts, evidence_spans=spans,
                       rationale=rationale, attempts=attempt,
                       model_version=response.get("modelVersion"),
                       response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                       usage_metadata=response.get("usageMetadata"),
                       attempt_errors=failures)
            return row
        except Exception as exc:
            failures.append({"attempt": attempt, "stage": stage,
                             "error_type": type(exc).__name__,
                             "validation_code": (str(exc) if stage == "facts_and_evidence"
                                                 and isinstance(exc, ValueError) else None),
                             "finish_reason": ((response.get("candidates") or [{}])[0]
                                               .get("finishReason") if response else None),
                             "model_version": response.get("modelVersion") if response else None,
                             "response_sha256": (hashlib.sha256(raw.encode()).hexdigest()
                                                 if raw is not None else None)})
    row.update(status="error", facts=None, evidence_spans=None,
               attempts=2, attempt_errors=failures)
    return row


def run(frozen_dir: Path, checkpoint: Path, project: str, location: str) -> dict:
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    if (sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            manifest.get("v5_planner_sha256") != sha_file(Path(routing.__file__)) or
            manifest.get("v5_fact_extractor_sha256") != sha_file(Path(__file__))):
        raise ValueError("frozen questions, v5 planner or extractor differ from manifest")
    questions = read_jsonl(frozen_dir / "blind_questions.jsonl")
    ids = {question["id"] for question in questions}
    if len(ids) != len(questions):
        raise ValueError("duplicate frozen question ID")
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["id"]: row for row in existing}
    if len(by_id) != len(existing) or set(by_id) - ids:
        raise ValueError("invalid checkpoint IDs")
    for question in questions:
        row = by_id.get(question["id"])
        if row is not None and (row.get("question_sha256") != question["question_sha256"] or
                                row.get("model_family") != "google" or
                                row.get("prompt_version") != PROMPT_VERSION or
                                row.get("requested_model") != MODEL or
                                row.get("prompt_sha256") != _request(question)[1]):
            raise ValueError("checkpoint question, prompt or model changed")
    pending = [question for question in questions if question["id"] not in by_id]
    token = (subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                     text=True, stderr=subprocess.DEVNULL).strip()
             if pending else "")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("a", encoding="utf-8") as handle:
        for question in pending:
            row = _extract_one(question, project, location, token)
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
