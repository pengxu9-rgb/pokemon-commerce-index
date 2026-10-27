"""Bounded contradiction cues; text can withhold a match, never prove one."""
from __future__ import annotations

import re

# Only the immediate claim context is inspected. This is deliberately a
# conservative review signal, not general-language or authenticity analysis.
_NEGATIVE_PREFIX = re.compile(
    r"(?:\b(?:not|non|no|without|except|excluding|isn\s*t|aren\s*t|wasn\s*t|doesn\s*t)\b"
    r"[\s:‐‑–—-]*(?:(?:a|an|the|any|actually|original|genuine|graded|certified|slabbed|stamped|have|in|as|by)\s+){0,3}"
    r"|(?:非|不是|并非|並非|没有|沒有|無|无)\s*)$", re.I)
_NEGATIVE_SUFFIX = re.compile(
    r"^[\s?!,:;‐‑–—-]*(?:(?:is\s+|was\s+)?(?:not\b|no\s*$)|isn\s*t\b|wasn\s*t\b|doesn\s*t\b|では(?:ない|ありません|無い)|じゃない)", re.I)


def negated_cue(text: str, start: int, end: int) -> bool:
    """A recognized token immediately negated in either direction needs review."""
    # Wrapping/quoting punctuation cannot turn an immediate negation into a
    # positive claim (e.g. NOT (PSA10), non-"English", or 1st edition [not]).
    # Preserve words/digits so negation of some other intervening claim does not
    # become negation of this one.
    prefix = re.sub(r"[\W_]+", " ", text[max(0, start - 80):start])
    suffix = re.sub(r"[\W_]+", " ", text[end:end + 40])
    return bool(_NEGATIVE_PREFIX.search(prefix) or _NEGATIVE_SUFFIX.search(suffix))
