"""Pure adapters: captured data in, normalized observations out; sockets denied."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pokemon_index import core, marketplace_sources as sources


FIXTURES = Path(__file__).parents[1] / "examples" / "marketplace_tracking"


def capture(name="mercari"):
    return json.loads((FIXTURES / f"{name}_fixture.json").read_text())


class MarketplaceSourceTests(unittest.TestCase):
    def test_explicit_unavailable_or_ambiguous_stock_never_refreshes_ebay_ask(self):
        for value in ([], None, [{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}],
                      [{"estimatedAvailabilityStatus": "UNKNOWN"}],
                      [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 0}],
                      [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": True}]):
            with self.subTest(availability=value):
                item = capture("ebay")
                item["payload"]["itemSummaries"][0]["estimatedAvailabilities"] = value
                with self.assertRaises(ValueError):
                    sources.normalize_capture(item)
        item = capture("ebay")
        item["payload"]["itemSummaries"][0]["estimatedAvailabilities"] = [
            {"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 1}]
        self.assertEqual(sources.normalize_capture(item)["observations"][0]["status"], "on_sale")

    def setUp(self):
        self.network = patch("socket.create_connection", side_effect=AssertionError("offline adapter"))
        self.network.start()
        self.socket = patch("socket.socket.connect", side_effect=AssertionError("offline adapter"))
        self.socket.start()

    def tearDown(self):
        self.socket.stop()
        self.network.stop()

    def test_three_fixture_contracts_preserve_native_units_and_unverified_quality(self):
        for name, prices in (("mercari", [3800, 12000]), ("snkrdunk", [4200, 13500]),
                             ("ebay", [2995, 9950])):
            with self.subTest(source=name):
                original = capture(name)
                before = copy.deepcopy(original)
                result = sources.normalize_capture(original)
                self.assertEqual(original, before)
                self.assertEqual([row["price_minor"] for row in result["observations"]], prices)
                self.assertEqual(result["coverage"]["returned_count"], 2)
                self.assertTrue(result["coverage"]["fixture"])
                self.assertTrue(result["coverage"]["nonappearance_is_not_sold"])
                self.assertFalse(result["coverage"]["live_collection_verified"])
                raw, slab = [row["marketplace_quality"] for row in result["observations"]]
                self.assertIsNone(raw["grade_company"])
                self.assertEqual((slab["grade_company"], slab["grade_value"]), ("PSA", "10"))
                for row in result["observations"]:
                    self.assertFalse(row["marketplace_quality"]["certificate_verified"])
                    self.assertFalse(row["marketplace_quality"]["authenticity_verified"])
                    self.assertFalse(row["marketplace_quality"]["physical_inspection_performed"])
                    self.assertIn(".invalid", row["url"])
                    self.assertRegex(row["evidence_ref"], r"sha256:[0-9a-f]{64}$")

    def test_export_language_is_explicit_and_never_inferred_from_marketplace(self):
        payload = capture()
        payload["payload"]["listings"][0].pop("language")
        result = sources.normalize_capture(payload)
        self.assertNotIn("language", result["observations"][0])
        payload["payload"]["listings"][0]["language"] = "JA"
        with self.assertRaisesRegex(ValueError, "canonical"):
            sources.normalize_capture(payload)

    def test_capture_and_request_require_explicit_schema_and_discovery_only(self):
        for field, value in (("schema", "unknown"), ("source", "other"),
                             ("payload_schema", "guessed-private-api"),
                             ("observed_at", "2026-10-20T12:00:00"),
                             ("observed_at", "2026-10-20T12:00:00+09:00")):
            with self.subTest(field=field, value=value):
                payload = capture(); payload[field] = value
                with self.assertRaises(ValueError):
                    sources.normalize_capture(payload)
        for request in ({"kind": "search", "access_token": "never-store"},
                        {"kind": "detail", "url": "https://example.invalid/secret"},
                        {"kind": "search", "query": "https://example.invalid/secret"},
                        {"kind": "search", "page": True}, {"kind": "search", "native_ids": []}):
            payload = capture(); payload["request"] = request
            with self.assertRaises(ValueError):
                sources.normalize_capture(payload)

    def test_fixture_and_real_domain_scopes_cannot_be_mixed(self):
        payload = capture()
        payload["payload"]["listings"][0]["url"] = "https://jp.mercari.com/item/m1001"
        with self.assertRaisesRegex(ValueError, "fixture"):
            sources.normalize_capture(payload)
        payload = capture(); payload["source"] = "mercari"
        with self.assertRaisesRegex(ValueError, "canonical"):
            sources.normalize_capture(payload)
        for item in payload["payload"]["listings"]:
            item["url"] = "https://jp.mercari.com/item/" + item["listing_id"]
        result = sources.normalize_capture(payload)
        self.assertEqual(result["source"], "mercari")
        self.assertFalse(result["coverage"]["fixture"])
        payload["payload"]["listings"][0]["url"] = "https://jp.mercari.com.evil.invalid/item/m1001"
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)

    def test_native_ebay_canonical_url_is_bound_to_item_id(self):
        payload = capture("ebay"); payload["source"] = "ebay_us"
        for item in payload["payload"]["itemSummaries"]:
            item["itemWebUrl"] = "https://www.ebay.com/itm/" + item["itemId"].split("|")[1]
        result = sources.normalize_capture(payload)
        self.assertFalse(result["coverage"]["fixture"])
        payload["payload"]["itemSummaries"][0]["itemWebUrl"] = "https://www.ebay.com/itm/9999"
        with self.assertRaisesRegex(ValueError, "stable listing ID"):
            sources.normalize_capture(payload)

    def test_export_prices_are_exact_minor_integers_not_guessed_yen_cents(self):
        for value in (True, 1.1, "3800", -1, 2**63):
            payload = capture(); payload["payload"]["listings"][0]["price"]["amount_minor"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                sources.normalize_capture(payload)
        payload = capture(); row = payload["payload"]["listings"][0]
        row["price"]["amount_minor"] = 2**63 - 1
        self.assertEqual(sources.normalize_capture(payload)["observations"][0]["price_minor"], 2**63 - 1)

    def test_terminal_status_allows_unknown_ask_but_never_creates_sale_evidence(self):
        payload = capture(); item = payload["payload"]["listings"][0]
        item.update(status="gone", price=None, currency="JPY")
        result = sources.normalize_capture(payload)["observations"][0]
        self.assertEqual(result["status"], "gone")
        self.assertIsNone(result["price_minor"])
        self.assertNotIn("paid_minor", result)
        item["status"] = "on_sale"
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)

    def test_product_tier_rows_and_auctions_are_rejected(self):
        for changes in ({"record_type": "product"}, {"lowest_price": 100},
                        {"sale_type": "auction"}, {"auction": True}):
            payload = capture("snkrdunk"); payload["payload"]["listings"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sources.normalize_capture(payload)
        payload = capture("snkrdunk"); payload["payload"]["listings"][0].pop("listing_id")
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)
        payload = capture("ebay"); payload["payload"]["itemSummaries"][0]["buyingOptions"] += ["AUCTION"]
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)

    def test_structured_grades_cannot_contradict_title_or_claim_verification(self):
        for name in ("mercari", "snkrdunk"):
            payload = capture(name)
            payload["payload"]["listings"][1]["grade_value"] = "9"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "contradicts"):
                sources.normalize_capture(payload)
        for field in ("certificate_verified", "authenticity_verified"):
            payload = capture(); payload["payload"]["listings"][0][field] = True
            with self.assertRaisesRegex(ValueError, "verification"):
                sources.normalize_capture(payload)
        payload = capture(); payload["payload"]["listings"][0]["title"] += " PSA10 鑑定品"
        with self.assertRaisesRegex(ValueError, "raw claim"):
            sources.normalize_capture(payload)

    def test_structured_grade_without_title_evidence_stays_unresolved_without_title_rewrite(self):
        payload = capture(); item = payload["payload"]["listings"][1]
        item["title"] = "ピカチュウ SV2a 173/165"
        row = sources.normalize_capture(payload)["observations"][1]
        self.assertEqual(row["title"], item["title"])
        self.assertEqual(row["resolution_gate"], "photo_required")
        self.assertEqual(row["marketplace_quality"]["grade_company"], "PSA")

    def test_unreadable_grader_or_certificate_metadata_never_becomes_a_raw_unit(self):
        payload = capture(); item = payload["payload"]["listings"][0]
        item.pop("grade_company")
        item["certificate_number_claim"] = "SELLER-UNREADABLE"
        row = sources.normalize_capture(payload)["observations"][0]
        self.assertEqual(row["resolution_gate"], "photo_required")
        self.assertIsNone(row["marketplace_quality"]["grade_company"])
        self.assertEqual(row["title"], item["title"])

    def test_unreadable_slab_titles_require_review_without_inventing_a_grade(self):
        for name in ("mercari", "snkrdunk"):
            for cue in ("slab", "graded", "graded slab", "PSA unknown"):
                with self.subTest(source=name, cue=cue):
                    payload = capture(name)
                    item = payload["payload"]["listings"][0]
                    item.pop("grade_company")
                    item["title"] += " " + cue
                    row = sources.normalize_capture(payload)["observations"][0]
                    self.assertEqual(row["resolution_gate"], "photo_required")
                    self.assertIsNone(row["marketplace_quality"]["grade_company"])
                    self.assertIsNone(row["marketplace_quality"]["grade_value"])
                    self.assertEqual(row["title"], item["title"])

    def test_structured_raw_claim_cannot_contradict_unreadable_slab_title(self):
        for name in ("mercari", "snkrdunk"):
            for cue in ("slab", "graded", "graded slab", "PSA unknown"):
                with self.subTest(source=name, cue=cue):
                    payload = capture(name)
                    item = payload["payload"]["listings"][0]
                    self.assertEqual(item["grade_company"], "RAW")
                    item["title"] += " " + cue
                    with self.assertRaisesRegex(ValueError, "raw claim"):
                        sources.normalize_capture(payload)

    def test_malformed_native_descriptors_fail_validation_and_paid_rows_are_separate(self):
        payload = capture("ebay"); payload["payload"]["itemSummaries"][0]["localizedAspects"] = None
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)
        payload = capture(); payload["payload"]["listings"][0]["paid_minor"] = 3800
        with self.assertRaisesRegex(ValueError, "settlement"):
            sources.normalize_capture(payload)

    def test_malformed_nested_contract_fields_raise_validation_errors(self):
        mutations = [
            lambda data: data["request"].update(kind={}),
            lambda data: data.update(payload_schema={}),
            lambda data: data["payload"]["listings"][0].update(status={}),
            lambda data: data["payload"]["listings"][0].update(grade_company={}),
            lambda data: data["payload"]["listings"][0].update(grade_company="RAW", grade_value=[]),
        ]
        for mutate in mutations:
            payload = capture(); mutate(payload)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                sources.normalize_capture(payload)
        payload = capture("ebay"); payload["payload"]["total"] = True
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)
        payload = capture("ebay"); payload["payload"]["itemSummaries"] = 2
        with self.assertRaises(ValueError):
            sources.normalize_capture(payload)

    def test_empty_search_is_coverage_not_sold_inventory(self):
        payload = capture("ebay"); payload["payload"] = {"total": 0}
        result = sources.normalize_capture(payload)
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["coverage"]["returned_count"], 0)
        self.assertTrue(result["coverage"]["nonappearance_is_not_sold"])

    def test_evidence_hash_binds_exact_native_item_and_output_does_not_alias_input(self):
        payload = capture(); first = sources.normalize_capture(payload)
        payload["payload"]["listings"][0]["seller_condition"] = "seller changed the claim"
        second = sources.normalize_capture(payload)
        self.assertNotEqual(first["observations"][0]["evidence_ref"], second["observations"][0]["evidence_ref"])
        self.assertEqual(first["observations"][1]["evidence_ref"], second["observations"][1]["evidence_ref"])

    def test_batch_and_stable_id_duplicates_are_bounded(self):
        payload = capture(); payload["payload"]["listings"] *= 51
        with self.assertRaisesRegex(ValueError, "100"):
            sources.normalize_capture(payload)
        payload = capture(); payload["payload"]["listings"].append(copy.deepcopy(payload["payload"]["listings"][0]))
        with self.assertRaisesRegex(ValueError, "repeats"):
            sources.normalize_capture(payload)

    def test_ebay_detail_native_descriptors_and_photo_gate(self):
        payload = capture("ebay")
        item = payload["payload"]["itemSummaries"][1]
        item.pop("localizedAspects")
        item["conditionDescriptors"] = [
            {"name": "Professional Grader", "values": [{"content": "PSA"}]},
            {"name": "Grade", "values": [{"content": "10"}]},
            {"name": "Certification Number", "values": [{"content": "SYNTHETIC-0003"}]}]
        payload.update(payload_schema="ebay.browse.item.v1", payload=item, request={"kind": "detail", "native_ids": [item["itemId"]]})
        row = sources.normalize_capture(payload)["observations"][0]
        self.assertEqual(row["resolution_gate"], "photo_required")
        self.assertEqual(row["marketplace_quality"]["certificate_number_claim"], "SYNTHETIC-0003")
        item["conditionDescriptors"][1]["values"][0]["content"] = "9"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            sources.normalize_capture(payload)

    def test_ebay_decimal_prices_reject_float_boolean_precision_and_overflow(self):
        for value in (True, 29.95, "0.001", "NaN", "92233720368547758.08"):
            payload = capture("ebay"); payload["payload"]["itemSummaries"][0]["price"]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                sources.normalize_capture(payload)
        payload = capture("ebay"); payload["payload"]["itemSummaries"][0]["price"]["value"] = "90071992547409.93"
        self.assertEqual(sources.normalize_capture(payload)["observations"][0]["price_minor"], 9007199254740993)

    def test_ebay_converted_prices_cannot_become_native_search_or_detail_asks(self):
        conversions = (
            {"convertedFromCurrency": "GBP"},
            {"convertedFromValue": "25.00"},
            {"convertedFromCurrency": "GBP", "convertedFromValue": "25.00"},
            {"convertedFromCurrency": "USD", "convertedFromValue": "29.95"},
        )
        for kind in ("search", "detail"):
            for conversion in conversions:
                with self.subTest(kind=kind, conversion=conversion):
                    payload = capture("ebay")
                    item = payload["payload"]["itemSummaries"][0]
                    item["price"].update(conversion)
                    if kind == "detail":
                        payload.update(payload_schema="ebay.browse.item.v1", payload=item,
                                       request={"kind": "detail", "native_ids": [item["itemId"]]})
                    with self.assertRaises(ValueError):
                        sources.normalize_capture(payload)


if __name__ == "__main__":
    unittest.main()
