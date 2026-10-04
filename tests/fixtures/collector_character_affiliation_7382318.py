# Frozen unbatched 7382318 implementation: test oracle only, never runtime code.
"""Explicit source-pinned EX-name retrieval affiliations, not new catalog dex facts.

The target sources omit dexId. Their exact names/category/EX suffix are pinned
separately; a species signal is derived only from unanimous, current Japanese
base-name facets. No substring expansion or physical/graph/commerce approval.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from pokemon_index import supported_catalog, collector_character_affiliation

BINDINGS_PATH = collector_character_affiliation.BINDINGS_PATH
DERIVATION = "exact_pinned_ex_name_to_unanimous_current_name_facets.v1"
MAX_BINDINGS = 27


def _bindings():
    payload = json.loads(BINDINGS_PATH.read_text())
    if payload.get("schema") != "pokemon.source-name-character-affiliation-bindings.v1":
        raise ValueError("unsupported source-name affiliation bindings")
    rows = payload.get("records")
    if not isinstance(rows, list) or len(rows) != MAX_BINDINGS:
        raise ValueError("source-name affiliation requires 27 explicit source bindings")
    if len({row.get("card_id") for row in rows}) != len(rows):
        raise ValueError("duplicate source-name affiliation target")
    return rows


def _anchors(db, base_name):
    rows = db.execute("""SELECT c.card_id,c.name,c.provenance card_provenance,
            c.rights_reference card_rights_reference,
            f.value,f.provenance,f.rights_reference,k.provenance classification_provenance,
            k.rights_reference classification_rights_reference
        FROM card c JOIN discovery_card_facet f ON f.card_id=c.card_id AND f.facet_type='dex_id'
        JOIN card_classification k ON k.card_id=c.card_id AND k.category='Pokemon'
        WHERE c.language='ja' AND c.name=? ORDER BY c.card_id,f.value,f.provenance""", (base_name,)).fetchall()
    current = []
    for row in rows:
        if (row["classification_provenance"] != row["card_provenance"] or
                row["classification_rights_reference"] != row["card_rights_reference"] or
                not row["rights_reference"] or not re.fullmatch(r"[1-9][0-9]{0,3}", row["value"])):
            continue
        # Raw facets must still describe this source snapshot. Official overlays
        # must be present in the existing active, snapshot-bound evidence view.
        if row["provenance"] == row["card_provenance"] and row["rights_reference"] != row["card_rights_reference"]:
            continue
        if row["provenance"] != row["card_provenance"] and not db.execute(
                "SELECT 1 FROM active_card_metadata_evidence WHERE card_id=? AND evidence_id=?",
                (row["card_id"], row["provenance"])).fetchone():
            continue
        current.append({"card_id": row["card_id"], "name": row["name"],
                        "dex_id": int(row["value"]), "provenance": row["provenance"],
                        "rights_reference": row["rights_reference"]})
    # A multi-character or contradictory source cannot be converted into an
    # arbitrary single-species label. Check all current anchors before sampling.
    if not current or len({row["dex_id"] for row in current}) != 1:
        return None
    dex_id = current[0]["dex_id"]
    if not 1 <= dex_id <= 1025:
        return None
    return dex_id, current


def affiliations(db):
    """Return current bounded derivations keyed by target ID; never write facts.

    Consumers should call once per candidate-pool build and reuse the result for
    explicit/liked matches and exclusions. An absent entry is not an exclusion
    from broad catalog research, only unavailable derived character evidence.
    """
    result = {}
    anchors = {}
    for binding in _bindings():
        identity = binding.get("identity", {})
        cid = binding.get("card_id")
        base_name = binding.get("base_name_ja")
        source_ref = binding.get("source_ref", "")
        if (binding.get("schema") != "pokemon.source-name-character-affiliation.v1" or
                not isinstance(base_name, str) or not base_name or
                identity.get("card_id") != cid or identity.get("language") != "ja" or
                identity.get("set_code") != "SV4A" or identity.get("name") != base_name + "ex" or
                identity.get("provenance") != source_ref or
                binding.get("declared_category") != "Pokemon" or binding.get("declared_suffix") != "EX" or
                not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("source_sha256", ""))) or
                not source_ref.endswith(":sha256:" + binding["source_sha256"]) or
                any(binding.get(field) is not False for field in (
                    "source_asserted_dex_id", "physical_printing_verified",
                    "automatic_offer_join_allowed", "public_display_allowed"))):
            continue
        card = db.execute("SELECT * FROM card WHERE card_id=?", (cid,)).fetchone()
        if (card is None or supported_catalog.identity_snapshot(card) != identity or
                card["rights_reference"] != binding.get("target_rights_reference")):
            continue
        support = supported_catalog.support_for_card(db, cid)
        if (support["status"] != "supported_for_internal_review" or
                supported_catalog.digest(support["evidence"]) != binding.get("supported_record_sha256")):
            continue
        classification = db.execute("SELECT category,provenance,rights_reference FROM card_classification WHERE card_id=?",
                                    (cid,)).fetchone()
        if not classification or tuple(classification) != ("Pokemon", source_ref, binding["target_rights_reference"]):
            continue
        # Never override a direct/current species assertion or its conflicts.
        if db.execute("SELECT 1 FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id'",
                      (cid,)).fetchone():
            continue
        if base_name not in anchors:
            anchors[base_name] = _anchors(db, base_name)
        matched = anchors[base_name]
        if matched is None:
            continue
        dex_id, evidence = matched
        result[cid] = {
            "card_id": cid, "dex_id": dex_id,
            "reason": {"field": "character_name_affiliation", "value": dex_id,
                       "basis": "source_name_character_affiliation", "source_ref": source_ref,
                       "target_name": identity["name"], "base_name_ja": base_name, "mechanic": "EX",
                       "source_asserted_dex_id": False, "anchor_evidence": evidence[:1],
                       "anchor_count": len(evidence),
                       "anchor_evidence_sha256": supported_catalog.digest({"anchors": evidence}),
                       "derivation": DERIVATION},
        }
    return result
