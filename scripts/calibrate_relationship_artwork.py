"""Blind second visual pass and agreement audit for source-bound card pairs.

The second prompt receives only the two images. Agreement is model stability,
not accuracy against independent ground truth. No graph state is promoted.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.relationship_pilot import read_jsonl, write_jsonl
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "image-only-artwork-calibration-v1"
TAXONOMY_PROMPT_VERSION = "image-only-artwork-lineage-v1"
DECISIONS = {"same", "different", "uncertain", "model_error",
             "insufficient_images", "source_image_changed"}


class SourceImageChanged(ValueError):
    """An audited URL now serves different bytes, so blind comparison is invalid."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _url_allowed(url: str, side: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        return False
    if parsed.hostname == "assets.tcgdex.net":
        return parsed.path.endswith("/high.webp") and parsed.path.startswith(f"/{side}/")
    return (side == "ja" and parsed.hostname == "www.pokemon-card.com"
            and parsed.path.startswith("/assets/images/card_images/large/")
            and parsed.path.endswith(".jpg"))


def _sample_image(evidence: dict[str, Any], side: str) -> dict[str, str]:
    image = evidence.get(f"{side}_image", {})
    url, sha = image.get("image_url", ""), image.get("image_sha256", "")
    if (image.get("status") != "included" or not _url_allowed(url, side)
            or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise ValueError("calibration sample needs both exact, hash-bound card images")
    return {"url": url, "sha256": sha}


def prepare(queue: list[dict], first: list[dict], audit: dict,
            positive_n: int = 150) -> tuple[list[dict], dict]:
    candidates = {row["candidate_id"]: row for row in queue}
    verdicts = {row["candidate_id"]: row for row in first}
    evidence = {row["candidate_id"]: row for row in audit["rows"]}
    if (len(candidates) != len(queue) or len(verdicts) != len(first)
            or len(evidence) != len(audit["rows"])
            or set(candidates) != set(verdicts) or set(candidates) != set(evidence)
            or audit.get("model") != MODEL):
        raise ValueError("calibration source has duplicate or missing candidate IDs")
    strata: dict[str, list[dict]] = defaultdict(list)
    for cid, candidate in candidates.items():
        verdict, source = verdicts[cid], evidence[cid]
        if (verdict["source_snapshot_sha256"] != candidate["source_snapshot_sha256"]
                or source["source_snapshot_sha256"] != candidate["source_snapshot_sha256"]):
            raise ValueError("calibration source snapshot mismatch")
        if verdict["artwork_decision"] in {"same", "different", "uncertain", "model_error"}:
            if verdict["ja_image_status"] != "included" or verdict["en_image_status"] != "included":
                raise ValueError("first visual decision lacks two images")
            strata[verdict["artwork_decision"]].append(candidate)
    positives = strata["same"]
    if not 1 <= positive_n <= len(positives):
        raise ValueError("positive sample size exceeds available same-artwork findings")
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for row in positives:
        by_reason[row["selection_reason"]].append(row)
    # Give every retrieval stratum a minimum, then allocate the rest by size.
    minimum = min(8, positive_n // len(by_reason))
    quotas = {key: min(minimum, len(rows)) for key, rows in by_reason.items()}
    remaining = positive_n - sum(quotas.values())
    while remaining:
        eligible = [key for key in by_reason if quotas[key] < len(by_reason[key])]
        key = max(eligible, key=lambda name: ((len(by_reason[name]) - quotas[name]) /
                                               len(by_reason[name]),
                                               len(by_reason[name]), name))
        quotas[key] += 1
        remaining -= 1
    selected = []
    for reason, rows in sorted(by_reason.items()):
        selected.extend(sorted(rows, key=lambda row: hashlib.sha256(
            (PROMPT_VERSION + "\0" + row["candidate_id"]).encode()).hexdigest())[:quotas[reason]])
    selected.extend(strata["different"])
    selected.extend(strata["uncertain"])
    selected.extend(strata["model_error"])
    selected.sort(key=lambda row: row["candidate_id"])
    sample = []
    for candidate in selected:
        cid = candidate["candidate_id"]
        source = evidence[cid]
        sample.append({"candidate_id": cid,
                       "source_snapshot_sha256": candidate["source_snapshot_sha256"],
                       "first_decision": verdicts[cid]["artwork_decision"],
                       "selection_reason": candidate["selection_reason"],
                       "ja_card_id": candidate["anchor"]["card_id"],
                       "en_card_id": candidate["candidate"]["card_id"],
                       "ja_image": _sample_image(source, "ja"),
                       "en_image": _sample_image(source, "en")})
    report = {"scope": "deterministic, source-bound blind second-pass sample; no accuracy or graph promotion",
              "first_batch_candidate_rows": len(queue), "sample_rows": len(sample),
              "positive_quota_by_retrieval_stratum": dict(sorted(quotas.items())),
              "first_decisions": dict(sorted(Counter(row["first_decision"] for row in sample).items())),
              "sample_sha256": _digest(sample), "first_audit_sha256": _digest(audit),
              "prompt_version": PROMPT_VERSION}
    return sample, report


def prepare_taxonomy(queue: list[dict], first: list[dict], audit: dict
                     ) -> tuple[list[dict], dict]:
    all_complete, _ = prepare(queue, first, audit, positive_n=sum(
        row["artwork_decision"] == "same" for row in first))
    flagged = {row["candidate_id"] for row in first
               if row["artwork_decision"] in {"same", "different"}
               and re.search(r"rainbow|recolor|palette|gradient", row["rationale"], re.I)}
    sample = [row for row in all_complete if row["candidate_id"] in flagged]
    if len(sample) != len(flagged):
        raise ValueError("taxonomy sample lost a source-bound image pair")
    report = {"scope": "rationale-keyword challenge set; not random or an accuracy estimate",
              "selection_terms": ["rainbow", "recolor", "palette", "gradient"],
              "sample_rows": len(sample),
              "first_decisions": dict(sorted(Counter(row["first_decision"]
                                                     for row in sample).items())),
              "sample_sha256": _digest(sample),
              "prompt_version": TAXONOMY_PROMPT_VERSION,
              "no_graph_promotion": True}
    return sample, report


def _fetch_image(row: dict, side: str) -> tuple[bytes, str]:
    image = row[f"{side}_image"]
    if not _url_allowed(image["url"], side):
        raise ValueError("image URL is outside approved audit source hosts")
    request = urllib.request.Request(image["url"], headers={
        "User-Agent": "pokemon-commerce-internal-calibration/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(7_000_001)
    if len(data) > 7_000_000:
        raise ValueError("image exceeds calibration size limit")
    mime = ("image/jpeg" if data.startswith(b"\xff\xd8\xff") else
            "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
    if mime is None:
        raise ValueError("source image format is unsupported")
    if hashlib.sha256(data).hexdigest() != image["sha256"]:
        raise SourceImageChanged(f"{side} source image bytes changed")
    return data, mime


def _request(images: list[tuple[bytes, str]]) -> dict:
    # Names, set codes, first-pass labels and prior rationale are deliberately absent.
    prompt = """Independently compare only the illustrated artwork area in these
two Pokémon card images. Ignore card text, language, card frames and set
symbols. Look for matching distinctive scene details, not just the same
character or a similar composition. If artwork is cropped or ambiguous,
choose uncertain. Return JSON with decision (same/different/uncertain) and a
short visual_basis describing visible details. Do not infer foil, edition,
physical printing, condition, rarity or value."""
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, (data, mime) in zip(("Image A", "Image B"), images):
        parts.extend(({"text": label}, {"inlineData": {
            "mimeType": mime, "data": base64.b64encode(data).decode()}}))
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 1200}}


def _taxonomy_request(images: list[tuple[bytes, str]]) -> dict:
    prompt = """Compare the artwork areas of these two Pokémon cards. Ignore
translated text, frames and set symbols. Choose exactly one category:
exact: the depicted scene, linework, palette and background match;
derived_recolor: distinctive composition, poses or linework match, but a
rainbow/gold/shiny treatment or material palette/background recolor differs;
different: the depicted poses, composition or scene details are distinct;
uncertain: the image evidence cannot settle the distinction.
Do not treat a shared character or artist alone as shared artwork. Describe
specific matching AND differing visible details. Return JSON with category
(exact/derived_recolor/different/uncertain) and visual_basis. These images
cannot establish physical finish, edition, condition or price equivalence."""
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, (data, mime) in zip(("Image A", "Image B"), images):
        parts.extend(({"text": label}, {"inlineData": {
            "mimeType": mime, "data": base64.b64encode(data).decode()}}))
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 1400}}


def _parse(response: dict) -> tuple[str, str, str]:
    if response.get("modelVersion") != MODEL:
        raise ValueError("unexpected model version")
    candidates = response.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
        raise ValueError("no complete model candidate")
    body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
    answer = json.loads(body)
    decision, basis = answer.get("decision"), answer.get("visual_basis")
    if decision not in {"same", "different", "uncertain"} or not isinstance(basis, str) or not basis.strip():
        raise ValueError("model returned an incomplete visual verdict")
    return decision, basis.strip(), hashlib.sha256(body.encode()).hexdigest()


def review_one(row: dict, project: str, location: str, token: str) -> dict:
    base = {"candidate_id": row["candidate_id"],
            "source_snapshot_sha256": row["source_snapshot_sha256"],
            "ja_image_sha256": row["ja_image"]["sha256"],
            "en_image_sha256": row["en_image"]["sha256"],
            "model": MODEL, "prompt_version": PROMPT_VERSION}
    try:
        images = [_fetch_image(row, side) for side in ("ja", "en")]
    except SourceImageChanged as exc:
        return base | {"second_decision": "source_image_changed", "visual_basis": "",
                       "error_type": type(exc).__name__, "changed_side": str(exc).split()[0],
                       "response_sha256": None}
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return base | {"second_decision": "insufficient_images", "visual_basis": "",
                       "error_type": type(exc).__name__, "response_sha256": None}
    request = _request(images)
    request_sha = _digest(request)
    error_type = None
    for attempt in range(3):
        try:
            response = _call_model(project, location, token, request)
            decision, basis, response_sha = _parse(response)
            return base | {"second_decision": decision, "visual_basis": basis,
                           "error_type": None, "request_sha256": request_sha,
                           "response_sha256": response_sha}
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as exc:
            error_type = type(exc).__name__
            if attempt < 2:
                time.sleep(attempt + 1)
    return base | {"second_decision": "model_error", "visual_basis": "",
                   "error_type": error_type, "request_sha256": request_sha,
                   "response_sha256": None}


def review_taxonomy_one(row: dict, project: str, location: str, token: str) -> dict:
    base = {"candidate_id": row["candidate_id"],
            "source_snapshot_sha256": row["source_snapshot_sha256"],
            "ja_image_sha256": row["ja_image"]["sha256"],
            "en_image_sha256": row["en_image"]["sha256"],
            "model": MODEL, "prompt_version": TAXONOMY_PROMPT_VERSION}
    try:
        images = [_fetch_image(row, side) for side in ("ja", "en")]
    except SourceImageChanged as exc:
        return base | {"category": "source_image_changed", "visual_basis": "",
                       "error_type": type(exc).__name__, "changed_side": str(exc).split()[0]}
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return base | {"category": "insufficient_images", "visual_basis": "",
                       "error_type": type(exc).__name__}
    request = _taxonomy_request(images)
    request_sha = _digest(request)
    error_type = None
    for attempt in range(3):
        try:
            response = _call_model(project, location, token, request)
            if response.get("modelVersion") != MODEL:
                raise ValueError("unexpected taxonomy model version")
            candidates = response.get("candidates") or []
            if not candidates or candidates[0].get("finishReason") not in {"STOP", None}:
                raise ValueError("no complete taxonomy response")
            body = "".join(part.get("text", "") for part in candidates[0]["content"]["parts"])
            answer = json.loads(body)
            category, basis = answer.get("category"), answer.get("visual_basis")
            if (category not in {"exact", "derived_recolor", "different", "uncertain"}
                    or not isinstance(basis, str) or not basis.strip()):
                raise ValueError("invalid taxonomy response")
            return base | {"category": category, "visual_basis": basis.strip(),
                           "error_type": None, "request_sha256": request_sha,
                           "response_sha256": hashlib.sha256(body.encode()).hexdigest()}
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as exc:
            error_type = type(exc).__name__
            if attempt < 2:
                time.sleep(attempt + 1)
    return base | {"category": "model_error", "visual_basis": "",
                   "error_type": error_type, "request_sha256": request_sha}


def run_taxonomy(sample: list[dict], sample_audit: dict, checkpoint: Path,
                 project: str, location: str, workers: int) -> tuple[list[dict], dict]:
    if _digest(sample) != sample_audit["sample_sha256"] or not 1 <= workers <= 8:
        raise ValueError("invalid taxonomy sample or worker count")
    checkpoint_rows = read_jsonl(checkpoint) if checkpoint.exists() else []
    seen = {row["candidate_id"]: row for row in checkpoint_rows}
    expected = {row["candidate_id"]: row for row in sample}
    if (len(seen) != len(checkpoint_rows) or len(expected) != len(sample)
            or set(seen) - set(expected)):
        raise ValueError("taxonomy checkpoint differs from sample")
    for cid, result in seen.items():
        row = expected[cid]
        if (result["source_snapshot_sha256"] != row["source_snapshot_sha256"]
                or result["ja_image_sha256"] != row["ja_image"]["sha256"]
                or result["en_image_sha256"] != row["en_image"]["sha256"]
                or result["prompt_version"] != TAXONOMY_PROMPT_VERSION
                or result.get("model") != MODEL
                or (result.get("category") in {"exact", "derived_recolor", "different", "uncertain"}
                    and not result.get("response_sha256"))):
            raise ValueError("taxonomy checkpoint source changed")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(review_taxonomy_one, row, project, location, token)
                   for row in sample if row["candidate_id"] not in seen]
        for future in as_completed(futures):
            result = future.result()
            seen[result["candidate_id"]] = result
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            print(f"taxonomy {len(seen)}/{len(sample)}", flush=True)
    ordered = [seen[row["candidate_id"]] for row in sample]
    report = {"scope": "image-only derived-recolor challenge set; no graph verification",
              "sample_sha256": sample_audit["sample_sha256"], "model": MODEL,
              "prompt_version": TAXONOMY_PROMPT_VERSION,
              "rows": len(ordered),
              "categories": dict(sorted(Counter(row["category"] for row in ordered).items())),
              "no_graph_promotion": True}
    return ordered, report


def run(sample: list[dict], sample_audit: dict, checkpoint: Path,
        project: str, location: str, workers: int) -> tuple[list[dict], dict]:
    if _digest(sample) != sample_audit["sample_sha256"]:
        raise ValueError("calibration sample changed")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be 1–8")
    seen = {}
    if checkpoint.exists():
        for row in read_jsonl(checkpoint):
            if row["candidate_id"] in seen:
                raise ValueError("duplicate calibration checkpoint row")
            seen[row["candidate_id"]] = row
    by_id = {row["candidate_id"]: row for row in sample}
    if len(by_id) != len(sample) or set(seen) - set(by_id):
        raise ValueError("calibration checkpoint differs from sample")
    for cid, row in seen.items():
        source = by_id[cid]
        if (row["source_snapshot_sha256"] != source["source_snapshot_sha256"]
                or row["ja_image_sha256"] != source["ja_image"]["sha256"]
                or row["en_image_sha256"] != source["en_image"]["sha256"]
                or row["prompt_version"] != PROMPT_VERSION
                or row.get("model") != MODEL
                or row.get("second_decision") not in DECISIONS
                or (row["second_decision"] in {"same", "different", "uncertain"}
                    and not row.get("response_sha256"))):
            raise ValueError("calibration checkpoint image or source changed")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    if not token:
        raise ValueError("gcloud returned no access token")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    missing = [row for row in sample if row["candidate_id"] not in seen]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(review_one, row, project, location, token): row["candidate_id"]
                   for row in missing}
        for future in as_completed(futures):
            result = future.result()
            seen[result["candidate_id"]] = result
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            if len(seen) % 20 == 0 or len(seen) == len(sample):
                print(f"calibration {len(seen)}/{len(sample)}", flush=True)
    ordered = [seen[row["candidate_id"]] for row in sample]
    report = {"scope": "blind same-model second pass; agreement is not accuracy or verified artwork",
              "sample_sha256": sample_audit["sample_sha256"],
              "model": MODEL, "prompt_version": PROMPT_VERSION,
              "rows": len(ordered),
              "second_decisions": dict(sorted(Counter(row["second_decision"] for row in ordered).items())),
              "no_graph_promotion": True}
    return ordered, report


def analyze(sample: list[dict], second: list[dict]) -> tuple[dict, list[dict]]:
    by_id = {row["candidate_id"]: row for row in second}
    if len(by_id) != len(second) or set(by_id) != {row["candidate_id"] for row in sample}:
        raise ValueError("second pass does not cover the sample exactly")
    matrix: dict[str, Counter] = defaultdict(Counter)
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    followup = []
    for row in sample:
        result = by_id[row["candidate_id"]]
        if (result["source_snapshot_sha256"] != row["source_snapshot_sha256"]
                or result["ja_image_sha256"] != row["ja_image"]["sha256"]
                or result["en_image_sha256"] != row["en_image"]["sha256"]
                or result["second_decision"] not in DECISIONS
                or result.get("model") != MODEL
                or result.get("prompt_version") != PROMPT_VERSION
                or (result["second_decision"] in {"same", "different", "uncertain"}
                    and not result.get("response_sha256"))):
            raise ValueError("second pass evidence differs from sampled images")
        first, latest = row["first_decision"], result["second_decision"]
        matrix[first][latest] += 1
        by_stratum[row["selection_reason"]][f"{first}->{latest}"] += 1
        if (first != latest or first not in {"same", "different"}
                or latest not in {"same", "different"}):
            followup.append({"candidate_id": row["candidate_id"],
                             "ja_card_id": row["ja_card_id"],
                             "en_card_id": row["en_card_id"],
                             "first_decision": first, "second_decision": latest,
                             "selection_reason": row["selection_reason"],
                             "source_snapshot_sha256": row["source_snapshot_sha256"],
                             "ja_image_sha256": row["ja_image"]["sha256"],
                             "en_image_sha256": row["en_image"]["sha256"],
                             "second_visual_basis": result["visual_basis"],
                             "review_status": "pending_independent_adjudication"})
    first_positive = matrix.get("same", Counter())
    first_negative = matrix.get("different", Counter())
    def agreement(counts: Counter, target: str) -> dict[str, int]:
        return {"n": counts[target],
                "model_answered_denominator": sum(counts[key] for key in
                                                 ("same", "different", "uncertain")),
                "decisive_denominator": counts["same"] + counts["different"],
                "selected_denominator": sum(counts.values())}
    report = {"scope": "blind same-model agreement; no accuracy, precision or recall estimate",
              "sample_rows": len(sample),
              "matrix": {key: dict(sorted(counts.items())) for key, counts in sorted(matrix.items())},
              "by_retrieval_stratum": {key: dict(sorted(counts.items()))
                                       for key, counts in sorted(by_stratum.items())},
              "same_agreement": agreement(first_positive, "same"),
              "different_agreement": agreement(first_negative, "different"),
              "source_image_changed": sum(counts["source_image_changed"]
                                          for counts in matrix.values()),
              "image_unavailable": sum(counts["insufficient_images"]
                                       for counts in matrix.values()),
              "disagreements_or_abstentions": len(followup),
              "verified_graph_edges_created": 0,
              "price_comparability_inferred": False}
    return report, followup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--queue", type=Path, required=True)
    prepare_cmd.add_argument("--first", type=Path, required=True)
    prepare_cmd.add_argument("--first-audit", type=Path, required=True)
    prepare_cmd.add_argument("--positive-n", type=int, default=150)
    prepare_cmd.add_argument("--sample", type=Path, required=True)
    prepare_cmd.add_argument("--sample-audit", type=Path, required=True)
    taxonomy_prepare = sub.add_parser("prepare-taxonomy")
    taxonomy_prepare.add_argument("--queue", type=Path, required=True)
    taxonomy_prepare.add_argument("--first", type=Path, required=True)
    taxonomy_prepare.add_argument("--first-audit", type=Path, required=True)
    taxonomy_prepare.add_argument("--sample", type=Path, required=True)
    taxonomy_prepare.add_argument("--sample-audit", type=Path, required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--sample", type=Path, required=True)
    run_cmd.add_argument("--sample-audit", type=Path, required=True)
    run_cmd.add_argument("--checkpoint", type=Path, required=True)
    run_cmd.add_argument("--workers", type=int, default=4)
    run_cmd.add_argument("--output", type=Path, required=True)
    run_cmd.add_argument("--audit", type=Path, required=True)
    taxonomy_run = sub.add_parser("run-taxonomy")
    taxonomy_run.add_argument("--sample", type=Path, required=True)
    taxonomy_run.add_argument("--sample-audit", type=Path, required=True)
    taxonomy_run.add_argument("--checkpoint", type=Path, required=True)
    taxonomy_run.add_argument("--workers", type=int, default=4)
    taxonomy_run.add_argument("--output", type=Path, required=True)
    taxonomy_run.add_argument("--audit", type=Path, required=True)
    analyze_cmd = sub.add_parser("analyze")
    analyze_cmd.add_argument("--sample", type=Path, required=True)
    analyze_cmd.add_argument("--second", type=Path, required=True)
    analyze_cmd.add_argument("--output", type=Path, required=True)
    analyze_cmd.add_argument("--followup", type=Path, required=True)
    args = parser.parse_args()
    if args.mode in {"prepare", "prepare-taxonomy"}:
        with args.first.open(encoding="utf-8", newline="") as handle:
            first = list(csv.DictReader(handle))
        queue = read_jsonl(args.queue)
        audit = json.loads(args.first_audit.read_text())
        sample, report = (prepare(queue, first, audit, args.positive_n)
                          if args.mode == "prepare" else prepare_taxonomy(queue, first, audit))
        write_jsonl(args.sample, sample)
        args.sample_audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    elif args.mode in {"run", "run-taxonomy"}:
        if args.output.exists() or args.audit.exists():
            raise FileExistsError("calibration output already exists")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
        if not project or not project.replace("-", "").isalnum() or location not in {"global", "us", "eu"}:
            raise ValueError("valid Google Cloud project and location are required")
        sample = read_jsonl(args.sample)
        audit = json.loads(args.sample_audit.read_text())
        rows, report = (run(sample, audit, args.checkpoint, project, location, args.workers)
                        if args.mode == "run" else
                        run_taxonomy(sample, audit, args.checkpoint, project, location, args.workers))
        write_jsonl(args.output, rows)
        args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        report, followup = analyze(read_jsonl(args.sample), read_jsonl(args.second))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        write_jsonl(args.followup, followup)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
