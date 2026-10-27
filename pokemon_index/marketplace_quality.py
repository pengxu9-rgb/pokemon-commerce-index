"""Shared contradiction checks for unverified marketplace grade evidence."""
from __future__ import annotations

import re
import unicodedata

from . import core
from .claim_text import negated_cue

NUMERIC_GRADE = re.compile(
    r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)\s*(\d+(?:\.\d+)?)(?![\d.])", re.I)

GRADE_EVIDENCE = {"snkr_used_condition", "structured_seller_claim", "structured_raw_claim",
                  "seller_title_claim", "no_grade_claim", "ambiguous_seller_title_claim"}
REVIEW_REASONS = {"grade_not_reported", "ambiguous_grade_claim", "conflicting_grade_claims",
                  "source_review_required", "special_grade_label_requires_review"}


def grade_details(company, value, *, title="", condition=None, evidence=None,
                  raw_claim=False, source_review=False):
    """Display a seller claim and its limitations, never authenticate a card."""
    title = unicodedata.normalize("NFKC", str(title))
    condition = unicodedata.normalize("NFKC", str(condition or ""))
    reasons = set()
    kind = "slab" if company and value else "raw" if raw_claim else "unknown"
    if raw_claim and company:
        reasons.add("conflicting_grade_claims")
    if kind == "unknown":
        reasons.add("grade_not_reported")
    if source_review:
        reasons.add("source_review_required")
    special = ("black_label" if re.search(r"black\s*label|ブラックラベル", title + " " + condition, re.I)
               else "pristine" if re.search(r"\bpristine\b", title + " " + condition, re.I) else None)
    if special:
        reasons.add("special_grade_label_requires_review")
    for text in (title, condition):
        if not text:
            continue
        # Explicit RAW is evidence of form, not an inferred low grade. Do not
        # treat its literal 'ungraded' label as a PSA candidate warning.
        raw_label = bool(re.fullmatch(r"raw|ungraded|未鑑定|鑑定前", text.strip(), re.I))
        if core.GRADE_UNSAFE_RE.search(text) and not (raw_claim and raw_label):
            reasons.add("ambiguous_grade_claim")
        if contradicts_grade(text, company or "RAW", value or "raw"):
            reasons.add("conflicting_grade_claims")
    basis = evidence if evidence in GRADE_EVIDENCE else (
        "structured_raw_claim" if raw_claim else "structured_seller_claim" if company else "no_grade_claim")
    return {"company": company, "value": value, "certificate_verified": False,
            "kind": kind, "evidence": basis, "review_required": bool(reasons),
            "review_reasons": sorted(reasons), "special_label": special}


def contradicts_grade(text: str, company: str, grade: str) -> bool:
    """Reject explicit conflicts; absence of a conflict is never verification."""
    text = unicodedata.normalize("NFKC", text)
    if core.BUNDLE_RE.search(text) or core.GRADE_UNSAFE_RE.search(text):
        return True
    if any(negated_cue(text, *match.span()) for pattern in (NUMERIC_GRADE, core.GRADER_RE)
           for match in pattern.finditer(text)):
        return True
    named = {match.group().upper() for match in core.GRADER_RE.finditer(text)}
    numeric = [(match.group(1).upper(), match.group(2)) for match in NUMERIC_GRADE.finditer(text)]
    if company == "RAW":
        return bool(named or numeric or core.SLAB_EVIDENCE_RE.search(text)
                    or re.search(r"\b(?:graded|slab)\b", text, re.I))
    return bool((named and named != {company}) or len(numeric) > 1
                or any(value != (company, grade) for value in numeric)
                or re.search(r"\b(?:raw|ungraded)\b|未鑑定|鑑定前", text, re.I))
