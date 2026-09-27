"""Import source-bound artwork comparisons for unresolved Japanese groups."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable


def apply_evidence(db: sqlite3.Connection,
                   rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    with db:
        for row in rows:
            card = db.execute("SELECT * FROM card WHERE card_id=?",
                              (row.get("card_id"),)).fetchone()
            if (card is None or card["language"] != "ja"
                    or card["variant"] != "unverified_multi_record"
                    or card["match_eligible"]
                    or card["set_code"].upper() != row.get("set_code")
                    or card["collector_number"] != row.get("collector_number")
                    or row.get("physical_printing_status") != "unverified"
                    or row.get("offer_matching_status") != "blocked"
                    or row.get("price_series_merge_allowed") is not False):
                raise ValueError("multi-record scan evidence requires a blocked group card")
            records = row.get("source_records")
            if not isinstance(records, list) or len(records) < 2:
                raise ValueError("multi-record scan evidence needs official records")
            ids = [x.get("source_jp_id") for x in records]
            if ids != sorted(set(ids)):
                raise ValueError("official source record IDs must be unique and ordered")
            provenance = card["provenance"].split("|")
            # The frozen catalog provenance names each source record and hash.
            def valid_record(record: dict) -> bool:
                path = record.get("source_path", "")
                item = f"{path}:sha256:{record['source_record_sha256']}"
                return (isinstance(record.get("source_jp_id"), int)
                        and re.fullmatch(r"data_jp/[A-Za-z0-9-]+/[0-9]+\.json", path)
                        and path.split("/")[1].upper() == card["set_code"].upper()
                        and path.split("/")[-1] == f"{record['source_jp_id']}.json"
                        and re.fullmatch(r"[0-9a-f]{64}", str(record.get("source_record_sha256", "")))
                        and sum(p.endswith(item) for p in provenance) == 1)
            if (not all(valid_record(record) for record in records)
                    or len(provenance) != len(records)):
                raise ValueError("scan evidence does not match catalog source provenance")
            status = row.get("review_status")
            comparisons = row.get("comparisons_to_first_record")
            if status == "ai_visual_candidate":
                if (row.get("artwork_relation") != "exact_artwork"
                        or not isinstance(comparisons, list)
                        or len(comparisons) != len(ids) - 1
                        or [c.get("source_jp_id") for c in comparisons] != ids[1:]
                        or any(c.get("label") != "exact_artwork"
                               or not isinstance(c.get("possible_surface_or_stamp_difference"), bool)
                               or not str(c.get("visible_reason", "")).strip()
                               for c in comparisons)):
                    raise ValueError("incomplete scan artwork comparison")
            elif status == "image_unavailable":
                if row.get("artwork_relation") != "unresolved" or comparisons != []:
                    raise ValueError("missing-image scan cannot claim artwork relation")
            else:
                raise ValueError("unknown scan evidence status")
            images = row.get("image_sha256_by_source_id")
            if (not isinstance(images, list) or len(images) != len(ids)
                    or [item.get("source_jp_id") for item in images] != ids
                    or (status == "ai_visual_candidate" and any(
                        not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                        for item in images))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("model_review_sha256", "")))
                    or row.get("model") != "gemini-3.8-flash"):
                raise ValueError("scan evidence lacks pinned image review")
            sources = row.get("source_snapshots_sha256")
            if (not isinstance(sources, dict) or set(sources) !=
                    {"queue", "visual", "recovered"}
                    or any(not re.fullmatch(r"[0-9a-f]{64}", str(x)) for x in sources.values())):
                raise ValueError("scan evidence lacks pinned source snapshots")
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
            prior = db.execute("SELECT evidence_json FROM card_multi_record_scan_evidence WHERE card_id=?",
                               (card["card_id"],)).fetchone()
            if prior and prior["evidence_json"] != canonical:
                raise ValueError("existing multi-record scan evidence differs")
            db.execute("INSERT OR IGNORE INTO card_multi_record_scan_evidence VALUES (?,?,?,?)",
                       (card["card_id"], status, canonical,
                        datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"multi_record_scan_groups": imported}
