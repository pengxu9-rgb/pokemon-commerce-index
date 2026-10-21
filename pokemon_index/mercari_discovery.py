"""Public Mercari resource hints supply coordinates only, never listing facts."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit


def preload_product_urls(scripts):
    """Decode exact React Flight high-priority first-image hints without JS.

    Every candidate still needs robots permission and a complete, query-matching
    product page. A thumbnail supplies neither price nor availability/identity.
    """
    if not isinstance(scripts, (list, tuple)) or len(scripts) > 200:
        return ()
    chunks = []
    size = 0
    for script in scripts:
        if not isinstance(script, str):
            continue
        size += len(script)
        if size > 1_000_000:
            return ()
        match = re.fullmatch(r"\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*", script, re.S)
        if not match:
            continue
        try:
            chunk = json.loads(match[1])
        except (ValueError, RecursionError):
            continue
        if (isinstance(chunk, list) and len(chunk) == 2 and chunk[0] == 1
                and isinstance(chunk[1], str)):
            chunks.append(chunk[1])
    result = []
    for line in "".join(chunks).splitlines():
        if not line.startswith(":HL["):
            continue
        try:
            hint = json.loads(line[3:])
            if (not isinstance(hint, list) or len(hint) != 3 or hint[1] != "image"
                    or not isinstance(hint[2], dict) or hint[2].get("fetchPriority") != "high"
                    or not isinstance(hint[0], str)):
                continue
            image = urlsplit(hint[0])
            if (image.scheme != "https" or image.hostname != "static.mercdn.net"
                    or image.username or image.password or image.port is not None
                    or image.fragment or image.query and not re.fullmatch(r"[0-9]{1,16}", image.query)):
                continue
            match = re.fullmatch(r"/thumb/item/webp/(m[0-9]{8,20})_1\.jpg", image.path)
            if not match:
                continue
            candidate = "https://jp.mercari.com/item/" + match[1]
            if candidate not in result:
                result.append(candidate)
            if len(result) == 3:
                break
        except (ValueError, TypeError, RecursionError):
            continue
    return tuple(result)
