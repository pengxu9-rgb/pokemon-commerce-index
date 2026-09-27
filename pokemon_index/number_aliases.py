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
