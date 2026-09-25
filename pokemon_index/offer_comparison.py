"""Evidence-bound listing photo review and cross-region landed ask comparison.

The result is a comparison of current offers, never a pooled card price index
or a verified sale. Listing images and review outputs are append-only inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable
from urllib.parse import urlparse

from . import core

SHA = re.compile(r"[0-9a-f]{64}")
FAMILIES = {"google", "openai", "anthropic"}
EVIDENCE_PREFIX = {"google": "vertex", "openai": "openai", "anthropic": "anthropic"}
CONDITIONS = {"mint", "near_mint", "light_played", "moderate_played",
              "heavy_played", "damaged"}


def _https_ref(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


def import_media(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with db:
        for row in rows:
            core._required(row, "source", "native_id", "observed_at", "front_ref",
                           "front_sha256", "rights_reference")
            policy = core._policy(db, row["source"])
            if not policy["media_ai_allowed"]:
                raise ValueError("source lacks media AI permission")
            at = core.parse_time(row["observed_at"]).isoformat()
            observation = db.execute(
                "SELECT 1 FROM observation WHERE source=? AND native_id=? AND observed_at=?",
                (row["source"], row["native_id"], at)).fetchone()
            if not observation:
                raise ValueError("media must bind to an imported listing observation")
            front, back = row["front_sha256"], row.get("back_sha256")
            if (not SHA.fullmatch(str(front)) or (back is not None and not SHA.fullmatch(str(back)))
                    or not _https_ref(row["front_ref"])
                    or (row.get("back_ref") and not _https_ref(row["back_ref"]))
                    or bool(row.get("back_ref")) != bool(back)):
                raise ValueError("media needs valid HTTPS refs and matching image hashes")
            values = (row["source"], row["native_id"], at, row["front_ref"], front,
                      row.get("back_ref"), back, row["rights_reference"])
            existing = db.execute(
                """SELECT source,native_id,observed_at,front_ref,front_sha256,back_ref,
                back_sha256,rights_reference FROM offer_media_snapshot
                WHERE source=? AND native_id=? AND observed_at=?""", values[:3]).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise ValueError("media evidence changed for an existing observation")
                continue
            db.execute("INSERT INTO offer_media_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (*values, core.utcnow()))
            count += 1
    return count


def import_visual_reviews(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with db:
        for row in rows:
            core._required(row, "review_id", "source", "native_id", "observed_at",
                           "card_id", "model_family", "model_version", "reviewed_at",
                           "front_sha256", "identity_decision", "finish_decision",
                           "condition_decision", "evidence_ref", "rationale")
            policy = core._policy(db, row["source"])
            if not policy["media_ai_allowed"]:
                raise ValueError("source lacks media AI permission")
            at = core.parse_time(row["observed_at"]).isoformat()
            reviewed = core.parse_time(row["reviewed_at"]).isoformat()
            if reviewed < at:
                raise ValueError("visual review precedes its listing observation")
            snapshot = db.execute(
                """SELECT front_sha256,back_sha256 FROM offer_media_snapshot
                WHERE source=? AND native_id=? AND observed_at=?""",
                (row["source"], row["native_id"], at)).fetchone()
            if not snapshot or (row["front_sha256"], row.get("back_sha256")) != tuple(snapshot):
                raise ValueError("visual review does not bind to the current image hashes")
            listing = db.execute(
                """SELECT u.card_id FROM listing l LEFT JOIN priceable_unit u ON u.unit_id=l.unit_id
                WHERE l.source=? AND l.native_id=?""",
                (row["source"], row["native_id"])).fetchone()
            if not listing or not db.execute("SELECT 1 FROM card WHERE card_id=?",
                                             (row["card_id"],)).fetchone():
                raise ValueError("visual review has an unknown listing or card")
            if listing["card_id"] is not None and listing["card_id"] != row["card_id"]:
                raise ValueError("visual review card conflicts with resolved listing identity")
            family = row["model_family"].casefold()
            if (family not in FAMILIES or row["identity_decision"] not in
                    {"match", "mismatch", "uncertain"} or row["finish_decision"] not in
                    {"match", "mismatch", "uncertain"} or row["condition_decision"] not in
                    {"assessed", "uncertain"}):
                raise ValueError("invalid AI review decision or model family")
            if not re.fullmatch(
                    re.escape(EVIDENCE_PREFIX[family]) + r":response-sha256:[0-9a-f]{64}",
                    str(row["evidence_ref"])):
                raise ValueError("AI review lacks provider-bound response hash")
            finish = row.get("observed_finish")
            condition = row.get("condition_bucket")
            if (finish is not None and not re.fullmatch(r"[a-z0-9_]{2,64}", finish)):
                raise ValueError("invalid observed finish")
            if (row["finish_decision"] == "match" and not finish):
                raise ValueError("matched finish needs an observed finish code")
            if (condition is not None and condition not in CONDITIONS):
                raise ValueError("invalid condition bucket")
            if (row["condition_decision"] == "assessed"
                    and (not snapshot["back_sha256"] or not condition)):
                raise ValueError("condition assessment needs front and back evidence")
            values = (row["review_id"], row["source"], row["native_id"], at,
                      row["card_id"], family, row["model_version"], reviewed,
                      row["front_sha256"], row.get("back_sha256"),
                      row["identity_decision"], finish, row["finish_decision"],
                      condition, row["condition_decision"], row["evidence_ref"],
                      row["rationale"])
            existing = db.execute("SELECT * FROM offer_visual_review WHERE review_id=?",
                                  (row["review_id"],)).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise ValueError("visual review ID reused with different evidence")
                continue
            db.execute("INSERT INTO offer_visual_review VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       values)
            count += 1
    return count


def visual_gate(db: sqlite3.Connection, source: str, native_id: str,
                observed_at: str, card_id: str) -> dict[str, Any]:
    if not core._policy(db, source)["media_ai_allowed"]:
        return {"status": "blocked_permission", "reason": "media AI permission is disabled"}
    at = core.parse_time(observed_at).isoformat()
    media = db.execute(
        """SELECT * FROM offer_media_snapshot
        WHERE source=? AND native_id=? AND observed_at=?""",
        (source, native_id, at)).fetchone()
    if media is None:
        return {"status": "need_photos", "reason": "no source-authorized photo snapshot"}
    rows = db.execute(
        """SELECT * FROM offer_visual_review WHERE source=? AND native_id=?
        AND observed_at=? AND card_id=? ORDER BY reviewed_at DESC, rowid DESC""",
        (source, native_id, at, card_id)).fetchall()
    by_family = {}
    for row in rows:
        by_family.setdefault(row["model_family"], row)
    if len(by_family) < 2:
        return {"status": "need_independent_ai", "review_families": sorted(by_family),
                "reason": "two distinct model families are required"}
    reviews = list(by_family.values())
    identity = {r["identity_decision"] for r in reviews}
    finish = {r["finish_decision"] for r in reviews}
    if identity == {"mismatch"} or finish == {"mismatch"}:
        return {"status": "exclude", "reason": "independent reviews agree listing identity or finish differs"}
    if "mismatch" in identity | finish and "match" in identity | finish:
        return {"status": "exception_review", "reason": "AI identity or finish findings conflict"}
    if identity != {"match"} or finish != {"match"}:
        return {"status": "need_photos", "reason": "identity or finish remains uncertain"}
    finishes = {r["observed_finish"] for r in reviews}
    if len(finishes) != 1:
        return {"status": "exception_review", "reason": "AI finish detail conflicts"}
    if not media["back_sha256"]:
        return {"status": "need_photos", "reason": "back photo needed for raw condition"}
    conditions = {r["condition_bucket"] for r in reviews if r["condition_decision"] == "assessed"}
    if any(r["condition_decision"] != "assessed" for r in reviews):
        return {"status": "need_photos", "reason": "condition evidence is insufficient"}
    if len(conditions) != 1:
        return {"status": "exception_review", "reason": "AI condition buckets conflict"}
    return {"status": "ready", "card_id": card_id, "observed_finish": finishes.pop(),
            "condition_bucket": conditions.pop(), "review_families": sorted(by_family),
            "image_hashes": {"front": media["front_sha256"], "back": media["back_sha256"]},
            "review_ids": sorted(r["review_id"] for r in reviews),
            "scope": "AI-assisted raw condition bucket; no grader score or authenticity claim"}


def _latest_artwork_edge(db: sqlite3.Connection, ja_card_id: str,
                         en_card_id: str) -> sqlite3.Row | None:
    left, right = sorted((ja_card_id, en_card_id))
    return db.execute(
        """SELECT * FROM card_relationship_assertion
        WHERE left_card_id=? AND right_card_id=? AND relation_type='same_artwork'
        ORDER BY rowid DESC LIMIT 1""", (left, right)).fetchone()


def _quote_ready(offer: dict[str, Any]) -> bool:
    quote = offer.get("quote")
    if not quote or offer["current_price_minor"] is None:
        return False
    assumptions = quote["assumptions"]
    return (type(assumptions.get("source_price_minor")) is int
            and assumptions["source_price_minor"] == offer["current_price_minor"]
            and assumptions.get("source_currency") == offer["currency"]
            and all(isinstance(assumptions.get(key), str) and assumptions[key].strip()
                    for key in ("fx_rate_ref", "fee_schedule_ref", "tax_basis")))


def compare_landed_asks(db: sqlite3.Connection, ja_card_id: str, en_card_id: str,
                        destination: str, now: str | None = None) -> dict[str, Any]:
    """Compare best current landed asks per identical photographed finish/condition.

    A cross-language gap is contextual and cannot be treated as a clearing
    price, a same-SKU index, or an arbitrage recommendation.
    """
    if not ja_card_id.startswith("ja:") or not en_card_id.startswith("en:"):
        raise ValueError("comparison needs Japanese and English card IDs")
    if not destination:
        raise ValueError("destination required")
    edge = _latest_artwork_edge(db, ja_card_id, en_card_id)
    if not edge or edge["review_status"] not in {"proposed", "verified"}:
        return {"status": "blocked", "reason": "no current source-backed same-artwork relation"}
    if edge["review_status"] == "proposed" and edge["asserted_by"] != "ai-artwork-review-v1":
        return {"status": "blocked", "reason": "same-artwork proposal lacks AI image audit"}
    instant = core.parse_time(now or core.utcnow()).isoformat()
    sides = {}
    for language, card_id in (("ja", ja_card_id), ("en", en_card_id)):
        offers = core.offers(db, card_id, destination, instant)
        eligible = []
        blocked = {}
        for offer in offers:
            policy = core._policy(db, offer["source"], display=True)
            if not policy["cross_region_use_allowed"]:
                blocked["source_permission"] = blocked.get("source_permission", 0) + 1
                continue
            if offer["grade_company"] != "RAW" or offer["grade_value"] != "raw":
                blocked["graded_card"] = blocked.get("graded_card", 0) + 1
                continue
            if not _quote_ready(offer):
                blocked["missing_bound_quote"] = blocked.get("missing_bound_quote", 0) + 1
                continue
            gate = visual_gate(db, offer["source"], offer["native_id"],
                               offer["last_seen"], card_id)
            if gate["status"] != "ready":
                key = "visual_" + gate["status"]
                blocked[key] = blocked.get(key, 0) + 1
                continue
            eligible.append((offer, gate))
        sides[language] = {"eligible": eligible, "blocked": blocked,
                           "active_offers": len(offers)}
    all_sources = {offer["source"] for side in sides.values()
                   for offer, _ in side["eligible"]}
    if len(all_sources) > 1 and any(not core._policy(db, source)["cross_source_use_allowed"]
                                    for source in all_sources):
        return {"status": "blocked", "reason": "cross-source comparison lacks permission"}
    grouped = {}
    for lang, side in sides.items():
        for offer, gate in side["eligible"]:
            key = (gate["observed_finish"], gate["condition_bucket"],
                   offer["quote"]["currency"])
            grouped.setdefault(key, {}).setdefault(lang, []).append((offer, gate))
    comparisons = []
    for (finish, condition, currency), group in sorted(grouped.items()):
        if set(group) != {"ja", "en"}:
            continue
        best = {lang: min(group[lang], key=lambda pair: pair[0]["quote"]["total_minor"])
                for lang in ("ja", "en")}
        ja, en = best["ja"][0]["quote"]["total_minor"], best["en"][0]["quote"]["total_minor"]
        if ja <= 0:
            continue
        def median_landed(lang: str) -> Decimal:
            prices = sorted(pair[0]["quote"]["total_minor"] for pair in group[lang])
            middle = len(prices) // 2
            return (Decimal(prices[middle]) if len(prices) % 2 else
                    (Decimal(prices[middle - 1]) + Decimal(prices[middle])) / 2)
        ja_median, en_median = median_landed("ja"), median_landed("en")
        percent_bps = int((Decimal(en - ja) * Decimal(10000) / Decimal(ja))
                          .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        median_percent_bps = (int(((en_median - ja_median) * Decimal(10000) / ja_median)
                                  .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                              if ja_median > 0 else None)
        def summarize(lang: str) -> dict[str, Any]:
            offer, gate = best[lang]
            return {"source": offer["source"], "native_id": offer["native_id"],
                    "url": offer["url"], "observed_at": offer["last_seen"],
                    "landed_minor": offer["quote"]["total_minor"],
                    "quote_expires_at": offer["quote"]["expires_at"],
                    "quote_evidence_ref": offer["quote"]["evidence_ref"],
                    "visual_review_ids": gate["review_ids"],
                    "image_hashes": gate["image_hashes"],
                    "n_eligible_in_bucket": len(group[lang])}
        comparisons.append({"finish": finish, "condition_bucket": condition,
                            "currency": currency, "ja": summarize("ja"),
                            "en": summarize("en"), "en_minus_ja_minor": en - ja,
                            "en_minus_ja_percent_bps": percent_bps,
                            "ja_median_landed_minor": str(ja_median),
                            "en_median_landed_minor": str(en_median),
                            "median_en_minus_ja_minor": str(en_median - ja_median),
                            "median_en_minus_ja_percent_bps": median_percent_bps})
    return {"status": "ready" if comparisons else "insufficient_evidence",
            "ja_card_id": ja_card_id, "en_card_id": en_card_id,
            "destination": destination, "as_of": instant,
            "comparison_type": "contextual_landed_ask_spread",
            "artwork_assertion_id": edge["assertion_id"],
            "comparisons": comparisons,
            "sides": {lang: {key: val for key, val in side.items() if key != "eligible"}
                      for lang, side in sides.items()},
            "interpretation": "Different-language printings remain separate; this is a current-offer cost gap, not a sale price or same-SKU index."}
