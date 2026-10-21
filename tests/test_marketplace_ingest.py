import copy
from contextlib import closing, ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, marketplace_ingest as ingest
from scripts import market_tracker

NOW = "2026-10-20T00:05:00Z"
SOURCE = "mercari_fixture"
CARD = "ja:FIX:001/100:normal"


class MarketplaceIngestTests(unittest.TestCase):
    def setUp(self):
        self.guards = ExitStack()
        for obj, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                          (socket.socket, "sendto"), (socket, "create_connection"), (socket, "getaddrinfo")):
            self.guards.enter_context(patch.object(obj, name, side_effect=AssertionError("offline test")))
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "market.sqlite3"
        self.db = core.connect(self.path)
        core.init_db(self.db)
        core.register_source(self.db, dict(source=SOURCE, rights_reference="synthetic test only",
            ingest_allowed=True, display_allowed=True, price_statistics_allowed=True,
            cross_source_use_allowed=True, retention_days=1, listing_ttl_hours=1))
        core.import_cards(self.db, [dict(language="ja", set_code="FIX", collector_number="001/100",
            variant="normal", name="Synthetic", provenance="synthetic", rights_reference="synthetic",
            match_eligible=True, display_allowed=True)])
        ingest.initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
        self.guards.close()

    def capture(self, **changes):
        result = dict(schema="pokemon.marketplace-capture.v1", source=SOURCE,
            observed_at="2026-10-20T00:00:00Z", request={"kind": "search", "query": "Synthetic FIX 001/100",
            "target_card_ids": [CARD]}, payload_schema="pokemon.mercari-authorized-export.v1",
            payload={"listings": [dict(listing_id="m100", title="Synthetic FIX 001/100", language="ja",
                url="https://mercari.invalid/item/m100", status="on_sale",
                price={"amount_minor": 1000, "currency": "JPY"}, seller_id="synthetic-seller")],
                "page_complete": True})
        result.update(changes)
        return result

    def counts(self):
        return {table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("listing", "observation", "ingest_receipt", "marketplace_capture",
                              "marketplace_observation_quality")}

    def test_atomic_import_and_idempotent_capture_replay(self):
        first = ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertEqual(first["imported"], 1)
        self.assertEqual(first["network_calls"], 0)
        self.assertEqual(set(self.counts().values()), {1})
        again = ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertEqual(again["duplicates"], 1)
        self.assertTrue(again["capture_replayed"])
        self.assertEqual(set(self.counts().values()), {1})
        quality = json.loads(self.db.execute("SELECT quality_json FROM marketplace_observation_quality").fetchone()[0])
        self.assertFalse(quality["certificate_verified"])

    def test_conflict_rolls_back_new_rows_and_quality_together(self):
        ingest.import_capture(self.db, self.capture(), now=NOW)
        before = self.counts()
        conflict = self.capture()
        second = copy.deepcopy(conflict["payload"]["listings"][0])
        second["listing_id"] = "m200"
        second["url"] = "https://mercari.invalid/item/m200"
        conflict["payload"]["listings"].insert(0, second)
        conflict["payload"]["listings"][1]["price"]["amount_minor"] = 2000
        with self.assertRaisesRegex(ValueError, "conflict"):
            ingest.import_capture(self.db, conflict, now=NOW)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.db.in_transaction)

    def test_quality_storage_failure_rolls_back_observation_and_receipt(self):
        self.db.execute("""CREATE TRIGGER reject_quality BEFORE INSERT ON marketplace_observation_quality
            BEGIN SELECT RAISE(ABORT, 'synthetic quality failure'); END""")
        with self.assertRaisesRegex(Exception, "quality failure"):
            ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertEqual(set(self.counts().values()), {0})

    def test_empty_search_is_coverage_not_a_sold_event(self):
        ingest.import_capture(self.db, self.capture(), now=NOW)
        empty = self.capture(observed_at="2026-10-20T00:04:00Z")
        empty["payload"]["listings"] = []
        receipt = ingest.import_capture(self.db, empty, now=NOW)
        self.assertEqual(receipt["imported"], 0)
        self.assertEqual(self.db.execute("SELECT current_status FROM listing").fetchone()[0], "on_sale")
        self.assertEqual(self.counts()["marketplace_capture"], 2)

    def test_per_card_coverage_shows_empty_page_without_removing_current_asks(self):
        from pokemon_index.market_tracking import build_report
        ingest.import_capture(self.db, self.capture(), now=NOW)
        empty = self.capture(observed_at="2026-10-20T00:04:00Z")
        empty["payload"]["listings"] = []
        ingest.import_capture(self.db, empty, now=NOW)
        panel = build_report(self.path, CARD, now=NOW, sources=[SOURCE])["platforms"][0]
        self.assertEqual(panel["collection_coverage"]["status"], "capture_recorded_for_declared_target")
        self.assertEqual(panel["collection_coverage"]["returned_rows_per_capture"], [0])
        self.assertFalse(panel["collection_coverage"]["live_collection_verified"])
        self.assertEqual(panel["groups"][0]["listing_count"], 1)

    def test_new_unreadable_slab_condition_demotes_old_human_raw_binding(self):
        from pokemon_index.market_tracking import build_report
        ingest.import_capture(self.db, self.capture(), now=NOW)
        unit = self.db.execute("SELECT unit_id FROM listing").fetchone()[0]
        with patch.object(core, "utcnow", return_value="2026-10-20T00:01:00Z"):
            core.override_resolution(self.db, SOURCE, "m100", unit, "synthetic reviewer", "synthetic review")
        newer = self.capture(observed_at="2026-10-20T00:04:00Z")
        newer["payload"]["listings"][0]["seller_condition"] = "PSA graded card, unreadable grade"
        ingest.import_capture(self.db, newer, now=NOW)
        self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])
        self.assertEqual(core.offers(self.db, CARD, now=NOW), [])
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual(report["platforms"][0]["groups"], [])
        # A later manual attempt also cannot bypass conflicting seller evidence.
        with patch.object(core, "utcnow", return_value="2026-10-20T00:04:30Z"):
            core.override_resolution(self.db, SOURCE, "m100", unit, "synthetic reviewer", "synthetic review")
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual(report["platforms"][0]["groups"], [])
        self.assertIn("raw unit", report["excluded"][0]["reason"])

    def test_unreadable_slab_or_grader_titles_never_start_as_raw_asks(self):
        from pokemon_index.market_tracking import build_report
        for index, cue in enumerate(("slab", "graded", "PSA unknown", "PSA"), 1):
            with self.subTest(cue=cue):
                capture = self.capture()
                item = capture["payload"]["listings"][0]
                item.update(listing_id=f"m{index}", url=f"https://mercari.invalid/item/m{index}",
                            title=f"Synthetic FIX 001/100 {cue}")
                ingest.import_capture(self.db, capture, now=NOW)
                listing = self.db.execute("SELECT unit_id FROM listing WHERE native_id=?",
                                          (item["listing_id"],)).fetchone()
                self.assertIsNone(listing["unit_id"])
        self.assertEqual(core.offers(self.db, CARD, now=NOW), [])
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual(report["platforms"][0]["groups"], [])
        self.assertFalse(any(event["unit_id"] for event in report["platforms"][0]["listing_events"]))

    def test_unreadable_title_demotes_human_raw_binding_and_leaves_prior_history(self):
        from pokemon_index.market_tracking import build_report
        for index, cue in enumerate(("slab", "graded", "PSA unknown", "PSA"), 1):
            with self.subTest(cue=cue):
                capture = self.capture()
                native = f"m{index}"
                item = capture["payload"]["listings"][0]
                item.update(listing_id=native, url=f"https://mercari.invalid/item/{native}")
                ingest.import_capture(self.db, capture, now=NOW)
                unit = self.db.execute("SELECT unit_id FROM listing WHERE native_id=?", (native,)).fetchone()[0]
                with patch.object(core, "utcnow", return_value="2026-10-20T00:01:00Z"):
                    core.override_resolution(self.db, SOURCE, native, unit, "synthetic reviewer", "synthetic review")
                newer = copy.deepcopy(capture)
                newer["observed_at"] = "2026-10-20T00:04:00Z"
                newer["payload"]["listings"][0]["title"] += f" {cue}"
                ingest.import_capture(self.db, newer, now=NOW)
                self.assertIsNone(self.db.execute("SELECT unit_id FROM listing WHERE native_id=?", (native,)).fetchone()[0])
                self.assertNotIn(native, {offer["native_id"] for offer in core.offers(self.db, CARD, now=NOW)})
                report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
                self.assertEqual(report["platforms"][0]["groups"], [])
                events = [event for event in report["platforms"][0]["listing_events"] if event["native_id"] == native]
                self.assertEqual(len(events), 2)
                self.assertEqual(events[0]["unit_id"], unit)
                self.assertIsNone(events[1]["unit_id"])
                # Even a later stale manual RAW assignment cannot make the
                # new unreadable slab title acceptable to the report.
                with patch.object(core, "utcnow", return_value="2026-10-20T00:04:30Z"):
                    core.override_resolution(self.db, SOURCE, native, unit, "synthetic reviewer", "synthetic review")
                report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
                self.assertEqual(report["platforms"][0]["groups"], [])
                newest = [event for event in report["platforms"][0]["listing_events"]
                          if event["native_id"] == native][-1]
                self.assertIsNone(newest["unit_id"])

    def test_older_observation_cannot_restore_newest_pending_grade_binding(self):
        from pokemon_index.market_tracking import build_report
        capture = self.capture()
        capture["payload"]["listings"][0].update(
            title="Synthetic FIX 001/100 PSA10 鑑定品", grade_company="PSA", grade_value="10")
        ingest.import_capture(self.db, capture, now=NOW)
        unit = self.db.execute("SELECT unit_id FROM listing").fetchone()[0]
        pending = copy.deepcopy(capture)
        pending["observed_at"] = "2026-10-20T00:04:00Z"
        pending["payload"]["listings"][0]["title"] = "Synthetic FIX 001/100"
        ingest.import_capture(self.db, pending, now=NOW)
        self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])
        older = copy.deepcopy(capture)
        older["observed_at"] = "2026-10-20T00:02:00Z"
        receipt = ingest.import_capture(self.db, older, now=NOW)
        self.assertEqual(receipt["imported"], 1)
        listing = self.db.execute("SELECT unit_id,last_seen FROM listing").fetchone()
        self.assertIsNone(listing["unit_id"])
        self.assertEqual(core.parse_time(listing["last_seen"]), core.parse_time(pending["observed_at"]))
        self.assertEqual(core.offers(self.db, CARD, now=NOW), [])
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual(report["platforms"][0]["groups"], [])
        events = report["platforms"][0]["listing_events"]
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["unit_id"], unit)
        self.assertIsNone(events[-1]["unit_id"])
        before = self.counts()
        replay = ingest.import_capture(self.db, older, now=NOW)
        self.assertTrue(replay["capture_replayed"])
        self.assertEqual(self.counts(), before)
        self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])

    def test_changed_grade_is_retained_unresolved_and_review_survives_exact_replay(self):
        from pokemon_index.market_tracking import build_report
        capture = self.capture()
        capture["payload"]["listings"][0].update(
            title="Synthetic FIX 001/100 PSA10 鑑定品", grade_company="PSA", grade_value="10")
        ingest.import_capture(self.db, capture, now=NOW)
        old_unit = self.db.execute("SELECT unit_id FROM listing").fetchone()[0]
        newer = copy.deepcopy(capture)
        newer["observed_at"] = "2026-10-20T00:04:00Z"
        newer["payload"]["listings"][0].update(title="Synthetic FIX 001/100 PSA9 鑑定品", grade_value="9")
        unrelated = copy.deepcopy(self.capture()["payload"]["listings"][0])
        unrelated.update(listing_id="m200", url="https://mercari.invalid/item/m200")
        newer["payload"]["listings"].append(unrelated)
        receipt = ingest.import_capture(self.db, newer, now=NOW)
        self.assertEqual(receipt["imported"], 2)
        self.assertEqual(self.counts(), dict(listing=2, observation=3, ingest_receipt=3,
            marketplace_capture=2, marketplace_observation_quality=3))
        self.assertIsNone(self.db.execute("SELECT unit_id FROM listing WHERE native_id='m100'").fetchone()[0])
        quality = json.loads(self.db.execute("SELECT quality_json FROM marketplace_observation_quality "
            "WHERE native_id='m100' ORDER BY observed_at DESC LIMIT 1").fetchone()[0])
        self.assertEqual((quality["grade_company"], quality["grade_value"]), ("PSA", "9"))
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        current = {offer["native_id"] for group in report["platforms"][0]["groups"] for offer in group["offers"]}
        self.assertEqual(current, {"m200"})
        events = [event for event in report["platforms"][0]["listing_events"] if event["native_id"] == "m100"]
        self.assertEqual(events[0]["unit_id"], old_unit)
        self.assertIsNone(events[-1]["unit_id"])
        new_unit = core._unit(self.db, CARD, "PSA", "9", "graded")
        self.db.commit()
        with patch.object(core, "utcnow", return_value="2026-10-20T00:04:30Z"):
            core.override_resolution(self.db, SOURCE, "m100", new_unit, "synthetic reviewer", "synthetic new grade review")
        before = self.counts()
        replay = ingest.import_capture(self.db, newer, now=NOW)
        self.assertTrue(replay["capture_replayed"])
        self.assertEqual(replay["duplicates"], 2)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.db.execute("SELECT unit_id FROM listing WHERE native_id='m100'").fetchone()[0], new_unit)
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        groups = [group for group in report["platforms"][0]["groups"]
                  if any(offer["native_id"] == "m100" for offer in group["offers"])]
        self.assertEqual([group["unit_id"] for group in groups], [new_unit])

    def test_older_changed_grade_cannot_change_current_unit_or_inherit_its_grade(self):
        from pokemon_index.market_tracking import build_report
        current = self.capture(observed_at="2026-10-20T00:04:00Z")
        current["payload"]["listings"][0].update(
            title="Synthetic FIX 001/100 PSA10 鑑定品", grade_company="PSA", grade_value="10")
        ingest.import_capture(self.db, current, now=NOW)
        unit = self.db.execute("SELECT unit_id FROM listing").fetchone()[0]
        older = copy.deepcopy(current)
        older["observed_at"] = "2026-10-20T00:02:00Z"
        older["payload"]["listings"][0].update(title="Synthetic FIX 001/100 PSA9 鑑定品", grade_value="9")
        receipt = ingest.import_capture(self.db, older, now=NOW)
        self.assertEqual(receipt["imported"], 1)
        listing = self.db.execute("SELECT unit_id,last_seen FROM listing").fetchone()
        self.assertEqual(listing["unit_id"], unit)
        self.assertEqual(core.parse_time(listing["last_seen"]), core.parse_time(current["observed_at"]))
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual([group["unit_id"] for group in report["platforms"][0]["groups"]], [unit])
        events = report["platforms"][0]["listing_events"]
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0]["unit_id"], unit)
        self.assertEqual(events[-1]["unit_id"], unit)

    def test_changed_unit_hold_survives_later_polls_until_explicit_human_review(self):
        from pokemon_index.market_tracking import build_report
        capture = self.capture()
        def observe(at, grade):
            result = copy.deepcopy(capture)
            result["observed_at"] = at
            result["payload"]["listings"][0].update(
                title=f"Synthetic FIX 001/100 PSA{grade} 鑑定品", grade_company="PSA", grade_value=grade)
            return result
        ingest.import_capture(self.db, observe("2026-10-20T00:00:00Z", "10"), now=NOW)
        # A second poll of the changed grade, or a return to the original
        # grade, cannot act as the explicit review required by this hold.
        for at, grade in (("2026-10-20T00:01:00Z", "9"),
                          ("2026-10-20T00:02:00Z", "9"),
                          ("2026-10-20T00:03:00Z", "10"),
                          ("2026-10-20T00:03:30Z", "9")):
            with self.subTest(at=at, grade=grade):
                ingest.import_capture(self.db, observe(at, grade), now=NOW)
                self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])
                self.assertEqual(core.offers(self.db, CARD, now=NOW), [])
                report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
                self.assertEqual(report["platforms"][0]["groups"], [])
                self.assertIsNone(report["platforms"][0]["listing_events"][-1]["unit_id"])
        unit = core._unit(self.db, CARD, "PSA", "9", "graded")
        self.db.commit()
        with patch.object(core, "utcnow", return_value="2026-10-20T00:04:00Z"):
            core.override_resolution(self.db, SOURCE, "m100", unit, "synthetic reviewer", "reviewed changed unit")
        ingest.import_capture(self.db, observe("2026-10-20T00:04:30Z", "9"), now=NOW)
        self.assertEqual(self.db.execute("SELECT unit_id FROM listing").fetchone()[0], unit)
        report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
        self.assertEqual([group["unit_id"] for group in report["platforms"][0]["groups"]], [unit])
        self.assertEqual(self.counts()["observation"], 6)

    def test_exact_replay_preserves_review_of_structured_grade(self):
        from pokemon_index.market_tracking import build_report
        capture = self.capture()
        capture["payload"]["listings"][0].update(grade_company="PSA", grade_value="10")
        ingest.import_capture(self.db, capture, now=NOW)
        self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])
        unit = core._unit(self.db, CARD, "PSA", "10", "graded")
        self.db.commit()
        with patch.object(core, "utcnow", return_value="2026-10-20T00:01:00Z"):
            core.override_resolution(self.db, SOURCE, "m100", unit, "synthetic reviewer", "synthetic review")
        ingest.import_capture(self.db, capture, now=NOW)
        self.assertEqual(self.db.execute("SELECT unit_id FROM listing").fetchone()[0], unit)
        group = build_report(self.path, CARD, now=NOW, sources=[SOURCE])["platforms"][0]["groups"][0]
        self.assertEqual(group["unit_id"], unit)
        self.assertFalse(group["offers"][0]["quality"]["certificate_verified"])

    def test_condition_grade_conflicts_never_enter_current_or_historical_grade_groups(self):
        from pokemon_index.market_tracking import build_report
        capture = self.capture()
        capture["payload"]["listings"][0].update(
            title="Synthetic FIX 001/100 PSA10 鑑定品", grade_company="PSA", grade_value="10")
        ingest.import_capture(self.db, capture, now=NOW)
        unit = self.db.execute("SELECT unit_id FROM listing").fetchone()[0]
        for index, condition in enumerate(("PSA9 graded card", "BGS10 graded card", "PSA11 slab", "raw ungraded"), 1):
            with self.subTest(condition=condition):
                newer = copy.deepcopy(capture)
                newer["observed_at"] = f"2026-10-20T00:0{index}:00Z"
                newer["payload"]["listings"][0]["seller_condition"] = condition
                ingest.import_capture(self.db, newer, now=NOW)
                self.assertIsNone(self.db.execute("SELECT unit_id FROM listing").fetchone()[0])
                with patch.object(core, "utcnow", return_value=f"2026-10-20T00:0{index}:30Z"):
                    core.override_resolution(self.db, SOURCE, "m100", unit, "synthetic reviewer", "synthetic review")
                report = build_report(self.path, CARD, now=NOW, sources=[SOURCE])
                self.assertEqual(report["platforms"][0]["groups"], [])
                self.assertIsNone(report["platforms"][0]["listing_events"][-1]["unit_id"])

    def test_future_old_or_revoked_empty_capture_refused(self):
        for at in ("2026-10-20T01:00:00Z", "2026-10-18T00:00:00Z"):
            capture = self.capture(observed_at=at)
            capture["payload"]["listings"] = []
            with self.assertRaisesRegex(ValueError, "time window"):
                ingest.import_capture(self.db, capture, now=NOW)
        self.db.execute("UPDATE source_policy SET ingest_allowed=0")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "policy"):
            ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertEqual(set(self.counts().values()), {0})

    def test_active_caller_transaction_is_refused_without_committing_it(self):
        self.db.execute("BEGIN")
        with self.assertRaisesRegex(ValueError, "active transaction"):
            ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertTrue(self.db.in_transaction)
        with self.assertRaisesRegex(ValueError, "active transaction"):
            ingest.initialize(self.db)
        self.db.rollback()

    def test_fixture_capture_cannot_enter_real_inventory_database(self):
        core.register_source(self.db, dict(source="real_authorized_example", rights_reference="test only",
            ingest_allowed=True, retention_days=1))
        core.import_observations(self.db, [dict(source="real_authorized_example", native_id="existing",
            title="Synthetic FIX 001/100", url="https://example.com/existing", language="ja",
            observed_at="2026-10-20T00:00:00Z", status="on_sale", price_minor=1,
            currency="JPY", evidence_ref="synthetic:test-real-isolation")])
        before = self.counts()
        with self.assertRaisesRegex(ValueError, "isolated"):
            ingest.import_capture(self.db, self.capture(), now=NOW)
        self.assertEqual(self.counts(), before)

    def test_retention_cascades_quality_and_removes_capture_receipts(self):
        ingest.import_capture(self.db, self.capture(), now=NOW)
        removed = ingest.purge(self.db, now="2026-10-22T00:00:00Z")
        self.assertEqual(removed["marketplace_observation_quality"], 1)
        self.assertEqual(removed["marketplace_capture"], 1)
        self.assertEqual(set(self.counts().values()), {0})
        with self.assertRaisesRegex(ValueError, "time window"):
            ingest.import_capture(self.db, self.capture(), now="2026-10-22T00:00:00Z")

    def test_foreign_keys_required_for_import_and_quality_retention(self):
        self.db.execute("PRAGMA foreign_keys=OFF")
        with self.assertRaisesRegex(ValueError, "foreign-key"):
            ingest.import_capture(self.db, self.capture(), now=NOW)
        with self.assertRaisesRegex(ValueError, "foreign-key"):
            ingest.purge(self.db, now=NOW)

    def test_bounded_local_json_rejects_duplicate_keys_nonfinite_and_nonobjects(self):
        path = Path(self.tmp.name) / "capture.json"
        for raw in ('{"source":"one","source":"two"}', '{"price": NaN}', '[]'):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                ingest.load_capture(path)
        path.write_bytes(b" " * (ingest.MAX_CAPTURE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "limit"):
            ingest.load_capture(path)

    def test_cli_init_is_exclusive_and_missing_replay_database_not_created(self):
        path = Path(self.tmp.name) / "new.sqlite3"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(market_tracker.main(["--db", str(path), "init"]), 0)
        with self.assertRaises(FileExistsError):
            market_tracker.main(["--db", str(path), "init"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(market_tracker.main(["--db", str(path), "prepare"]), 0)
        with closing(core.connect(path, readonly=True)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_policy").fetchone()[0], 0)
        missing = Path(self.tmp.name) / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError):
            market_tracker.main(["--db", str(missing), "replay", "unused.json"])
        self.assertFalse(missing.exists())

    def test_cli_replay_and_readonly_report_emit_native_asks_and_quality(self):
        path = Path(self.tmp.name) / "capture.json"
        path.write_text(json.dumps(self.capture()))
        receipt_out, report_out = io.StringIO(), io.StringIO()
        with patch.object(core, "utcnow", return_value=NOW), redirect_stdout(receipt_out):
            self.assertEqual(market_tracker.main(["--db", str(self.path), "replay", str(path)]), 0)
        self.assertEqual(json.loads(receipt_out.getvalue())["imported"], 1)
        before = self.path.read_bytes()
        with patch.object(core, "utcnow", return_value=NOW), redirect_stdout(report_out):
            self.assertEqual(market_tracker.main(["--db", str(self.path), "report", CARD, "--source", SOURCE]), 0)
        report = json.loads(report_out.getvalue())
        offer = report["platforms"][0]["groups"][0]["offers"][0]
        self.assertEqual(offer["price_minor"], 1000)
        self.assertEqual(report["price_type"], "native_listing_ask")
        self.assertFalse(offer["quality"]["certificate_verified"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_disposable_rehearsal_runs_without_network_or_quote_records(self):
        from scripts.rehearse_market_tracking import rehearse
        result = rehearse()
        self.assertTrue(result["passed"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["fixture"]["counts"]["landed_quote"], 0)


if __name__ == "__main__":
    unittest.main()
