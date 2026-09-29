"""Freeze and merge a new source-backed question cohort under the v2 rubric.

The v1 cohort remains immutable. V2 separates first action, missing context,
blocking evidence, optional evidence and question-relevant unsupported claims.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from scripts.public_question_sandbox import (ACTORS, IDENTITY_STATES, ROOT,
                                             freeze, read_jsonl, sha_file,
                                             validate_source)

SCHEMA = "pokemon.public-question-sandbox.v2"
INTENTS = {"identify_card", "identify_variant", "cross_language_relation",
           "collecting_preference", "price_comparison", "condition_assessment",
           "authenticity", "seller_pricing", "grading_decision", "channel_choice",
           "merchant_reliability", "landed_cost", "collection_triage", "other"}
OBJECT_TYPES = {"card_single", "card_lot", "mixed_collection", "sealed_product",
                "marketplace_service", "unknown"}
NEXT_ACTIONS = {"out_of_scope", "ask_photos", "ask_context", "retrieve_evidence",
                "discuss_preferences", "general_explanation"}
MISSING_CONTEXT = {"card_identity", "sale_goal", "destination", "platform",
                   "quantity", "condition", "cost_basis", "budget", "seller_identity"}
EVIDENCE = {"card_metadata", "card_photos", "listing_photos", "authorized_live_offers",
            "verified_sales", "shipping_fees", "grading_policy", "seller_outcomes",
            "official_release_source", "user_preferences", "marketplace_policy",
            "selling_fees", "cost_basis", "product_metadata"}
FORBIDDEN = {"exact_card", "exact_variant", "price", "paid_sale", "counterpart",
             "same_artwork", "condition", "authenticity", "grade_outcome",
             "seller_reliability", "landed_total", "guaranteed_profit"}
FIELDS = ("actor", "object_type", "primary_intent", "identity_state",
          "next_action", "missing_context", "blocking_evidence",
          "optional_evidence", "forbidden_claims")
SET_FIELDS = {"missing_context", "blocking_evidence", "optional_evidence",
              "forbidden_claims"}


def _url_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.netloc.lower(), parsed.path.rstrip("/").lower()


def freeze_new(source: Path, prior_source: Path, out_dir: Path,
               *, seed: int = 20260929) -> dict:
    current, prior = read_jsonl(source), read_jsonl(prior_source)
    validate_source(current)
    validate_source(prior)
    prior_urls = {_url_key(row["source_url"]) for row in prior}
    overlap = prior_urls & {_url_key(row["source_url"]) for row in current}
    if overlap:
        raise ValueError(f"v2 source reuses {len(overlap)} v1 posts")
    manifest = freeze(source, out_dir, seed=seed, schema=SCHEMA)
    manifest["prior_source_sha256"] = sha_file(prior_source)
    manifest["new_source_posts_vs_prior"] = len(current)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return manifest


def validate_label(label: dict) -> dict:
    if not isinstance(label, dict) or set(label) != set(FIELDS):
        raise ValueError("v2 label has missing or unexpected fields")
    for key, options in (("actor", ACTORS), ("object_type", OBJECT_TYPES),
                         ("primary_intent", INTENTS), ("identity_state", IDENTITY_STATES),
                         ("next_action", NEXT_ACTIONS)):
        if label[key] not in options:
            raise ValueError(f"unsupported {key}")
    for key, options in (("missing_context", MISSING_CONTEXT),
                         ("blocking_evidence", EVIDENCE),
                         ("optional_evidence", EVIDENCE),
                         ("forbidden_claims", FORBIDDEN)):
        values = label[key]
        if (not isinstance(values, list) or any(not isinstance(item, str) for item in values)
                or len(values) != len(set(values)) or set(values) - options):
            raise ValueError(f"unsupported {key}")
    if label["next_action"] == "ask_context" and not label["missing_context"]:
        raise ValueError("ask_context requires at least one missing context item")
    if label["next_action"] != "ask_context" and label["missing_context"]:
        raise ValueError("missing context is only reported for ask_context")
    if label["next_action"] == "ask_photos" and not {
            "card_photos", "listing_photos"} & set(label["blocking_evidence"]):
        raise ValueError("ask_photos requires missing photo evidence")
    if set(label["blocking_evidence"]) & set(label["optional_evidence"]):
        raise ValueError("evidence cannot be both blocking and optional")
    return label


def merge(frozen_dir: Path, astra_path: Path, gemini_path: Path, output: Path) -> dict:
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError("v2 report must use a new path outside the repository")
    manifest_path = frozen_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            sha_file(frozen_dir / "source_index.jsonl") != manifest["source_index_sha256"]):
        raise ValueError("v2 frozen question data changed")
    questions = {row["id"]: row for row in read_jsonl(frozen_dir / "blind_questions.jsonl")}
    sources = {row["id"]: row for row in read_jsonl(frozen_dir / "source_index.jsonl")}
    if questions.keys() != sources.keys():
        raise ValueError("v2 source index does not match blind questions")
    reviews: dict[tuple[str, str], dict] = {}
    for family, path in (("astra", astra_path), ("google", gemini_path)):
        rows = read_jsonl(path)
        if len(rows) != len(questions) or len({row.get("id") for row in rows}) != len(rows):
            raise ValueError(f"{family} must review each question exactly once")
        for row in rows:
            question = questions.get(row.get("id"))
            if (not question or row.get("question_sha256") != question["question_sha256"]
                    or row.get("model_family") != family):
                raise ValueError(f"{family} review does not match frozen question")
            if row.get("status") == "ok":
                validate_label(row.get("label"))
            elif row.get("status") != "error" or row.get("label") is not None:
                raise ValueError("review must be ok with a label or error without one")
            reviews[(family, row["id"])] = row
    results = []
    for item_id, question in questions.items():
        left, right = reviews[("astra", item_id)], reviews[("google", item_id)]
        if left["status"] != "ok" or right["status"] != "ok":
            disagreements, status = [], "review_failed"
        else:
            disagreements = [key for key in FIELDS if
                             (set(left["label"][key]) != set(right["label"][key])
                              if key in SET_FIELDS else
                              left["label"][key] != right["label"][key])]
            status = "silver_agreed" if not disagreements else "disputed"
        results.append({"id": item_id, "split": sources[item_id]["split"],
                        "selection_bucket": sources[item_id]["selection_bucket"],
                        "language": question["language"],
                        "media_state": question["media_state"],
                        "status": status, "disagreements": disagreements,
                        "label": left["label"] if status == "silver_agreed" else None})
    jointly_reviewed = [row for row in results if row["status"] != "review_failed"]
    routing_fields = {"primary_intent", "identity_state", "next_action"}
    report = {"schema": "pokemon.public-question-silver.v2",
              "manifest_sha256": sha_file(manifest_path),
              "astra_sha256": sha_file(astra_path),
              "gemini_sha256": sha_file(gemini_path),
              "questions": len(results), "jointly_reviewed": len(jointly_reviewed),
              "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
              "field_agreement": {key: sum(key not in row["disagreements"]
                                           for row in jointly_reviewed) for key in FIELDS},
              "core_routing_agreement": sum(
                  not routing_fields.intersection(row["disagreements"])
                  for row in jointly_reviewed),
              "disagreement_fields": dict(sorted(Counter(
                  key for row in results for key in row["disagreements"]).items())),
              "results": results,
              "interpretation": "Independent AI routing agreement on new public posts; not human accuracy, market truth, or visual accuracy"}
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                 indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--source", type=Path, required=True)
    freezing.add_argument("--prior-source", type=Path, required=True)
    freezing.add_argument("--out-dir", type=Path, required=True)
    freezing.add_argument("--seed", type=int, default=20260929)
    merging = commands.add_parser("merge")
    merging.add_argument("--frozen-dir", type=Path, required=True)
    merging.add_argument("--astra", type=Path, required=True)
    merging.add_argument("--gemini", type=Path, required=True)
    merging.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_new(args.source, args.prior_source, args.out_dir, seed=args.seed)
        print(json.dumps({key: result[key] for key in (
            "questions", "holdout", "by_platform", "by_language", "by_media")},
            ensure_ascii=False))
    else:
        result = merge(args.frozen_dir, args.astra, args.gemini, args.output)
        print(json.dumps({key: result[key] for key in (
            "questions", "jointly_reviewed", "status_counts", "field_agreement",
            "core_routing_agreement")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
