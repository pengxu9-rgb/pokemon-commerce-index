import sqlite3
import unittest

from pokemon_index import calibration, core


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.register_source(self.db, {
            "source": "fixture", "rights_reference": "synthetic test data",
            "ingest_allowed": True, "display_allowed": True, "retention_days": 365,
            "listing_ttl_hours": 24,
        })
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "SV2a", "collector_number": "173/165",
            "name": "ピカチュウ AR", "provenance": "test fixture",
            "rights_reference": "synthetic fixture", "display_allowed": True,
        }])

    def tearDown(self):
        self.db.close()

    def observation(self, native_id, title, timestamp, status="on_sale", price=400000, **extra):
        return dict(source="fixture", native_id=native_id, title=title,
                    url=f"https://example.invalid/{native_id}", language="ja",
                    observed_at=timestamp, status=status, price_minor=price,
                    currency="JPY", evidence_ref=f"test:{native_id}:{timestamp}", **extra)

    def test_grade_and_condition_are_separate_units(self):
        core.import_observations(self.db, [
            self.observation("a", "PSA10 ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z"),
            self.observation("b", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z", condition_bucket="A"),
        ])
        units = core.units_for_card(self.db, "ja:SV2A:173/165:standard")
        self.assertEqual(len(units), 2)
        self.assertEqual({u["grade_company"] for u in units}, {"PSA", "RAW"})
        raw = next(u for u in units if u["grade_company"] == "RAW")
        self.assertEqual(len(core.recommend(self.db, raw["unit_id"], "HK", "2026-09-22T09:30:00Z")["offers"]), 1)
        found = core.discover_intent(self.db, "日版 PSA10 ピカチュウ SV2a 173/165")
        self.assertEqual(found["constraints"]["grade_company"], "PSA")
        self.assertEqual(len(found["candidates"]), 1)
        self.assertEqual(found["candidates"][0]["matching_units"][0]["grade_value"], "10")

    def test_title_matching_requires_set_and_handles_japanese_order_and_grade_claims(self):
        expected = "ja:SV2A:173/165:standard"
        unit, _ = core.resolve(self.db, {"title": "【PSA10】ピカチュウ SV2a 拡張パック 173/165"})
        self.assertEqual(unit.split("|")[:3], [expected, "PSA", "10"])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ 173/165"})[0])
        claimed, _ = core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 PSA9レベル？"})
        self.assertEqual(claimed.split("|")[1:3], ["RAW", "raw"])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 2枚セット"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "中国語 ピカチュウ SV2a 173/165"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 マスターボールミラー"})[0])

    def test_collector_number_padding_is_consistent_for_short_sets(self):
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "SV1a", "collector_number": "80/73",
            "variant": "holo", "name": "コイキング", "provenance": "test fixture",
            "rights_reference": "synthetic fixture", "display_allowed": True,
        }])
        for number in ("080/073", "80/73"):
            unit, _ = core.resolve(self.db, {"title": f"コイキング SV1a {number}"})
            self.assertEqual(unit.split("|")[0], "ja:SV1A:080/073:holo")

    def test_internal_catalog_search_preserves_public_display_gate(self):
        core.import_sets(self.db, [{
            "set_code": "SV1a", "name_ja": "トリプレットビート",
            "release_date_ja": "2023-03-10", "official_card_count": 73,
            "provenance": "test fixture", "rights_reference": "synthetic fixture",
            "display_allowed": False,
        }])
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "SV1a", "collector_number": "80/73",
            "variant": "holo", "name": "コイキング", "provenance": "test fixture",
            "rights_reference": "synthetic fixture", "display_allowed": False,
        }])
        status = core.catalog_status(self.db)
        self.assertEqual((status["printings"], status["sets"], status["display_approved"]), (2, 2, 1))
        result = core.catalog_search_internal(self.db, "sv1a 80/73")
        self.assertEqual(result["total"], 1)
        cid = result["cards"][0]["card_id"]
        self.assertEqual(cid, "ja:SV1A:080/073:holo")
        self.assertFalse(core.catalog_card_internal(self.db, cid)["card"]["display_allowed"])
        self.assertEqual(core.catalog_card_internal(self.db, cid)["set"]["name_ja"], "トリプレットビート")
        self.assertEqual(core.catalog_search_internal(self.db, "トリプレットビート 80/73")["total"], 1)
        self.assertEqual(core.discover(self.db, "コイキング"), [])
        with self.assertRaisesRegex(ValueError, "not approved"):
            core.units_for_card(self.db, cid)

    def test_unverified_supplemental_card_cannot_resolve_an_offer(self):
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "S6a", "collector_number": "087/069",
            "variant": "unverified", "name": "マクワ", "provenance": "supplemental test",
            "rights_reference": "synthetic fixture", "display_allowed": False,
            "match_eligible": False, "attributes": {"source_jp_id": 39899},
        }])
        cid = "ja:S6A:087/069:unverified"
        core.import_card_references(self.db, [{
            "source": "fixture-reference", "source_jp_id": 39899,
            "set_code": "S6A", "collector_number": "087/069", "name": "マクワ",
            "rarity": "SR", "attributes": {"card_type": "Trainer"},
            "provenance": "synthetic reference", "rights_reference": "synthetic fixture",
            "display_allowed": False,
        }])
        self.assertEqual(core.catalog_card_internal(self.db, cid)["card"]["attributes"]["source_jp_id"], 39899)
        self.assertEqual(core.catalog_card_internal(self.db, cid)["reference_records"][0]["attributes"]["card_type"], "Trainer")
        self.assertEqual(core.resolve(self.db, {"title": "マクワ S6a 087/069"}), (None, "unresolved"))
        self.assertEqual(core.resolve(self.db, {"title": "マクワ S6a 087/069", "card_id": cid}),
                         (None, "unresolved"))

    def test_transition_is_not_a_verified_sale_and_reversion_removes_signal(self):
        title = "ピカチュウ SV2a 173/165"
        core.import_observations(self.db, [
            self.observation("a", title, "2026-09-22T09:00:00Z", condition_bucket="A"),
            self.observation("a", title, "2026-09-22T10:00:00Z", "trading", condition_bucket="A"),
        ])
        unit = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        first = core.index_for_unit(self.db, unit, "2026-09-22")["series"]
        self.assertEqual(first["last_list_at_transition"]["JPY"]["n"], 1)
        self.assertEqual(first["verified_paid"], {})
        core.import_observations(self.db, [
            self.observation("a", title, "2026-09-22T11:00:00Z", "on_sale", condition_bucket="A"),
        ])
        later = core.index_for_unit(self.db, unit, "2026-09-22")["series"]
        self.assertEqual(later["last_list_at_transition"], {})

    def test_historical_ask_uses_day_snapshot_not_current_status(self):
        title = "ピカチュウ SV2a 173/165"
        core.import_observations(self.db, [
            self.observation("a", title, "2026-09-22T09:00:00Z", condition_bucket="A"),
            self.observation("a", title, "2026-09-23T10:00:00Z", "sold_out", condition_bucket="A"),
        ])
        unit = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        self.assertEqual(core.index_for_unit(self.db, unit, "2026-09-22")["series"]["ask"]["JPY"]["n"], 1)
        self.assertEqual(core.index_for_unit(self.db, unit, "2026-09-23")["series"]["ask"], {})

    def test_landed_quote_must_be_complete_and_valid(self):
        core.import_observations(self.db, [
            self.observation("a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z", condition_bucket="A")
        ])
        unit = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        self.assertIsNone(core.recommend(self.db, unit, "HK", "2026-09-22T09:30:00Z")["recommendation"])
        core.import_quotes(self.db, [{
            "source": "fixture", "native_id": "a", "destination": "HK", "currency": "HKD",
            "components": {"item": 20000, "domestic": 0, "service": 1200, "international": 1800,
                           "tax": 0, "insurance": 0, "fx_spread": 0, "other": 0},
            "quoted_at": "2026-09-22T09:01:00Z", "expires_at": "2026-09-22T10:00:00Z",
            "evidence_ref": "test:quote",
        }])
        self.assertIsNone(core.recommend(self.db, unit, "HK", "2026-09-22T11:00:00Z")["recommendation"])
        result = core.recommend(self.db, unit, "HK", "2026-09-22T09:30:00Z")
        self.assertEqual(result["recommendation"]["quote"]["total_minor"], 23000)

    def test_source_policy_controls_ingest_and_display(self):
        with self.assertRaisesRegex(ValueError, "SNKRDUNK"):
            core.register_source(self.db, {"source": "snkrdunk", "rights_reference": "public_site",
                                           "ingest_allowed": True, "display_allowed": True, "retention_days": 30})
        core.import_observations(self.db, [
            self.observation("a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")
        ])
        core.register_source(self.db, {"source": "fixture", "rights_reference": "synthetic test data",
                                       "ingest_allowed": True, "display_allowed": False, "retention_days": 365})
        self.assertEqual(core.offers(self.db, "ja:SV2A:173/165:standard"), [])

    def test_calibration_uses_discovery_lane_and_reports_uncertainty(self):
        core.import_observations(self.db, [
            self.observation("caught", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z"),
            self.observation("tracked", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z",
                             poll_reason="tracking"),
        ])
        report = calibration.evaluate(self.db, [
            {"source": "fixture", "native_id": "caught", "sold_at": "2026-09-22T10:00:00Z",
             "last_price_minor": 400000, "bucket": "hot"},
            {"source": "fixture", "native_id": "tracked", "sold_at": "2026-09-22T10:00:00Z",
             "last_price_minor": 300000, "bucket": "hot"},
        ])
        hot = report["buckets"]["hot"]
        self.assertEqual(hot["coverage"], 0.5)
        self.assertEqual(hot["missed_to_caught_median_price_ratio"], 0.75)
        self.assertLess(hot["coverage_wilson_95"][0], hot["coverage_wilson_95"][1])

    def test_cross_source_comparison_requires_explicit_rights(self):
        core.register_source(self.db, {
            "source": "other", "rights_reference": "second synthetic source",
            "ingest_allowed": True, "display_allowed": True, "retention_days": 30,
            "listing_ttl_hours": 24,
        })
        first = self.observation("a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")
        second = dict(first, source="other", native_id="b")
        core.import_observations(self.db, [first, second])
        with self.assertRaisesRegex(ValueError, "cross-source"):
            core.offers(self.db, "ja:SV2A:173/165:standard", now="2026-09-22T09:30:00Z")

    def test_human_resolution_survives_new_observations(self):
        base = self.observation("a", "PSA10 ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")
        core.import_observations(self.db, [base])
        original = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        raw = core._unit(self.db, "ja:SV2A:173/165:standard", "RAW", "raw", "a")
        core.override_resolution(self.db, "fixture", "a", raw, "reviewer-1", "photo confirms raw card")
        core.import_observations(self.db, [dict(base, observed_at="2026-09-22T10:00:00Z")])
        current = self.db.execute("SELECT unit_id, resolution_method FROM listing WHERE native_id='a'").fetchone()
        self.assertNotEqual(original, current["unit_id"])
        self.assertEqual((current["unit_id"], current["resolution_method"]), (raw, "human"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM resolution_record WHERE native_id='a'").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
