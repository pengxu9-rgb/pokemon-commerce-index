"""Read-only collector pilot diagnostic; source support is not physical approval.

The cohort comes from existing supported_card evidence. The current runtime's
ordinary exact-ID journey gates determine selection eligibility; this script
does not implement a second permission policy or change recommendation scope.
Question anchors are deliberately partial unless the fixture says otherwise.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path

from pokemon_index import collector_character_affiliation, collector_journey, core, supported_catalog

DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "sandbox/collector_journeys/supported-pilot-review-v1/questions.json"
APPROVAL_FIELDS = {
    "physical_printing_verified", "physical_copy_verified", "automatic_offer_join_allowed",
    "public_display_allowed", "transaction_ready", "purchase_ready", "ready_for_offer_tracking",
}


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unexpected_approvals(value, path="result"):
    """Check the diagnostic's no-new-authority contract at every nesting level."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            location = path + "." + key
            if key in APPROVAL_FIELDS and item not in (None, False, 0):
                found.append(location)
            if key in {"prices", "live_offers"} and item:
                found.append(location)
            found.extend(unexpected_approvals(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(unexpected_approvals(item, f"{path}[{index}]"))
    return found


def inspect_record(db, card_id, revision):
    support = supported_catalog.support_for_card(db, card_id)
    action = {"type": "ask", "question": card_id}
    result = collector_journey.replay(db, {"turns": [action]}, revision=revision)
    shown = card_id in {card["card_id"] for card in result["candidate_cards"]}
    blockers = sorted(set(result["selection_blockers"] +
                          result["card_selection_blockers"].get(card_id, [])))
    selectable = shown and result["selection_allowed"] and not blockers
    selected = None
    if selectable:
        selected = collector_journey.replay(db, {"turns": [action, {
            "type": "select", "card_id": card_id}]}, revision=revision)
    intent = selected.get("target_intent") if selected else None
    card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    return {
        "card_id": card_id, "name": card["name"], "variant": card["variant"],
        "support_status": support["status"], "structural_match_eligible": bool(card["match_eligible"]),
        "discoverable_by_exact_id": shown, "catalog_selection_eligible": selectable,
        "current_supported_and_selection_eligible": selectable and support["status"] == "supported_for_internal_review",
        "catalog_intent_roundtrip": bool(intent and intent["card_id"] == card_id),
        "blockers": blockers,
        "physical_printing_approval_exposed": bool(intent and intent["physical_printing_verified"]),
        "automatic_offer_join_approval_exposed": bool(intent and intent["automatic_offer_join_allowed"]),
        "unexpected_approval_paths": unexpected_approvals(result) + unexpected_approvals(selected),
    }


def run_question(db, question, revision, supported_ids, affiliation_rows=None):
    expected = question.get("expect", {})
    result = collector_journey.replay(db, {"turns": question["turns"],
                                          "limit": question.get("limit", 50)}, revision=revision)
    ids = [card["card_id"] for card in result["candidate_cards"]]
    anchors = set(expected.get("required_anchor_ids", []))
    errors = []
    for key, actual in (("task", result["discovery"]["task"]),
                        ("status", result["status"]),
                        ("selection_allowed", result["selection_allowed"])):
        if key in expected and expected[key] != actual:
            errors.append(key)
    if anchors - set(ids):
        errors.append("missing_supported_anchors")
    if set(expected.get("absent_ids", [])) & set(ids):
        errors.append("owned_or_excluded_record_returned")
    if set(expected.get("required_blockers", [])) - set(result["selection_blockers"]):
        errors.append("missing_blocker")
    if "target_card_id" in expected:
        target = result["target_intent"]["card_id"] if result["target_intent"] else None
        if target != expected["target_card_id"]:
            errors.append("target_card_id")
    required_scope = expected.get("returned_scope", {})
    if any(any(card[field] != value for field, value in required_scope.items())
           for card in result["candidate_cards"]):
        errors.append("returned_scope")
    approvals = unexpected_approvals(result)
    if approvals:
        errors.append("unexpected_authority")
    blockers = result["card_selection_blockers"]
    evidence = []
    affiliation_rows = affiliation_rows if affiliation_rows is not None else collector_character_affiliation.affiliations(db)
    items = {item["card_id"]: item for item in (result.get("recommendation") or {}).get("items", [])}
    if expected.get("returned_facet") and not ids:
        errors.append("no_relevant_candidates")
    for card in result["candidate_cards"]:
        cid = card["card_id"]
        facets = [dict(row) for row in db.execute("""SELECT facet_type,value,provenance,rights_reference
            FROM discovery_card_facet WHERE card_id=? AND facet_type IN ('dex_id','illustrator')
            ORDER BY facet_type,value,provenance""", (cid,))]
        expected_facet = expected.get("returned_facet")
        relevant = (any(f["facet_type"] == expected_facet["field"] and
                        f["value"] == str(expected_facet["value"]) for f in facets)
                    if expected_facet else None)
        reasons = items.get(cid, {}).get("reasons", [])
        checks = []
        for reason in reasons:
            field = reason["field"]
            if field in {"dex_id", "illustrator"}:
                matched = any(f["facet_type"] == field and f["value"] == str(reason["value"])
                              and f["provenance"] == reason["source_ref"] for f in facets)
            elif field == "language_set_coordinate":
                matched = reason["value"] == {"language": card["language"], "set_code": card["set_code"]}
                matched = matched and reason["source_ref"] == card["provenance"]
            elif field == "character_name_affiliation":
                affiliate_id = reason.get("affiliated_card_id")
                current = affiliation_rows.get(affiliate_id, {}).get("reason")
                matched = bool(current and all(reason.get(key) == value for key, value in current.items())
                    and set(reason) == set(current) | {"affiliated_card_id", "affiliation_role", "preference_origin"}
                    and reason.get("affiliation_role") in {"candidate", "liked_example"}
                    and reason.get("preference_origin") in {"explicit_preference", "liked_example"}
                    and (reason["affiliation_role"] != "candidate" or affiliate_id == cid)
                    and (reason["affiliation_role"] != "liked_example" or reason["preference_origin"] == "liked_example"))
            else:
                matched = False
            checks.append({"field": field, "basis": reason.get("basis"), "source_matches": matched})
        axis_for_field = {"dex_id": "character", "illustrator": "illustrator",
                          "language_set_coordinate": "release", "character_name_affiliation": "character"}
        axis_matches = True
        for axis_field, basis in [("explicit_match_axes", "catalog_facet"),
                                  ("liked_example_match_axes", "liked_example_catalog_facet")]:
            evidenced = {axis_for_field[reason["field"]] for reason in reasons
                          if reason["field"] in axis_for_field and (reason.get("basis") == basis
                              or axis_field == "explicit_match_axes" and reason.get("basis") == "catalog_coordinate"
                              or reason.get("basis") == "source_name_character_affiliation" and
                              reason.get("preference_origin") == ("explicit_preference" if axis_field == "explicit_match_axes" else "liked_example"))}
            if set(items.get(cid, {}).get(axis_field, [])) != evidenced:
                axis_matches = False
        evidence.append({"card_id": cid, "source_facets": facets,
                         "requested_facet_matches": relevant, "reason_checks": checks,
                         "match_axes_have_corresponding_reasons": axis_matches,
                         "explicit_match_axes": items.get(cid, {}).get("explicit_match_axes", []),
                         "liked_example_match_axes": items.get(cid, {}).get("liked_example_match_axes", []),
                         "selection_eligible": result["selection_allowed"] and not blockers[cid]
                                               and not result["selection_blockers"]})
    if any(card["requested_facet_matches"] is False for card in evidence):
        errors.append("requested_facet_correspondence")
    if any(not check["source_matches"] for card in evidence for check in card["reason_checks"]):
        errors.append("recommendation_reason_provenance")
    if any(not card["match_axes_have_corresponding_reasons"] for card in evidence):
        errors.append("recommendation_axes_without_reasons")
    return {
        "id": question["id"], "family": question["family"], "passed": not errors,
        "errors": errors, "turns": question["turns"], "expect": expected,
        "task": result["discovery"]["task"], "status": result["status"],
        "returned_card_ids": ids, "returned_supported_ids": sorted(set(ids) & supported_ids),
        "returned_research_ids": sorted(set(ids) - supported_ids),
        "returned_selection_eligible_ids": [cid for cid in ids if result["selection_allowed"] and not blockers[cid]
                                            and not result["selection_blockers"]],
        "required_anchor_count": len(anchors), "returned_anchor_count": len(anchors & set(ids)),
        "full_result_precision_or_recall_established": False,
        "coverage": result["discovery"].get("coverage"),
        "selection_blockers": result["selection_blockers"], "card_selection_blockers": blockers,
        "target_card_id": result["target_intent"]["card_id"] if result["target_intent"] else None,
        "next_step": result["next_step"], "unexpected_approval_paths": approvals,
        "per_card_evidence": evidence,
        "requested_facet_matching_records": sum(card["requested_facet_matches"] is True for card in evidence),
        "selection_eligible_records": sum(card["selection_eligible"] for card in evidence),
        "reason_checks": sum(len(card["reason_checks"]) for card in evidence),
        "reason_checks_passed": sum(check["source_matches"] for card in evidence for check in card["reason_checks"]),
    }


def audit(db, suite, *, language="ja", set_code="SV4A"):
    if suite.get("schema") != "pokemon.supported-collector-pilot-questions.v1":
        raise ValueError("unsupported pilot question schema")
    revision = collector_journey.catalog_revision(db)
    ids = [row[0] for row in db.execute("""SELECT s.card_id FROM supported_card s
        JOIN card c ON c.card_id=s.card_id WHERE c.language=? AND c.set_code=? ORDER BY s.card_id""",
                                         (language, set_code))]
    records = [inspect_record(db, cid, revision) for cid in ids]
    current = {row["card_id"] for row in records if row["support_status"] == "supported_for_internal_review"}
    derived = collector_character_affiliation.affiliations(db)
    for record in records:
        cid = record["card_id"]
        record["current_character_facets"] = [dict(row) for row in db.execute(
            "SELECT value,provenance,rights_reference FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id' ORDER BY value,provenance", (cid,))]
        classified = db.execute("""SELECT k.category FROM card_classification k JOIN card c ON c.card_id=k.card_id
            WHERE k.card_id=? AND k.provenance=c.provenance AND k.rights_reference=c.rights_reference""", (cid,)).fetchone()
        record["current_source_category"] = classified[0] if classified else None
        record["derived_name_affiliation"] = derived.get(cid)
    character_coverage = {
        "current_explicit_dex_facet": sum(bool(r["current_character_facets"]) for r in records),
        "valid_derived_name_affiliation": sum(r["derived_name_affiliation"] is not None for r in records),
        "source_classified_pokemon_still_unresolved": sum(r["current_source_category"] == "Pokemon" and
            not r["current_character_facets"] and r["derived_name_affiliation"] is None for r in records),
        "source_classified_non_pokemon": sum(r["current_source_category"] in {"Trainer", "Energy"} for r in records),
        "unknown_or_stale_classification": sum(r["current_source_category"] is None for r in records),
    }
    questions = []
    for question in suite["questions"]:
        try:
            questions.append(run_question(db, question, revision, current, derived))
        except (ValueError, KeyError, TypeError) as error:
            questions.append({"id": question["id"], "family": question["family"],
                              "passed": False, "errors": ["runtime_error"], "error": str(error)})
    flags = ["discoverable_by_exact_id", "catalog_selection_eligible",
             "current_supported_and_selection_eligible", "catalog_intent_roundtrip",
             "physical_printing_approval_exposed", "automatic_offer_join_approval_exposed"]
    stage_counts = {key: sum(bool(record[key]) for record in records) for key in flags}
    stage_counts.update(declared_support_records=len(records), currently_supported_records=len(current),
                        structurally_match_eligible=sum(record["structural_match_eligible"] for record in records))
    contract_errors = []
    if "expected_cohort_card_ids" in suite and set(ids) != set(suite["expected_cohort_card_ids"]):
        contract_errors.append("source_bound_cohort_membership_changed")
    if ("expected_current_supported_records" in suite and
            len(current) != suite["expected_current_supported_records"]):
        contract_errors.append("source_support_count_changed")
    if any(record["unexpected_approval_paths"] for record in records):
        contract_errors.append("unexpected_cohort_authority")
    market = {table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
              for table in ("listing", "observation", "verified_sale", "landed_quote")}
    families = sorted({question["family"] for question in questions})
    family_summary = {family: {
        "total": sum(question["family"] == family for question in questions),
        "passed": sum(question["family"] == family and question["passed"] for question in questions),
    } for family in families}
    explicit_targets = [question for question in questions if
                        question.get("expect", {}).get("target_card_id") is not None]
    return {
        "schema": "pokemon.supported-collector-pilot-audit.v1", "catalog_revision": revision,
        "cohort": {"language": language, "set_code": set_code,
                   "membership_basis": "existing supported_card evidence only; no new allowlist or approval"},
        "catalog_counts": {"source_records": db.execute("SELECT count(*) FROM card").fetchone()[0],
                           "coordinates": db.execute("SELECT count(*) FROM (SELECT DISTINCT language,set_code,collector_number FROM card)").fetchone()[0],
                           "structurally_match_eligible": db.execute("SELECT count(*) FROM card WHERE match_eligible=1").fetchone()[0]},
        "stage_counts": stage_counts,
        "character_coverage_counts": character_coverage,
        "remaining_character_evidence_gap_ids": [r["card_id"] for r in records if
            r["current_source_category"] == "Pokemon" and not r["current_character_facets"]
            and r["derived_name_affiliation"] is None],
        "support_status_counts": dict(Counter(record["support_status"] for record in records)),
        "blocker_counts": dict(Counter(blocker for record in records for blocker in record["blockers"])),
        "variant_counts": dict(Counter(record["variant"] for record in records)),
        "market_row_counts": market, "records": records, "questions": questions,
        "question_summary": {"total": len(questions), "passed": sum(q["passed"] for q in questions),
                             "failed": sum(not q["passed"] for q in questions)},
        "question_family_summary": family_summary,
        "explicit_catalog_target_outcomes": {
            "attempted": len(explicit_targets),
            "succeeded": sum(question["passed"] and question["target_card_id"] ==
                             question["expect"]["target_card_id"] for question in explicit_targets),
            "scope": "separate explicit catalog selections; no physical-copy or shopping success"},
        "contract_errors": contract_errors,
        "interpretation": [
            "Exact-ID discoverability is an engineering count, not natural-language discovery success.",
            "Catalog selection is an explicit research target, not a verified physical printing or purchasable copy.",
            "Physical/offer approval counts describe authority exposed by this runtime; no new physical audit occurred.",
            "Partial supported-anchor retrieval is not full-catalog precision, completeness or real-user relevance.",
            "Recommendations may include broad research records; this diagnostic does not silently filter them.",
        ],
        "source_selection_independent_of_runtime": suite.get("source_selection_independent_of_runtime", False),
        "real_user_quality_established": False, "new_verification_claims": False,
    }


def run(db_path, suite_path, output):
    if output.exists():
        raise FileExistsError(output)
    before = digest_file(db_path)
    suite = json.loads(suite_path.read_text())
    with closing(core.connect(db_path, readonly=True)) as db:
        db.execute("PRAGMA query_only=ON")
        report = audit(db, suite)
    report.update(catalog_sha256=before, catalog_bytes_unchanged=before == digest_file(db_path),
                  suite_sha256=digest_file(suite_path), script_sha256=digest_file(__file__))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ["catalog_counts", "stage_counts", "character_coverage_counts", "question_summary", "question_family_summary",
                       "explicit_catalog_target_outcomes", "contract_errors", "catalog_bytes_unchanged"]}))
    for question in report["questions"]:
        print(json.dumps({key: question[key] for key in
                          ["id", "family", "passed", "errors", "task", "status",
                           "required_anchor_count", "returned_anchor_count", "target_card_id", "error",
                           "requested_facet_matching_records", "selection_eligible_records",
                           "reason_checks", "reason_checks_passed"]
                          if key in question}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.db, args.suite, args.output)
    if (not report["catalog_bytes_unchanged"] or report["question_summary"]["failed"]
            or report["contract_errors"]):
        raise SystemExit(1)
