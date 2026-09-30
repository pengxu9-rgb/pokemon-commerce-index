import copy
import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import buyship_partner, core


FIXTURE = json.loads((Path(__file__).parents[1] / "examples" /
                      "buyship_partner_preview.json").read_text(encoding="utf-8"))
NOW = "2026-09-22T09:05:00Z"
CARD_ID = "ja:SV2A:173/165:standard"
UNIT_ID = CARD_ID + "|RAW|raw|a"


class PartnerPreviewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.register_source(handoff=True)
        core.import_cards(self.db, [{"match_eligible": True,
            "language": "ja", "set_code": "SV2a", "collector_number": "173/165",
            "variant": "standard", "name": "ピカチュウ AR", "rarity": "AR",
            "provenance": "synthetic test", "rights_reference": "synthetic test",
            "display_allowed": True,
        }])
        core.import_observations(self.db, [{
            "source": "licensed_fixture", "native_id": "demo-2",
            "title": "ピカチュウ AR SV2a 173/165",
            "url": "https://example.invalid/demo-2", "language": "ja",
            "condition_bucket": "A", "observed_at": "2026-09-22T09:00:00Z",
            "status": "on_sale", "price_minor": 380000, "currency": "JPY",
            "evidence_ref": "synthetic:test:1",
        }])

    def tearDown(self):
        self.db.close()

    def register_source(self, *, handoff, store=False):
        core.register_source(self.db, {
            "source": "licensed_fixture", "rights_reference": "synthetic test",
            "ingest_allowed": True, "display_allowed": True,
            "partner_handoff_allowed": handoff,
            "partner_quote_store_allowed": store,
            "retention_days": 1, "listing_ttl_hours": 24,
        })

    def preview(self, payload=None, **kwargs):
        client = buyship_partner.FixturePartnerClient(copy.deepcopy(payload or FIXTURE))
        options = dict(card_id=CARD_ID, unit_id=UNIT_ID, source="licensed_fixture",
                       native_id="demo-2", destination={"country": "HK"},
                       client=client, now=NOW)
        options.update(kwargs)
        return buyship_partner.preview_quote(self.db, **options), client

    def test_exact_offer_to_binding_quote_preview_without_order(self):
        result, client = self.preview()
        self.assertEqual([call["endpoint"] for call in client.calls], ["resolve", "quote"])
        self.assertEqual(client.calls[0]["url"], "https://example.invalid/demo-2")
        self.assertEqual(result["card_id"], CARD_ID)
        self.assertEqual(result["unit_id"], UNIT_ID)
        self.assertEqual(result["buyship"]["grand_total"],
                         {"currency": "HKD", "subunit_amount": 24060})
        self.assertEqual(result["buyship"]["expires_at"], "2026-09-22T09:20:00Z")
        self.assertFalse(result["purchasable"])
        self.assertIsNone(result["purchase_action"])
        self.assertFalse(result["order_created"])

    def test_disallowed_handoff_stops_before_partner_call(self):
        self.register_source(handoff=False)
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_wrong_card_unit_or_expired_listing_stops_before_partner_call(self):
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "no current"):
            self.preview(unit_id=CARD_ID + "|RAW|raw|unknown", client=client)
        self.assertEqual(client.calls, [])
        with self.assertRaisesRegex(ValueError, "no current"):
            self.preview(now="2026-09-24T09:05:00Z", client=client)
        self.assertEqual(client.calls, [])

    def test_url_switch_is_rejected_before_quote(self):
        payload = copy.deepcopy(FIXTURE)
        payload["resolve"]["url"] = "https://example.invalid/another-card"
        client = buyship_partner.FixturePartnerClient(payload)
        with self.assertRaisesRegex(ValueError, "different product URL"):
            self.preview(client=client)
        self.assertEqual([call["endpoint"] for call in client.calls], ["resolve"])

    def test_multiple_variants_need_explicit_selection(self):
        payload = copy.deepcopy(FIXTURE)
        second = copy.deepcopy(payload["resolve"]["variants"][0])
        second["variant_key"] = "another-card-condition"
        payload["resolve"]["variants"].append(second)
        with self.assertRaisesRegex(ValueError, "explicit variant_key"):
            self.preview(payload)
        result, client = self.preview(payload, variant_key="fixture-variant-1")
        self.assertEqual(result["buyship"]["variant_key"], "fixture-variant-1")
        self.assertEqual(client.calls[-1]["variant_key"], "fixture-variant-1")

    def test_quote_expiry_item_and_math_are_enforced(self):
        for change, message in (
            (lambda p: p["quote"].update(expires_at=NOW), "expired"),
            (lambda p: p["quote"]["items"][0].update(variant_key="different"), "differs"),
            (lambda p: p["quote"]["totals"]["grand_total"].update(subunit_amount=1), "reconcile"),
        ):
            with self.subTest(message=message):
                payload = copy.deepcopy(FIXTURE)
                change(payload)
                with self.assertRaisesRegex(ValueError, message):
                    self.preview(payload)

    def test_changed_resolve_price_is_visible(self):
        payload = copy.deepcopy(FIXTURE)
        payload["resolve"]["variants"][0]["price"]["subunit_amount"] = 390000
        result, _ = self.preview(payload)
        self.assertTrue(result["buyship"]["resolve_price_differs_from_observation"])
        self.assertEqual(result["listing"]["ask"]["subunit_amount"], 380000)

    def test_url_query_change_is_not_silently_accepted(self):
        payload = copy.deepcopy(FIXTURE)
        payload["resolve"]["url"] += "?item=another"
        with self.assertRaisesRegex(ValueError, "different product URL"):
            self.preview(payload)

    def test_shortlist_ranks_same_unit_by_delivered_quote_only(self):
        core.import_observations(self.db, [{
            "source": "licensed_fixture", "native_id": "demo-3",
            "title": "ピカチュウ AR SV2a 173/165",
            "url": "https://example.invalid/demo-3", "language": "ja",
            "condition_bucket": "A", "observed_at": "2026-09-22T09:00:00Z",
            "status": "on_sale", "price_minor": 400000, "currency": "JPY",
            "evidence_ref": "synthetic:test:2",
        }])
        second_fixture = json.loads((Path(__file__).parents[1] / "examples" /
                                     "buyship_partner_preview_2.json").read_text(encoding="utf-8"))
        first, _ = self.preview()
        second, _ = self.preview(second_fixture, native_id="demo-3")
        ranked = buyship_partner.rank_quote_previews([second, first], now=NOW)
        self.assertEqual(ranked["best"]["listing"]["native_id"], "demo-2")
        self.assertEqual(ranked["alternatives"][0]["listing"]["native_id"], "demo-3")
        self.assertFalse(ranked["purchasable"])
        with self.assertRaisesRegex(ValueError, "mixes"):
            changed = copy.deepcopy(second)
            changed["unit_id"] = "another-printing"
            buyship_partner.rank_quote_previews([first, changed], now=NOW)
        with self.assertRaisesRegex(ValueError, "expired"):
            buyship_partner.rank_quote_previews([first], now="2026-09-22T09:20:00Z")

    def test_partner_quote_storage_requires_distinct_permission(self):
        preview, _ = self.preview()
        with self.assertRaisesRegex(ValueError, "storage is not approved"):
            buyship_partner.persist_quote_preview(self.db, preview)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_persisted_quote_reaches_existing_recommendation_and_expires(self):
        self.register_source(handoff=True, store=True)
        payload = copy.deepcopy(FIXTURE)
        payload["resolve"]["variants"][0]["price"]["subunit_amount"] = 390000
        preview, _ = self.preview(payload)
        self.assertEqual(buyship_partner.persist_quote_preview(self.db, preview), 1)
        self.assertEqual(buyship_partner.persist_quote_preview(self.db, preview), 0)
        result = core.recommend(self.db, UNIT_ID, "HK", "2026-09-22T09:06:00Z")
        self.assertEqual(result["recommendation_type"], "price_only")
        quote = result["recommendation"]["quote"]
        self.assertEqual(quote["total_minor"], 24060)
        self.assertEqual(quote["assumptions"]["provider"], "buyship_partner_v1")
        self.assertTrue(quote["assumptions"]["resolve_price_differs_from_observation"])
        self.assertIsNone(core.recommend(self.db, UNIT_ID, "HK",
                                         "2026-09-22T09:20:00Z")["recommendation"])

    def test_new_listing_observation_invalidates_previous_partner_quote(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        buyship_partner.persist_quote_preview(self.db, preview)
        core.import_observations(self.db, [{
            "source": "licensed_fixture", "native_id": "demo-2",
            "title": "ピカチュウ AR SV2a 173/165",
            "url": "https://example.invalid/demo-2", "language": "ja",
            "condition_bucket": "A", "observed_at": "2026-09-22T09:06:00Z",
            "status": "on_sale", "price_minor": 390000, "currency": "JPY",
            "evidence_ref": "synthetic:test:price-edit",
        }])
        self.assertIsNone(core.recommend(self.db, UNIT_ID, "HK",
                                         "2026-09-22T09:07:00Z")["recommendation"])

    def test_revoked_quote_storage_permission_hides_existing_quote(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        buyship_partner.persist_quote_preview(self.db, preview)
        self.register_source(handoff=True, store=False)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)
        result = core.recommend(self.db, UNIT_ID, "HK", "2026-09-22T09:06:00Z")
        self.assertIsNone(result["recommendation"])
        self.assertEqual(len(result["offers"]), 1)
        self.assertIsNone(result["offers"][0]["quote"])

    def test_tampered_preview_cannot_be_stored(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        changed = copy.deepcopy(preview)
        changed["buyship"]["components"]["bns_service_fee"]["subunit_amount"] = 1
        with self.assertRaisesRegex(ValueError, "reconcile"):
            buyship_partner.persist_quote_preview(self.db, changed)
        changed = copy.deepcopy(preview)
        changed["listing"]["observed_at"] = "2026-09-22T08:00:00Z"
        with self.assertRaisesRegex(ValueError, "snapshot"):
            buyship_partner.persist_quote_preview(self.db, changed)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_shortlist_storage_is_atomic(self):
        self.register_source(handoff=True, store=True)
        good, _ = self.preview()
        bad = copy.deepcopy(good)
        bad["listing"]["native_id"] = "missing-listing"
        with self.assertRaisesRegex(ValueError, "snapshot"):
            buyship_partner.persist_quote_previews(self.db, [good, bad])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_cross_source_price_ranking_requires_comparison_permission(self):
        first, _ = self.preview()
        core.register_source(self.db, {
            "source": "second_fixture", "rights_reference": "synthetic test",
            "ingest_allowed": True, "display_allowed": True,
            "partner_handoff_allowed": True,
            "cross_source_use_allowed": False,
            "retention_days": 1, "listing_ttl_hours": 24,
        })
        core.import_observations(self.db, [{
            "source": "second_fixture", "native_id": "demo-3",
            "title": "ピカチュウ AR SV2a 173/165",
            "url": "https://example.invalid/demo-3", "language": "ja",
            "condition_bucket": "A", "observed_at": "2026-09-22T09:00:00Z",
            "status": "on_sale", "price_minor": 400000, "currency": "JPY",
            "evidence_ref": "synthetic:test:second-source",
        }])
        second_fixture = json.loads((Path(__file__).parents[1] / "examples" /
                                     "buyship_partner_preview_2.json").read_text(encoding="utf-8"))
        second, _ = self.preview(second_fixture, source="second_fixture", native_id="demo-3")
        with self.assertRaisesRegex(ValueError, "cross-source"):
            buyship_partner.rank_quote_previews([first, second], now=NOW, db=self.db)


class PartnerClientTests(unittest.TestCase):
    def test_oauth_refreshes_once_on_401_and_only_resolves(self):
        calls = []

        def sender(request):
            calls.append((request.full_url, request.get_header("Authorization")))
            if request.full_url.endswith("/oauth/token"):
                return 200, {"access_token": f"token-{len(calls)}", "expires_in": 3600}
            if len(calls) == 2:
                return 401, {"error": {"code": "unauthorized", "retryable": False}}
            return 200, {"url": "https://example.invalid/card"}

        client = buyship_partner.PartnerClient("https://partner.example.invalid", "id", "secret",
                                               sender=sender)
        self.assertEqual(client.resolve("https://example.invalid/card")["url"],
                         "https://example.invalid/card")
        self.assertEqual(len(calls), 4)
        self.assertTrue(calls[0][1].startswith("Basic "))
        self.assertTrue(calls[1][1].startswith("Bearer "))
        self.assertNotEqual(calls[1][1], calls[3][1])

    def test_oauth_error_and_insecure_product_url(self):
        def denied(_request):
            return 401, {"error": "invalid_client", "error_description": "failed"}

        client = buyship_partner.PartnerClient("https://partner.example.invalid", "id", "secret",
                                               sender=denied)
        with self.assertRaises(buyship_partner.PartnerAPIError) as context:
            client.resolve("https://example.invalid/card")
        self.assertEqual(context.exception.code, "invalid_client")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            client.resolve("http://example.invalid/card")


if __name__ == "__main__":
    unittest.main()
