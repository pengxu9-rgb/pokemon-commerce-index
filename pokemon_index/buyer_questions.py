"""Evidence-gated plans for card questions after an exact catalog identity is known.

The caller supplies a question type. Natural-language interpretation is deliberately
outside this module; a model may propose a type, but this function checks the graph.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import discovery_graph


QUESTION_TYPES = {
    "printing_variants", "english_or_japanese_counterpart", "same_artwork",
    "cross_region_price", "condition", "merchant_choice",
}
RELATION_TYPES = {
    "english_or_japanese_counterpart": {"localization_counterpart"},
    "same_artwork": {"same_artwork", "localization_counterpart"},
}


def plan_card_question(db: sqlite3.Connection, question_type: str,
                       card_id: str | None = None,
                       target_language: str | None = None) -> dict[str, Any]:
    """Return an internal answer plan, never a generated factual or price answer."""
    if question_type not in QUESTION_TYPES:
        raise ValueError("unsupported buyer question type")
    if target_language not in (None, "ja", "en"):
        raise ValueError("unsupported target language")
    result: dict[str, Any] = {
        "question_type": question_type, "card_id": card_id,
        "target_language": target_language, "price_comparable": False,
        "scope": "internal evidence plan; no public card display approval or live marketplace data",
    }
    if not card_id:
        result.update(status="need_exact_card", verified_links=[], candidate_leads=[],
                      required_inputs=["exact_card_id"],
                      next_question="Which exact language, set, collector number and printing do you mean?")
        return result
    neighborhood = discovery_graph.card_neighborhood(db, card_id)
    source = discovery_graph._card(db, card_id)
    if question_type in RELATION_TYPES:
        allowed = RELATION_TYPES[question_type]
        cross_language_only = question_type == "english_or_japanese_counterpart"
        links = [edge for edge in neighborhood["relationships"]
                 if edge["relation_type"] in allowed
                 and (not cross_language_only or edge["other_language"] != source["language"])
                 and (target_language is None or edge["other_language"] == target_language)]
        verified_card_ids = {edge["other_card_id"] for edge in links}
        # AI artwork proposals are research leads even for a counterpart question;
        # they never establish a counterpart or unlock a cross-card price join.
        leads = [edge for edge in neighborhood["ai_artwork_candidates"]
                 if (not cross_language_only or edge["other_language"] != source["language"])
                 and (target_language is None or edge["other_language"] == target_language)
                 and edge["other_card_id"] not in verified_card_ids]
        result.update(
            status="verified_links_available" if links else "relationship_review_needed",
            verified_links=[{"card_id": edge["other_card_id"],
                             "relation_type": edge["relation_type"],
                             "assertion_id": edge["assertion_id"],
                             "review_status": "verified"} for edge in links],
            candidate_leads=[{"card_id": edge["other_card_id"],
                              "relation_type": "same_artwork",
                              "assertion_id": edge["assertion_id"],
                              "review_status": "proposed"} for edge in leads],
            required_inputs=[] if links else ["card_specific_relationship_review"],
            next_question=("Which verified printing would you like to inspect?" if links else
                           "Would you like to inspect the unverified artwork leads?" if leads else
                           "Which candidate printing should be checked against this card?"),
            interpretation="The absence of a reviewed link does not prove that no related printing exists",
        )
        return result
    if question_type == "printing_variants":
        variants = neighborhood["variants_at_number"]
        result.update(status="structural_variants_available" if variants else "no_variant_recorded",
                      verified_links=[], candidate_leads=[
                          {"card_id": card["card_id"], "relation_type": "same_set_number",
                           "claim_status": "structural_only"} for card in variants],
                      required_inputs=[],
                      next_question="Which finish or physical printing do you want?" if variants else None,
                      interpretation="A shared set and number does not prove matching artwork or finish")
        return result
    requirements = {
        "cross_region_price": (["second_exact_card_id", "authorized_fresh_offers",
                                "currency_and_landed_cost"],
                               "Which exact printing in the other region should be compared?"),
        "condition": (["authorized_listing_id", "front_and_back_listing_photos",
                       "condition_review"],
                      "Which listing and its front and back photos should be assessed?"),
        "merchant_choice": (["authorized_fresh_offers", "landed_quotes",
                              "seller_fulfilment_evidence"],
                             "Which destination and current listings should be compared?"),
    }
    needed, question = requirements[question_type]
    result.update(status="market_evidence_needed", verified_links=[], candidate_leads=[],
                  required_inputs=needed, next_question=question,
                  interpretation="Catalog and graph metadata alone cannot establish this market claim")
    return result
