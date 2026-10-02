"""Source-bound catalog support, release overlays and collector family facts.

Support authorizes internal discovery/review, never automatic live offer joining.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Iterable
from . import core


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def identity_snapshot(card) -> dict:
    return {key: card[key] for key in ("card_id", "language", "set_code",
            "collector_number", "variant", "name", "rarity", "provenance")}


def _hash(value) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("evidence needs a SHA-256")


def _release(db, language: str, code: str):
    return db.execute("SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?",
                      (language, code)).fetchone()


def import_releases(db: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Keep the original pinned release identity and overlay exact official facts."""
    count = 0
    with db:
        for row in rows:
            core._required(row, "language", "set_code", "source_provenance", "original_name",
                           "name", "release_date", "official_url", "official_page_sha256")
            _hash(row["official_page_sha256"])
            if not re.fullmatch(r"https://www\.pokemon-card\.com/ex/[a-z0-9]+/index\.html", row["official_url"]):
                raise ValueError("release evidence URL is not official")
            core.parse_time(row["release_date"] + "T00:00:00Z")
            release = _release(db, row["language"], row["set_code"])
            if (release is None or release["provenance"] != row["source_provenance"]
                    or release["name"] not in {row["original_name"], row["name"]}):
                raise ValueError("release overlay differs from pinned source")
            existing = db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?",
                                  (row["language"], row["set_code"])).fetchone()
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if existing and existing[0] != encoded:
                raise ValueError("conflicting release evidence")
            db.execute("INSERT OR IGNORE INTO catalog_release_evidence VALUES (?,?,?)",
                       (row["language"], row["set_code"], encoded))
            db.execute("UPDATE catalog_set_localized SET name=?,release_date=? WHERE language=? AND set_code=?",
                       (row["name"], row["release_date"], row["language"], row["set_code"]))
            if row["language"] == "ja":
                db.execute("UPDATE catalog_set SET name_ja=?,release_date_ja=? WHERE set_code=?",
                           (row["name"], row["release_date"], row["set_code"]))
            count += 1
    return count


def release_scope_snapshot(db: sqlite3.Connection, language: str, code: str) -> dict:
    """Bind metadata to the current numbering scope, never a physical edition."""
    cards = [{key: r[key] for key in ("card_id", "collector_number", "provenance")}
             for r in db.execute("SELECT * FROM card WHERE language=? AND set_code=? ORDER BY card_id",
                                 (language, code))]
    return {"record_count": len(cards), "records_sha256": digest({"cards": cards}),
            "denominators": sorted({r["collector_number"].split("/", 1)[1]
                                    for r in cards if "/" in r["collector_number"]
                                    and r["collector_number"].split("/", 1)[1].isdigit()
                                    and int(r["collector_number"].split("/", 1)[1]) > 0}),
            "unnumbered_records": sum(not re.fullmatch(r"[0-9]+/[0-9]+", r["collector_number"]) for r in cards)}


def import_release_metadata(db: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Fill missing release fields from official product + exact card-link evidence.

    Dates describe a product family, not a particular copy or reprint. Multiple
    dates stay unknown. Existing positive support and source identities survive.
    """
    count = 0
    with db:
        for row in rows:
            if row.get("schema") != "pokemon.catalog-release-metadata.v1":
                raise ValueError("unknown release metadata schema")
            core._required(row, "language", "set_code", "name", "source_provenance",
                           "official_url", "official_page_sha256", "scope_snapshot",
                           "coordinate_reference")
            if "original_release" not in row:
                raise ValueError("release baseline snapshot is absent")
            if row["language"] != "ja" or row["set_code"] != row["set_code"].upper():
                raise ValueError("release metadata requires exact Japanese scope")
            for flag in ("physical_finish_verified", "price_comparable", "automatic_offer_join_allowed", "display_allowed"):
                if row.get(flag) is not False:
                    raise ValueError("release metadata cannot widen physical or display permissions")
            _hash(row["official_page_sha256"])
            if not re.fullmatch(r"https://www\.pokemon-card\.com/(?:ex/[a-z0-9]+/(?:index\.html)?|products/[a-z0-9]+/[a-z0-9]+\.html)", row["official_url"]):
                raise ValueError("release product URL is not official")
            scope = release_scope_snapshot(db, row["language"], row["set_code"])
            if not scope["record_count"] or scope != row["scope_snapshot"] or len(scope["denominators"]) != 1:
                raise ValueError("release numbering scope is stale or combines products")
            reference = row["coordinate_reference"]
            core._required(reference, "native_id", "collector_number", "provenance", "official_url", "official_page_sha256", "product_href", "product_link_text")
            _hash(reference["official_page_sha256"])
            if reference["official_url"] != "https://www.pokemon-card.com/card-search/details.php/card/" + reference["native_id"]:
                raise ValueError("release coordinate URL differs from its exact reference")
            product_path = re.sub(r"/index\.html$", "/", row["official_url"].removeprefix("https://www.pokemon-card.com"))
            if (reference["product_href"].rstrip("/") != product_path.rstrip("/")
                    or re.sub(r"\s+", "", row["name"]) not in re.sub(r"\s+", "", reference["product_link_text"])):
                raise ValueError("card does not link to the stated release product")
            bound = db.execute("SELECT * FROM card_reference WHERE source='ptcg-database' AND native_id=? AND set_code=? AND collector_number=? AND provenance=?",
                               (reference["native_id"], row["set_code"], reference["collector_number"], reference["provenance"])).fetchone()
            if bound is None:
                raise ValueError("release coordinate reference is stale")
            date = row.get("release_date")
            if date is not None:
                if row.get("date_scope") != "initial_product_release_not_copy_date":
                    raise ValueError("dated release needs an explicit product date scope")
                core.parse_time(date + "T00:00:00Z")
            elif row.get("date_scope") != "unknown_or_multiple_product_dates":
                raise ValueError("unknown release date must remain explicit")
            original = row["original_release"]
            release = _release(db, row["language"], row["set_code"])
            previous = db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?",
                                  (row["language"], row["set_code"])).fetchone()
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if previous:
                if previous[0] != encoded:
                    raise ValueError("conflicting release metadata evidence")
                if not release or release["name"] != row["name"] or release["release_date"] != date:
                    raise ValueError("imported release metadata has drifted")
                count += 1
                continue
            if (dict(release) if release else None) != original:
                raise ValueError("release metadata baseline is stale")
            if release and release["name"] and release["name"] != row["name"]:
                raise ValueError("release fill cannot silently overwrite a named source")
            if release and release["release_date"] and release["release_date"] != date:
                raise ValueError("release fill cannot silently overwrite a source date")
            if row.get("original_name") != (original["name"] if original else None):
                raise ValueError("original release name differs from snapshot")
            provenance = original["provenance"] if original else "official-release:sha256:" + row["official_page_sha256"]
            if row["source_provenance"] != provenance:
                raise ValueError("release provenance differs from baseline")
            official_count = int(scope["denominators"][0]) if scope["denominators"][0].isdigit() else 0
            rights = original["rights_reference"] if original else "https://www.pokemon-card.com/rules/"
            db.execute("INSERT OR IGNORE INTO catalog_release_evidence VALUES (?,?,?)", (row["language"], row["set_code"], encoded))
            db.execute("INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(language,set_code) DO UPDATE SET name=excluded.name,release_date=excluded.release_date",
                       (row["language"], row["set_code"], row["name"], date,
                        original["official_card_count"] if original else official_count, provenance, rights, 0))
            db.execute("INSERT INTO catalog_set VALUES (?,?,?,?,?,?,?) ON CONFLICT(set_code) DO UPDATE SET name_ja=excluded.name_ja,release_date_ja=excluded.release_date_ja",
                       (row["set_code"], row["name"], date, original["official_card_count"] if original else official_count, provenance, rights, 0))
            count += 1
    return count


def import_vocabulary(db: sqlite3.Connection, rows: Iterable[dict]) -> int:
    count = 0
    with db:
        for row in rows:
            core._required(row, "language", "set_code", "alias", "alias_kind", "evidence")
            if row["alias_kind"] not in {"set_name", "printed_code"}:
                raise ValueError("invalid vocabulary kind")
            if not isinstance(row["alias"], str) or not 2 <= len(row["alias"].strip()) <= 120:
                raise ValueError("invalid catalog alias")
            release = db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?",
                                 (row["language"], row["set_code"])).fetchone()
            if release is None or json.loads(release[0]) != row["evidence"]:
                raise ValueError("vocabulary lacks imported release evidence")
            if row["alias_kind"] == "set_name" and row["alias"] != row["evidence"]["name"]:
                raise ValueError("set name alias is not evidenced")
            if row["alias_kind"] == "printed_code" and row["alias"].upper() != row["set_code"]:
                raise ValueError("printed code must match release scope")
            db.execute("INSERT OR REPLACE INTO catalog_vocabulary VALUES (?,?,?,?,?)",
                       (row["language"], row["set_code"], row["alias"], row["alias_kind"],
                        json.dumps(row["evidence"], ensure_ascii=False, sort_keys=True)))
            count += 1
    return count


def import_supported(db: sqlite3.Connection, rows: Iterable[dict]) -> int:
    count = 0
    with db:
        for row in rows:
            if row.get("schema") != "pokemon.supported-card.v1" or row.get("support_scope") != "catalog_discovery_and_listing_review":
                raise ValueError("unsupported positive support record")
            core._required(row, "card_id", "identity", "reference", "release", "finish_evidence_status", "selection_reason")
            if row.get("automatic_offer_join_allowed") is not False:
                raise ValueError("catalog support cannot authorize automatic offer joining")
            card = db.execute("SELECT * FROM card WHERE card_id=?", (row["card_id"],)).fetchone()
            if card is None or identity_snapshot(card) != row["identity"] or not card["match_eligible"]:
                raise ValueError("support identity is stale or structurally ineligible")
            refs = db.execute("SELECT * FROM card_reference WHERE set_code=? AND collector_number=?",
                              (card["set_code"], card["collector_number"])).fetchall()
            if len(refs) != 1 or row["reference"] != {k: refs[0][k] for k in ('source', 'native_id', 'name', 'provenance')}:
                raise ValueError("support needs one exact corroborating reference")
            correction = db.execute("SELECT * FROM card_rarity_correction WHERE card_id=?", (row["card_id"],)).fetchone()
            if (correction is None or row.get("official_card") != {key: correction[key] for key in
                    ("official_url", "official_page_sha256", "official_rarity_icon")}
                    or core._compact_identity_text(refs[0]["name"]) != core._compact_identity_text(card["name"])):
                raise ValueError("support lacks exact official name/rarity evidence")
            release = db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?",
                                 (card["language"], card["set_code"])).fetchone()
            if release is None or json.loads(release[0]) != row["release"]:
                raise ValueError("support release evidence is missing")
            if row["finish_evidence_status"] != "pinned_source_variant_listing_copy_unverified":
                raise ValueError("unsupported finish claim")
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            current = db.execute("SELECT evidence_json FROM supported_card WHERE card_id=?", (row["card_id"],)).fetchone()
            if current and current[0] != encoded:
                raise ValueError("conflicting support record")
            db.execute("INSERT OR IGNORE INTO supported_card VALUES (?,?,?,?)",
                       (row["card_id"], encoded, digest(row["identity"]), row["support_scope"]))
            count += 1
    return count


def support_for_card(db: sqlite3.Connection, card_id: str) -> dict:
    card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    if card is None:
        raise ValueError("unknown card")
    record = db.execute("SELECT * FROM supported_card WHERE card_id=?", (card_id,)).fetchone()
    current = bool(record and card["match_eligible"] and digest(identity_snapshot(card)) == record["identity_sha256"])
    if current:
        evidence = json.loads(record["evidence_json"])
        release = _release(db, card["language"], card["set_code"])
        current = bool(release and release["name"] == evidence["release"]["name"]
                       and release["release_date"] == evidence["release"]["release_date"]
                       and release["provenance"] == evidence["release"]["source_provenance"])
        refs = db.execute("SELECT * FROM card_reference WHERE set_code=? AND collector_number=?",
                          (card["set_code"],card["collector_number"])).fetchall()
        official = db.execute("SELECT * FROM card_rarity_correction WHERE card_id=?",(card_id,)).fetchone()
        stored_release = db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?",
                                    (card["language"],card["set_code"])).fetchone()
        current = bool(current and len(refs)==1 and
                       {k:refs[0][k] for k in ('source','native_id','name','provenance')} == evidence['reference']
                       and official and {k:official[k] for k in ('official_url','official_page_sha256','official_rarity_icon')} == evidence['official_card']
                       and stored_release and json.loads(stored_release[0])==evidence['release'])
    return {"card_id": card_id, "status": "supported_for_internal_review" if current else
            "stale_support_evidence" if record else "research_candidate",
            "automatic_offer_join_allowed": False,
            "evidence": json.loads(record["evidence_json"]) if current else None}


def status(db: sqlite3.Connection) -> dict:
    from . import card_metadata,coordinate_family,printing_evidence
    ids = [r[0] for r in db.execute("SELECT card_id FROM supported_card ORDER BY card_id")]
    ready = [cid for cid in ids if support_for_card(db, cid)["status"] == "supported_for_internal_review"]
    return {**card_metadata.status(db),**coordinate_family.status(db),**printing_evidence.status(db), "supported_records": len(ids), "current_supported_targets": len(ready),
            "stale_supported_targets": len(ids)-len(ready), "automatic_offer_join_ready": 0,
            "bilingual_alias_revisions": db.execute("SELECT COUNT(*) FROM bilingual_concept_revision").fetchone()[0],
            "concept_review_events": db.execute("SELECT COUNT(*) FROM concept_review_event").fetchone()[0],
            "release_evidence_records": db.execute("SELECT COUNT(*) FROM catalog_release_evidence").fetchone()[0],
            "vocabulary_records": db.execute("SELECT COUNT(*) FROM catalog_vocabulary").fetchone()[0],
            "character_families": db.execute("SELECT COUNT(*) FROM character_family").fetchone()[0],
            "scope": "Internal source-backed metadata; physical copy, live matching precision and display rights remain separate"}


def import_families(db: sqlite3.Connection, rows: Iterable[dict]) -> int:
    count = 0
    with db:
        for row in rows:
            if row.get("schema") != "pokemon.character-family.v1":
                raise ValueError("unknown character family")
            core._required(row, "family_id", "members", "official_url", "official_page_sha256")
            _hash(row["official_page_sha256"])
            if not re.fullmatch(r"https://zukan\.pokemon\.co\.jp/detail/\d{4}", row["official_url"]):
                raise ValueError("family source must be official")
            members = row["members"]
            if not isinstance(members, list) or not members:
                raise ValueError("family members missing")
            ids = [m["dex_id"] for m in members]
            if len(set(ids)) != len(ids) or any(type(x) is not int or x < 1 for x in ids):
                raise ValueError("invalid family species IDs")
            parents = {m["dex_id"]:m["parent_dex_id"] for m in members}
            if sum(p is None for p in parents.values()) != 1:
                raise ValueError("family must have one root")
            for member in members:
                core._required(member, "name_ja", "name_en", "name_en_provenance")
                if member["parent_dex_id"] is not None and member["parent_dex_id"] not in ids:
                    raise ValueError("family parent is absent")
                visited = set(); node = member["dex_id"]
                while node is not None:
                    if node in visited:
                        raise ValueError("family lineage cycle")
                    visited.add(node); node = parents[node]
                english = db.execute("""SELECT 1 FROM card c JOIN discovery_card_facet f ON f.card_id=c.card_id
                    WHERE c.language='en' AND c.name=? AND c.provenance=? AND f.facet_type='dex_id' AND f.value=?""",
                    (member["name_en"], member["name_en_provenance"], str(member["dex_id"]))).fetchone()
                if not english:
                    raise ValueError("family English name lacks source evidence")
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            previous = db.execute("SELECT record_json FROM character_family WHERE family_id=?", (row["family_id"],)).fetchone()
            if previous and previous[0] != encoded:
                raise ValueError("conflicting family evidence")
            db.execute("INSERT OR IGNORE INTO character_family VALUES (?,?)", (row["family_id"], encoded))
            for m in members:
                db.execute("INSERT OR IGNORE INTO character_family_member VALUES (?,?,?,?,?)",
                           (row["family_id"], m["dex_id"], m["name_ja"], m["name_en"], m["parent_dex_id"]))
            count += 1
    return count
