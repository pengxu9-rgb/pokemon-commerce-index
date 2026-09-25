"""Compile user-authorized independent AI name reviews into internal imports.

The concept revisions enable bilingual candidate retrieval. The card edges are
proposals for collection discovery, never verified printing counterparts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pokemon_index.core import parse_time
from scripts.relationship_pilot import read_jsonl, write_jsonl

REVIEWER = "ai-consensus:gpt-6-astra+gpt-6-sol"
REVIEW_BASIS = "dual_ai_agreement_user_authorized"
TRIPLE_REVIEWER = "ai-consensus:gpt-6-astra+gpt-6-sol+gemini-3.8-flash"
TRIPLE_REVIEW_BASIS = "triple_ai_agreement_user_authorized_images_when_available"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _csv_by_id(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [row.get("proposal_id") for row in rows]
    if not ids or len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError(f"missing or duplicate proposal ID in {path}")
    return {row["proposal_id"]: row for row in rows}


def compile_consensus(queue: list[dict[str, Any]], astra: dict[str, dict[str, str]],
                      sol: dict[str, dict[str, str]], reviewed_at: str,
                      batch_id: str = "v2", allow_deferred: bool = False,
                      gemini: dict[str, dict[str, str]] | None = None,
                      gemini_audit: dict[str, Any] | None = None
                      ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if batch_id not in {"v2", "v3", "v4", "v5", "v6"}:
        raise ValueError("unsupported concept batch ID")
    timestamp = parse_time(reviewed_at).isoformat()
    ids = [row["proposal_id"] for row in queue]
    if len(ids) != len(set(ids)) or set(ids) != set(astra) or set(ids) != set(sol):
        raise ValueError("queue and AI reviews must contain the same unique proposal IDs")
    if (gemini is None) != (gemini_audit is None):
        raise ValueError("Gemini review and audit must be provided together")
    triple = gemini is not None
    if triple:
        if batch_id != "v6" or set(ids) != set(gemini):
            raise ValueError("v6 triple review must cover the exact queue")
        if (gemini_audit.get("model") != "gemini-3.8-flash"
                or gemini_audit.get("pinned_revision") !=
                "a211f11f3ba57d56c65c5ac33be35b77d3280757"):
            raise ValueError("Gemini audit has the wrong model or source revision")
        audit_rows = gemini_audit.get("rows") or []
        if len(audit_rows) != len(ids) or len({r.get("proposal_id") for r in audit_rows}) != len(ids):
            raise ValueError("Gemini audit rows do not cover the queue")
        gemini_evidence = {r["proposal_id"]: r for r in audit_rows}
        if set(gemini_evidence) != set(ids):
            raise ValueError("Gemini audit rows do not cover the queue")
    else:
        gemini_evidence = {}
    reviewer = TRIPLE_REVIEWER if triple else REVIEWER
    review_basis = TRIPLE_REVIEW_BASIS if triple else REVIEW_BASIS
    events: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    selected_ja: set[tuple[str, str]] = set()
    selected_en: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    deferred: list[dict[str, str]] = []
    for proposal in queue:
        pid = proposal["proposal_id"]
        first, second = astra[pid], sol[pid]
        third = gemini[pid] if triple else None
        if _digest(proposal["source_snapshot"]) != proposal["source_snapshot_sha256"]:
            raise ValueError(f"source snapshot changed for {pid}")
        for label, row in (("Astra", first), ("Sol", second)):
            if batch_id != "v2" and row.get("source_snapshot_sha256") != proposal["source_snapshot_sha256"]:
                raise ValueError(f"{label} review no longer binds pinned evidence for {pid}")
        if third and third.get("source_snapshot_sha256") != proposal["source_snapshot_sha256"]:
            raise ValueError(f"Gemini review no longer binds pinned evidence for {pid}")
        if batch_id == "v2":
            if any(first.get(field) != proposal[field] for field in
                   ("name_ja", "name_en", "source_ja", "source_en", "source_snapshot_sha256")):
                raise ValueError(f"Astra review no longer binds pinned evidence for {pid}")
            if first.get("review_status") != "AI_ONLY_HUMAN_REVIEW_REQUIRED":
                raise ValueError(f"Astra AI-only provenance missing for {pid}")
        decision = first.get("suggested_decision")
        second_decision = second.get("suggested_decision")
        third_decision = third.get("suggested_decision") if third else None
        if decision not in {"approve", "reject", "uncertain"} or second_decision not in {
                "approve", "reject", "uncertain"}:
            raise ValueError(f"invalid AI review decision for {pid}")
        if third and (third_decision not in {"approve", "reject", "uncertain"}
                      or not (third.get("rationale") or "").strip()):
            raise ValueError(f"invalid or unexplained Gemini review for {pid}")
        image_pair = True
        if triple:
            evidence = gemini_evidence[pid]
            if evidence.get("model_version") != "gemini-3.8-flash":
                raise ValueError(f"Gemini model version mismatch for {pid}")
            image_pair = all(evidence.get(f"{side}_image", {}).get("status") == "included"
                             and evidence.get(f"{side}_image", {}).get("image_sha256")
                             for side in ("ja", "en"))
        if (decision != second_decision or decision == "uncertain"
                or (triple and decision != third_decision)):
            if not allow_deferred:
                raise ValueError(f"AI reviewers disagree or abstain on {pid}")
            item = {"proposal_id": pid, "astra": decision, "sol": second_decision}
            if triple:
                item["gemini"] = third_decision
            deferred.append(item)
            continue
        first_rationale = first.get("rationale") or first.get("evidence_rationale")
        second_rationale = second.get("rationale") or second.get("evidence_rationale")
        if not (first_rationale or "").strip() or not (second_rationale or "").strip():
            raise ValueError(f"missing independent review rationale for {pid}")
        counts[decision] += 1
        review = {
            "review_revision": 1, "decision": decision, "reviewer": reviewer,
            "reviewed_at": timestamp, "review_basis": review_basis,
            "ja_identity_checked": decision == "approve",
            "en_identity_checked": decision == "approve",
            "translation_checked": decision == "approve",
            "evidence_note": (("Three independent AI reviews agree on the name concept; Gemini saw pinned text and both source-matched card images. No human or printing verification."
                               if image_pair else
                               "Three independent AI reviews agree on the name concept; Gemini saw pinned text and source-matched card images where available. Missing image evidence is recorded. No human or printing verification.")
                              if triple else
                              "Dual AI agreement on name concept only; see both retained rationales. No human or printing verification."),
            "extra_source_ja": first.get("extra_source_ja", ""),
            "extra_source_en": first.get("extra_source_en", ""),
            "ai_reviews": [
                {"model": "gpt-6-astra", "decision": decision,
                 "rationale": first_rationale,
                 "limitations": first.get("evidence_limits") or first.get("source_limitations", "")},
                {"model": "gpt-6-sol", "decision": decision,
                 "rationale": second_rationale,
                 "limitations": second.get("evidence_limits") or second.get("source_limitations", "")},
            ],
        }
        if triple:
            evidence = gemini_evidence[pid]
            review["ai_reviews"].append({
                "model": "gemini-3.8-flash", "decision": decision,
                "rationale": third["rationale"],
                "limitations": third.get("evidence_limits", ""),
                "image_evidence": third.get("image_evidence", ""),
                "ja_image_sha256": evidence.get("ja_image", {}).get("image_sha256"),
                "en_image_sha256": evidence.get("en_image", {}).get("image_sha256"),
                "image_pair_checked": bool(image_pair),
                "request_sha256": evidence.get("request_sha256"),
                "response_sha256": evidence.get("response_sha256"),
            })
        event = {"schema": "pokemon.concept_review.v1", "proposal": proposal,
                 "review": review}
        event["event_id"] = _digest(event)
        events.append(event)
        if decision != "approve":
            continue
        ja_key = (proposal["category"], proposal["name_ja"])
        en_key = (proposal["category"], proposal["name_en"])
        if ja_key in selected_ja or en_key in selected_en:
            raise ValueError(f"conflicting approved concept name for {pid}")
        selected_ja.add(ja_key)
        selected_en.add(en_key)
        concept_id = "concept-" + hashlib.sha256((
            proposal["category"] + "\0" + proposal["name_ja"]
        ).encode()).hexdigest()[:20]
        revisions.append({
            "concept_id": concept_id, "revision": 1,
            "category": proposal["category"],
            "name_ja": proposal["name_ja"], "name_en": proposal["name_en"],
            "source_ja": proposal["source_ja"], "source_en": proposal["source_en"],
            "rights_reference": proposal["rights_reference"],
            "reviewer": reviewer, "reviewed_at": timestamp,
            "status": "approved", "review_event_id": event["event_id"],
        })
        evidence = {
            "schema": "pokemon.concept_candidate_edge.v1",
            "concept_id": concept_id, "concept_review_event_id": event["event_id"],
            "proposal_id": pid, "source_snapshot_sha256": proposal["source_snapshot_sha256"],
            "review_basis": review_basis, "source_ja": proposal["source_ja"],
            "source_en": proposal["source_en"],
            "scope": "same bilingual name concept; candidate collecting alternative only; artwork, finish and physical printing unverified",
        }
        edges.append({
            "assertion_id": f"concept-candidate-{batch_id}:" + pid,
            "left_card_id": proposal["ja_card_id"],
            "right_card_id": proposal["en_card_id"],
            "relation_type": "collecting_alternative",
            "review_status": "proposed",
            "evidence_ref": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "rights_reference": proposal["rights_reference"],
            "asserted_by": f"ai-consensus-concept-{batch_id}", "asserted_at": timestamp,
        })
    bundle = {
        "schema": "pokemon.concept_review_bundle.v1",
        "review_events": events, "concept_revisions": revisions,
        "audit": {"proposal_rows": len(queue), "decisions": dict(sorted(counts.items())),
                  "retained_review_events": len(events),
                  "approved_import_rows": len(revisions),
                  "proposed_candidate_edges": len(edges), "review_basis": review_basis,
                  "deferred_rows": len(deferred), "deferred": deferred,
                  "scope": "AI-agreed name concepts and proposed collecting alternatives; no human-certified printing counterparts"},
    }
    return bundle, edges


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--astra", type=Path, required=True)
    parser.add_argument("--sol", type=Path, required=True)
    parser.add_argument("--gemini", type=Path)
    parser.add_argument("--gemini-audit", type=Path)
    parser.add_argument("--reviewed-at", default=datetime.now().astimezone().isoformat())
    parser.add_argument("--batch-id", choices=("v2", "v3", "v4", "v5", "v6"), default="v2")
    parser.add_argument("--allow-deferred", action="store_true")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    args = parser.parse_args()
    bundle, edges = compile_consensus(read_jsonl(args.queue), _csv_by_id(args.astra),
                                      _csv_by_id(args.sol), args.reviewed_at,
                                      args.batch_id, args.allow_deferred,
                                      _csv_by_id(args.gemini) if args.gemini else None,
                                      json.loads(args.gemini_audit.read_text(encoding="utf-8"))
                                      if args.gemini_audit else None)
    if args.bundle.exists() or args.edges.exists():
        raise FileExistsError("consensus outputs must be new files")
    args.bundle.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
    write_jsonl(args.edges, edges)
    print(json.dumps(bundle["audit"], ensure_ascii=False))


if __name__ == "__main__":
    main()
