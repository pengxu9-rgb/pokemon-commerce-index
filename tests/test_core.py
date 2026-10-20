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
            "ingest_allowed": True, "display_allowed": True,
            "price_statistics_allowed": True, "retention_days": 365,
            "listing_ttl_hours": 24,
        })
        core.import_cards(self.db, [{"match_eligible": True, "variant": "standard",
            "language": "ja", "set_code": "SV2a", "collector_number": "173/165",
            "name": "ピカチュウ", "rarity": "AR", "provenance": "test fixture",
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
            self.observation("a", "PSA10 鑑定品 ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z"),
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
        unit, _ = core.resolve(self.db, {"title": "【PSA10】鑑定品 ピカチュウ SV2a 拡張パック 173/165"})
        self.assertEqual(unit.split("|")[:3], [expected, "PSA", "10"])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ 173/165"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 PSA9レベル？"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 2枚セット"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "中国語 ピカチュウ SV2a 173/165"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "ピカチュウ SV2a 173/165 マスターボールミラー"})[0])
        self.assertIsNone(core.resolve(self.db, {"title": "リザードン SV2a 173/165"})[0])

    def test_grade_claims_and_special_grades_fail_closed(self):
        base = "ピカチュウ SV2a 173/165"
        unsafe = ("PSA10狙える", "psa10候補", "PSA 10 目指せ",
                  "元PSA10 ケースから出しました", "PSA9 PSA10 まとめ",
                  "ARS10+ 鑑定品", "BGS 9.5 ブラックラベル 鑑定品",
                  "PSA10")
        for prefix in unsafe:
            with self.subTest(prefix=prefix):
                self.assertIsNone(core.resolve(self.db, {"title": prefix + " " + base})[0])
        self.assertEqual(core.resolve(self.db, {
            "title": "PSA10 鑑定品 " + base})[0].split("|")[1:3], ["PSA", "10"])

    def test_vintage_edition_requires_decisive_marker(self):
        cards = [{"match_eligible": True, "language": "ja", "set_code": "E2", "collector_number": "009/092",
                  "variant": variant, "name": "アリアドス", "provenance": "fixture",
                  "rights_reference": "fixture", "display_allowed": True}
                 for variant in ("holo_1st_edition", "holo_unlimited")]
        core.import_cards(self.db, cards)
        base = "アリアドス E2 009/092 ホロ"
        self.assertIsNone(core.resolve(self.db, {"title": base})[0])
        self.assertEqual(core.resolve(self.db, {"title": base + " 1st edition"})[0].split("|")[0],
                         "ja:E2:009/092:holo_1st_edition")
        self.assertEqual(core.resolve(self.db, {"title": base + " unlimited"})[0].split("|")[0],
                         "ja:E2:009/092:holo_unlimited")
        self.assertIsNone(core.resolve(self.db, {"title": base + " shadowless"})[0])

    def test_collector_number_padding_is_consistent_for_short_sets(self):
        core.import_cards(self.db, [{"match_eligible": True,
            "language": "ja", "set_code": "SV1a", "collector_number": "80/73",
            "variant": "holo", "name": "コイキング", "provenance": "test fixture",
            "rights_reference": "synthetic fixture", "display_allowed": True,
        }])
        for number in ("080/073", "80/73"):
            unit, _ = core.resolve(self.db, {"title": f"コイキング SV1a {number}"})
            self.assertEqual(unit.split("|")[0], "ja:SV1A:080/073:holo")

    def test_mega_dream_name_outweighs_ma_artwork_shorthand(self):
        core.import_cards(self.db, [
            {"match_eligible": True, "language": "ja", "set_code": "M2a", "collector_number": "223/193",
             "variant": "holo", "name": "メガリザードンXex", "provenance": "fixture",
             "rights_reference": "fixture", "display_allowed": True},
            {"match_eligible": True, "language": "ja", "set_code": "MA", "collector_number": "223/193",
             "variant": "normal", "name": "別カード", "provenance": "fixture",
             "rights_reference": "fixture", "display_allowed": True},
        ])
        unit, method = core.resolve(self.db, {
            "title": "メガリザードンXex MA 223/193 メガドリームex", "language": "ja"})
        self.assertEqual(method, "exact")
        self.assertEqual(unit.split("|")[0], "ja:M2A:223/193:holo")

    def test_missing_x_in_mega_charizard_name_abstains(self):
        core.import_cards(self.db, [{"match_eligible": True,
            "language": "ja", "set_code": "M2", "collector_number": "116/080",
            "variant": "holo", "name": "メガリザードンXex", "provenance": "fixture",
            "rights_reference": "fixture", "display_allowed": True,
        }])
        self.assertEqual(core.resolve(self.db, {
            "title": "PSA10 メガリザードンex 116/080 MUR M2"}), (None, "unresolved"))
        unit, _ = core.resolve(self.db, {
            "title": "PSA10 鑑定品 メガリザードンX ex 116/080 MUR M2"})
        self.assertEqual(unit.split("|")[0], "ja:M2:116/080:holo")

    def test_internal_catalog_search_preserves_public_display_gate(self):
        core.import_sets(self.db, [{
            "set_code": "SV1a", "name_ja": "トリプレットビート",
            "release_date_ja": "2023-03-10", "official_card_count": 73,
            "provenance": "test fixture", "rights_reference": "synthetic fixture",
            "display_allowed": False,
        }])
        core.import_cards(self.db, [{"match_eligible": True,
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

    def test_english_set_identity_does_not_use_japanese_set_metadata(self):
        core.import_sets(self.db, [{
            "language": "en", "set_code": "SV2A", "name": "English Test Set",
            "release_date": "2026-09-01", "official_card_count": 165,
            "provenance": "test fixture", "rights_reference": "synthetic fixture",
            "display_allowed": False,
        }])
        core.import_cards(self.db, [{"match_eligible": True, "variant": "standard",
            "language": "en", "set_code": "SV2A", "collector_number": "173/165",
            "name": "English Pikachu", "provenance": "test fixture",
            "rights_reference": "synthetic fixture", "display_allowed": False,
        }])
        result = core.catalog_search_internal(self.db, "English Test Set 173/165")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["cards"][0]["language"], "en")
        self.assertEqual(core.catalog_status(self.db)["sets"], 2)
        self.assertEqual(core.catalog_card_internal(self.db, "en:SV2A:173/165:standard")["set"]["name"],
                         "English Test Set")
        self.assertEqual(core.catalog_card_internal(self.db, "ja:SV2A:173/165:standard")["set"], None)

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
        as_known_before_reversion = core.index_for_unit(
            self.db, unit, "2026-09-22", "2026-09-22T10:30:00Z")["series"]
        self.assertEqual(as_known_before_reversion["last_list_at_transition"]["JPY"]["n"], 1)

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
            "assumptions": {"source_price_minor": 400000, "source_currency": "JPY",
                            "fx_rate_ref": "fixture:fx", "fee_schedule_ref": "fixture:fee",
                            "tax_basis": "fixture:tax"},
        }])
        self.assertIsNone(core.recommend(self.db, unit, "HK", "2026-09-22T11:00:00Z")["recommendation"])
        result = core.recommend(self.db, unit, "HK", "2026-09-22T09:30:00Z")
        self.assertEqual(result["recommendation_type"], "price_only")
        self.assertEqual(result["recommendation"]["quote"]["total_minor"], 23000)

    def test_recommendation_rejects_quote_bound_to_wrong_source_price(self):
        core.import_observations(self.db, [self.observation(
            "a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")])
        unit = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        core.import_quotes(self.db, [{
            "source": "fixture", "native_id": "a", "destination": "HK", "currency": "HKD",
            "components": {"item": 1000, "domestic": 0, "service": 0,
                           "international": 0, "tax": 0, "insurance": 0,
                           "fx_spread": 0, "other": 0},
            "quoted_at": "2026-09-22T09:01:00Z", "expires_at": "2026-09-22T10:00:00Z",
            "evidence_ref": "fixture:stale-quote",
            "assumptions": {"source_price_minor": 300000, "source_currency": "JPY",
                            "fx_rate_ref": "fixture:fx", "fee_schedule_ref": "fixture:fee",
                            "tax_basis": "fixture:tax"},
        }])
        self.assertIsNone(core.recommend(
            self.db, unit, "HK", "2026-09-22T09:30:00Z")["recommendation"])

    def test_landed_quote_is_append_only_at_its_timestamp(self):
        core.import_observations(self.db, [self.observation(
            "a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")])
        row = {"source": "fixture", "native_id": "a", "destination": "HK",
               "currency": "HKD", "components": {
                   "item": 20000, "domestic": 0, "service": 1000,
                   "international": 0, "tax": 0, "insurance": 0,
                   "fx_spread": 0, "other": 0},
               "quoted_at": "2026-09-22T09:01:00Z",
               "expires_at": "2026-09-22T10:00:00Z", "evidence_ref": "fixture:quote"}
        self.assertEqual(core.import_quotes(self.db, [row]), 1)
        self.assertEqual(core.import_quotes(self.db, [row]), 0)
        changed = {**row, "components": {**row["components"], "item": 21000}}
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            core.import_quotes(self.db, [changed])

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

    def test_price_statistics_need_separate_source_permission(self):
        core.import_observations(self.db, [self.observation(
            "a", "ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")])
        unit = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        self.assertEqual(core.index_for_unit(self.db, unit, "2026-09-22")
                         ["series"]["ask"]["JPY"]["n"], 1)
        core.register_source(self.db, {
            "source": "fixture", "rights_reference": "synthetic display only",
            "ingest_allowed": True, "display_allowed": True,
            "price_statistics_allowed": False, "retention_days": 365,
            "listing_ttl_hours": 24,
        })
        self.assertEqual(len(core.offers(self.db, "ja:SV2A:173/165:standard",
                                         now="2026-09-22T09:30:00Z")), 1)
        self.assertEqual(core.index_for_unit(self.db, unit, "2026-09-22")
                         ["series"]["ask"], {})

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
        base = self.observation("a", "PSA10 鑑定品 ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")
        core.import_observations(self.db, [base])
        original = core.units_for_card(self.db, "ja:SV2A:173/165:standard")[0]["unit_id"]
        raw = core._unit(self.db, "ja:SV2A:173/165:standard", "RAW", "raw", "a")
        core.override_resolution(self.db, "fixture", "a", raw, "reviewer-1", "photo confirms raw card")
        core.import_observations(self.db, [dict(base, observed_at="2026-09-22T10:00:00Z")])
        current = self.db.execute("SELECT unit_id, resolution_method FROM listing WHERE native_id='a'").fetchone()
        self.assertNotEqual(original, current["unit_id"])
        self.assertEqual((current["unit_id"], current["resolution_method"]), (raw, "human"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM resolution_record WHERE native_id='a'").fetchone()[0], 2)

    def test_slab_or_grader_without_readable_grade_is_not_a_raw_card(self):
        base = "ピカチュウ SV2a 173/165"
        for prefix in ("鑑定品", "Graded card", "スラブ", "ケース入り", "PSA", "PSA鑑定品", "BGS"):
            with self.subTest(prefix=prefix):
                self.assertIsNone(core.resolve(self.db, {"title": prefix + " " + base})[0])
        self.assertEqual(core.resolve(self.db, {"title": base})[0].split("|")[1:3], ["RAW", "raw"])
        self.assertEqual(core.resolve(self.db, {"title": "PSA10 鑑定品 " + base})[0].split("|")[1:3], ["PSA", "10"])

    def listing(self, native_id):
        return self.db.execute("SELECT unit_id, resolution_method FROM listing WHERE native_id=?",
                               (native_id,)).fetchone()

    def test_newest_title_that_no_longer_supports_a_graded_unit_stops_pricing(self):
        graded = "ja:SV2A:173/165:standard|PSA|10|graded"
        core.import_observations(self.db, [
            self.observation("a", "PSA10 鑑定品 ピカチュウ SV2a 173/165", "2026-09-22T09:00:00Z")])
        self.assertEqual(self.listing("a")["unit_id"], graded)
        core.import_observations(self.db, [
            self.observation("a", "元PSA10 ケースから出しました ピカチュウ SV2a 173/165", "2026-09-22T10:00:00Z")])
        self.assertEqual(tuple(self.listing("a")), (None, "unresolved"))
        self.assertEqual(core.recommend(self.db, graded, "HK", "2026-09-22T10:30:00Z")["offers"], [])
        record = self.db.execute("""SELECT unit_id, method, reason FROM resolution_record
            WHERE native_id='a' ORDER BY id DESC LIMIT 1""").fetchone()
        self.assertEqual(record[:2], (None, "unresolved"))
        self.assertIn(graded, record["reason"])
        # Restoring the original title resolves the listing again.
        core.import_observations(self.db, [
            self.observation("a", "PSA10 鑑定品 ピカチュウ SV2a 173/165", "2026-09-22T11:00:00Z")])
        self.assertEqual(tuple(self.listing("a")), (graded, "exact"))

    def test_older_out_of_order_title_cannot_demote_a_unit(self):
        core.import_observations(self.db, [
            self.observation("a", "PSA10 鑑定品 ピカチュウ SV2a 173/165", "2026-09-22T10:00:00Z")])
        core.import_observations(self.db, [
            self.observation("a", "元PSA10 ケースから出しました ピカチュウ SV2a 173/165", "2026-09-22T08:00:00Z")])
        self.assertEqual(tuple(self.listing("a")), ("ja:SV2A:173/165:standard|PSA|10|graded", "exact"))

    def test_older_out_of_order_observation_cannot_overwrite_listing_text(self):
        core.import_observations(self.db, [dict(self.observation(
            "a", "PSA10 鑑定品 ピカチュウ SV2a 173/165 NEW", "2026-09-22T12:00:00Z"), seller_native_id="s-new")])
        core.import_observations(self.db, [dict(self.observation(
            "a", "PSA10 鑑定品 ピカチュウ SV2a 173/165 OLD", "2026-09-22T08:00:00Z"), seller_native_id="s-old")])
        row = self.db.execute("SELECT title, seller_native_id, last_seen FROM listing WHERE native_id='a'").fetchone()
        self.assertEqual(tuple(row), ("PSA10 鑑定品 ピカチュウ SV2a 173/165 NEW", "s-new", "2026-09-22T12:00:00+00:00"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observation WHERE native_id='a'").fetchone()[0], 2)

    def test_reviewed_binding_is_demoted_only_when_the_newest_title_disputes_its_grade(self):
        card = "ja:SV2A:173/165:standard"
        graded = core._unit(self.db, card, "PSA", "10", "graded")
        core.import_observations(self.db, [
            self.observation("h", "ピカチュウ SV2a 173/165 まとめ 2枚", "2026-09-22T09:00:00Z")])
        core.override_resolution(self.db, "fixture", "h", graded, "reviewer-1", "photo shows PSA 10 slab")
        core.import_observations(self.db, [
            self.observation("h", "ピカチュウ SV2a 173/165 まとめ 3枚", "2026-09-22T10:00:00Z")])
        self.assertEqual(tuple(self.listing("h")), (graded, "human"))
        core.import_observations(self.db, [
            self.observation("h", "PSA9 鑑定品 ピカチュウ SV2a 173/165 2枚", "2026-09-22T11:00:00Z")])
        self.assertEqual(tuple(self.listing("h")), (None, "unresolved"))

        core.import_observations(self.db, [dict(self.observation("r", "ピカチュウ", "2026-09-22T09:00:00Z"),
                                                card_id=card)])
        raw = self.listing("r")["unit_id"]
        self.assertEqual((raw.split("|")[1], self.listing("r")["resolution_method"]), ("RAW", "explicit"))
        core.import_observations(self.db, [dict(self.observation("r", "PSA10狙える ピカチュウ", "2026-09-22T10:00:00Z"),
                                                card_id=card)])
        self.assertEqual(tuple(self.listing("r")), (raw, "explicit"))
        core.import_observations(self.db, [dict(self.observation("r", "鑑定品 ピカチュウ", "2026-09-22T11:00:00Z"),
                                                card_id=card)])
        self.assertEqual(tuple(self.listing("r")), (None, "unresolved"))


if __name__ == "__main__":
    unittest.main()
