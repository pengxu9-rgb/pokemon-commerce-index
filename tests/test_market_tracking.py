"""Socket-denied regression checks for the standalone tracking read model."""
from __future__ import annotations

from contextlib import closing
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.rehearse_market_tracking import (build_fixture, deny_network, CARD_ID, RAW_UNIT, PSA9_UNIT,
                      PSA10_UNIT, SOURCES)
from pokemon_index import core
from pokemon_index.market_tracking import build_report


class TrackingReportTests(unittest.TestCase):
    def setUp(self):
        self.network = deny_network()
        self.network.__enter__()
        self.temporary = tempfile.TemporaryDirectory(prefix="tracking-report-test-")
        self.path = Path(self.temporary.name) / "fixture ?#%カタログ.sqlite3"
        self.fixture = build_fixture(self.path)
        self.now = self.fixture["as_of"]

    def tearDown(self):
        self.temporary.cleanup()
        self.network.__exit__(None, None, None)

    def report(self):
        return build_report(self.path, CARD_ID, now=self.now, history_days=7)

    def groups(self, report=None):
        report = report or self.report()
        return [group for platform in report["platforms"] for group in platform["groups"]]

    def current_ids(self, report=None):
        return {offer["native_id"] for group in self.groups(report) for offer in group["offers"]}

    def add_quality(self, native, metadata, *, observed_at=None):
        with closing(core.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS marketplace_observation_quality (
                source TEXT NOT NULL, native_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                quality_json TEXT NOT NULL, evidence_ref TEXT NOT NULL,
                PRIMARY KEY(source,native_id,observed_at),
                FOREIGN KEY(source,native_id,observed_at) REFERENCES observation(source,native_id,observed_at)
                ON DELETE CASCADE)""")
            selected = db.execute("SELECT source,last_seen FROM listing WHERE native_id=?", (native,)).fetchone()
            observed = observed_at or selected["last_seen"]
            evidence = db.execute("SELECT evidence_ref FROM observation WHERE source=? AND native_id=? AND observed_at=?",
                                  (selected["source"], native, observed)).fetchone()[0]
            metadata = dict(metadata, evidence_ref=evidence)
            if metadata.get("grade_company"):
                metadata.setdefault("grade_evidence", "structured_seller_claim")
            db.execute("INSERT INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                       (selected["source"], native, observed, json.dumps(metadata), evidence))
            db.commit()

    def title(self, native, title):
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE listing SET title=?,resolution_method='human' WHERE native_id=?", (title, native))
            db.execute("UPDATE observation SET title=? WHERE native_id=?", (title, native))
            db.commit()

    def test_structured_grade_supports_missing_title_grade_as_unverified_seller_claim(self):
        self.title("psa10-a", "ピカチュウ SV2a 173/165")
        self.assertNotIn("psa10-a", self.current_ids())
        self.add_quality("psa10-a", {"grade_company": "PSA", "grade_value": "10",
            "seller_condition": "seller describes clean slab", "certificate_number_claim": "12345678",
            "certificate_verified": False, "authenticity_verified": False})
        offer = next(o for group in self.groups() for o in group["offers"] if o["native_id"] == "psa10-a")
        self.assertEqual(offer["quality"]["grade_evidence"], "seller_structured_claim")
        self.assertEqual(offer["quality"]["certificate_number_claim"], "12345678")
        self.assertEqual(offer["quality"]["condition_evidence"], "seller_claim")
        self.assertIs(offer["quality"]["certificate_verified"], False)
        self.assertIs(offer["quality"]["physical_condition_assessed"], False)
        self.assertEqual(offer["quality_evidence_ref"], offer["evidence_ref"])

    def test_structured_grade_never_overrides_unsafe_or_conflicting_title(self):
        self.add_quality("psa10-a", {"grade_company": "PSA", "grade_value": "10"})
        for title in ("ピカチュウ SV2a 173/165 PSA9 鑑定品", "ピカチュウ SV2a 173/165 PSA10狙える",
                      "ピカチュウ SV2a 173/165 BGS 鑑定品", "ピカチュウ SV2a 173/165 2枚セット",
                      "ピカチュウ SV2a 173/165 PSA11 鑑定品", "ピカチュウ SV2a 173/165 PSA10.5 鑑定品"):
            with self.subTest(title=title):
                self.title("psa10-a", title)
                self.assertNotIn("psa10-a", self.current_ids())

    def test_structured_grade_and_certificate_claim_cannot_turn_raw_into_graded(self):
        self.add_quality("raw-a", {"grade_company": "PSA", "grade_value": "10"})
        self.add_quality("raw-a2", {"certificate_number_claim": "12345678"})
        self.assertFalse({"raw-a", "raw-a2"} & self.current_ids())

    def test_malformed_or_verified_quality_metadata_is_excluded(self):
        changes = ({"grade_company": "PSA"}, {"grade_company": "PSA", "grade_value": "9"},
                   {"certificate_verified": True}, {"authenticity_verified": True},
                   {"seller_condition": ["not a string"]})
        for metadata in changes:
            with self.subTest(metadata=metadata):
                self.add_quality("psa10-a", metadata)
                self.assertNotIn("psa10-a", self.current_ids())
                with closing(core.connect(self.path)) as db:
                    db.execute("DELETE FROM marketplace_observation_quality")
                    db.commit()

    def test_quality_metadata_is_bound_to_exact_observation_not_backdated(self):
        self.title("raw-a", "ピカチュウ SV2a 173/165")
        self.add_quality("raw-a", {"seller_condition": "newest seller condition only"})
        events = [event for platform in self.report()["platforms"] for event in platform["listing_events"]
                  if event["native_id"] == "raw-a"]
        self.assertEqual([event["quality"]["seller_condition"] for event in events],
                         [None, None, "newest seller condition only"])

    def test_quality_metadata_with_different_evidence_reference_is_excluded(self):
        self.add_quality("psa10-a", {"grade_company": "PSA", "grade_value": "10"})
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE marketplace_observation_quality SET evidence_ref='different:unbound:evidence'")
            db.commit()
        self.assertNotIn("psa10-a", self.current_ids())
        with closing(core.connect(self.path)) as db:
            observed = db.execute("SELECT evidence_ref FROM observation WHERE native_id='psa10-a'").fetchone()[0]
            metadata = json.loads(db.execute("SELECT quality_json FROM marketplace_observation_quality").fetchone()[0])
            metadata["evidence_ref"] = "different:json:evidence"
            db.execute("UPDATE marketplace_observation_quality SET quality_json=?,evidence_ref=?",
                       (json.dumps(metadata), observed))
            db.commit()
        self.assertNotIn("psa10-a", self.current_ids())

    def test_title_extracted_metadata_is_not_independent_structured_grade_evidence(self):
        self.title("psa10-a", "ピカチュウ SV2a 173/165")
        for basis in (None, "seller_title_claim"):
            with self.subTest(basis=basis):
                self.add_quality("psa10-a", {"grade_company": "PSA", "grade_value": "10", "grade_evidence": basis})
                self.assertNotIn("psa10-a", self.current_ids())
                with closing(core.connect(self.path)) as db:
                    db.execute("DELETE FROM marketplace_observation_quality")
                    db.commit()

    def test_three_source_adapters_import_atomic_quality_and_report_without_bns(self):
        from pokemon_index import marketplace_ingest as ingest

        database = Path(self.temporary.name) / "three-adapter-captures.sqlite3"
        sources = ["mercari_fixture", "ebay_us_fixture", "snkrdunk_fixture"]
        observed = (core.parse_time(self.now) - timedelta(minutes=5)).isoformat()
        title = "ピカチュウ SV2a 173/165"
        def envelope(source, schema, payload):
            return dict(schema="pokemon.marketplace-capture.v1", source=source,
                observed_at=observed, request={"kind": "search", "query": title,
                    "target_card_ids": [CARD_ID]}, payload_schema=schema, payload=payload)
        captures = [
            envelope(sources[0], "pokemon.mercari-authorized-export.v1", {
                "listings": [dict(listing_id="m901", title=title + " PSA10 鑑定品", language="ja",
                    url="https://mercari-fixture.invalid/item/m901", status="on_sale",
                    price={"amount_minor": 12000, "currency": "JPY"}, seller_condition="clean slab claim",
                    grade_company="PSA", grade_value="10", certificate_number_claim="12345678")],
                "page_complete": True}),
            envelope(sources[1], "ebay.browse.search.v1", {"total": 1, "itemSummaries": [dict(
                itemId="v1|901|0", title=title + " PSA10 graded card", language="ja",
                itemWebUrl="https://ebay-fixture.invalid/itm/901", buyingOptions=["FIXED_PRICE"],
                price={"value": "180.00", "currency": "USD"}, condition="Graded",
                localizedAspects=[{"name": "Professional Grader", "value": "PSA"},
                                  {"name": "Grade", "value": "10"},
                                  {"name": "Certification Number", "value": "87654321"}])]}),
            envelope(sources[2], "pokemon.snkrdunk-authorized-export.v1", {
                "listings": [dict(listing_id="listing_901", title=title + " PSA9 鑑定品", language="ja",
                    url="https://snkrdunk-fixture.invalid/listings/901", status="on_sale",
                    price={"amount_minor": 8000, "currency": "JPY"},
                    grade_company="PSA", grade_value="9")], "page_complete": True}),
        ]
        with closing(core.connect(database)) as db:
            core.init_db(db)
            core.import_cards(db, [dict(language="ja", set_code="SV2a", collector_number="173/165",
                variant="standard", name="ピカチュウ", provenance="synthetic integration only",
                rights_reference="synthetic integration only", display_allowed=True, match_eligible=True)])
            for source in sources:
                core.register_source(db, dict(source=source, rights_reference="synthetic integration only",
                    ingest_allowed=True, display_allowed=True, price_statistics_allowed=True,
                    cross_source_use_allowed=True, photo_resolution_required=source == "ebay_us_fixture",
                    retention_days=7, listing_ttl_hours=1))
            ingest.initialize(db)
            for capture in captures:
                receipt = ingest.import_capture(db, capture, now=self.now)
                self.assertEqual(receipt["imported"], 1)
                self.assertEqual(receipt["network_calls"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM marketplace_capture").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM marketplace_observation_quality").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ingest_receipt").fetchone()[0], 3)
            ebay = db.execute("SELECT unit_id FROM listing WHERE source='ebay_us_fixture'").fetchone()
            self.assertIsNone(ebay["unit_id"])
            ebay_quality = json.loads(db.execute("SELECT quality_json FROM marketplace_observation_quality "
                                                 "WHERE source='ebay_us_fixture'").fetchone()[0])
            self.assertEqual((ebay_quality["grade_company"], ebay_quality["grade_value"]), ("PSA", "10"))
            self.assertEqual(ebay_quality["certificate_number_claim"], "87654321")
            self.assertIs(ebay_quality["certificate_verified"], False)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        report = build_report(database, CARD_ID, now=self.now, sources=sources)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        panels = {panel["source"]: panel for panel in report["platforms"]}
        self.assertEqual(set(panels), set(sources))
        self.assertEqual(panels["ebay_us_fixture"]["groups"], [])
        self.assertEqual(panels["mercari_fixture"]["groups"][0]["unit_id"], PSA10_UNIT)
        self.assertEqual(panels["snkrdunk_fixture"]["groups"][0]["unit_id"], PSA9_UNIT)
        self.assertEqual(report["data_readiness"]["current_eligible_listing_count"], 2)
        mercari_quality = panels["mercari_fixture"]["groups"][0]["offers"][0]["quality"]
        self.assertEqual(mercari_quality["certificate_number_claim"], "12345678")
        self.assertIs(mercari_quality["certificate_verified"], False)
        self.assertIs(report["data_readiness"]["live_source_collection_verified"], False)

    def test_open_caller_cursor_cannot_hide_committed_permission_revocation(self):
        with closing(core.connect(self.path)) as reader:
            reader.execute("PRAGMA journal_mode=WAL").fetchall()
            cursor = reader.execute("SELECT * FROM source_policy")
            try:
                self.assertFalse(reader.in_transaction)
                with closing(core.connect(self.path)) as writer:
                    writer.execute("UPDATE source_policy SET display_allowed=0 WHERE source=?", (SOURCES[1],))
                    writer.commit()
                self.assertEqual(reader.execute("SELECT display_allowed FROM source_policy WHERE source=?",
                                                (SOURCES[1],)).fetchone()[0], 1)
                self.assertNotIn(SOURCES[1], {p["source"] for p in self.report()["platforms"]})
                self.assertIsNotNone(cursor.fetchone())
            finally:
                cursor.close()

    def test_catalog_identity_hold_blocks_report(self):
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE card SET match_eligible=0 WHERE card_id=?", (CARD_ID,))
            db.commit()
        with self.assertRaisesRegex(ValueError, "not match-eligible"):
            self.report()

    def test_exact_units_currencies_and_current_listing_counts(self):
        report = self.report()
        self.assertEqual(report["price_type"], "native_listing_ask")
        self.assertEqual({platform["source"] for platform in report["platforms"]}, set(SOURCES))
        groups = self.groups(report)
        self.assertEqual({group["unit_id"] for group in groups}, {RAW_UNIT, PSA9_UNIT, PSA10_UNIT})
        self.assertEqual({group["currency"] for group in groups}, {"JPY", "USD"})
        alpha = next(platform for platform in report["platforms"] if platform["source"] == SOURCES[0])
        raw = next(group for group in alpha["groups"] if group["unit_id"] == RAW_UNIT)
        self.assertEqual(raw["listing_count"], 2)
        self.assertEqual(raw["min_ask_minor"], 1100)
        self.assertEqual(raw["median_ask_minor_decimal"], "1300")
        self.assertEqual([event["price_minor"] for event in alpha["listing_events"]
                          if event["native_id"] == "raw-a"], [1000, 1100, 1100])

    def test_stale_sold_and_gone_stay_in_history_but_not_current(self):
        report = self.report()
        self.assertFalse(self.current_ids(report) & {"stale-a", "sold-a", "gone-a"})
        events = [event for platform in report["platforms"] for event in platform["listing_events"]]
        self.assertTrue({"stale-a", "sold-a", "gone-a"} <= {event["native_id"] for event in events})
        self.assertTrue({"sold_out", "gone"} <= {event["status"] for event in events})
        with closing(core.connect(self.path, readonly=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM verified_sale").fetchone()[0], 0)

    def test_grade_labels_never_claim_certificate_or_authenticity_verification(self):
        offers = [offer for group in self.groups() for offer in group["offers"]]
        for offer in offers:
            quality = offer["quality"]
            self.assertIs(quality["certificate_verified"], False)
            self.assertIs(quality["authenticity_verified"], False)
            self.assertIs(quality["physical_inspection_performed"], False)

    def test_revoked_ingest_display_or_statistics_removes_source_data(self):
        for field in ("ingest_allowed", "display_allowed", "price_statistics_allowed"):
            with self.subTest(field=field):
                with closing(core.connect(self.path)) as db:
                    db.execute(f"UPDATE source_policy SET {field}=0 WHERE source=?", (SOURCES[1],))
                    db.commit()
                report = self.report()
                self.assertNotIn(SOURCES[1], {platform["source"] for platform in report["platforms"]})
                # Rights-blocked reports may name the source, but never its listings.
                self.assertNotIn('"raw-b"', json.dumps(report))
                self.assertNotIn('"psa10-b"', json.dumps(report))
                with closing(core.connect(self.path)) as db:
                    db.execute(f"UPDATE source_policy SET {field}=1 WHERE source=?", (SOURCES[1],))
                    db.commit()

    def test_expired_source_removes_current_and_historical_data(self):
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE source_policy SET expires_at=? WHERE source=?",
                       ((core.parse_time(self.now) - timedelta(days=1)).isoformat(), SOURCES[1]))
            db.commit()
        self.assertNotIn(SOURCES[1], {platform["source"] for platform in self.report()["platforms"]})

    def test_combined_source_report_requires_cross_source_permission(self):
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE source_policy SET cross_source_use_allowed=0 WHERE source=?", (SOURCES[1],))
            db.commit()
        with self.assertRaisesRegex(ValueError, "cross-source"):
            self.report()

    def test_latest_human_bound_slab_missing_grade_is_not_current(self):
        with closing(core.connect(self.path)) as db:
            title = "ピカチュウ SV2a 173/165 PSA 鑑定品"
            db.execute("UPDATE listing SET title=?,resolution_method='human' WHERE native_id='psa10-a'", (title,))
            db.execute("UPDATE observation SET title=? WHERE native_id='psa10-a'", (title,))
            db.commit()
        self.assertNotIn("psa10-a", self.current_ids())

    def test_human_bound_raw_listing_with_psa_claim_is_not_current(self):
        with closing(core.connect(self.path)) as db:
            title = "ピカチュウ SV2a 173/165 PSA10 鑑定品"
            db.execute("UPDATE listing SET title=?,resolution_method='human' WHERE native_id='raw-a'", (title,))
            db.execute("UPDATE observation SET title=? WHERE native_id='raw-a'", (title,))
            db.commit()
        self.assertNotIn("raw-a", self.current_ids())

    def test_later_human_resolution_does_not_backdate_unit_history(self):
        at = core.parse_time(self.now)
        observed = (at - timedelta(minutes=20)).isoformat()
        reviewed = (at - timedelta(minutes=10)).isoformat()
        source, native = SOURCES[0], "later-human-binding"
        title = "ピカチュウ SV2a 173/165"
        with closing(core.connect(self.path)) as db:
            core.import_observations(db, [dict(source=source, native_id=native, title=title,
                url=f"https://example.invalid/{native}", observed_at=observed, status="on_sale",
                price_minor=1234, currency="JPY", evidence_ref="synthetic:later-human-binding",
                resolution_gate="photo_required")])
            with patch.object(core, "utcnow", return_value=reviewed):
                core.override_resolution(db, source, native, RAW_UNIT, "synthetic-reviewer", "synthetic later review")
        events = [event for platform in self.report()["platforms"] for event in platform["listing_events"]
                  if event["native_id"] == native]
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["unit_id"])
        self.assertNotEqual(events[0]["unit_binding_status"], "time_effective_indexed_binding")

    def test_demoted_listing_keeps_prior_bound_history_without_current_price(self):
        newer = (core.parse_time(self.now) - timedelta(minutes=5)).isoformat()
        with closing(core.connect(self.path)) as db:
            core.import_observations(db, [dict(source=SOURCES[0], native_id="psa10-a",
                title="ピカチュウ SV2a 173/165 PSA 鑑定品",
                url="https://alpha-market-fixture.invalid/psa10-a", language="ja",
                observed_at=newer, status="on_sale", price_minor=12000, currency="JPY",
                evidence_ref="synthetic:newest-unreadable-grade")])
        report = self.report()
        self.assertNotIn("psa10-a", self.current_ids(report))
        events = [event for platform in report["platforms"] for event in platform["listing_events"]
                  if event["native_id"] == "psa10-a"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["unit_id"], PSA10_UNIT)
        self.assertEqual(events[0]["unit_binding_status"], "time_effective_indexed_binding")
        self.assertIsNone(events[1]["unit_id"])

    def test_native_minor_median_remains_exact_above_float_integer_precision(self):
        newer = (core.parse_time(self.now) - timedelta(minutes=1)).isoformat()
        with closing(core.connect(self.path)) as db:
            for native, amount in (("raw-a", 9007199254740992), ("raw-a2", 9007199254740993)):
                core.import_observations(db, [dict(source=SOURCES[0], native_id=native,
                    title="ピカチュウ SV2a 173/165", language="ja",
                    url=f"https://alpha-market-fixture.invalid/{native}",
                    observed_at=newer, status="on_sale", price_minor=amount, currency="JPY",
                    evidence_ref=f"synthetic:exact-integer:{native}")])
        platform = next(platform for platform in self.report()["platforms"] if platform["source"] == SOURCES[0])
        raw = next(group for group in platform["groups"] if group["unit_id"] == RAW_UNIT)
        self.assertEqual(raw["median_ask_minor_decimal"], "9007199254740992.5")
        self.assertNotIn("median_ask_minor", raw)

    def test_expected_missing_source_is_blocked_and_whitelist_excludes_others(self):
        missing = "not_configured_market_fixture"
        report = build_report(self.path, CARD_ID, now=self.now, sources=[SOURCES[1], missing])
        self.assertEqual({platform["source"] for platform in report["platforms"]}, {SOURCES[1]})
        self.assertEqual({blocked["source"] for blocked in report["blocked_sources"]}, {missing})
        self.assertEqual(set(report["requested_sources"]), {SOURCES[1], missing})
        self.assertNotIn('"raw-a"', json.dumps(report))
        self.assertNotIn('"raw-c"', json.dumps(report))
        self.assertIs(report["data_readiness"]["live_source_collection_verified"], False)

    def test_expected_allowed_empty_source_is_local_missing_data_not_search_zero(self):
        empty = "empty_market_fixture"
        with closing(core.connect(self.path)) as db:
            core.register_source(db, dict(source=empty, rights_reference="synthetic empty fixture",
                ingest_allowed=True, display_allowed=True, price_statistics_allowed=True,
                cross_source_use_allowed=True, retention_days=7, listing_ttl_hours=1))
        report = build_report(self.path, CARD_ID, now=self.now, sources=[empty])
        self.assertEqual(report["blocked_sources"], [])
        self.assertEqual(len(report["platforms"]), 1)
        self.assertEqual(report["platforms"][0]["source"], empty)
        self.assertEqual(report["platforms"][0]["groups"], [])
        self.assertEqual(report["platforms"][0]["listing_events"], [])
        self.assertEqual(report["data_readiness"]["current_eligible_listing_count"], 0)
        self.assertTrue(all(row["status"] == "no_eligible_asks_in_local_snapshot" for row in report["coverage"]))
        self.assertTrue(all(row["live_search_coverage_verified"] is False for row in report["coverage"]))

    def test_missing_database_is_not_created(self):
        missing = Path(self.temporary.name) / "does-not-exist.sqlite3"
        with self.assertRaises((ValueError, FileNotFoundError, sqlite3.OperationalError)):
            build_report(missing, CARD_ID, now=self.now)
        self.assertFalse(missing.exists())

    def test_report_does_not_write_database_or_import_partner_client(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        before_modules = set(sys.modules)
        self.report()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertNotIn("pokemon_index.buyship_partner", set(sys.modules) - before_modules)
        from pokemon_index import market_tracking
        source = Path(market_tracking.__file__).read_text()
        self.assertNotIn("import buyship", source)
        self.assertNotIn("import psa", source.lower())
        with closing(core.connect(self.path, readonly=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM landed_quote").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
