"""Gate public-question candidates on source evidence before blind freezing.

The two independent audits are claims about fidelity, not human ground truth.
Rejected candidates remain in the report and cannot leak into the blind set.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.public_question_sandbox import (read_jsonl, sha_file,
                                             validate_source, write_jsonl)
from scripts.public_question_sandbox_v2 import _url_key

AUDIT_STATUSES = {"faithful", "inferred_case", "mismatch", "unverifiable"}
EVIDENCE_METHODS = {"opened_post", "title_only", "search_snippet"}


def _unique(rows: list[dict], name: str) -> dict[str, dict]:
    result = {row.get("id"): row for row in rows}
    if len(result) != len(rows) or None in result:
        raise ValueError(f"{name} has duplicate or missing IDs")
    return result


def preflight(source: Path, evidence: Path, astra: Path, gemini: Path,
              priors: list[Path], out_dir: Path) -> dict:
    if out_dir.exists():
        raise FileExistsError("preflight output must be new")
    candidates = read_jsonl(source)
    validate_source(candidates)
    by_id = _unique(candidates, "candidates")
    prior_urls = set()
    for prior in priors:
        rows = read_jsonl(prior)
        validate_source(rows)
        prior_urls.update(_url_key(row["source_url"]) for row in rows)
    if prior_urls & {_url_key(row["source_url"]) for row in candidates}:
        raise ValueError("candidate reuses a prior source post")
    evidence_rows = _unique(read_jsonl(evidence), "evidence")
    if evidence_rows.keys() != by_id.keys():
        raise ValueError("evidence must cover every candidate")
    for item_id, row in evidence_rows.items():
        if (set(row) != {"id", "source_url", "post_locator", "anchor", "source_context",
                         "verification_method", "observed_date"}
                or row["source_url"] != by_id[item_id]["source_url"]
                or row["verification_method"] not in EVIDENCE_METHODS
                or not isinstance(row["post_locator"], str)
                or not row["post_locator"].strip()
                or not isinstance(row["anchor"], str)
                or not row["anchor"].strip()
                or len(row["anchor"].split()) > 25
                or len(row["anchor"]) > 180
                or not isinstance(row["source_context"], str)
                or not 30 <= len(row["source_context"]) <= 1000
                or row["observed_date"] != by_id[item_id]["observed_date"]):
            raise ValueError(f"invalid source evidence: {item_id}")
    audits = {}
    for family, path in (("astra", astra), ("google", gemini)):
        rows = _unique(read_jsonl(path), family)
        if rows.keys() != by_id.keys():
            raise ValueError(f"{family} audit must cover every candidate")
        for item_id, row in rows.items():
            if (not {"id", "model_family", "source_sha256", "evidence_sha256",
                     "status", "reason"} <= set(row)
                    or row["model_family"] != family
                    or row["source_sha256"] != sha_file(source)
                    or row["evidence_sha256"] != sha_file(evidence)
                    or row["status"] not in AUDIT_STATUSES
                    or not isinstance(row["reason"], str)
                    or not row["reason"].strip()):
                raise ValueError(f"invalid {family} audit: {item_id}")
        audits[family] = rows
    decisions = []
    for item_id, candidate in by_id.items():
        a, g = audits["astra"][item_id], audits["google"][item_id]
        method = evidence_rows[item_id]["verification_method"]
        accepted = method == "opened_post" and a["status"] == g["status"] == "faithful"
        decisions.append({"id": item_id, "accepted": accepted,
                          "source_url": candidate["source_url"],
                          "verification_method": method,
                          "astra_status": a["status"], "gemini_status": g["status"]})
    accepted_ids = {row["id"] for row in decisions if row["accepted"]}
    if not accepted_ids:
        raise ValueError("no candidate passed the source gate")
    out_dir.mkdir(parents=True)
    write_jsonl(out_dir / "eligible_source_questions.jsonl",
                [row for row in candidates if row["id"] in accepted_ids])
    report = {"schema": "pokemon.public-question-preflight.v1",
              "candidate_sha256": sha_file(source),
              "evidence_sha256": sha_file(evidence),
              "astra_sha256": sha_file(astra), "gemini_sha256": sha_file(gemini),
              "prior_source_sha256": [sha_file(path) for path in priors],
              "eligible_sha256": sha_file(out_dir / "eligible_source_questions.jsonl"),
              "candidates": len(candidates), "accepted": len(accepted_ids),
              "rejected": len(candidates) - len(accepted_ids),
              "audit_statuses": {family: dict(sorted(Counter(
                  row["status"] for row in rows.values()).items()))
                  for family, rows in audits.items()},
              "decisions": decisions,
              "interpretation": "Pre-freeze AI source-fidelity gate; dual agreement is not human accuracy or market truth"}
    (out_dir / "report.json").write_text(json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--astra", type=Path, required=True)
    parser.add_argument("--gemini", type=Path, required=True)
    parser.add_argument("--prior-source", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(preflight(args.source, args.evidence, args.astra,
                               args.gemini, args.prior_source, args.out_dir),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
