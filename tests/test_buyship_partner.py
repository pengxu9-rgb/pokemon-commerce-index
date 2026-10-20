import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def updated_observation(self, **changes):
        row = dict(self.db.execute("SELECT * FROM observation ORDER BY observed_at DESC LIMIT 1").fetchone())
        row.update(language="ja", condition_bucket="A", observed_at="2026-09-22T09:04:00Z")
        row.update(changes)
        core.import_observations(self.db, [row])

    def test_evidence_and_unverified_raw_labels(self):
        preview, _ = self.preview()
        self.assertEqual(preview["buyer_labels"]["label"], "raw, condition not assessed")
        self.assertFalse(preview["buyer_labels"]["certificate_verified"])
        self.assertEqual(preview["buyer_labels"]["real_verified_psa_inventory"], 0)
        self.assertEqual(preview["listing"]["evidence_ref"], "synthetic:test:1")
        self.assertEqual(preview["evidence"]["mode"], "synthetic_fixture")
        for key in ("observation_sha256", "listing_snapshot_sha256", "resolve_response_sha256",
                    "quote_response_sha256", "binding_sha256"):
            self.assertRegex(preview["evidence"][key], r"^[0-9a-f]{64}$")

    def test_seller_claimed_slab_is_labelled_without_certificate_verification(self):
        core.import_observations(self.db, [{"source": "licensed_fixture", "native_id": "demo-slab",
            "title": "ピカチュウ AR SV2a 173/165 PSA 10 鑑定品", "language": "ja",
            "url": "https://example.invalid/demo-slab", "observed_at": "2026-09-22T09:01:00Z",
            "status": "on_sale", "price_minor": 380000, "currency": "JPY", "evidence_ref": "synthetic:slab"}])
        unit = CARD_ID + "|PSA|10|graded"
        fixture = copy.deepcopy(FIXTURE)
        fixture["resolve"]["url"] = "https://example.invalid/demo-slab"
        result, _ = self.preview(fixture, unit_id=unit, native_id="demo-slab")
        self.assertEqual(result["buyer_labels"]["label"], "seller says PSA 10, certificate not verified")
        self.updated_observation(title="ピカチュウ AR SV2a 173/165 PSA 鑑定品")
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "no current"):
            self.preview(unit_id=unit, native_id="demo-slab", client=client)
        self.assertEqual(client.calls, [])

    def test_rights_refusals_make_zero_calls(self):
        for changes, message in (({"ingest_allowed": False}, "ingest policy"),
                                 ({"display_allowed": False}, "display"),
                                 ({"partner_handoff_allowed": False}, "not approved"),
                                 ({"expires_at": "2020-01-01T00:00:00Z"}, "expired")):
            with self.subTest(changes=changes):
                self.register_source(handoff=True)
                for key, value in changes.items():
                    self.db.execute(f"UPDATE source_policy SET {key}=?", (value,))
                self.db.commit()
                client = buyship_partner.FixturePartnerClient(FIXTURE)
                with self.assertRaisesRegex(ValueError, message):
                    self.preview(client=client)
                self.assertEqual(client.calls, [])

    def test_disabled_card_identity_makes_zero_calls(self):
        self.db.execute("UPDATE card SET match_eligible=0")
        self.db.commit()
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "not match-eligible"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_terminal_listing_states_make_zero_calls(self):
        for status in ("trading", "sold_out", "gone"):
            with self.subTest(status=status):
                self.updated_observation(status=status)
                client = buyship_partner.FixturePartnerClient(FIXTURE)
                with self.assertRaisesRegex(ValueError, "no current"):
                    self.preview(client=client)
                self.assertEqual(client.calls, [])
                self.db.execute("DELETE FROM observation WHERE observed_at>?", ("2026-09-22T09:00:00+00:00",))
                self.db.execute("UPDATE listing SET last_seen=?,current_status='on_sale'", ("2026-09-22T09:00:00+00:00",))
                self.db.commit()

    def test_historical_clock_cannot_hide_a_newer_observation(self):
        self.updated_observation(observed_at="2026-09-22T09:06:00Z")
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "newest observation"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_reviewed_raw_binding_cannot_hide_an_unreadable_slab(self):
        self.updated_observation(title="ピカチュウ AR SV2a 173/165 PSA 鑑定品")
        self.db.execute("UPDATE listing SET unit_id=?,resolution_method='human'", (UNIT_ID,))
        self.db.commit()
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "raw unit"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_inflight_observation_changes_are_refused_after_each_step(self):
        for phase in ("resolve", "quote"):
            with self.subTest(phase=phase):
                client = buyship_partner.FixturePartnerClient(FIXTURE)
                original = getattr(client, phase)
                def changed(*args):
                    response = original(*args)
                    self.updated_observation(price_minor=390000)
                    return response
                with patch.object(client, phase, side_effect=changed):
                    with self.assertRaisesRegex(ValueError, "snapshot"):
                        self.preview(client=client)
                self.assertEqual(len(client.calls), 1 if phase == "resolve" else 2)
                self.db.execute("DELETE FROM observation WHERE observed_at>?", ("2026-09-22T09:00:00+00:00",))
                self.db.execute("UPDATE listing SET last_seen=?,current_price_minor=380000", ("2026-09-22T09:00:00+00:00",))
                self.db.commit()

    def test_inflight_rights_revocation_stops_before_quote(self):
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        original = client.resolve
        def changed(url):
            response = original(url)
            self.register_source(handoff=False)
            return response
        with patch.object(client, "resolve", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "not approved"):
                self.preview(client=client)
        self.assertEqual([call["endpoint"] for call in client.calls], ["resolve"])

    def test_inflight_evidence_rewrite_is_refused(self):
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        original = client.quote
        def changed(*args):
            response = original(*args)
            self.db.execute("UPDATE observation SET evidence_ref='rewritten'")
            self.db.commit()
            return response
        with patch.object(client, "quote", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "snapshot"):
                self.preview(client=client)

    def test_concurrent_connection_cannot_reuse_the_pre_resolve_snapshot(self):
        original_db = self.db
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.sqlite3"
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            original_db.backup(self.db)
            other = sqlite3.connect(path)
            client = buyship_partner.FixturePartnerClient(FIXTURE)
            original_resolve = client.resolve
            def changed(url):
                response = original_resolve(url)
                other.execute("UPDATE source_policy SET partner_handoff_allowed=0")
                other.commit()
                return response
            try:
                with patch.object(client, "resolve", side_effect=changed):
                    with self.assertRaisesRegex(ValueError, "not approved"):
                        self.preview(client=client)
                self.assertEqual(len(client.calls), 1)
            finally:
                other.close()
                self.db.close()
                self.db = original_db

    def test_fixture_client_cannot_quote_or_mix_real_inventory(self):
        self.db.execute("UPDATE listing SET url='https://jp.mercari.com/item/m123'")
        self.db.execute("UPDATE observation SET url='https://jp.mercari.com/item/m123'")
        self.db.commit()
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "isolated synthetic"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_fixture_client_refuses_unrelated_real_inventory_added_inflight(self):
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        original = client.resolve
        def changed(url):
            response = original(url)
            self.updated_observation(native_id="real", url="https://jp.mercari.com/item/m123")
            return response
        with patch.object(client, "resolve", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "isolated synthetic"):
                self.preview(client=client)
        self.assertEqual(len(client.calls), 1)

    def test_duplicate_timestamp_listing_rewrite_is_refused(self):
        self.updated_observation(price_minor=390000, observed_at="2026-09-22T09:00:00Z")
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_current_storage_clock_and_snapshot_are_required(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        for stamp, message in (("2026-09-22T09:04:00Z", "future"),
                               ("2026-09-22T09:20:00Z", "expired")):
            with self.subTest(stamp=stamp):
                with self.assertRaisesRegex(ValueError, message):
                    buyship_partner.persist_quote_preview(self.db, preview, now=stamp)
        self.updated_observation(price_minor=390000, observed_at="2026-09-22T09:06:00Z")
        with self.assertRaisesRegex(ValueError, "snapshot"):
            buyship_partner.persist_quote_preview(self.db, preview, now="2026-09-22T09:07:00Z")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_missing_costs_and_malformed_or_mismatched_partner_fields_are_refused(self):
        changes = [
            (lambda p: p.update(resolve=[]), "different product URL"),
            (lambda p: p["resolve"].pop("reference_id"), "reference or variants"),
            (lambda p: p["resolve"].update(variants=[]), "reference or variants"),
            (lambda p: p["resolve"]["variants"][0].update(availability="sold_out"), "not in stock"),
            (lambda p: p["resolve"]["variants"][0].update(variant_key=""), "variant_key"),
            (lambda p: p["resolve"]["variants"][0].update(options=[]), "options"),
            (lambda p: p["resolve"]["variants"][0].update(price=None), "money"),
            (lambda p: p["resolve"].update(product=[]), "product name"),
            (lambda p: p["resolve"]["product"].update(name="ピカチュウ SV2a 172/165"), "card number"),
            (lambda p: p["resolve"]["product"].update(name="PSA 9 鑑定品"), "raw unit"),
            (lambda p: p["quote"].update(status="CLOSED"), "not open"),
            (lambda p: p["quote"].pop("quote_id"), "id or expiry"),
            (lambda p: p["quote"].update(destination={"country": "US", "state": "CA"}), "destination"),
            (lambda p: p["quote"].update(currency="hkd"), "invalid currency"),
            (lambda p: p["quote"].update(items=[]), "one item"),
            (lambda p: p["quote"]["items"][0].update(quantity=True), "differs"),
            (lambda p: p["quote"]["items"][0].update(reference_id="wrong"), "differs"),
            (lambda p: p["quote"]["items"][0].update(name="ピカチュウ SV2a 172/165"), "card number"),
            (lambda p: p["quote"]["items"][0].update(variant_options={"grade": "PSA9"}), "options"),
            (lambda p: p["quote"]["items"][0].update(availability="sold_out"), "not in stock"),
            (lambda p: p["quote"]["items"][0].update(url="https://example.invalid/other"), "different product URL"),
            (lambda p: p["quote"]["items"][0]["unit_price"].update(subunit_amount=1), "inconsistent"),
            (lambda p: p["quote"].pop("totals"), "lacks totals"),
            (lambda p: p["quote"]["totals"].pop("local_shipping"), "money"),
            (lambda p: p["quote"]["totals"]["duties"].update(subunit_amount=-1), "money"),
            (lambda p: p["quote"]["totals"]["duties"].update(subunit_amount=True), "money"),
            (lambda p: p["quote"]["totals"]["duties"].update(subunit_amount=2**63), "money"),
            (lambda p: p["quote"]["totals"]["duties"].update(currency="USD"), "mixed currencies"),
        ]
        for change, message in changes:
            with self.subTest(message=message, change=changes.index((change, message))):
                payload = copy.deepcopy(FIXTURE)
                change(payload)
                with self.assertRaisesRegex(ValueError, message):
                    self.preview(payload)

    def test_destination_currency_variant_and_client_preflight_refusals(self):
        for options, message in (({"destination": {"country": "JP"}}, "supports US and HK"),
                                 ({"destination": {"country": "US"}}, "needs a state"),
                                 ({"destination": {"country": "HK", "address": "private"}}, "no delivery address"),
                                 ({"currency": "hkd"}, "uppercase"),
                                 ({"currency": "USD"}, "differs from request"),
                                 ({"variant_key": "absent"}, "absent or duplicated"),
                                 ({"client": object()}, "unsupported")):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    self.preview(**options)

    def test_tampered_evidence_and_labels_cannot_be_stored(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        preview["buyer_labels"]["certificate_verified"] = True
        with self.assertRaisesRegex(ValueError, "evidence binding"):
            buyship_partner.persist_quote_preview(self.db, preview, now=NOW)

    def test_missing_evidence_and_caller_transaction_are_refused(self):
        self.register_source(handoff=True, store=True)
        preview, _ = self.preview()
        del preview["evidence"]
        with self.assertRaisesRegex(ValueError, "evidence binding"):
            buyship_partner.persist_quote_preview(self.db, preview, now=NOW)
        preview, _ = self.preview()
        self.db.execute("BEGIN")
        with self.assertRaisesRegex(ValueError, "own atomic transaction"):
            buyship_partner.persist_quote_preview(self.db, preview, now=NOW)
        self.db.rollback()

    def test_active_transaction_and_live_historical_clock_refused_before_calls(self):
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        self.db.execute("BEGIN")
        with self.assertRaisesRegex(ValueError, "active transaction"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])
        self.db.rollback()
        live = buyship_partner.PartnerClient("https://partner.example.invalid", "id", "secret")
        with patch.object(buyship_partner, "urlopen") as network:
            with self.assertRaisesRegex(ValueError, "current clock"):
                self.preview(client=live)
            network.assert_not_called()

    def test_live_quote_ranking_cannot_be_revived_by_a_fixture_clock(self):
        preview, _ = self.preview()
        preview["evidence"]["mode"] = "live"
        with self.assertRaisesRegex(ValueError, "historical clock"):
            buyship_partner.rank_quote_previews([preview], now=NOW)

    def test_reviewed_binding_with_newest_conflicting_card_number_is_refused(self):
        title = "ピカチュウ AR SV2a 172/165"
        self.db.execute("UPDATE listing SET title=?,resolution_method='human'", (title,))
        self.db.execute("UPDATE observation SET title=?", (title,))
        self.db.commit()
        client = buyship_partner.FixturePartnerClient(FIXTURE)
        with self.assertRaisesRegex(ValueError, "card number"):
            self.preview(client=client)
        self.assertEqual(client.calls, [])

    def test_malformed_buyer_claims_never_get_promoted_by_manual_raw_binding(self):
        for suffix in ("PSA10狙える", "2枚セット", "PSA10", "PSA10 PSA9 鑑定品"):
            with self.subTest(suffix=suffix):
                title = "ピカチュウ AR SV2a 173/165 " + suffix
                self.db.execute("UPDATE listing SET title=?,resolution_method='human'", (title,))
                self.db.execute("UPDATE observation SET title=?", (title,))
                self.db.commit()
                client = buyship_partner.FixturePartnerClient(FIXTURE)
                with self.assertRaisesRegex(ValueError, "newest title"):
                    self.preview(client=client)
                self.assertEqual(client.calls, [])

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
            buyship_partner.persist_quote_preview(self.db, preview, now=NOW)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_persisted_quote_reaches_existing_recommendation_and_expires(self):
        self.register_source(handoff=True, store=True)
        payload = copy.deepcopy(FIXTURE)
        payload["resolve"]["variants"][0]["price"]["subunit_amount"] = 390000
        preview, _ = self.preview(payload)
        self.assertEqual(buyship_partner.persist_quote_preview(self.db, preview, now=NOW), 1)
        self.assertEqual(buyship_partner.persist_quote_preview(self.db, preview, now=NOW), 0)
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
        buyship_partner.persist_quote_preview(self.db, preview, now=NOW)
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
        buyship_partner.persist_quote_preview(self.db, preview, now=NOW)
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
            buyship_partner.persist_quote_preview(self.db, changed, now=NOW)
        changed = copy.deepcopy(preview)
        changed["listing"]["observed_at"] = "2026-09-22T08:00:00Z"
        with self.assertRaisesRegex(ValueError, "snapshot"):
            buyship_partner.persist_quote_preview(self.db, changed, now=NOW)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_shortlist_storage_is_atomic(self):
        self.register_source(handoff=True, store=True)
        good, _ = self.preview()
        bad = copy.deepcopy(good)
        bad["listing"]["native_id"] = "missing-listing"
        with self.assertRaisesRegex(ValueError, "snapshot"):
            buyship_partner.persist_quote_previews(self.db, [good, bad], now=NOW)
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
    def test_default_transport_requires_owner_authorization_before_oauth(self):
        client = buyship_partner.PartnerClient("https://partner.example.invalid", "id", "secret")
        with patch.object(buyship_partner, "urlopen") as network:
            with self.assertRaisesRegex(ValueError, "explicit owner authorization"):
                client.resolve("https://example.invalid/card")
            network.assert_not_called()

    def test_offline_rehearsal_opens_no_production_db_and_stores_no_quotes(self):
        from scripts.rehearse_c2c_bns_quote import rehearse
        report = rehearse()
        self.assertEqual(report["network_calls"], 0)
        self.assertFalse(report["production_database_opened"])
        self.assertEqual(report["stored_quotes"], 0)
        self.assertEqual(len(report["previews"]), 2)
        self.assertFalse(report["order_created"])

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
