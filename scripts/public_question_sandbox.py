"""Freeze source-backed questions and merge independent AI routing reviews.

This is an AI silver-label research sandbox, not a marketplace-price benchmark.
Source material and model outputs are kept outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pokemon.public-question-sandbox.v1"
INTENTS = {"identify_card", "identify_variant", "cross_language_relation",
           "collecting_preference", "price_comparison", "condition_assessment",
           "authenticity", "seller_pricing", "grading_decision", "channel_choice",
           "merchant_reliability", "sealed_product", "other"}
ACTORS = {"buyer", "seller", "collector", "unknown"}
IDENTITY_STATES = {"exact_in_text", "ambiguous", "needs_photo", "not_applicable"}
NEXT_ACTIONS = {"ask_card_details", "ask_photos", "catalog_lookup",
                "request_offer_data", "request_sold_data", "request_current_policy",
                "discuss_preferences", "general_explanation", "out_of_scope"}
EVIDENCE = {"card_metadata", "card_photos", "listing_photos", "authorized_live_offers",
            "verified_sales", "shipping_fees", "grading_policy", "seller_outcomes",
            "official_release_source", "user_preferences"}
FORBIDDEN = {"exact_card", "price", "paid_sale", "counterpart", "same_artwork",
             "condition", "authenticity", "grade_outcome", "seller_reliability"}
HOSTS = {"www.reddit.com", "www.elitefourum.com", "detail.chiebukuro.yahoo.co.jp"}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            for row in rows), encoding="utf-8")


def question_sha(row: dict) -> str:
    payload = {key: row[key] for key in ("id", "question", "source_url", "media_state")}
    return sha_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode())


def validate_source(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("source question set is empty")
    ids, urls = set(), set()
    for row in rows:
        if set(row) != {"id", "question", "source_url", "source_platform", "language",
                        "selection_bucket", "media_state", "observed_date", "text_form"}:
            raise ValueError("source question has missing or unexpected fields")
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in ids:
            raise ValueError("source question IDs must be unique")
        ids.add(row["id"])
        url = urlparse(row["source_url"])
        canonical = (url.netloc.lower(), url.path.rstrip("/").lower())
        if url.scheme != "https" or url.hostname not in HOSTS or canonical in urls:
            raise ValueError("source URLs must be unique approved HTTPS forum posts")
        urls.add(canonical)
        if (not isinstance(row["question"], str) or not 5 <= len(row["question"]) <= 300
                or "http" in row["question"].lower()):
            raise ValueError("question must be a short public excerpt without URLs")
        if row["language"] not in {"en", "ja"} or row["media_state"] not in {
                "text_only", "referenced_not_collected"}:
            raise ValueError("unsupported language or media state")
        if row["text_form"] not in {"verbatim_excerpt", "source_condensed"}:
            raise ValueError("question text provenance is required")
        if (not isinstance(row["selection_bucket"], str)
                or not row["selection_bucket"].startswith(("buyer_", "seller_"))):
            raise ValueError("selection bucket must state buyer or seller coverage")
        if not isinstance(row["observed_date"], str) or len(row["observed_date"]) != 10:
            raise ValueError("observed date must be YYYY-MM-DD")


def freeze(source: Path, out_dir: Path, *, seed: int = 20260929,
           holdout_ratio: float = 0.25, schema: str = SCHEMA) -> dict:
    if out_dir.exists() or out_dir.resolve().is_relative_to(ROOT):
        raise ValueError("frozen question output must be a new directory outside the repository")
    if not 0 < holdout_ratio < 1:
        raise ValueError("holdout ratio must be between zero and one")
    rows = read_jsonl(source)
    validate_source(rows)
    # Split by source post, and stratify the small pilot by actor bucket and language.
    groups = defaultdict(list)
    for row in rows:
        actor = row["selection_bucket"].split("_", 1)[0]
        groups[(actor, row["language"])].append(row)
    rng = random.Random(seed)
    holdout = set()
    for group_rows in groups.values():
        ids = sorted(row["id"] for row in group_rows)
        rng.shuffle(ids)
        take = min(len(ids) - 1, max(1, round(len(ids) * holdout_ratio))) if len(ids) > 1 else 0
        holdout.update(ids[:take])
    blind = [{"id": row["id"], "question": row["question"],
              "language": row["language"], "media_state": row["media_state"],
              "question_sha256": question_sha(row)} for row in rows]
    source_index = [{"id": row["id"], "source_url": row["source_url"],
                     "source_platform": row["source_platform"],
                     "selection_bucket": row["selection_bucket"],
                     "text_form": row["text_form"],
                     "observed_date": row["observed_date"],
                     "question_sha256": question_sha(row),
                     "split": "holdout" if row["id"] in holdout else "development"}
                    for row in rows]
    out_dir.mkdir(parents=True)
    write_jsonl(out_dir / "blind_questions.jsonl", blind)
    write_jsonl(out_dir / "source_index.jsonl", source_index)
    manifest = {"schema": schema, "source_sha256": sha_file(source),
                "blind_sha256": sha_file(out_dir / "blind_questions.jsonl"),
                "source_index_sha256": sha_file(out_dir / "source_index.jsonl"),
                "seed": seed, "holdout_ratio": holdout_ratio,
                "questions": len(rows), "holdout": len(holdout),
                "by_platform": dict(sorted(Counter(row["source_platform"] for row in rows).items())),
                "by_language": dict(sorted(Counter(row["language"] for row in rows).items())),
                "by_media": dict(sorted(Counter(row["media_state"] for row in rows).items())),
                "text_forms": dict(sorted(Counter(row["text_form"] for row in rows).items())),
                "scope": "search-discovered public question situations; not representative; source-condensed text is not raw-language accuracy"}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
                                                     sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_label(label: dict) -> dict:
    if not isinstance(label, dict) or set(label) != {
            "actor", "primary_intent", "identity_state", "next_action",
            "required_evidence", "forbidden_claims"}:
        raise ValueError("review label has missing or unexpected fields")
    for key, options in (("actor", ACTORS), ("primary_intent", INTENTS),
                         ("identity_state", IDENTITY_STATES), ("next_action", NEXT_ACTIONS)):
        if label[key] not in options:
            raise ValueError(f"unsupported {key}")
    for key, options in (("required_evidence", EVIDENCE), ("forbidden_claims", FORBIDDEN)):
        values = label[key]
        if not isinstance(values, list) or len(values) != len(set(values)) or set(values) - options:
            raise ValueError(f"unsupported {key}")
    return label


def merge(frozen_dir: Path, astra_path: Path, gemini_path: Path, output: Path) -> dict:
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError("silver report must use a new path outside the repository")
    manifest_path = frozen_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            sha_file(frozen_dir / "source_index.jsonl") != manifest["source_index_sha256"]):
        raise ValueError("frozen question data changed")
    questions = {row["id"]: row for row in read_jsonl(frozen_dir / "blind_questions.jsonl")}
    indexes = {row["id"]: row for row in read_jsonl(frozen_dir / "source_index.jsonl")}
    reviews = {}
    for family, path in (("astra", astra_path), ("google", gemini_path)):
        rows = read_jsonl(path)
        if len(rows) != len(questions) or len({row.get("id") for row in rows}) != len(rows):
            raise ValueError(f"{family} reviews must cover every frozen question once")
        for row in rows:
            q = questions.get(row.get("id"))
            if not q or row.get("question_sha256") != q["question_sha256"]:
                raise ValueError(f"{family} review does not match frozen question")
            if row.get("model_family") != family:
                raise ValueError("review model family mismatch")
            if row.get("status") == "ok":
                validate_label(row.get("label"))
            elif row.get("status") != "error" or row.get("label") is not None:
                raise ValueError("review status must be ok with label or error without label")
            reviews[(family, row["id"])] = row
    results = []
    for item_id, q in questions.items():
        a, g = reviews[("astra", item_id)], reviews[("google", item_id)]
        if a["status"] != "ok" or g["status"] != "ok":
            status = "review_failed"
            disagreements = []
        else:
            disagreements = [key for key in a["label"] if
                             (set(a["label"][key]) != set(g["label"][key])
                              if key in {"required_evidence", "forbidden_claims"}
                              else a["label"][key] != g["label"][key])]
            status = "silver_agreed" if not disagreements else "disputed"
        results.append({"id": item_id, "split": indexes[item_id]["split"],
                        "selection_bucket": indexes[item_id]["selection_bucket"],
                        "language": q["language"], "media_state": q["media_state"],
                        "status": status, "disagreements": disagreements,
                        "label": a["label"] if status == "silver_agreed" else None})
    counts = Counter(row["status"] for row in results)
    jointly_reviewed = [row for row in results if row["status"] != "review_failed"]
    fields = ("actor", "primary_intent", "identity_state", "next_action",
              "required_evidence", "forbidden_claims")
    field_agreement = {key: sum(key not in row["disagreements"]
                                for row in jointly_reviewed) for key in fields}
    routing_fields = {"primary_intent", "identity_state", "next_action"}
    report = {"schema": "pokemon.public-question-silver.v1",
              "manifest_sha256": sha_file(manifest_path),
              "astra_sha256": sha_file(astra_path), "gemini_sha256": sha_file(gemini_path),
              "questions": len(results), "status_counts": dict(sorted(counts.items())),
              "jointly_reviewed": len(jointly_reviewed),
              "field_agreement": field_agreement,
              "core_routing_agreement": sum(
                  not routing_fields.intersection(row["disagreements"])
                  for row in jointly_reviewed),
              "disagreement_fields": dict(sorted(Counter(
                  key for row in results for key in row["disagreements"]).items())),
              "by_language": {lang: dict(Counter(row["status"] for row in results
                                             if row["language"] == lang))
                              for lang in sorted({row["language"] for row in results})},
              "results": results,
              "interpretation": "Independent AI routing agreement, not human accuracy or card/price truth"}
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freezing = sub.add_parser("freeze")
    freezing.add_argument("--source", type=Path, required=True)
    freezing.add_argument("--out-dir", type=Path, required=True)
    freezing.add_argument("--seed", type=int, default=20260929)
    merging = sub.add_parser("merge")
    merging.add_argument("--frozen-dir", type=Path, required=True)
    merging.add_argument("--astra", type=Path, required=True)
    merging.add_argument("--gemini", type=Path, required=True)
    merging.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(args.source, args.out_dir, seed=args.seed)
        print(json.dumps({key: result[key] for key in ("questions", "holdout", "by_platform",
                                                        "by_language", "by_media")}, ensure_ascii=False))
    else:
        result = merge(args.frozen_dir, args.astra, args.gemini, args.output)
        print(json.dumps({"questions": result["questions"],
                          "status_counts": result["status_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
