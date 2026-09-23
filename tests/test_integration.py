import sqlite3
import unittest
import json
from pathlib import Path

from pokemon_index import buyship_mercari, calibration, core, pivota, tcgdex, tcgdex_source


class GatewayAdapterTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "id": "m123456789", "name": "PSA10 ピカチュウ SV2a 173/165",
            "status": "on_sale", "price": 400000, "seller": {"id": 42},
            "created": "2026-09-22T08:00:00Z", "updated": "2026-09-22T09:00:00Z",
        }

    def test_response_normalization_preserves_evidence_without_inventing_identity(self):
        rows = buyship_mercari.normalize_response(
            {"data": [self.item]}, "2026-09-22T10:00:00Z", endpoint="search")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["source"], row["native_id"], row["seller_native_id"]),
                         ("mercari_bns", "m123456789", "42"))
        self.assertEqual(row["price_minor"], 400000)
        self.assertNotIn("language", row)
        self.assertNotIn("card_id", row)
        self.assertTrue(row["evidence_ref"].startswith("mercari-gateway:sha256:"))
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            buyship_mercari.normalize_item({**self.item, "status": "unknown"},
                                           "2026-09-22T10:00:00Z")

    def test_gate0_probe_is_bounded_and_reports_contract_shape(self):
        calls = []

        class FakeClient:
            def get(self, path, params):
                calls.append((path, params))
                if path == "item":
                    return 200, {"data": self_item}
                return 200, {"data": [self_item]}

        self_item = self.item
        checks = buyship_mercari.gate0_probe(FakeClient(), historical_item_id="m123456789",
                                             category_id="123")
        self.assertEqual([check.check for check in checks],
                         ["historical_item", "category_feed", "sold_search"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(checks[0].statuses, ("on_sale",))
        with self.assertRaisesRegex(ValueError, "explicit opt-in"):
            buyship_mercari.GatewayClient("https://example.invalid", "secret")


class HandoffAndRetentionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.register_source(self.db, {
            "source": "mercari_bns", "rights_reference": "synthetic fixture",
            "ingest_allowed": True, "display_allowed": True,
            "retention_days": 1, "listing_ttl_hours": 24,
        })
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "SV2a", "collector_number": "173/165",
            "name": "ピカチュウ AR", "provenance": "synthetic fixture",
            "rights_reference": "synthetic fixture", "display_allowed": True,
        }])
        item = {"id": "m123456789", "name": "ピカチュウ SV2a 173/165",
                "status": "on_sale", "price": 400000, "seller": {"id": 42}}
        rows = buyship_mercari.normalize_response(
            {"data": [item]}, "2026-09-22T09:00:00Z", endpoint="search")
        core.archive_raw_item(self.db, rows[0], item, "search")
        core.import_observations(self.db, rows)

    def tearDown(self):
        self.db.close()

    def test_pivota_candidate_keeps_unit_grain_and_has_no_checkout_claim(self):
        card_id = "ja:SV2A:173/165:standard"
        payload = pivota.export_card(self.db, card_id, "HK", "2026-09-22T09:30:00Z")
        self.assertEqual(payload["contract"], "pokemon-commerce-to-pivota.v1")
        self.assertTrue(payload["candidate_only"])
        self.assertEqual(len(payload["priceable_units"]), 1)
        self.assertEqual(payload["card"]["rights_reference"], "synthetic fixture")
        core.import_observations(self.db, [{
            "source": "mercari_bns", "native_id": "m222222222", "title": "ピカチュウ SV2a 173/165",
            "url": "https://jp.mercari.com/item/m222222222", "observed_at": "2026-09-22T09:00:00Z",
            "status": "on_sale", "price_minor": 400000, "currency": "JPY",
            "language": "ja", "condition_bucket": "a", "evidence_ref": "synthetic:2",
        }])
        payload = pivota.export_card(self.db, card_id, "HK", "2026-09-22T09:30:00Z")
        unit = next(unit for unit in payload["priceable_units"] if unit["condition_bucket"] == "a")
        self.assertIsNone(unit["pivota_content_key"])
        self.assertEqual(unit["condition_bucket"], "a")
        self.assertFalse(unit["offers"][0]["purchasable"])

    def test_retention_deletes_resolution_before_parent_listing(self):
        removed = core.purge_expired(self.db, "2026-09-25T00:00:00Z")
        self.assertEqual(removed["observation"], 1)
        self.assertEqual(removed["raw_item_blob"], 1)
        self.assertEqual(removed["resolution_record"], 1)
        self.assertEqual(removed["listing"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM listing").fetchone()[0], 0)

    def test_catalog_not_approved_for_display_cannot_export(self):
        core.import_cards(self.db, [{
            "language": "ja", "set_code": "SV2a", "collector_number": "173/165",
            "name": "ピカチュウ AR", "provenance": "internal seed",
            "rights_reference": "internal use only", "display_allowed": False,
        }])
        with self.assertRaisesRegex(ValueError, "not approved"):
            pivota.export_card(self.db, "ja:SV2A:173/165:standard", "HK")


class MigrationTests(unittest.TestCase):
    def test_legacy_catalog_is_hidden_until_rights_are_reviewed(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE card (card_id TEXT PRIMARY KEY, language TEXT NOT NULL,
            set_code TEXT NOT NULL, collector_number TEXT NOT NULL, variant TEXT NOT NULL,
            name TEXT NOT NULL, rarity TEXT, provenance TEXT NOT NULL)""")
        db.execute("INSERT INTO card VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   ("ja:SV2A:173/165:standard", "ja", "SV2A", "173/165", "standard",
                    "ピカチュウ AR", "AR", "old fixture"))
        core.init_db(db)
        row = db.execute("SELECT rights_reference, display_allowed FROM card").fetchone()
        self.assertEqual(row["display_allowed"], 0)
        self.assertEqual(row["rights_reference"], "unreviewed legacy import")
        self.assertEqual(core.discover(db, "ピカチュウ"), [])
        db.close()


class GateDecisionTests(unittest.TestCase):
    def test_gate_thresholds_keep_transition_price_distinct_from_paid_price(self):
        report = {"buckets": {
            "hot": {"panel_sales": 100, "coverage": 0.85, "missed_sales": 15,
                    "missed_to_caught_median_price_ratio": 1.02},
            "mid": {"panel_sales": 50, "coverage": 0.70, "missed_sales": 15,
                    "missed_to_caught_median_price_ratio": 0.99},
        }}
        go = calibration.gate1_decision(report, sold_detail_has_price=True,
                                        required_calls_per_day=9000, quota_calls_per_day=10000,
                                        min_hot_sales=50, min_mid_sales=30)
        self.assertEqual(go["decision"], "go_clear_price_candidate")
        self.assertNotIn("verified_paid", go["publish"])
        no_go = calibration.gate1_decision(report, sold_detail_has_price=False,
                                           required_calls_per_day=9000, quota_calls_per_day=10000)
        self.assertEqual(no_go["decision"], "no_go_clear_price")
        self.assertEqual(no_go["publish"], ["ask", "landed_quote"])


class CatalogAdapterTests(unittest.TestCase):
    def test_legacy_first_edition_and_unlimited_are_distinct_printings(self):
        source = '''const card = { name: { ja: "カクナ" }, variants: [
            { type: "normal", stamp: ["1st edition"] },
            { type: "normal", subtype: "unlimited" }
        ] };'''
        rows = tcgdex_source.parse_card_source(source, set_id="PCG1", official_count=100,
                                               path="data-asia/PCG/PCG1/005.ts", revision="a" * 40)
        self.assertEqual({row["variant"] for row in rows},
                         {"normal_1st_edition", "normal_unlimited"})

    def test_promo_set_and_lettered_collector_ids_are_kept(self):
        header = 'const set = { id: "SV-P", cardCount: { official: 0 } };'
        self.assertEqual(tcgdex_source.parse_set_source(header), ("SV-P", 0))
        source = 'const card = { name: { ja: "基本悪エネルギー" }, variants: [{ type: "normal" }] };'
        promo = tcgdex_source.parse_card_source(source, set_id="SV-P", official_count=0,
                                                 path="data-asia/SV/SV-P/001.ts", revision="a" * 40)
        energy = tcgdex_source.parse_card_source(source, set_id="M6a", official_count=103,
                                                  path="data-asia/M/M6a/DAR.ts", revision="a" * 40)
        self.assertEqual(promo[0]["collector_number"], "001/SV-P")
        self.assertEqual(energy[0]["collector_number"], "DAR/103")

    def test_japanese_set_adapter_keeps_metadata_and_excludes_images(self):
        payload = {"id": "svx", "cardCount": {"official": 165}, "cards": [
            {"id": "svx-1", "localId": "1", "name": "カードA", "image": "https://example.invalid/art"},
            {"id": "svx-173", "localId": "173", "name": "カードB"},
        ]}
        cards = tcgdex.normalize_japanese_set(payload,
                                              rights_reference="synthetic metadata fixture")
        self.assertEqual([card["collector_number"] for card in cards], ["001/165", "173/165"])
        self.assertFalse(cards[0]["display_allowed"])
        self.assertNotIn("image", cards[0])
        self.assertTrue(cards[0]["provenance"].startswith("tcgdex:v2:ja:sets/svx:svx-1:sha256:"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            tcgdex.normalize_japanese_set({**payload, "cards": [payload["cards"][0]] * 2},
                                          rights_reference="synthetic metadata fixture")

    def test_finish_variants_never_merge_into_an_ambiguous_price_unit(self):
        revision = "a211f11f3ba57d56c65c5ac33be35b77d3280757"
        header = "const set = { id: 'SV2a', cardCount: { official: 165 } };"
        set_id, count = tcgdex_source.parse_set_source(header)
        card = '''const card = { name: { ja: "フシギダネ" }, rarity: "Common",
            variants: [{ type: "normal" }, { type: "reverse", foil: "pokeball" },
                       { type: "reverse", foil: "masterball" }] };'''
        rows = tcgdex_source.parse_card_source(card, set_id=set_id,
                                               official_count=count,
                                               path="data-asia/SV/SV2a/001.ts",
                                               revision=revision)
        short_set = tcgdex_source.parse_card_source(card, set_id="SV1a",
                                                   official_count=73,
                                                   path="data-asia/SV/SV1a/080.ts",
                                                   revision=revision)
        self.assertEqual(short_set[0]["collector_number"], "080/073")
        self.assertEqual({row["variant"] for row in rows},
                         {"normal", "reverse_pokeball", "reverse_masterball"})
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        core.init_db(db)
        core.import_cards(db, [{**row, "display_allowed": True} for row in rows])
        base = {"title": "フシギダネ SV2a 001/165"}
        self.assertEqual(core.resolve(db, base), (None, "unresolved"))
        resolved, method = core.resolve(db, {"title": "フシギダネ SV2a 001/165 マスターボールミラー"})
        self.assertEqual(method, "exact")
        self.assertIn("reverse_masterball", resolved)
        db.close()

    def test_pinned_sv2a_seed_has_distinct_printings_and_no_public_display(self):
        catalog = Path(__file__).resolve().parents[1] / "catalog"
        rows = [json.loads(line) for line in (catalog / "ja-sv2a.jsonl").read_text().splitlines()]
        audit = json.loads((catalog / "ja-sv2a-audit.json").read_text())
        self.assertEqual((audit["source_files_parsed"], len(rows)), (210, 516))
        self.assertEqual(audit["errors"], [])
        self.assertTrue(all(not row["display_allowed"] and "image" not in row for row in rows))
        self.assertEqual(len({(row["set_code"], row["collector_number"], row["variant"])
                              for row in rows}), len(rows))
        variants = {row["variant"] for row in rows if row["collector_number"] == "001/165"}
        self.assertEqual(variants, {"normal", "reverse_pokeball", "reverse_masterball"})


if __name__ == "__main__":
    unittest.main()
