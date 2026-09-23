"""Conservative parser for TCGdex's pinned TypeScript metadata snapshots.

Only identity fields are extracted. Unsupported syntax raises rather than
inventing a card name or collapsing distinct finish variants.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any

LITERAL = r"((?:'(?:\\.|[^'\\])*')|(?:\"(?:\\.|[^\"\\])*\"))"


def _string_field(source: str, key: str) -> str | None:
    found = re.search(r"(?:^|[\s,{])(?:['\"])?" + re.escape(key) +
                      r"(?:['\"])?\s*:\s*" + LITERAL, source, re.M)
    if not found:
        return None
    try:
        value = ast.literal_eval(found.group(1))
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"invalid TypeScript string for {key}") from exc
    return value if isinstance(value, str) else None


def _balanced(source: str, opening_at: int, opening: str, closing: str) -> str:
    depth = 0
    quote = None
    escaped = False
    for offset in range(opening_at, len(source)):
        char = source[offset]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return source[opening_at + 1:offset]
    raise ValueError(f"unclosed TypeScript {opening}")


def _object_field(source: str, key: str, opening: str, closing: str) -> str | None:
    match = re.search(r"\b" + re.escape(key) + r"\s*:\s*" + re.escape(opening), source)
    if not match:
        return None
    return _balanced(source, match.end() - 1, opening, closing)


def parse_set_source(source: str) -> tuple[str, int]:
    set_id = _string_field(source, "id")
    count = _object_field(source, "cardCount", "{", "}")
    official = re.search(r"\bofficial\s*:\s*(\d+)", count or "")
    if not set_id or not official:
        raise ValueError("set source lacks id or official card count")
    return set_id, int(official.group(1))


def parse_set_metadata(source: str) -> dict[str, Any]:
    set_id, official_count = parse_set_source(source)
    return {"set_code": set_id,
            "name_ja": _string_field(_object_field(source, "name", "{", "}") or "", "ja"),
            "release_date_ja": _string_field(_object_field(source, "releaseDate", "{", "}") or "", "ja"),
            "official_card_count": official_count}


def _variant_objects(source: str) -> list[str]:
    variants = _object_field(source, "variants", "[", "]")
    if variants is None:
        return []
    result = []
    offset = 0
    while offset < len(variants):
        start = variants.find("{", offset)
        if start < 0:
            break
        body = _balanced(variants, start, "{", "}")
        result.append(body)
        # Advance past the entire balanced object, including nested mappings.
        offset = start + len(body) + 2
    return result


def _stamp_names(source: str) -> list[str]:
    body = _object_field(source, "stamp", "[", "]")
    if body is None:
        return []
    try:
        values = ast.literal_eval("[" + body + "]")
    except (ValueError, SyntaxError) as exc:
        raise ValueError("unsupported stamp array") from exc
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("unsupported stamp array")
    return values


def _variant_token(value: str, *, normalize_hyphen: bool = False) -> str:
    token = re.sub(r"\s+", "_", value.strip().lower())
    if normalize_hyphen:
        token = token.replace("-", "_")
    if not re.fullmatch(r"[a-z0-9_-]+", token):
        raise ValueError("variant contains unsupported identifier")
    return token


def parse_card_source(source: str, *, set_id: str, official_count: int,
                      path: str, revision: str, language: str = "ja",
                      source_directory: str | None = None) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("dataset revision must be a full Git commit SHA")
    filename = PurePosixPath(path)
    if filename.suffix != ".ts" or filename.parent.name != (source_directory or set_id):
        raise ValueError("card source path does not match set")
    local_id = filename.stem
    if not local_id:
        raise ValueError("card filename lacks local id")
    name_block = _object_field(source, "name", "{", "}")
    if language not in {"ja", "en"}:
        raise ValueError("unsupported card language")
    name = _string_field(name_block or "", language)
    if not name:
        raise ValueError(f"card source lacks {language} name")
    rarity = _string_field(source, "rarity")
    if not re.fullmatch(r"[A-Za-z0-9]+", local_id):
        raise ValueError("card filename is not an alphanumeric collector id")
    width = max(3, len(local_id), len(str(official_count)))
    denominator = str(official_count).zfill(width) if official_count else set_id
    number = f"{local_id.upper().zfill(width)}/{denominator}"
    variants = _variant_objects(source)
    names = []
    for variant in variants:
        kind = _string_field(variant, "type")
        foil = _string_field(variant, "foil")
        subtype = _string_field(variant, "subtype")
        stamps = _stamp_names(variant)
        if not kind:
            raise ValueError("variant lacks type")
        normalized = _variant_token(kind)
        if foil:
            normalized += "_" + _variant_token(foil)
        if subtype:
            normalized += "_" + _variant_token(subtype, normalize_hyphen=True)
        for stamp in stamps:
            normalized += "_" + _variant_token(stamp, normalize_hyphen=True)
        names.append(normalized)
    if len(set(names)) != len(names):
        raise ValueError("two source variants collapse to the same identity")
    if not names:
        names = ["standard"]
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    rights = f"https://github.com/tcgdex/cards-database/blob/{revision}/LICENSE"
    return [{
        "language": language, "set_code": set_id, "collector_number": number,
        "variant": variant, "name": name, "rarity": rarity,
        "provenance": f"tcgdex:{revision}:{path}:sha256:{digest}",
        "rights_reference": rights, "display_allowed": False,
    } for variant in names]
