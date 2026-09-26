"""Find a card-specific English TCGdex scan when the detail API is unavailable.

The CDN path is only a candidate until a visual model checks the printed name
and collector number. No image bytes are persisted by this module.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def candidate_url(card_id: str, provenance: str) -> str:
    parts = card_id.split(":")
    if len(parts) != 4 or parts[0] != "en":
        raise ValueError("expected English card ID")
    set_code = parts[1].lower()
    family = next((prefix for prefix in ("swsh", "sm", "sv", "me", "xy", "bw")
                   if set_code.startswith(prefix)), None)
    if family is None or not re.fullmatch(r"[a-z0-9.]+", set_code):
        raise ValueError("unsupported English card set for asset discovery")
    if ":sha256:" not in provenance:
        raise ValueError("source provenance lacks a hash")
    source_path = provenance.split(":sha256:", 1)[0].split(":", 2)[-1]
    local_id = Path(source_path).stem
    printed_number = parts[2].split("/", 1)[0]
    if local_id.casefold() != printed_number.casefold() or not re.fullmatch(
            r"[A-Za-z0-9]+", local_id):
        raise ValueError("source filename does not match card number")
    asset_set = set_code[:-2] if set_code.endswith("tg") else set_code
    return f"https://assets.tcgdex.net/en/{family}/{asset_set}/{local_id}/high.webp"


def fetch(card_id: str, provenance: str) -> tuple[bytes | None, dict[str, Any]]:
    evidence: dict[str, Any] = {"status": "asset_unavailable",
                                "source": "convention_asset_discovery"}
    try:
        url = candidate_url(card_id, provenance)
        evidence["image_url"] = url
        request = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-commerce-internal-review/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            image = response.read(7_000_001)
        if (len(image) > 7_000_000 or image[:4] != b"RIFF"
                or image[8:12] != b"WEBP"):
            evidence["status"] = "unsupported_image"
            return None, evidence
        evidence.update({"status": "included", "image_sha256": hashlib.sha256(image).hexdigest(),
                         "image_bytes": len(image), "identity_check_required": True})
        return image, evidence
    except (ValueError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            http.client.HTTPException, OSError) as exc:
        evidence.update({"status": "fetch_failed", "error_type": type(exc).__name__})
        return None, evidence
