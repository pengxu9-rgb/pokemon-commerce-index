"""Import source-bound number leads without equating physical printings or prices."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable

from . import number_conflicts


def compact_name(name: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", name).casefold())


def apply_candidates(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    with db:
        for row in rows:
            card = db.execute("SELECT * FROM card WHERE card_id=?", (row.get("card_id"),)).fetchone()
            if card is None or card["match_eligible"]:
                raise ValueError("number alias requires an existing match-blocked card")
            rule = number_conflicts.rule_for_card(
                db, card["language"], card["set_code"], card["collector_number"],
                card["provenance"])
            if rule is None or row.get("rule_id") != rule["rule_id"]:
                raise ValueError("number alias lacks its pinned conflict rule")
            if (row.get("source_provenance") != card["provenance"]
                    or row.get("catalog_number") != card["collector_number"]
                    or compact_name(str(row.get("catalog_name", ""))) != compact_name(card["name"])):
                raise ValueError("number alias differs from catalog card")
            expected = card["collector_number"].split("/", 1)[0] + "/" + rule["official_denominator"]
            if row.get("official_number_candidate") != expected:
                raise ValueError("number alias changed the numerator or official denominator")
            records = row.get("official_records")
            if not isinstance(records, list) or not records:
                raise ValueError("number alias needs pinned official-source records")
            ids = set()
            for record in records:
                if (not isinstance(record, dict)
                        or not re.fullmatch(r"data_jp/[A-Za-z0-9-]+/[0-9]+\.json",
                                            str(record.get("path", "")))
                        or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                        or not re.fullmatch(
                            r"https://www\.pokemon-card\.com/card-search/details\.php/card/[0-9]+",
                            str(record.get("url", "")))
                        or record["path"].split("/")[1].upper() != card["set_code"]
                        or record["path"].split("/")[-1][:-5] != record["url"].rsplit("/", 1)[-1]
                        or record.get("collector_number") != expected
                        or compact_name(str(record.get("name", ""))) != compact_name(card["name"])):
                    raise ValueError("number alias official record identity is inconsistent")
                ids.add(record["path"])
            if len(ids) != len(records) or row.get("official_source_revision") != rule["official_source_revision"]:
                raise ValueError("number alias record IDs or source revision differ")
            evidence = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            previous = db.execute("SELECT evidence_json FROM card_number_alias_candidate WHERE card_id=?",
                                  (card["card_id"],)).fetchone()
            if previous and previous["evidence_json"] != evidence:
                raise ValueError("existing number alias evidence differs")
            db.execute("""INSERT OR IGNORE INTO card_number_alias_candidate VALUES (?,?,?,?,?,?,?,?)""",
                       (card["card_id"], rule["rule_id"], card["collector_number"],
                        expected, card["provenance"], len(records), evidence,
                        datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"candidates": imported}


def apply_visual_context(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Attach earlier AI image comparisons without assigning a physical finish."""
    imported = 0
    with db:
        for row in rows:
            alias = db.execute("SELECT * FROM card_number_alias_candidate WHERE card_id=?",
                               (row.get("card_id"),)).fetchone()
            if alias is None:
                raise ValueError("visual context requires an existing number alias")
            evidence = json.loads(alias["evidence_json"])
            number = alias["official_number_candidate"]
            group_id = f"ja:{row['card_id'].split(':')[1]}:{number}:unverified_multi_record"
            if (alias["official_record_count"] != 2 or row.get("group_id") != group_id
                    or row.get("official_number_candidate") != number
                    or row.get("physical_printing_status") != "unverified"
                    or row.get("official_record_to_catalog_variant_assignment") != "unestablished"
                    or row.get("offer_matching_status") != "blocked"):
                raise ValueError("visual context must preserve its ambiguous number group")
            records = evidence["official_records"]
            ids = sorted(int(record["path"].rsplit("/", 1)[1][:-5]) for record in records)
            hashes = sorted(record["sha256"] for record in records)
            if (sorted(row.get("source_jp_ids", [])) != ids
                    or sorted(row.get("source_record_sha256", [])) != hashes):
                raise ValueError("visual context differs from pinned source records")
            status = row.get("visual_status")
            if status not in {"ai_exact_artwork_surface_question", "image_unavailable"}:
                raise ValueError("unknown visual context status")
            if (not re.fullmatch(r"[0-9a-f]{64}", str(row.get("visual_row_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("review_queue_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("visual_batch_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("followup_batch_sha256", "")))):
                raise ValueError("visual context lacks source snapshot hashes")
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            prior = db.execute("SELECT evidence_json FROM card_number_alias_visual_context WHERE card_id=?",
                               (row["card_id"],)).fetchone()
            if prior and prior["evidence_json"] != canonical:
                raise ValueError("existing visual context differs")
            db.execute("INSERT OR IGNORE INTO card_number_alias_visual_context VALUES (?,?,?,?,?)",
                       (row["card_id"], group_id, status, canonical,
                        datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"visual_contexts": imported}


def apply_visual_recoveries(db: sqlite3.Connection,
                            rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    recovered = 0
    with db:
        for row in rows:
            prior = db.execute("""SELECT * FROM card_number_alias_visual_context
                WHERE card_id=?""", (row.get("card_id"),)).fetchone()
            if prior is None or prior["visual_status"] != "image_unavailable":
                raise ValueError("visual recovery requires a prior missing-image result")
            baseline = json.loads(prior["evidence_json"])
            if (row.get("group_id") != prior["group_id"]
                    or row.get("prior_visual_row_sha256") != baseline["visual_row_sha256"]
                    or row.get("source_jp_ids") != baseline["source_jp_ids"]
                    or row.get("source_record_sha256") != baseline["source_record_sha256"]
                    or row.get("visual_status") != "ai_exact_artwork_surface_question"
                    or row.get("physical_printing_status") != "unverified"
                    or row.get("official_record_to_catalog_variant_assignment") != "unestablished"
                    or row.get("offer_matching_status") != "blocked"):
                raise ValueError("visual recovery differs from its source-bound missing-image result")
            for key in ("stable_audit_sha256", "review_batch_sha256", "recovery_review_row_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key, ""))):
                    raise ValueError("visual recovery lacks stable-image review hashes")
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            existing = db.execute("SELECT evidence_json FROM card_number_alias_visual_recovery WHERE card_id=?",
                                  (row["card_id"],)).fetchone()
            if existing and existing["evidence_json"] != canonical:
                raise ValueError("existing visual recovery evidence differs")
            db.execute("INSERT OR IGNORE INTO card_number_alias_visual_recovery VALUES (?,?,?,?)",
                       (row["card_id"], row["group_id"], canonical,
                        datetime.now(timezone.utc).isoformat()))
            recovered += 1
    return {"visual_recoveries": recovered}


def apply_scan_candidates(db: sqlite3.Connection,
                          rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Store image-presentation hypotheses; never change offer eligibility."""
    imported = 0
    with db:
        for row in rows:
            card_id = row.get("card_id")
            alias = db.execute("SELECT * FROM card_number_alias_candidate WHERE card_id=?",
                               (card_id,)).fetchone()
            visual = db.execute("SELECT * FROM card_number_alias_visual_context WHERE card_id=?",
                                (card_id,)).fetchone()
            card = db.execute("SELECT variant,match_eligible FROM card WHERE card_id=?",
                              (card_id,)).fetchone()
            if not alias or not visual or not card or card["match_eligible"]:
                raise ValueError("scan candidate needs blocked alias and visual context")
            old = json.loads(visual["evidence_json"])
            records = sorted(json.loads(alias["evidence_json"])["official_records"],
                             key=lambda item: int(item["path"].rsplit("/", 1)[-1][:-5]))
            scans = row.get("official_scans")
            if (len(records) != 2 or not isinstance(scans, list) or len(scans) != 2
                    or [item.get("source_jp_id") for item in scans] != [
                        int(item["path"].rsplit("/", 1)[-1][:-5]) for item in records]
                    or [item.get("source_record_sha256") for item in scans] != [
                        item["sha256"] for item in records]
                    or [item["source_jp_id"] for item in scans] != old["source_jp_ids"]
                    or sorted(item["source_record_sha256"] for item in scans) !=
                       sorted(old["source_record_sha256"])
                    or [item.get("scan_role") for item in scans] != [
                        "reference_image_no_motif_assertion",
                        "visible_pokeball_pattern_candidate"]):
                raise ValueError("scan candidate differs from official record ID/hash binding")
            variant = card["variant"]
            expected_id = (scans[0]["source_jp_id"] if variant == "normal" else
                           scans[1]["source_jp_id"] if variant == "reverse_pokeball" else None)
            expected_strength = ("metadata_plus_contrasting_reference_scan" if variant == "normal"
                                 else "metadata_plus_visible_scan_motif" if variant == "reverse_pokeball"
                                 else "unassigned")
            if (row.get("group_id") != visual["group_id"]
                    or row.get("official_number_candidate") != alias["official_number_candidate"]
                    or row.get("catalog_variant") != variant
                    or row.get("candidate_official_scan_id") != expected_id
                    or row.get("candidate_strength") != expected_strength
                    or row.get("physical_printing_status") != "unverified"
                    or row.get("offer_matching_status") != "blocked"
                    or row.get("price_series_merge_allowed") is not False
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("ai_visual_review_sha256", "")))
                    or not isinstance(row.get("source_snapshots_sha256"), dict)
                    or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in
                           row["source_snapshots_sha256"].values())):
                raise ValueError("scan candidate cannot establish physical printing or matching")
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            previous = db.execute("SELECT evidence_json FROM card_number_alias_scan_candidate WHERE card_id=?",
                                  (card_id,)).fetchone()
            if previous and previous["evidence_json"] != canonical:
                raise ValueError("existing scan candidate evidence differs")
            db.execute("INSERT OR IGNORE INTO card_number_alias_scan_candidate VALUES (?,?,?,?,?)",
                       (card_id, row["group_id"], expected_id, canonical,
                        datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"scan_candidates": imported}


def apply_secondary_candidates(db: sqlite3.Connection,
                               rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    expected_urls = {
        "https://www.hareruya2.com/en/pages/buying-list-sm",
        "https://shopping.fullcomp.jp/collections/p_sm10b",
    }
    with db:
        for row in rows:
            card = db.execute("SELECT * FROM card WHERE card_id=?", (row.get("card_id"),)).fetchone()
            if card is None or card["match_eligible"]:
                raise ValueError("secondary number candidate requires a blocked card")
            rule = number_conflicts.rule_for_card(
                db, card["language"], card["set_code"], card["collector_number"],
                card["provenance"])
            if (rule is None or row.get("rule_id") != rule["rule_id"]
                    or card["set_code"] != "SM10B"
                    or card["collector_number"].split("/")[0] not in
                    {str(n).zfill(3) for n in range(63, 70)}
                    or db.execute("SELECT 1 FROM card_number_alias_candidate WHERE card_id=?",
                                  (card["card_id"],)).fetchone()):
                raise ValueError("secondary number candidate is outside the official-search gap")
            candidate = card["collector_number"].split("/")[0] + "/" + rule["official_denominator"]
            rarity = "HR" if int(candidate[:3]) <= 66 else "UR"
            if (row.get("candidate_number") != candidate
                    or row.get("catalog_number") != card["collector_number"]
                    or row.get("source_provenance") != card["provenance"]
                    or compact_name(str(row.get("catalog_name", ""))) != compact_name(card["name"])
                    or row.get("rarity_label") != rarity
                    or row.get("evidence_class") != "two_independent_merchant_catalog_text"
                    or row.get("physical_printing_status") != "unverified"
                    or row.get("offer_matching_status") != "blocked"
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("official_search_gap_sha256", "")))):
                raise ValueError("secondary number candidate changed its card or evidence scope")
            sources = row.get("merchant_sources")
            if (not isinstance(sources, list) or len(sources) != 2
                    or {source.get("url") for source in sources} != expected_urls):
                raise ValueError("secondary number candidate needs two independent merchant catalogs")
            for source in sources:
                if (not re.fullmatch(r"[0-9a-f]{64}", str(source.get("page_sha256", "")))
                        or source.get("matched_number") != candidate
                        or compact_name(str(source.get("matched_name", ""))) != compact_name(card["name"])
                        or source.get("rarity_label") != rarity):
                    raise ValueError("secondary merchant evidence disagrees with the card")
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            old = db.execute("SELECT evidence_json FROM card_number_secondary_candidate WHERE card_id=?",
                             (card["card_id"],)).fetchone()
            if old and old["evidence_json"] != canonical:
                raise ValueError("existing secondary number evidence differs")
            db.execute("INSERT OR IGNORE INTO card_number_secondary_candidate VALUES (?,?,?,?,?)",
                       (card["card_id"], rule["rule_id"], candidate, canonical,
                        datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"secondary_candidates": imported}
