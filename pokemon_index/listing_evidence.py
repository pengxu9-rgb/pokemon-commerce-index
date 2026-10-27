"""Exact listing claims and photos, compared with a server-owned catalog row.

Matching means structured listing claims agree with catalog identity dimensions.
It does not authenticate a card, a photograph, a seller, or a physical finish.
No image, marketplace, catalog HTTP endpoint or provider is requested here.
"""
from __future__ import annotations

from contextlib import closing
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

from .claim_text import negated_cue

FIELDS = ("language", "set_code", "collector_number", "finish", "edition")
FINISHES = {"normal", "holo", "reverse", "reverse_masterball", "reverse_pokeball", "cosmos_holo", "alternate_holo"}
EDITIONS = {"first_edition", "unlimited", "shadowless", "standard", "not_applicable"}
ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


def _text(value, limit=2048):
    return isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value and not re.search(r"[\x00-\x1f\x7f]", value)


def _stamp(value):
    if not _text(value, 40) or not ISO.fullmatch(value):
        raise ValueError("invalid listing evidence timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalized(field, value):
    if not isinstance(value, str) or len(value) > 160:
        return None
    value = unicodedata.normalize("NFKC", value).strip()
    lower = value.casefold()
    if field == "language":
        return {"ja": "ja", "japanese": "ja", "日本語": "ja", "en": "en", "english": "en", "英語": "en",
                "zh-hans": "zh-Hans", "zh-hant": "zh-Hant", "ko": "ko", "fr": "fr", "de": "de", "es": "es", "it": "it", "pt": "pt"}.get(lower)
    if field == "set_code":
        return value.upper() if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", value) else None
    if field == "collector_number":
        if not re.fullmatch(r"[A-Za-z]?[0-9]{1,4}[A-Za-z]?(?:/[A-Za-z]?[0-9]{1,4}[A-Za-z]?)?", value):
            return None
        return "/".join(re.sub(r"[0-9]+", lambda m: str(int(m[0])), part.upper()) for part in value.split("/"))
    if field == "finish":
        return {"non-holo": "normal", "non holo": "normal", "nonfoil": "normal", "non-foil": "normal", "non foil": "normal", "no holo": "normal", "ノンホロ": "normal", "ホロ": "holo", "reverse holo": "reverse",
                "マスターボールミラー": "reverse_masterball", "モンスターボールミラー": "reverse_pokeball"}.get(lower, lower if lower in FINISHES else None)
    if field == "edition":
        return {"1st edition": "first_edition", "1st_edition": "first_edition", "first edition": "first_edition", "初版": "first_edition",
                "unlimited edition": "unlimited"}.get(lower, lower if lower in EDITIONS else None)
    return None


class CatalogIdentityLookup:
    """An explicit local read-only catalog dependency, never a request-supplied DB.

    Legacy plain finish variants do not specify an edition. Their edition stays
    unknown; an apparently unique card/query cannot fill a missing dimension.
    """
    def __init__(self, database):
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise ValueError("an existing server-owned catalog database is required")

    def __call__(self, card_id):
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT card_id,language,set_code,collector_number,variant,provenance,match_eligible,display_allowed FROM card WHERE card_id=?", (card_id,)).fetchone()
            if not row or row["match_eligible"] != 1 or row["display_allowed"] != 1 or not _text(row["provenance"]):
                return None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_identity_quarantine'").fetchone():
                if db.execute("SELECT 1 FROM catalog_identity_quarantine WHERE quarantine_id GLOB 'variant-dimension-hold:*' AND json_extract(record_json,'$.identity.card_id')=? LIMIT 1", (card_id,)).fetchone():
                    return None
            return catalog_identity_target(row)


def catalog_identity_target(row):
    """Decode reported catalog dimensions; caller owns eligibility and scope."""
    variant = row["variant"]
    finish, edition = None, None
    if isinstance(variant, str):
        for suffix, value in (("_1st_edition", "first_edition"), ("_unlimited", "unlimited"), ("_shadowless", "shadowless")):
            if variant.endswith(suffix):
                finish, edition = normalized("finish", variant[:-len(suffix)]), value
                break
        else:
            finish = normalized("finish", variant)
    target = {field: normalized(field, row[field]) for field in FIELDS[:3]}
    target.update(finish=finish, edition=edition)
    digest = hashlib.sha256(json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"card_id": row["card_id"], **target, "evidence_ref": "catalog-row:sha256:" + digest}


def photo_url(value, source, *, synthetic=False):
    if not _text(value) or "\\" in value:
        return None
    try:
        u = urlsplit(value)
        if (u.scheme != "https" or u.username or u.password or u.port not in (None, 443)
                or u.query or u.fragment or "%" in u.path or any(p in (".", "..") for p in u.path.split("/"))
                or not re.search(r"\.(?:jpg|jpeg|png|webp)\Z", u.path, re.I)):
            return None
        paths = {"mercari": ("static.mercdn.net", r"/item/detail/orig/photos/[A-Za-z0-9_./-]+"),
                 "ebay_us": ("i.ebayimg.com", r"/images/g/[A-Za-z0-9_~./!-]+"),
                 "snkrdunk": ("images.snkrdunk.com", r"/[A-Za-z0-9_./-]+")}
        allowed = (u.hostname == "images.example.invalid" and bool(re.fullmatch(r"/listings/[A-Za-z0-9_/-]+\.(?:jpg|jpeg|png|webp)", u.path, re.I))) if synthetic else (
            source in paths and u.hostname == paths[source][0] and bool(re.fullmatch(paths[source][1], u.path)))
        return value if allowed else None
    except (ValueError, TypeError):
        return None


def validate_photos(values, source, listing_url, observed_at, *, synthetic=False):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError("invalid listing photos")
    result, urls = [], set()
    for value in values:
        if (not isinstance(value, dict) or set(value) != {"url", "role", "listing_url", "evidence_ref", "observed_at"}
                or photo_url(value["url"], source, synthetic=synthetic) is None or value["url"] in urls
                or value["role"] != "listing_photo" or value["listing_url"] != listing_url
                or not _text(value["evidence_ref"]) or _stamp(value["observed_at"]) > _stamp(observed_at)):
            raise ValueError("invalid exact-listing photo binding")
        urls.add(value["url"]); result.append(copy.deepcopy(value))
    return result


def extracted_listing_evidence(source, native_id, listing_url, observed_at, evidence_ref, *, item=None, offer=None, synthetic=False):
    """Only exact item attributes and exact Offer attachments are admitted.

    The caller already rejects ambiguous/wrong-URL/summary records. Product.image,
    og:image, related records and the SNKR item.apparel catalog are never read.
    """
    attributes, conflicts, photos = {}, set(), []
    entries = []
    if isinstance(item, dict):
        if isinstance(item.get("attributes"), dict):
            entries.extend((key, value) for key, value in item["attributes"].items() if key in FIELDS)
        photos.extend(item.get("images", []) if isinstance(item.get("images"), list) else [])
    if isinstance(offer, dict) and offer.get("url") == listing_url:
        offered = offer.get("itemOffered")
        if isinstance(offered, dict) and offered.get("url") == listing_url:
            for prop in offered.get("additionalProperty", []) if isinstance(offered.get("additionalProperty"), list) else []:
                if isinstance(prop, dict) and prop.get("name") in FIELDS:
                    entries.append((prop["name"], prop.get("value")))
        image = offer.get("image", [])
        photos.extend(image if isinstance(image, list) else [image])
    for field, raw in entries:
        value = normalized(field, raw)
        if value is None or field in attributes and attributes[field] != value:
            conflicts.add(field)
        else:
            attributes[field] = value
    # Truncate only attachments, never identity conflicts. Unsafe URLs are absent,
    # not sent to a proxy or fetched to determine whether they are images.
    safe_photos, seen = [], set()
    for value in photos[:40]:
        value = value.get("url") if isinstance(value, dict) else value
        safe = photo_url(value, source, synthetic=synthetic)
        if safe and safe not in seen:
            seen.add(safe)
            safe_photos.append({"url": safe, "role": "listing_photo", "listing_url": listing_url,
                                "evidence_ref": evidence_ref, "observed_at": observed_at})
        if len(safe_photos) == 8:
            break
    identity = None
    if entries:
        identity = {"source": source, "native_id": native_id, "listing_url": listing_url,
                    "attributes": {field: attributes.get(field) for field in FIELDS},
                    "conflicting_fields": sorted(conflicts), "evidence_ref": evidence_ref,
                    "observed_at": observed_at, "basis": "exact_listing_structured"}
    return identity, safe_photos


def _finish_mentions(title):
    # Remove only each compound phrase's own span. A separate Holo / Non-Holo
    # alternative must remain two conflicting claims, never collapse to one.
    patterns = (
        ("normal", r"\bnon[- ]?(?:holo(?:graphic)?|foil)\b|\b(?:no|not)[- ]holo\b|ノンホロ"),
        ("reverse_masterball", r"\b(?:(?:holo|reverse(?:\s+holo)?)\s+)?master\s*ball(?:\s+(?:reverse(?:\s+holo)?|holo))?\b|マスターボール(?:ミラー)?"),
        ("reverse_pokeball", r"\b(?:(?:holo|reverse(?:\s+holo)?)\s+)?poke\s*ball(?:\s+(?:reverse(?:\s+holo)?|holo))?\b|モンスターボール(?:ミラー)?"),
        ("cosmos_holo", r"\bcosmos\s+holo\b"), ("alternate_holo", r"\balternate\s+holo\b"),
        ("reverse", r"\b(?:reverse(?:\s+holo)?|holo\s+reverse)\b|ミラー"),
        ("holo", r"\bholo(?:graphic)?\b|ホロ"))
    original, found, negated = title, set(), False
    for value, pattern in patterns:
        matches = list(re.finditer(pattern, title, re.I))
        if matches:
            found.add(value)
            negated = negated or any(negated_cue(original, *match.span()) for match in matches)
            # Keep original spans so contextual negation remains scoped even
            # after a complete compound (such as non-holo) has been consumed.
            title = re.sub(pattern, lambda match: " " * len(match[0]), title, flags=re.I)
    return found, negated


def _title_conflicts(title, claims):
    """Titles may contradict structured claims but cannot supply positive proof."""
    title = unicodedata.normalize("NFKC", title)
    result = set()
    number_mentions = list(re.finditer(r"(?<![A-Za-z0-9])([A-Za-z]?[0-9]{1,4}[A-Za-z]?\s*/\s*[A-Za-z]?[0-9]{1,4}[A-Za-z]?)(?![A-Za-z0-9])", title))
    numbers = {normalized("collector_number", re.sub(r"\s+", "", match[0])) for match in number_mentions}
    if (numbers and claims["collector_number"] and numbers != {claims["collector_number"]}
            or any(negated_cue(title, *match.span()) for match in number_mentions)):
        result.add("collector_number")
    patterns = {"language": {"ja": r"\bJapanese\b|日本語|日版|日文", "en": r"\bEnglish\b|英語|英文|英版",
                            "de": r"\b(?:German|Deutsch)\b|德文|德語|德语", "fr": r"\b(?:French|Français|Francais)\b|法文|法語|法语",
                            "ko": r"\bKorean\b|韓国語|韓文|韩文|韓版|韩版|한국어|한글", "es": r"\b(?:Spanish|Español|Espanol)\b|西班牙[文語语]",
                            "it": r"\b(?:Italian|Italiano)\b|意大利[文語语]|義大利[文語语]", "pt": r"\b(?:Portuguese|Português|Portugues)\b|葡萄牙[文語语]|葡文",
                            "zh-Hans": r"\bSimplified\s+Chinese\b|简体中文|簡體中文|简中", "zh-Hant": r"\bTraditional\s+Chinese\b|繁體中文|繁体中文|繁中"},
                "edition": {"first_edition": r"\b1st\s+(?:edition|ed\.?)\b|\bfirst\s+edition\b|初版", "unlimited": r"\bunlimited\b", "shadowless": r"\bshadowless\b"}}
    for field, values in patterns.items():
        mentions = [(value, match) for value, pattern in values.items()
                    for match in re.finditer(pattern, title, re.I)]
        found = {value for value, _ in mentions}
        if (found and claims[field] and found != {claims[field]}
                or any(negated_cue(title, *match.span()) for _, match in mentions)):
            result.add(field)
    finishes, negated_finish = _finish_mentions(title)
    if finishes and claims["finish"] and finishes != {claims["finish"]} or negated_finish:
        result.add("finish")
    if claims["language"] and claims["language"] not in {"zh-Hans", "zh-Hant"} and re.search(r"\bChinese\b|中文", title, re.I):
        result.add("language")
    set_mentions = list(re.finditer(r"(?<![A-Za-z0-9])((?:SV|SM|XY|S)[0-9]{1,3}[A-Za-z]?)(?![A-Za-z0-9])", title, re.I))
    sets = {match[0].upper() for match in set_mentions}
    # Classic named set codes (e.g. BASE) are also recognized when they are the
    # explicit structured claim; generic unrelated title words are not set IDs.
    claimed_set_mentions = list(re.finditer(r"(?<![A-Za-z0-9])" + re.escape(claims["set_code"]) + r"(?![A-Za-z0-9])", title, re.I)) if claims["set_code"] else []
    if (sets and claims["set_code"] and sets != {claims["set_code"]}
            or any(negated_cue(title, *match.span()) for match in set_mentions + claimed_set_mentions)):
        result.add("set_code")
    return result


def identity_evidence(raw, source, listing_url, observed_at, target):
    claims = {field: None for field in FIELDS}
    conflicts, evidence, claim_url = set(), None, None
    basis, captured_at = "unavailable", observed_at
    value = raw.get("listing_identity") if raw.get("scope", "listing") == "listing" else None
    if value is not None:
        if (not isinstance(value, dict) or set(value) != {"source", "native_id", "listing_url", "attributes", "conflicting_fields", "evidence_ref", "observed_at", "basis"}
                or value["source"] != source or value["native_id"] != raw.get("native_id") or value["listing_url"] != listing_url
                or value["basis"] != "exact_listing_structured" or not _text(value["evidence_ref"])
                or _stamp(value["observed_at"]) > _stamp(observed_at) or not isinstance(value["attributes"], dict)
                or set(value["attributes"]) != set(FIELDS) or not isinstance(value["conflicting_fields"], list)
                or len(value["conflicting_fields"]) != len(set(value["conflicting_fields"])) or set(value["conflicting_fields"]) - set(FIELDS)):
            raise ValueError("invalid structured listing identity binding")
        for field, claim in value["attributes"].items():
            if claim is not None and normalized(field, claim) != claim:
                raise ValueError("noncanonical listing identity claim")
        claims = copy.deepcopy(value["attributes"])
        conflicts = set(value["conflicting_fields"]) | _title_conflicts(raw.get("title", ""), claims)
        evidence, claim_url, basis = value["evidence_ref"], listing_url, value["basis"]
        captured_at = value["observed_at"]
    target_card_id = target.get("card_id") if target else None
    target_value = {key: target[key] for key in (*FIELDS, "evidence_ref")} if target else None
    matched, missing = [], []
    for field in FIELDS:
        expected = target.get(field) if target else None
        if field in conflicts:
            continue
        if expected is None or claims[field] is None:
            missing.append(field)
        elif expected != claims[field]:
            conflicts.add(field)
        else:
            matched.append(field)
    status = "conflict" if conflicts else "exact_match" if len(matched) == len(FIELDS) else "candidate"
    return {"status": status, "target_card_id": target_card_id, "target": target_value, "claims": claims,
            "matched_fields": matched, "missing_fields": missing, "conflicting_fields": sorted(conflicts),
            "listing_url": claim_url, "evidence_ref": evidence, "observed_at": captured_at,
            "basis": basis, "authenticity_verified": False}


def semantic_binding(offer):
    value = offer.get("identity_evidence") or {}
    identity = {key: value.get(key) for key in ("status", "target_card_id", "claims", "matched_fields", "missing_fields", "conflicting_fields", "listing_url", "basis")}
    target = value.get("target")
    identity["target"] = {field: target.get(field) for field in FIELDS} if target else None
    photos = sorted((p["url"], p["role"], p["listing_url"]) for p in offer.get("listing_photos", []))
    return {"identity": identity, "photos": photos}


def research_coverage(offers, *, search_used):
    return {"returned_listings": len(offers),
            "exact_match_listings": sum(o["identity_evidence"]["status"] == "exact_match" for o in offers),
            "candidate_listings": sum(o["identity_evidence"]["status"] == "candidate" for o in offers),
            "conflicting_listings": sum(o["identity_evidence"]["status"] == "conflict" for o in offers),
            "sold_listings": sum(o["availability"] == "sold_out" for o in offers),
            "listings_with_photos": sum(bool(o.get("listing_photos")) for o in offers),
            "search_limit_per_source": 3 if search_used else None, "exhaustive": False, "live_coverage_verified": False}
