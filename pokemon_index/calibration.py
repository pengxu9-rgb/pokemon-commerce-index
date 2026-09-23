"""Evaluate discovery coverage against an authorized seller or marketplace truth panel."""

from __future__ import annotations

from math import sqrt
from statistics import median
from typing import Any, Iterable

from .core import _policy, parse_time


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def evaluate(db, panel_sales: Iterable[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, list[int] | int]] = {}
    seen = set()
    for sale in panel_sales:
        for field in ("source", "native_id", "sold_at", "last_price_minor", "bucket"):
            if sale.get(field) in (None, ""):
                raise ValueError(f"panel sale missing {field}")
        _policy(db, sale["source"])
        sold_at = parse_time(sale["sold_at"]).isoformat()
        key = (sale["source"], sale["native_id"], sold_at)
        if key in seen:
            continue
        seen.add(key)
        if type(sale["last_price_minor"]) is not int or sale["last_price_minor"] < 0:
            raise ValueError("panel last_price_minor must be a nonnegative integer")
        discovery = db.execute(
            """SELECT 1 FROM observation WHERE source=? AND native_id=?
            AND poll_reason='discovery' AND status='on_sale' AND observed_at<? LIMIT 1""",
            (sale["source"], sale["native_id"], sold_at),
        ).fetchone()
        bucket = buckets.setdefault(sale["bucket"], {"caught": [], "missed": []})
        group = "caught" if discovery else "missed"
        bucket[group].append(int(sale["last_price_minor"]))
    result = {}
    for name, bucket in buckets.items():
        caught, missed = bucket["caught"], bucket["missed"]
        total = len(caught) + len(missed)
        result[name] = {
            "panel_sales": total,
            "observed_before_sale": len(caught),
            "missed_sales": len(missed),
            "coverage": len(caught) / total,
            "coverage_wilson_95": wilson_interval(len(caught), total),
            "missed_to_caught_median_price_ratio": median(missed) / median(caught)
            if caught and missed and median(caught) else None,
            "ratio_note": "descriptive only; panel selection and list-versus-paid price may bias it",
        }
    return {"buckets": result, "total_panel_sales": len(seen)}


def gate1_decision(report: dict[str, Any], *, sold_detail_has_price: bool | None,
                   required_calls_per_day: int | None,
                   quota_calls_per_day: int | None,
                   min_hot_sales: int | None = None,
                   min_mid_sales: int | None = None) -> dict[str, Any]:
    """Apply the pre-agreed sweep-fidelity thresholds; absence is inconclusive."""
    if sold_detail_has_price is not None and type(sold_detail_has_price) is not bool:
        raise ValueError("sold_detail_has_price must be true, false, or null")
    for label, value in (("required_calls_per_day", required_calls_per_day),
                         ("quota_calls_per_day", quota_calls_per_day),
                         ("min_hot_sales", min_hot_sales),
                         ("min_mid_sales", min_mid_sales)):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"{label} must be a positive integer or null")
    hot = report.get("buckets", {}).get("hot")
    mid = report.get("buckets", {}).get("mid")
    reasons = []
    if sold_detail_has_price is False:
        reasons.append("sold item detail has no price")
    if required_calls_per_day is not None and quota_calls_per_day is not None:
        if required_calls_per_day > quota_calls_per_day:
            reasons.append("gateway quota cannot sustain measured cadence")
    if reasons:
        return {"decision": "no_go_clear_price", "reasons": reasons,
                "publish": ["ask", "landed_quote"]}
    missing = []
    if not hot or not hot["panel_sales"]:
        missing.append("hot seller-panel sales")
    if not mid or not mid["panel_sales"]:
        missing.append("mid seller-panel sales")
    if sold_detail_has_price is None:
        missing.append("sold-item price probe")
    if required_calls_per_day is None or quota_calls_per_day is None:
        missing.append("measured daily calls and gateway quota")
    if min_hot_sales is None or min_mid_sales is None:
        missing.append("power-analysis minimum panel sales for hot and mid buckets")
    elif (hot and hot["panel_sales"] < min_hot_sales) or (mid and mid["panel_sales"] < min_mid_sales):
        missing.append("seller-panel sale counts below power-analysis minimum")
    if missing:
        return {"decision": "insufficient_evidence", "reasons": missing,
                "publish": ["ask", "landed_quote"]}
    if hot["coverage"] < 0.70:
        return {"decision": "no_go_clear_price",
                "reasons": ["hot observed-before-sale coverage below 70% after sample-size gate"],
                "publish": ["ask", "landed_quote"]}
    bias_ratios = {bucket: report["buckets"][bucket]["missed_to_caught_median_price_ratio"]
                   for bucket in ("hot", "mid")}
    if (hot["coverage"] >= 0.85 and mid["coverage"] >= 0.70
            and all(ratio is not None and 0.95 <= ratio <= 1.05
                    for ratio in bias_ratios.values())):
        return {"decision": "go_clear_price_candidate",
                "reasons": ["point estimates meet Gate 1 thresholds; review panel representativeness"],
                "bias_ratios": bias_ratios,
                "publish": ["ask", "landed_quote", "last_list_at_transition"]}
    missed = sum(bucket["missed_sales"] for bucket in report["buckets"].values())
    if hot["coverage"] >= 0.70 and missed >= 30 and bias_ratios["hot"] is not None:
        return {"decision": "conditional_corrected_only",
                "reasons": ["publish only a corrected, coverage-labelled transition series after method review"],
                "missed_sales": missed, "bias_ratios": bias_ratios,
                "publish": ["ask", "landed_quote"]}
    return {"decision": "insufficient_evidence",
            "reasons": ["Gate 1 go or conditional criteria not established"],
            "missed_sales": missed, "bias_ratios": bias_ratios,
            "publish": ["ask", "landed_quote"]}
