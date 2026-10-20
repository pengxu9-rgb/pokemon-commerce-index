"""Shared contradiction checks for unverified marketplace grade evidence."""
from __future__ import annotations

import re
import unicodedata

from . import core

NUMERIC_GRADE = re.compile(
    r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)\s*(\d+(?:\.\d+)?)(?![\d.])", re.I)


def contradicts_grade(text: str, company: str, grade: str) -> bool:
    """Reject explicit conflicts; absence of a conflict is never verification."""
    text = unicodedata.normalize("NFKC", text)
    if core.BUNDLE_RE.search(text) or core.GRADE_UNSAFE_RE.search(text):
        return True
    named = {match.group().upper() for match in core.GRADER_RE.finditer(text)}
    numeric = [(match.group(1).upper(), match.group(2)) for match in NUMERIC_GRADE.finditer(text)]
    if company == "RAW":
        return bool(named or numeric or core.SLAB_EVIDENCE_RE.search(text)
                    or re.search(r"\b(?:graded|slab)\b", text, re.I))
    return bool((named and named != {company}) or len(numeric) > 1
                or any(value != (company, grade) for value in numeric)
                or re.search(r"\b(?:raw|ungraded)\b|未鑑定|鑑定前", text, re.I))
