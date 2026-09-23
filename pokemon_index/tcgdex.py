"""Metadata-only adapter for a reviewed TCGdex Japanese set snapshot.

No card images, logos, artwork URLs, or rules text are imported. The operator
records the snapshot's rights reference and separately approves public display.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SET_RE = re.compile(r"^[A-Za-z0-9-]{1,24}$")


def normalize_japanese_set(payload: dict[str, Any], *, rights_reference: str,
                           display_approved: bool = False) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("TCGdex set response must be an object")
    set_code = payload.get("id")
    if not isinstance(set_code, str) or not SET_RE.fullmatch(set_code):
        raise ValueError("TCGdex set id is missing or invalid")
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("TCGdex set has no card briefs")
    if not rights_reference or not rights_reference.strip():
        raise ValueError("rights_reference is required")
    count = payload.get("cardCount") or {}
    official = count.get("official") if isinstance(count, dict) else None
    if official is not None and (type(official) is not int or official < 0):
        raise ValueError("cardCount.official must be nonnegative when present")
    if official == 0:
        official = None
    payload_sha = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    normalized = []
    identities = set()
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("TCGdex card brief must be an object")
        local_id = card.get("localId")
        name = card.get("name")
        source_id = card.get("id")
        if not isinstance(local_id, str) or not local_id.strip():
            raise ValueError("TCGdex card is missing localId")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("TCGdex card is missing name")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("TCGdex card is missing id")
        local_id = local_id.strip()
        if official is not None:
            width = max(3, len(local_id), len(str(official)))
            numerator = local_id.zfill(width) if local_id.isdigit() else local_id
            number = f"{numerator}/{str(official).zfill(width)}"
        else:
            number = local_id
        identity = (set_code.upper(), number)
        if identity in identities:
            raise ValueError(f"duplicate set and collector number: {identity}; curate a variant")
        identities.add(identity)
        normalized.append({
            "language": "ja",
            "set_code": set_code,
            "collector_number": number,
            "variant": "standard",
            "name": name.strip(),
            "provenance": f"tcgdex:v2:ja:sets/{set_code}:{source_id}:sha256:{payload_sha}",
            "rights_reference": rights_reference.strip(),
            "display_allowed": display_approved,
        })
    return normalized
