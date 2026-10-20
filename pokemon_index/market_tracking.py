"""Read-only per-card native ask tracking. No marketplace, BNS or PSA transport."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

from . import core
from .marketplace_quality import contradicts_grade


def _quality(core, title, unit, card, metadata=None):
    title = unicodedata.normalize("NFKC", title)
    claims = list(core.GRADE_RE.finditer(title))
    company, grade = unit["grade_company"], unit["grade_value"]
    if core.BUNDLE_RE.search(title) or core.GRADE_UNSAFE_RE.search(title):
        raise ValueError("bundle or unsafe/aspirational grade claim")
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict):
        raise ValueError("malformed observation quality metadata")
    if any(metadata.get(key, False) is not False for key in
           ("certificate_verified", "authenticity_verified")):
        raise ValueError("source claims cannot establish certificate or authenticity verification")
    declared = (metadata.get("grade_company"), metadata.get("grade_value"))
    declared_grade = declared != (None, None)
    structured = declared_grade and metadata.get("grade_evidence") == "structured_seller_claim"
    if declared_grade:
        if (not all(isinstance(v, str) and v.strip() for v in declared)
                or (declared != ("RAW", "raw") and not core.GRADE_RE.fullmatch(" ".join(declared)))):
            raise ValueError("malformed structured grader and grade claim")
        if declared != (company, grade):
            raise ValueError("structured grade claim contradicts indexed unit")
    condition = metadata.get("seller_condition")
    if condition is not None and (not isinstance(condition, str) or not condition.strip()):
        raise ValueError("malformed seller condition claim")
    certificate = metadata.get("certificate_number_claim")
    if certificate is not None and (not isinstance(certificate, str) or not certificate.strip()):
        raise ValueError("malformed seller certificate-number claim")
    if company == "RAW":
        condition_text = unicodedata.normalize("NFKC", condition or "")
        if (claims or core.GRADER_RE.search(title) or core.SLAB_EVIDENCE_RE.search(title)
                or certificate is not None or contradicts_grade(condition_text, company, grade)):
            raise ValueError("current seller evidence does not support the raw unit")
        label = "raw; condition not assessed"
    else:
        if contradicts_grade(title, company, grade) or contradicts_grade(condition or "", company, grade):
            raise ValueError("seller condition contradicts indexed graded unit")
        named_graders = {match.group().upper() for match in core.GRADER_RE.finditer(title)}
        numeric_claims = {(match.group(1).upper(), match.group(2)) for match in re.finditer(
            r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)\s*(\d+(?:\.\d+)?)(?![\d.])", title, re.I)}
        if (len(claims) > 1 or (named_graders and named_graders != {company})
                or (numeric_claims and numeric_claims != {(company, grade)})
                or any((claim.group(1).upper(), claim.group(2)) != (company, grade) for claim in claims)
                or (not structured and (len(claims) != 1 or not core.SLAB_EVIDENCE_RE.search(title)))):
            raise ValueError("latest title does not support the indexed grader and grade")
        label = f"seller says {company} {grade}; certificate not verified"
    numbers = {core.normalize_collector_number(n) for n in core.NUMBER_RE.findall(title)}
    languages = {language for language, pattern in core.LANGUAGE_RE.items() if pattern.search(title)}
    if numbers and numbers != {card["collector_number"]}:
        raise ValueError("title contradicts indexed card number")
    if languages and languages != {card["language"]}:
        raise ValueError("title contradicts indexed card language")
    return {"label": label, "grade_company": company, "grade_value": grade,
            "grade_evidence": ("seller_structured_claim" if structured and company != "RAW" else
                               "seller_title_claim" if company != "RAW" else "no_grade_claim"),
            "seller_condition": condition,
            "condition_evidence": "seller_claim" if condition is not None else "not_assessed",
            "certificate_number_claim": certificate,
            "condition_bucket": unit["condition_bucket"], "physical_condition_assessed": False,
            "physical_inspection_performed": False,
            "certificate_verified": False, "authenticity_verified": False,
            "identity_evidence": "indexed_binding; not physical verification"}


def _observation_quality(db, source, native_id, observed_at):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marketplace_observation_quality'").fetchone():
        return None, None
    row = db.execute("""SELECT q.quality_json,q.evidence_ref,o.evidence_ref AS observation_evidence
        FROM marketplace_observation_quality q JOIN observation o
        ON (o.source,o.native_id,o.observed_at)=(q.source,q.native_id,q.observed_at)
        WHERE q.source=? AND q.native_id=? AND q.observed_at=?""", (source, native_id, observed_at)).fetchone()
    if row is None:
        return None, None
    if not isinstance(row["evidence_ref"], str) or not row["evidence_ref"].strip():
        raise ValueError("observation quality metadata lacks evidence reference")
    if row["evidence_ref"] != row["observation_evidence"]:
        raise ValueError("quality evidence differs from its exact observation")
    try:
        metadata = json.loads(row["quality_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed observation quality metadata") from exc
    if not isinstance(metadata, dict):
        raise ValueError("malformed observation quality metadata")
    if metadata.get("evidence_ref") != row["observation_evidence"]:
        raise ValueError("quality metadata evidence differs from its exact observation")
    return metadata, row["evidence_ref"]


def _money(price, currency):
    if type(price) is not int or not 0 <= price < 2**63 or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("missing or malformed native ask; no currency conversion performed")


def _url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("listing URL must be HTTPS without embedded credentials")


def _median_minor_decimal(prices):
    ordered = sorted(prices)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return str(ordered[middle])
    twice = ordered[middle - 1] + ordered[middle]
    return str(twice // 2) + (".5" if twice % 2 else "")


def _capture_coverage(db, source, card_id, instant, policy):
    """A saved page describes its declared query scope, never proven inventory coverage."""
    unknown = {"status": "not_recorded_for_this_card", "live_collection_verified": False}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marketplace_capture'").fetchone():
        return unknown
    rows = db.execute("""SELECT observed_at,request_json,coverage_json FROM marketplace_capture
        WHERE source=? ORDER BY observed_at DESC,capture_sha256 LIMIT 1001""", (source,)).fetchall()
    # Incomplete bounded scans must never appear as an empty search result.
    if len(rows) > 1000:
        return {**unknown, "status": "capture_scan_bound_exceeded"}
    cutoff = instant - timedelta(days=policy["retention_days"])
    matching = []
    for row in rows:
        at = core.parse_time(row["observed_at"])
        if not cutoff <= at <= instant:
            continue
        try:
            request, coverage = json.loads(row["request_json"]), json.loads(row["coverage_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed marketplace capture coverage") from exc
        if not isinstance(request, dict) or not isinstance(coverage, dict):
            raise ValueError("malformed marketplace capture coverage")
        if card_id in request.get("target_card_ids", []):
            matching.append((at, request, coverage))
    if not matching:
        return unknown
    newest = max(item[0] for item in matching)
    latest = [item for item in matching if item[0] == newest]
    return {"status": "capture_recorded_for_declared_target", "observed_at": newest.isoformat(),
            "captures_at_latest_time": len(latest),
            "request_kinds": sorted({item[1]["kind"] for item in latest}),
            "returned_rows_per_capture": [item[2]["returned_count"] for item in latest],
            "complete_page_count": sum(item[2]["page_complete"] is True for item in latest),
            "next_page_present": any(item[2].get("next_cursor") is not None for item in latest),
            "nonappearance_is_not_sold": True, "live_collection_verified": False}


def _report(db, core, card_id, now, history_days, sources):
    instant = core.parse_time(now or core.utcnow())
    stamp = instant.isoformat()
    core._require_card_display(db, card_id)
    card = dict(db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone())
    if not card["match_eligible"]:
        raise ValueError("card identity is not match-eligible")
    units = {u["unit_id"]: dict(u) for u in db.execute("SELECT * FROM priceable_unit WHERE card_id=?", (card_id,))}
    listings = db.execute("""SELECT * FROM listing l WHERE
        l.unit_id IN (SELECT unit_id FROM priceable_unit WHERE card_id=?) OR EXISTS (
            SELECT 1 FROM resolution_record r JOIN priceable_unit u ON r.unit_id=u.unit_id
            WHERE r.source=l.source AND r.native_id=l.native_id AND u.card_id=?)
        ORDER BY source,native_id LIMIT 501""", (card_id, card_id)).fetchall()
    if len(listings) > 500:
        raise ValueError("tracking bound exceeded: 500 listings per exact card")
    allowed, blocked = {}, []
    requested_sources = sorted(set(sources)) if sources else sorted({l["source"] for l in listings})
    for source in requested_sources:
        try:
            policy = dict(core._policy(db, source, display=True))
            if not policy["price_statistics_allowed"]:
                raise ValueError("source price statistics permission missing")
            if policy["expires_at"] and core.parse_time(policy["expires_at"]) <= instant:
                raise ValueError("source permission expired at report time")
            allowed[source] = policy
        except ValueError as exc:
            blocked.append({"source": source, "reason": str(exc)})
    if len(allowed) > 1 and any(not p["cross_source_use_allowed"] for p in allowed.values()):
        raise ValueError("cross-source tracking lacks permission")
    report = {"schema": "pokemon.native-market-tracking-offline.v1", "card_id": card_id,
              "as_of": stamp, "history_days": history_days, "price_type": "native_listing_ask",
              "platforms": [], "excluded": [], "blocked_sources": blocked,
              "requested_sources": requested_sources,
              "network_calls": 0, "bns_calls": 0, "quote_requested": False,
              "purchasable": False, "purchase_action": None, "order_created": False,
              "certificate_verified": False, "cross_platform_copy_deduplication": "not_available",
              "physical_quality_comparison_verified": False,
              "landed_cost": None, "fx_conversion": None,
              "definitions": {"listing_count": "distinct source/native IDs, not polls or physical copies",
                              "history": "listing observations attributed by resolution record effective timestamps; actual system knowledge time is not established",
                              "sold_out": "status observation, not payment evidence",
                              "money_units": "native integer units from source contract; no assumed exponent"}}
    event_count = 0
    for source, policy in sorted(allowed.items()):
        current = {o["native_id"]: o for o in core.offers(db, card_id, now=stamp, source_filter=source)}
        groups = {}
        panel = {"source": source, "listing_ttl_hours": policy["listing_ttl_hours"],
                 "groups": [], "listing_events": [],
                 "collection_coverage": _capture_coverage(db, source, card_id, instant, policy)}
        for listing in (l for l in listings if l["source"] == source):
            native_id = listing["native_id"]
            history = db.execute("SELECT * FROM observation WHERE source=? AND native_id=? ORDER BY observed_at DESC LIMIT 10001", (source, native_id)).fetchall()
            if len(history) > 10000:
                raise ValueError("tracking bound exceeded: 10000 observation rows per listing")
            resolutions = db.execute("SELECT * FROM resolution_record WHERE source=? AND native_id=? ORDER BY id LIMIT 10001", (source, native_id)).fetchall()
            if len(resolutions) > 10000:
                raise ValueError("tracking resolution bound exceeded")
            retained = instant - timedelta(days=min(history_days, policy["retention_days"]))
            events = sorted((r for r in history if retained <= core.parse_time(r["observed_at"]) <= instant),
                            key=lambda r: core.parse_time(r["observed_at"]))
            for row in events:
                event_count += 1
                if event_count > 10000:
                    raise ValueError("tracking bound exceeded: 10000 returned events")
                event = {key: row[key] for key in ("native_id", "observed_at", "status", "price_minor", "currency", "evidence_ref")}
                event.update(unit_id=None, unit_binding_status="unassigned_no_time_effective_binding")
                effective = [r for r in resolutions if core.parse_time(r["resolved_at"]) <= core.parse_time(row["observed_at"])]
                if effective:
                    at = max(core.parse_time(r["resolved_at"]) for r in effective)
                    bound = {r["unit_id"] for r in effective if core.parse_time(r["resolved_at"]) == at}
                    if len(bound) == 1 and next(iter(bound)) in units:
                        unit_id = next(iter(bound))
                        try:
                            metadata, quality_evidence = _observation_quality(db, source, native_id, row["observed_at"])
                            quality = _quality(core, row["title"], units[unit_id], card, metadata)
                            _money(row["price_minor"], row["currency"])
                            if policy["photo_resolution_required"] and not core._visual_approval(db, source, native_id, row["observed_at"], unit_id, stamp):
                                raise ValueError("exact observation lacks required photo approval")
                            event.update(unit_id=unit_id, unit_binding_status="time_effective_indexed_binding",
                                         quality=quality, quality_evidence_ref=quality_evidence)
                        except ValueError:
                            event["unit_binding_status"] = "unassigned_quality_or_photo_evidence"
                panel["listing_events"].append(event)
            offer = current.get(native_id)
            try:
                if offer is None:
                    raise ValueError("not a fresh, on-sale, display-permitted exact-unit offer")
                core._reject_held_unit(db, offer["unit_id"])
                unit = units[offer["unit_id"]]
                metadata, quality_evidence = _observation_quality(db, source, native_id, offer["last_seen"])
                quality = _quality(core, offer["title"], unit, card, metadata)
                _money(offer["current_price_minor"], offer["currency"])
                _url(offer["url"])
                if listing["last_seen"] != offer["last_seen"]:
                    raise ValueError("indexed listing is newer than selected observation")
                selected = next(r for r in history if r["observed_at"] == offer["last_seen"])
                for current_key, observed_key in (("title", "title"), ("url", "url"),
                        ("seller_native_id", "seller_native_id"), ("current_status", "status"),
                        ("current_price_minor", "price_minor")):
                    if listing[current_key] != selected[observed_key]:
                        raise ValueError("indexed listing conflicts with observation")
                key = (unit["unit_id"], offer["currency"])
                group = groups.setdefault(key, {**unit, "currency": offer["currency"], "offers": []})
                group["offers"].append({"native_id": native_id, "url": offer["url"],
                    "observed_at": offer["last_seen"], "price_minor": offer["current_price_minor"],
                    "currency": offer["currency"], "evidence_ref": selected["evidence_ref"],
                    "quality_evidence_ref": quality_evidence,
                    "observation_age_seconds": (instant-core.parse_time(offer["last_seen"])).total_seconds(),
                    "quality": quality})
            except (ValueError, KeyError, StopIteration) as exc:
                report["excluded"].append({"source": source, "native_id": native_id, "reason": str(exc)})
        for key, group in sorted(groups.items()):
            prices = [o["price_minor"] for o in group["offers"]]
            group.update(listing_count=len(prices), min_ask_minor=min(prices),
                         median_ask_minor_decimal=_median_minor_decimal(prices),
                         statistic_scope="native asks for the indexed seller-claim unit; physical quality unverified")
            panel["groups"].append(group)
        report["platforms"].append(panel)
    report["coverage"] = [{"source": p["source"], "unit_id": unit_id,
                           "status": "has_eligible_asks" if any(g["unit_id"] == unit_id for g in p["groups"])
                           else "no_eligible_asks_in_local_snapshot",
                           "live_search_coverage_verified": False}
                          for p in report["platforms"] for unit_id in sorted(units)]
    report["data_readiness"] = {"current_eligible_listing_count": sum(
        g["listing_count"] for p in report["platforms"] for g in p["groups"]),
        "sources_with_current_asks": sum(bool(p["groups"]) for p in report["platforms"]),
        "live_source_collection_verified": False, "quality_scope": "seller_claims_only"}
    return report


def build_report(database: Path, card_id: str, *, now: str | None = None,
                 history_days: int = 7, sources: list[str] | None = None) -> dict:
    if type(history_days) is not int or not 1 <= history_days <= 30:
        raise ValueError("history_days must be 1 through 30")
    if sources is not None and (not isinstance(sources, list) or not 1 <= len(sources) <= 8
                               or any(not isinstance(s, str) or not s.strip() for s in sources)):
        raise ValueError("sources must contain 1 through 8 source identifiers")
    path = Path(database).resolve()
    if not path.is_file():
        raise FileNotFoundError("existing local pilot database required; no database is created")
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return _report(db, core, card_id, now, history_days, sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--card-id", required=True)
    parser.add_argument("--history-days", type=int, default=7)
    parser.add_argument("--source", action="append", help="expected source ID; repeat to expose missing sources")
    args = parser.parse_args()
    print(json.dumps(build_report(args.db, args.card_id, history_days=args.history_days,
                                 sources=args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
