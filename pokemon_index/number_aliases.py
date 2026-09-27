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
