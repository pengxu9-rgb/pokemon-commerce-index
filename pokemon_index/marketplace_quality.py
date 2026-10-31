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

# Unsupported grading companies still contradict a different claimed grader.
# Recognizing their names here does not add a provider or admit their grades.
OTHER_GRADER = re.compile(
    r"(?<![A-Za-z])(TAG|SGC)\s*(?:\d+(?:\.\d+)?|graded|grading|slab)(?![A-Za-z0-9.])", re.I)
QUALIFIED_GRADE = re.compile(
    r"(?<![A-Za-z])(?:PSA|BGS|CGC|ARS|PGC)\s*(?:10|[1-9](?:\.5)?)\s*"
    r"(?:\(\s*(OC|ST|PD|OF|MK|MC)\s*\)|(OC|ST|PD|OF|MK|MC)(?![A-Za-z]))", re.I)


def special_grade_label(title, condition):
    """Preserve qualified/special claims instead of flattening to a number."""
    combined = title + " " + condition
    labels = set()
    for name, pattern in (("black_label", r"black\s*label|ブラックラベル"),
                          ("gold_label", r"gold\s*label|ゴールドラベル"),
                          ("pristine", r"\bpristine\b"),
                          ("perfect", r"\bperfect\s*10\b"),
                          ("authentic_altered", r"\bauthentic\s+altered\b")):
        if re.search(pattern, combined, re.I):
            labels.add(name)
    for match in QUALIFIED_GRADE.finditer(combined):
        labels.add("qualifier_" + (match.group(1) or match.group(2)).lower())
    # A structured seller condition may omit the grader name but still qualify
    # its numeric score. Do not scan arbitrary unbound two-letter title tokens.
    match = re.fullmatch(r"\s*(?:10|[1-9](?:\.5)?)\s*\(?\s*(OC|ST|PD|OF|MK|MC)\s*\)?\s*", condition, re.I)
    if match:
        labels.add("qualifier_" + match.group(1).lower())
    return " + ".join(sorted(labels)) or None


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
    special = special_grade_label(title, condition)
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
    named.update(match.group(1).upper() for match in OTHER_GRADER.finditer(text))
    numeric = [(match.group(1).upper(), match.group(2)) for match in NUMERIC_GRADE.finditer(text)]
    if company == "RAW":
        return bool(named or numeric or core.SLAB_EVIDENCE_RE.search(text)
                    or re.search(r"\b(?:graded|slab)\b", text, re.I))
    return bool((named and named != {company}) or len(numeric) > 1
                or any(value != (company, grade) for value in numeric)
                or re.search(r"\b(?:raw|ungraded)\b|未鑑定|鑑定前", text, re.I))
