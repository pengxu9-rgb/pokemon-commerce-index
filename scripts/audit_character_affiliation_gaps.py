"""Read-only replay of the 21 source-qualified character gaps from 024a72d.

This is a bounded engineering/source diagnostic, not an independent user-quality
evaluation. The original 34-question fixture and its failure receipts stay fixed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path

from pokemon_index import collector_character_affiliation as affiliation
from pokemon_index import collector_journey, core, supported_catalog
from scripts.audit_supported_collector_pilot import unexpected_approvals

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "catalog/character-affiliation-gap-review-v1.json"
GAP_IDS = {f"ja:SV4A:{n}/190:holo" for n in [*range(320, 327), 329, 330, *range(332, 338), *range(355, 361)]}


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_receipt(path=RECEIPT):
    receipt = json.loads(Path(path).read_text())
    if (receipt.get("schema") != "pokemon.character-affiliation-gap-source-review.v1"
            or len(receipt.get("targets", [])) != 21
            or {r["card_id"] for r in receipt["targets"]} != GAP_IDS):
        raise ValueError("the original 21 character-gap targets must remain fixed")
    if any(file_sha256(ROOT / name) != digest for name, digest in receipt["input_sha256"].items()):
        raise ValueError("source-review catalog input changed; re-review required")
    return receipt


def audit(db, receipt):
    current = affiliation.affiliations(db)
    revision = collector_journey.catalog_revision(db)
    pins = {r["card_id"]: r for r in affiliation._bindings()}
    rows = []
    for target in receipt["targets"]:
        cid = target["card_id"]
        dex = target["expected_derived_dex_id"]
        derived = current.get(cid)
        errors = []
        pin = pins.get(cid)
        if not pin or any(pin.get(key) != target[key] for key in (
                "source_ref", "source_sha256", "source_git_blob_sha", "base_name_ja")):
            errors.append("target_source_pin_differs_from_review")
        source_dex = [dict(r) for r in db.execute("""SELECT value,provenance,rights_reference
            FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id'""", (cid,))]
        if source_dex:
            errors.append("target_now_has_explicit_facet_reassess_derived_expectation")
        if not derived or derived["dex_id"] != dex:
            errors.append("reviewed_affiliation_not_current")
        # A natural-language goal plus explicit preferences exercises the real
        # collector action contract. It is not scored as natural-language recall.
        turns = [{"type": "ask", "question": "Recommend Japanese cards"},
                 {"type": "refine", "scope": {"set_code": "SV4A"}},
                 {"type": "preferences", "preferences": {"collecting": {"preferred_dex_ids": [dex]}}}]
        result = collector_journey.replay(db, {"turns": turns, "limit": 50}, revision=revision)
        ids = [card["card_id"] for card in result["candidate_cards"]]
        if cid not in ids:
            errors.append("qualified_target_not_recommended")
        selectable = cid in ids and result["selection_allowed"] and not result["selection_blockers"] and not result["card_selection_blockers"][cid]
        if not selectable:
            errors.append("target_not_catalog_selectable")
        item = next((item for item in (result.get("recommendation") or {}).get("items", []) if item["card_id"] == cid), {})
        proof_matches = any(derived and all(reason.get(k) == v for k, v in derived["reason"].items())
                            and reason.get("affiliated_card_id") == cid
                            and reason.get("affiliation_role") == "candidate"
                            and reason.get("preference_origin") == "explicit_preference"
                            for reason in item.get("reasons", []))
        if not proof_matches:
            errors.append("derived_reason_missing_or_mislabelled")
        approvals = unexpected_approvals(result)
        if approvals:
            errors.append("unexpected_authority")
        rows.append({"card_id": cid, "name": target["target_name"], "expected_derived_dex_id": dex,
                     "current_explicit_dex_facets": source_dex, "current_derived_affiliation": derived,
                     "recommended": cid in ids, "catalog_selection_eligible": bool(selectable),
                     "typed_proof_matches": proof_matches, "unexpected_approval_paths": approvals,
                     "passed": not errors, "errors": errors})
    return {"schema": "pokemon.character-affiliation-gap-audit.v1", "catalog_revision": revision,
            "source_review_baseline": receipt["baseline_commit"], "reviewed_target_count": len(rows),
            "reviewed_anchor_source_count": len(receipt["anchor_sources"]),
            "current_derived_target_count": sum(r["current_derived_affiliation"] is not None for r in rows),
            "recommended_target_count": sum(r["recommended"] for r in rows),
            "catalog_selection_eligible_count": sum(r["catalog_selection_eligible"] for r in rows),
            "passed": sum(r["passed"] for r in rows), "failed": sum(not r["passed"] for r in rows),
            "unexpected_approval_count": sum(len(r["unexpected_approval_paths"]) for r in rows),
            "independent_user_quality_established": False, "new_stored_target_dex_facts": False,
            "records": rows}


def run(db_path, output):
    output = Path(output)
    if output.exists():
        raise ValueError("refusing to overwrite a diagnostic receipt")
    receipt = load_receipt()
    before = file_sha256(db_path)
    with closing(core.connect(db_path, readonly=True)) as db:
        db.execute("PRAGMA query_only=ON")
        result = audit(db, receipt)
    result.update(catalog_bytes_unchanged=before == file_sha256(db_path), catalog_sha256=before,
                  source_review_sha256=file_sha256(RECEIPT), script_sha256=file_sha256(__file__))
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}))
    for row in result["records"]:
        print(json.dumps({k: row[k] for k in ("card_id", "passed", "errors", "recommended", "catalog_selection_eligible")}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.db, args.output)
    if result["failed"] or not result["catalog_bytes_unchanged"] or result["unexpected_approval_count"]:
        raise SystemExit(1)
