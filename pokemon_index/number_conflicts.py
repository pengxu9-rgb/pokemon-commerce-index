"""Source-bound collector-denominator conflicts that block exact offer matching."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

REQUIRED_FIELDS = ("language", "set_code", "catalog_denominator", "official_denominator",
                   "catalog_source_prefix", "official_source_revision",
                   "official_record_count", "official_record_manifest_sha256",
                   "official_pages", "reason")


def rule_id_for_evidence(row: dict[str, Any]) -> str:
    evidence = json.dumps({key: row[key] for key in REQUIRED_FIELDS},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "numconf:" + hashlib.sha256(evidence.encode()).hexdigest()[:24]


def _validate(row: dict[str, Any]) -> tuple[str, str]:
    if any(key not in row for key in REQUIRED_FIELDS):
        raise ValueError("number conflict rule lacks required evidence")
    if (row["language"] != "ja" or not re.fullmatch(r"[A-Z0-9-]+", row["set_code"])
            or not re.fullmatch(r"[0-9]{3}", row["catalog_denominator"])
            or not re.fullmatch(r"[0-9]{3}", row["official_denominator"])
            or row["catalog_denominator"] == row["official_denominator"]
            or not re.fullmatch(r"tcgdex:[0-9a-f]{40}:", row["catalog_source_prefix"])
            or not re.fullmatch(r"[0-9a-f]{40}", row["official_source_revision"])
            or not isinstance(row["official_record_count"], int)
            or row["official_record_count"] < 2
            or not re.fullmatch(r"[0-9a-f]{64}", row["official_record_manifest_sha256"])
            or not isinstance(row["reason"], str) or not row["reason"].strip()):
        raise ValueError("invalid number conflict rule scope")
    pages = row["official_pages"]
    if (not isinstance(pages, list) or len(pages) < 2
            or not all(isinstance(page, dict) for page in pages)
            or len({page.get("url") for page in pages}) != len(pages)):
        raise ValueError("number conflict rule needs two distinct official pages")
    for page in pages:
        if (not isinstance(page, dict)
                or not re.fullmatch(r"https://www\.pokemon-card\.com/card-search/details\.php/card/[0-9]+",
                                    str(page.get("url", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(page.get("page_sha256", "")))
                or not re.fullmatch(r"[0-9]{3}/[0-9]{3}", str(page.get("collector_number", "")))
                or page["collector_number"].split("/")[1] != row["official_denominator"]):
            raise ValueError("official page evidence does not support denominator")
    evidence = json.dumps({key: row[key] for key in REQUIRED_FIELDS}, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
    rule_id = rule_id_for_evidence(row)
    if row.get("rule_id") != rule_id:
        raise ValueError("number conflict rule ID differs from evidence")
    return rule_id, evidence


def rule_for_card(db: sqlite3.Connection, language: str, set_code: str,
                  collector_number: str, provenance: str) -> dict[str, Any] | None:
    denominator = collector_number.split("/", 1)[-1] if "/" in collector_number else ""
    row = db.execute("""SELECT * FROM card_number_conflict_rule
        WHERE language=? AND set_code=? AND catalog_denominator=?
          AND ? LIKE catalog_source_prefix || '%' LIMIT 1""",
        (language.lower(), set_code.upper(), denominator, provenance)).fetchone()
    return dict(row) if row else None


def apply_rules(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rules, affected = 0, 0
    with db:
        for row in rows:
            rule_id, evidence = _validate(row)
            existing = db.execute("SELECT * FROM card_number_conflict_rule WHERE rule_id=?",
                                  (rule_id,)).fetchone()
            if existing:
                if existing["evidence_ref"] != evidence:
                    raise ValueError("existing number conflict rule differs")
            else:
                db.execute("""INSERT INTO card_number_conflict_rule VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        rule_id, row["language"], row["set_code"],
                        row["catalog_denominator"], row["official_denominator"],
                        row["catalog_source_prefix"], row["official_source_revision"],
                        row["official_record_count"],
                        row["official_record_manifest_sha256"], evidence,
                        row["reason"], datetime.now(timezone.utc).isoformat()))
            result = db.execute("""UPDATE card SET match_eligible=0
                WHERE language=? AND set_code=?
                  AND substr(collector_number,instr(collector_number,'/')+1)=?
                  AND provenance LIKE ? AND match_eligible=1""",
                (row["language"], row["set_code"], row["catalog_denominator"],
                 row["catalog_source_prefix"] + "%"))
            affected += result.rowcount
            rules += 1
    return {"rules": rules, "cards_disabled": affected}
