"""Resolve an exact Japanese card image from a pinned local card-source snapshot.

Images are fetched into memory for internal review only. No image is committed,
served, or treated as proof of a particular foil pattern or physical condition.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_official_url(url: str, *, image: bool) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.pokemon-card.com":
        return False
    if parsed.query or parsed.fragment:
        return False
    pattern = (r"/assets/images/card_images/large/[^/]+/[^/]+\.jpg"
               if image else r"/card-search/details\.php/card/[0-9]+")
    return re.fullmatch(pattern, parsed.path) is not None


class OfficialJPImageIndex:
    """Exact set/number/name lookup over a pinned PTCG-database checkout."""

    def __init__(self, repo: Path, revision: str):
        import subprocess

        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                         text=True).strip()
        if actual != revision or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Japanese card source checkout differs from pinned revision")
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--", "data_jp"], cwd=repo,
            text=True).strip()
        if dirty:
            raise ValueError("Japanese card source data differs from pinned commit")
        self.repo = repo
        self.revision = revision
        self.paths: dict[tuple[str, str], list[Path]] = {}
        for path in (repo / "data_jp").glob("*/*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            set_code = str(record.get("set_name", "")).upper()
            number = str(record.get("number", ""))
            if set_code and number:
                self.paths.setdefault((set_code, number.zfill(3)), []).append(path)

    def get(self, card_id: str, name: str) -> tuple[bytes | None, dict[str, Any]]:
        parts = card_id.split(":")
        if len(parts) != 4 or parts[0] != "ja" or "/" not in parts[2]:
            raise ValueError("expected Japanese card printing ID")
        set_code, number_total = parts[1].upper(), parts[2]
        number, total = number_total.split("/", 1)
        evidence: dict[str, Any] = {"status": "no_exact_official_record",
                                    "source_revision": self.revision}
        matches = []
        for path in self.paths.get((set_code, number.zfill(3)), []):
            raw = path.read_bytes()
            record = json.loads(raw)
            if (str(record.get("name")) != name
                    or str(record.get("set_total", "")).zfill(3) != total.zfill(3)
                    or str(record.get("set_name", "")).upper() != set_code
                    or not _valid_official_url(str(record.get("url", "")), image=False)
                    or not _valid_official_url(str(record.get("img", "")), image=True)):
                continue
            matches.append((path, raw, record))
        if len(matches) != 1:
            evidence["status"] = "ambiguous_official_record" if matches else "no_exact_official_record"
            return None, evidence
        path, raw, record = matches[0]
        image_url = record["img"]
        evidence.update({"card_url": record["url"], "image_url": image_url,
                         "record_path": str(path.relative_to(self.repo)),
                         "record_sha256": _sha(raw), "rarity_source": record.get("rarity")})
        try:
            request = urllib.request.Request(image_url, headers={
                "User-Agent": "pokemon-commerce-internal-review/1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                image = response.read(7_000_001)
            if len(image) > 7_000_000 or not image.startswith(b"\xff\xd8\xff"):
                evidence["status"] = "unsupported_image"
                return None, evidence
            evidence.update({"status": "included", "image_sha256": _sha(image),
                             "image_bytes": len(image), "mime_type": "image/jpeg"})
            return image, evidence
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            evidence.update({"status": "fetch_failed", "error_type": type(exc).__name__})
            return None, evidence
