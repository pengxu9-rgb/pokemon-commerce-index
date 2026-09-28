import json
import sqlite3
import unittest

from pokemon_index import core, discovery_graph, offer_comparison


class OfferComparisonTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        for source in ("jp_feed", "en_feed"):
            core.register_source(self.db, {
                "source": source, "rights_reference": "synthetic licensed fixture",
                "ingest_allowed": True, "display_allowed": True,
                "cross_source_use_allowed": True, "media_ai_allowed": True,
                "cross_region_use_allowed": True, "retention_days": 30,
                "listing_ttl_hours": 24,
            })
        core.import_cards(self.db, [
            {"language": "ja", "set_code": "S1", "collector_number": "001/100",
             "variant": "normal", "name": "カード", "provenance": "fixture",
             "rights_reference": "fixture", "display_allowed": True},
            {"language": "en", "set_code": "E1", "collector_number": "002/100",
             "variant": "normal", "name": "Card", "provenance": "fixture",
             "rights_reference": "fixture", "display_allowed": True},
        ])
        self.ja = "ja:S1:001/100:normal"
        self.en = "en:E1:002/100:normal"
        self.at = "2026-09-25T09:00:00Z"
        discovery_graph.assert_relationships(self.db, [{
            "assertion_id": "fixture-ai-art", "left_card_id": self.en,
            "right_card_id": self.ja, "relation_type": "same_artwork",
            "review_status": "proposed", "evidence_ref": "fixture:two-hashed-images",
            "rights_reference": "synthetic fixture", "asserted_by": "ai-artwork-review-v1",
            "reviewer": "gemini-3.8-flash",
        }])
        for source, native, card, currency, price in (
                ("jp_feed", "j1", self.ja, "JPY", 10000),
                ("en_feed", "e1", self.en, "USD", 90)):
            core.import_observations(self.db, [{
                "source": source, "native_id": native, "title": native,
                "url": f"https://example.invalid/{native}",
                "observed_at": self.at, "status": "on_sale",
                "currency": currency, "price_minor": price,
                "card_id": card, "evidence_ref": "fixture:observation",
            }])
            offer_comparison.import_media(self.db, [{
                "source": source, "native_id": native, "observed_at": self.at,
                "front_ref": f"https://example.invalid/{native}-front",
                "front_sha256": "a" * 64,
                "back_ref": f"https://example.invalid/{native}-back",
                "back_sha256": "b" * 64,
                "rights_reference": "synthetic fixture permits AI image analysis",
            }])
            core.import_quotes(self.db, [{
                "source": source, "native_id": native, "destination": "HK",
                "currency": "HKD", "components": {
                    "item": 10000 if source == "jp_feed" else 12000,
                    "domestic": 0, "service": 1000, "international": 0,
                    "tax": 0, "insurance": 0, "fx_spread": 0, "other": 0,
                }, "quoted_at": "2026-09-25T09:05:00Z",
                "expires_at": "2026-09-25T11:00:00Z",
                "evidence_ref": f"fixture:quote:{native}",
                "assumptions": {"source_price_minor": price,
                                "source_currency": currency,
                                "fx_rate_ref": "fixture:dated-fx",
                                "fee_schedule_ref": "fixture:fees-v1",
                                "tax_basis": "fixture:tax"},
            }])

    def tearDown(self):
        self.db.close()

    def review(self, source, native, card, family, condition="near_mint"):
        provider = "vertex" if family == "google" else family
        return {"review_id": f"{source}:{family}:{condition}",
                "source": source, "native_id": native, "observed_at": self.at,
                "card_id": card, "model_family": family,
                "model_version": family + "-fixture", "reviewed_at": "2026-09-25T09:10:00Z",
                "front_sha256": "a" * 64, "back_sha256": "b" * 64,
                "identity_decision": "match", "observed_finish": "normal",
                "finish_decision": "match", "condition_bucket": condition,
                "condition_decision": "assessed",
                "evidence_ref": provider + ":response-sha256:" + "c" * 64,
                "rationale": "Visible number, set, normal finish, front and back condition"}

    def accept_both(self):
        for source, native, card in (("jp_feed", "j1", self.ja),
                                     ("en_feed", "e1", self.en)):
            offer_comparison.import_visual_reviews(self.db, [
                self.review(source, native, card, "google"),
                self.review(source, native, card, "openai"),
            ])

    def verify_artwork_edge(self):
        event_id = "fixture-verified-artwork"
        evidence = {
            "schema": "pokemon.relationship_review.v1",
            "review_event_id": event_id, "source_snapshot_sha256": "0" * 64,
            "cards": [{"card_id": card, "source_ref": "fixture:" + card,
                       "source_kind": "fixture", "identity_checked": True}
                      for card in (self.en, self.ja)],
            "first_review": {"reviewer": "first", "decision": "same_artwork",
                             "reviewed_at": "2026-09-25T09:00:00Z"},
            "second_review": {"reviewer": "second", "decision": "same_artwork",
                              "reviewed_at": "2026-09-25T09:01:00Z"},
            "artwork": {"outcome": "same", "note": "synthetic match"},
            "finish": {"outcome": "same", "note": "synthetic finish"},
            "rationale": "synthetic reviewed artwork relation",
        }
        discovery_graph.assert_relationships(self.db, [{
            "assertion_id": event_id, "left_card_id": self.en,
            "right_card_id": self.ja, "relation_type": "same_artwork",
            "review_status": "verified", "evidence_ref": json.dumps(evidence),
            "rights_reference": "synthetic fixture", "asserted_by": "fixture",
            "reviewer": "second",
        }])

    def test_landed_spread_requires_two_models_photos_and_bound_quotes(self):
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("comparisons", result)
        self.verify_artwork_edge()
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.accept_both()
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["relationship_status"], "verified")
        self.assertEqual(result["relationship_basis"], "reviewed_same_artwork")
        self.assertEqual(result["artwork_review_count"], 2)
        self.assertEqual(result["identity_certainty"], "reviewed_artwork_only")
        self.assertIn("paid_sale", result["excluded_dimensions"])
        comparison = result["comparisons"][0]
        self.assertEqual(comparison["en_minus_ja_minor"], 2000)
        self.assertEqual(comparison["en_minus_ja_percent_bps"], 1818)
        self.assertEqual(comparison["currency"], "HKD")
        self.assertEqual(comparison["ja"]["n_eligible_in_bucket"], 1)
        self.assertEqual(offer_comparison.import_visual_reviews(
            self.db, [self.review("jp_feed", "j1", self.ja, "google")]), 0)

    def test_conflicting_condition_blocks_numeric_gap(self):
        self.verify_artwork_edge()
        self.accept_both()
        offer_comparison.import_visual_reviews(self.db, [
            self.review("en_feed", "e1", self.en, "openai", "light_played")])
        gate = offer_comparison.visual_gate(self.db, "en_feed", "e1", self.at, self.en)
        self.assertEqual(gate["status"], "exception_review")
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_photo_rights_and_quote_freshness_are_hard_gates(self):
        self.verify_artwork_edge()
        self.accept_both()
        core.register_source(self.db, {
            "source": "en_feed", "rights_reference": "fixture permission changed",
            "ingest_allowed": True, "display_allowed": True,
            "cross_source_use_allowed": True, "media_ai_allowed": False,
            "cross_region_use_allowed": False, "retention_days": 30,
            "listing_ttl_hours": 24,
        })
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "insufficient_evidence")
        with self.assertRaisesRegex(ValueError, "media AI permission"):
            offer_comparison.import_media(self.db, [{
                "source": "en_feed", "native_id": "e1", "observed_at": self.at,
                "front_ref": "https://example.invalid/e1-front", "front_sha256": "a" * 64,
                "back_ref": "https://example.invalid/e1-back", "back_sha256": "b" * 64,
                "rights_reference": "fixture"}])

    def test_price_change_invalidates_earlier_quote_and_visual_snapshot(self):
        self.verify_artwork_edge()
        self.accept_both()
        core.import_observations(self.db, [{
            "source": "en_feed", "native_id": "e1", "title": "e1 updated",
            "url": "https://example.invalid/e1", "observed_at": "2026-09-25T09:20:00Z",
            "status": "on_sale", "currency": "USD", "price_minor": 95,
            "card_id": self.en, "evidence_ref": "fixture:price-edit",
        }])
        result = offer_comparison.compare_landed_asks(
            self.db, self.ja, self.en, "HK", "2026-09-25T09:30:00Z")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["sides"]["en"]["blocked"]["missing_bound_quote"], 1)

    def test_visual_review_cannot_override_resolved_card_identity(self):
        with self.assertRaisesRegex(ValueError, "conflicts with resolved"):
            offer_comparison.import_visual_reviews(
                self.db, [self.review("jp_feed", "j1", self.en, "google")])


if __name__ == "__main__":
    unittest.main()
