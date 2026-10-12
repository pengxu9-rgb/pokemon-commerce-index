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

from .languages import normalize_language

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


def _card_field_source(source: str, key: str) -> str:
    """Find a card property at depth zero, excluding attack names and comments."""
    root = re.search(r"\bconst\s+card\s*(?::[^=]+)?=\s*\{", source)
    if not root:
        raise ValueError("card object declaration missing")
    body = _balanced(source, root.end() - 1, "{", "}")
    property_pattern = re.compile(r"(?:[A-Za-z_$][\w$]*|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")\s*:")
    offset, depth = 0, 0
    while offset < len(body):
        if body.startswith("//", offset):
            newline = body.find("\n", offset)
            offset = len(body) if newline < 0 else newline + 1
            continue
        if body.startswith("/*", offset):
            end = body.find("*/", offset + 2)
            if end < 0:
                raise ValueError("unclosed TypeScript comment")
            offset = end + 2
            continue
        if depth == 0:
            found = property_pattern.match(body, offset)
            if found:
                if found.group().rsplit(":", 1)[0].strip().strip("'\"") == key:
                    return body[offset:]
                offset = found.end()
                continue
        char = body[offset]
        if char in ("'", '"', "`"):
            quote = char
            offset += 1
            while offset < len(body):
                if body[offset] == "\\":
                    offset += 2
                elif body[offset] == quote:
                    offset += 1
                    break
                else:
                    offset += 1
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        offset += 1
    return ""


def parse_set_source(source: str) -> tuple[str, int]:
    set_id = _string_field(source, "id")
    count = _object_field(source, "cardCount", "{", "}")
    official = re.search(r"\bofficial\s*:\s*(\d+)", count or "")
    if not set_id or not official:
        raise ValueError("set source lacks id or official card count")
    return set_id, int(official.group(1))


def parse_set_metadata(source: str, language: str = "ja") -> dict[str, Any]:
    language = normalize_language(language)
    set_id, official_count = parse_set_source(source)
    name = _string_field(_object_field(source, "name", "{", "}") or "", language)
    dates = _object_field(source, "releaseDate", "{", "}")
    # A missing localized date must not inherit another region's date.
    date = _string_field(dates, language) if dates is not None else _string_field(source, "releaseDate")
    if language == "ja":
        return {"set_code": set_id, "name_ja": name, "release_date_ja": date,
                "official_card_count": official_count}
    return {"language": language, "set_code": set_id, "name": name,
            "release_date": date, "official_card_count": official_count}


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


def _lexical_source(source: str) -> tuple[str, str]:
    clean, masked = list(source), list(source)
    offset = 0
    while offset < len(source):
        start, comment = offset, False
        if source.startswith('//', offset):
            end = source.find('\n', offset);offset = len(source) if end < 0 else end;comment = True
        elif source.startswith('/*', offset):
            end = source.find('*/', offset + 2)
            if end < 0:raise ValueError('unclosed source comment')
            offset = end + 2;comment = True
        elif source[offset] in ('"', "'", '`'):
            quote = source[offset];offset += 1
            while offset < len(source):
                if source[offset] == '\\':offset += 2
                elif source[offset] == quote:offset += 1;break
                elif source[offset] == '\n' and quote != '`':raise ValueError('unclosed source string')
                else:offset += 1
            else:raise ValueError('unclosed source string')
        else:offset += 1;continue
        for index in range(start, min(offset, len(source))):
            if source[index] != '\n':
                masked[index] = ' '
                if comment:clean[index] = ' '
    return ''.join(clean), ''.join(masked)


def _literal_parts(source: str) -> list[str]:
    clean, masked = _lexical_source(source);parts = [];start = 0;stack = []
    for offset, char in enumerate(masked):
        if char in '{[(':stack.append(char)
        elif char in '}])':
            if not stack or stack.pop() != {'}':'{', ']':'[', ')':'('}[char]:raise ValueError('unbalanced source value')
        elif char == ',' and not stack:
            if clean[start:offset].strip():parts.append(clean[start:offset].strip())
            start = offset + 1
    if stack:raise ValueError('unclosed source value')
    if clean[start:].strip():parts.append(clean[start:].strip())
    return parts


def _literal_properties(body: str) -> dict[str, str]:
    fields = {}
    for part in _literal_parts(body):
        match = re.fullmatch(r'(?P<key>[A-Za-z_$][\w$]*|' + LITERAL + r')\s*:\s*(?P<value>[\s\S]+)', part)
        if not match:raise ValueError('unsupported source property; identity review required')
        key = match['key']
        if key[0] in ('"', "'"):key = ast.literal_eval(key)
        if key in fields:raise ValueError('duplicate source property; identity review required')
        fields[key] = match['value'].strip()
    return fields


def _strict_variant_fields(source: str) -> list[dict[str, str]]:
    clean, masked = _lexical_source(source)
    roots = {m.start():m for m in re.finditer(r'\bconst\s+card\s*(?::\s*Card\s*)?=\s*\{', masked)}
    top = [];stack = []
    for offset, char in enumerate(masked):
        if offset in roots and not stack:top.append(roots[offset])
        if char in '{[(':stack.append(char)
        elif char in '}])':
            if not stack or stack.pop() != {'}':'{', ']':'[', ')':'('}[char]:raise ValueError('unbalanced card source')
    if stack or len(top) != 1:raise ValueError('single actual top-level card declaration required')
    start = top[0].end() - 1;depth = 0;end = None
    for offset in range(start, len(masked)):
        if masked[offset] == '{':depth += 1
        elif masked[offset] == '}':
            depth -= 1
            if depth == 0:end = offset;break
    fields = _literal_properties(clean[start + 1:end])
    value = fields.get('variants')
    if value is None:return []
    if not value.startswith('[') or not value.endswith(']'):raise ValueError('literal source variants required')
    variants = []
    for part in _literal_parts(value[1:-1]):
        if not part.startswith('{') or not part.endswith('}'):raise ValueError('literal source variant object required')
        variants.append(_literal_properties(part[1:-1]))
    return variants


def variant_dimension_losses(source: str) -> list[dict[str, str]]:
    """Read actual variant properties; reject unsafe legacy projections."""
    losses, labels = [], []
    for fields in _strict_variant_fields(source):
        def literal(key, required=False):
            value = fields.get(key)
            if value is None and not required:return None
            if value is None or not re.fullmatch(LITERAL, value):raise ValueError('explicit source literal required for ' + key)
            result = ast.literal_eval(value)
            if not isinstance(result, str) or not result.strip():raise ValueError('nonempty source literal required for ' + key)
            return result
        label = _variant_token(literal('type', True))
        for key in ('foil', 'subtype'):
            value = literal(key)
            if value:label += '_' + _variant_token(value, normalize_hyphen=key == 'subtype')
        if 'stamp' in fields:
            try:stamps = ast.literal_eval(fields['stamp'])
            except (ValueError, SyntaxError) as error:raise ValueError('literal source stamps required') from error
            if not isinstance(stamps, list) or not all(isinstance(s, str) for s in stamps):raise ValueError('literal source stamps required')
            for stamp in stamps:label += '_' + _variant_token(stamp, normalize_hyphen=True)
        labels.append(label)
        if 'size' in fields:losses.append(dict(legacy_variant=label, source_size=literal('size', True)))
    projected = []
    for variant in _variant_objects(source):
        kind = _string_field(variant, 'type')
        if not kind:raise ValueError('legacy source projection lacks type')
        label = _variant_token(kind)
        for key in ('foil', 'subtype'):
            value = _string_field(variant, key)
            if value:label += '_' + _variant_token(value, normalize_hyphen=key == 'subtype')
        for stamp in _stamp_names(variant):label += '_' + _variant_token(stamp, normalize_hyphen=True)
        projected.append(label)
    if projected != labels:raise ValueError('legacy variant projection differs from actual properties; identity review required')
    return losses


def parse_discovery_facets(source: str) -> dict[str, Any]:
    """Read text-only character and artist facts without inferring a printing link."""
    attributes: dict[str, Any] = {}
    dex_body = _object_field(source, "dexId", "[", "]")
    if dex_body is not None:
        if not re.fullmatch(r"[\d,\s]*", dex_body):
            raise ValueError("unsupported dexId array")
        values = ast.literal_eval("[" + dex_body + "]")
        if not isinstance(values, list) or not values or any(
                type(value) is not int or not 1 <= value <= 9999 for value in values):
            raise ValueError("invalid dexId array")
        attributes["dex_ids"] = sorted(set(values))
    illustrator = _string_field(source, "illustrator")
    if illustrator:
        illustrator = illustrator.strip()
        if not illustrator or len(illustrator) > 160:
            raise ValueError("invalid illustrator")
        attributes["illustrator"] = illustrator
    return attributes


def parse_card_classification(source: str) -> tuple[str, str | None] | None:
    """Extract the source's category and optional subtype without guessing."""
    category = _string_field(source, "category")
    trainer = _string_field(source, "trainerType")
    energy = _string_field(source, "energyType")
    if category is None:
        return None
    if category not in {"Pokemon", "Trainer", "Energy"}:
        raise ValueError("unsupported card category")
    if trainer and (category != "Trainer" or trainer not in {"Item", "Stadium", "Supporter", "Tool"}):
        raise ValueError("invalid trainer subtype")
    if energy and (category != "Energy" or energy not in {"Normal", "Special"}):
        raise ValueError("invalid energy subtype")
    if trainer and energy:
        raise ValueError("card has two subtype families")
    return category, trainer or energy


def parse_card_source(source: str, *, set_id: str, official_count: int,
                      path: str, revision: str, language: str = "ja",
                      source_directory: str | None = None,
                      strict_variant_dimensions: bool = False) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("dataset revision must be a full Git commit SHA")
    if type(strict_variant_dimensions) is not bool:
        raise ValueError('strict variant dimension policy must be a boolean')
    if strict_variant_dimensions and variant_dimension_losses(source):
        raise ValueError('source variant size omitted by legacy IDs; identity correction review required')
    filename = PurePosixPath(path)
    if filename.suffix != ".ts" or filename.parent.name != (source_directory or set_id):
        raise ValueError("card source path does not match set")
    local_id = filename.stem
    if not local_id:
        raise ValueError("card filename lacks local id")
    name_block = _object_field(_card_field_source(source, "name"), "name", "{", "}")
    language = normalize_language(language)
    name = _string_field(name_block or "", language)
    if not name:
        raise ValueError(f"card source lacks {language} name")
    rarity = _string_field(_card_field_source(source, "rarity"), "rarity")
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
        "match_eligible": bool(variants),
    } for variant in names]
