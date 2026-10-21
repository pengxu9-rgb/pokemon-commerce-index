"""Provider preparation is offline; all future wire calls use injected fixtures."""
import copy
from contextlib import redirect_stdout
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request

from pokemon_index import core, provider_smoke as smoke
from pokemon_index.buyship_partner import PartnerClient
from pokemon_index.commerce_loop import CommerceLoop

CARD = "ja:SV2A:173/165:standard"
BASE = "https://bns.partner.example.com"
CLIENT_SECRET = "private-fixture-secret-never-print"


class ProviderSmokeTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("socket.create_connection", side_effect=AssertionError("offline tests"))
        self.connect = patch("socket.socket.connect", side_effect=AssertionError("offline tests"))
        self.network.start(); self.connect.start()
        self.addCleanup(self.network.stop); self.addCleanup(self.connect.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "operator.sqlite3"
        self.db = sqlite3.connect(self.path); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        core.init_db(self.db)
        core.register_source(self.db, {"source": "mercari", "rights_reference": "offline fixture only",
            "ingest_allowed": True, "display_allowed": True, "partner_handoff_allowed": True,
            "retention_days": 1, "listing_ttl_hours": 1})
        core.import_cards(self.db, [{"match_eligible": True, "language": "ja", "set_code": "SV2a",
            "collector_number": "173/165", "variant": "standard", "name": "Pikachu", "rarity": "AR",
            "provenance": "offline fixture", "rights_reference": "offline fixture", "display_allowed": True}])
        self.instant = smoke._instant(core.utcnow())
        self.now = lambda: self.instant.isoformat()
        row = {"source": "mercari", "native_id": "m1001", "url": "https://jp.mercari.com/item/m1001",
            "title": "Pikachu SV2a 173/165 PSA 10 graded card", "price_minor": 12000, "currency": "JPY",
            "availability": "in_stock", "status": "on_sale", "grade_company": "PSA", "grade_value": "10",
            "scope": "listing", "observed_at": self.now(), "language": "ja", "evidence_ref": "offline:fixture"}
        core.import_observations(self.db, [row])
        self.offer = CommerceLoop(object(), now=self.now)._offer(row, "mercari", self.instant)
        self.fixture = json.loads((Path(__file__).parents[1] / "examples/buyship_partner_preview.json").read_text())
        self.fixture["resolve"]["url"] = row["url"]
        self.fixture["resolve"]["product"]["name"] = row["title"]
        self.fixture["resolve"]["variants"][0]["price"] = {"currency": "JPY", "subunit_amount": 12000}
        self.fixture["quote"]["expires_at"] = (self.instant + timedelta(minutes=10)).isoformat()
        self.wire = []

    def transport(self, request, **bounds):
        self.wire.append((request.full_url, bounds))
        if request.full_url.endswith("/oauth/token"):
            payload = {"access_token": "private-fixture-access-token", "expires_in": 300}
        else:
            payload = self.fixture["resolve" if request.full_url.endswith("/resolve") else "quote"]
        return {"status": 200, "body": copy.deepcopy(payload)}

    def client(self, transport=None):
        sender = smoke.OneShotBNSSender(BASE, authorized=True, transport=transport or self.transport)
        return PartnerClient(BASE, "fixture-client", CLIENT_SECRET, sender=sender, live_authorized=True)

    def plan(self):
        return {"schema": smoke.PLAN_SCHEMA, "psa": {"certificate_number": "00001234",
            "expected": {"subject": "PIKACHU", "card_number": "173", "year": "2023", "brand": "POKEMON", "grade": "10"}},
            "bns": {"card_id": CARD, "offer": copy.deepcopy(self.offer), "destination": {"country": "HK"},
                    "approved_base_url": BASE, "contract_confirmation_reference": "offline fixture, not real approval"}}

    def env(self):
        return {"PSA_API_TOKEN": "private-fixture-psa", "BNS_PARTNER_BASE_URL": BASE,
                "BNS_PARTNER_CLIENT_ID": "fixture-client", "BNS_PARTNER_CLIENT_SECRET": CLIENT_SECRET,
                "POKEMON_COMMERCE_QUOTE_DB": str(self.path)}

    def test_preflight_and_default_cli_stay_offline_even_with_configured_access(self):
        plan = self.plan()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = smoke.readiness(plan, env=self.env(), now=self.now)
        self.assertTrue(report["bns"]["ready"]); self.assertTrue(report["psa"]["ready"])
        self.assertEqual(report["network_requests"], 0)
        file = Path(self.tmp.name) / "case.json"; file.write_text(json.dumps(plan))
        with patch.dict(os.environ, self.env(), clear=True), patch("sys.argv", ["probe", "--plan", str(file)]), \
                patch.object(smoke, "execute_bounded", side_effect=AssertionError("default must not execute")), \
                redirect_stdout(io.StringIO()) as output:
            smoke.main()
        self.assertEqual(json.loads(output.getvalue())["mode"], "offline_preflight")
        self.assertNotIn(CLIENT_SECRET, output.getvalue())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertEqual(self.wire, [])

    def test_positive_probe_is_three_calls_quantity_one_and_never_writes_database(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = smoke.bns_smoke(self.path, CARD, self.offer, {"country": "HK"}, client=self.client(), authorized=True)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["requests"], list(smoke.BNS_PATHS))
        self.assertEqual(len(self.wire), 3)
        self.assertTrue(all(b["timeout"] <= 5 and b["max_bytes"] == 65536 for _, b in self.wire))
        self.assertFalse(report["order_created"]); self.assertFalse(report["purchasable"])
        self.assertIsNone(report["purchase_action"])
        self.assertNotIn(CLIENT_SECRET, json.dumps(report)); self.assertNotIn("private-fixture-access-token", json.dumps(report))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_authorization_stock_age_identity_and_permissions_block_before_transport(self):
        cases = [{"availability": "unknown"}, {"scope": "product_summary"}, {"price_minor": 12001},
                 {"fresh_until": self.now()}, {"grade": {"company": "PSA", "value": "9", "certificate_verified": False}}]
        report = smoke.bns_smoke(self.path, CARD, self.offer, {"country": "HK"}, client=self.client())
        self.assertEqual(report["status"], "blocked")
        for change in cases:
            with self.subTest(change=change):
                report = smoke.bns_smoke(self.path, CARD, self.offer | change, {"country": "HK"}, client=self.client(), authorized=True)
                self.assertEqual(report["status"], "blocked")
        self.db.execute("UPDATE source_policy SET partner_handoff_allowed=0"); self.db.commit()
        report = smoke.bns_smoke(self.path, CARD, self.offer, {"country": "HK"}, client=self.client(), authorized=True)
        self.assertEqual(report["status"], "blocked"); self.assertEqual(self.wire, [])

    def test_unauthorized_401_and_redirect_never_refresh_or_retry(self):
        for status in (401, 302, 429):
            calls = []
            def rejected(request, **bounds):
                calls.append(request.full_url)
                if len(calls) == 1:
                    return self.transport(request, **bounds)
                return {"status": status, "body": CLIENT_SECRET}
            report = smoke.bns_smoke(self.path, CARD, self.offer, {"country": "HK"}, client=self.client(rejected), authorized=True)
            self.assertEqual(report["status"], "failed", report)
            self.assertEqual(len(calls), 2)
            self.assertNotIn(CLIENT_SECRET, json.dumps(report))
            self.assertEqual(report["requests"], list(smoke.BNS_PATHS[:2]))

    def test_changed_url_multiple_variants_bad_totals_and_expiry_fail_closed(self):
        original = copy.deepcopy(self.fixture)
        for stage in ("url", "variants", "totals", "expiry"):
            self.fixture = copy.deepcopy(original); self.wire.clear()
            if stage == "url": self.fixture["resolve"]["url"] += "0"
            if stage == "variants": self.fixture["resolve"]["variants"] *= 2
            if stage == "totals": self.fixture["quote"]["totals"]["grand_total"]["subunit_amount"] += 1
            if stage == "expiry": self.fixture["quote"]["expires_at"] = self.now()
            report = smoke.bns_smoke(self.path, CARD, self.offer, {"country": "HK"}, client=self.client(), authorized=True)
            self.assertEqual(report["status"], "failed", stage)
            self.assertLessEqual(len(self.wire), 3)

    def test_sender_rejects_unapproved_endpoints_order_routes_and_repeated_calls(self):
        for url in ("http://bns.partner.example.com", "https://127.0.0.1", "https://bns.invalid", "https://user:pass@example.com", BASE + "/v1/orders"):
            with self.assertRaises(ValueError): smoke.OneShotBNSSender(url)
        sender = smoke.OneShotBNSSender(BASE, authorized=True, transport=self.transport)
        for path in ("/v1/orders", "/v1/payments", "/v1/products/resolve"):
            with self.assertRaises(smoke.ProbeError): sender(Request(BASE + path, data=b"{}", method="POST"))
        sender(Request(BASE + smoke.BNS_PATHS[0], data=b"grant_type=client_credentials", method="POST"))
        with self.assertRaises(smoke.ProbeError): sender(Request(BASE + smoke.BNS_PATHS[0], data=b"x", method="POST"))
        self.assertEqual(len(self.wire), 1)

    def test_http_transport_never_follows_redirect_or_reads_its_body(self):
        response = SimpleNamespace(status=302, read=lambda *a: self.fail("redirect body must not be read"))
        connection = SimpleNamespace(request=unittest.mock.Mock(), getresponse=lambda: response, close=unittest.mock.Mock())
        with patch.object(smoke, "_PinnedHTTPS", return_value=connection) as factory:
            result = smoke._bns_https(Request(BASE + smoke.BNS_PATHS[0], data=b"grant_type=client_credentials", method="POST"), timeout=5, max_bytes=65536)
        self.assertEqual(result, {"status": 302, "body": b""})
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(factory.call_args.kwargs["context"].check_hostname)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", smoke.BNS_PATHS[0]))
        connection.close.assert_called_once()

    def test_sender_rejects_quantity_two_and_enforces_elapsed_budget(self):
        client = self.client()
        client.resolve(self.offer["url"])
        bad = {"items": [{"reference_id": "fixture-reference-1", "variant_key": "fixture-variant-1", "quantity": 2}], "destination": {"country": "HK"}}
        with self.assertRaises(smoke.ProbeError):
            client.sender(Request(BASE + smoke.BNS_PATHS[2], data=json.dumps(bad).encode(), method="POST"))
        self.assertEqual(len(self.wire), 2)
        clock = [0]
        def delayed(request, **bounds):
            clock[0] = 18
            return {"status": 200, "body": {"access_token": "fixture-token", "expires_in": 300}}
        sender = smoke.OneShotBNSSender(BASE, authorized=True, transport=delayed, monotonic=lambda: clock[0])
        with self.assertRaisesRegex(smoke.ProbeError, "deadline"):
            sender(Request(BASE + smoke.BNS_PATHS[0], data=b"grant_type=client_credentials", method="POST"))
        self.assertEqual(len(sender.requests), 1)

    def test_worker_has_25_second_wall_bound_and_never_exposes_failed_output(self):
        calls = []
        def timeout(args, **kwargs):
            calls.append((args, kwargs))
            raise subprocess.TimeoutExpired(args, 25, output=CLIENT_SECRET, stderr=CLIENT_SECRET)
        report = smoke.execute_bounded(self.plan(), "bns", runner=timeout)
        self.assertEqual(report["reason"], "worker_wall_timeout")
        self.assertEqual(calls[0][1]["timeout"], 25)
        self.assertNotIn(CLIENT_SECRET, repr(calls[0][0]))
        self.assertNotIn(CLIENT_SECRET, json.dumps(report))
        bad = smoke._report("bns") | {"status": "passed", "order_created": True}
        report = smoke.execute_bounded(self.plan(), "bns", runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(bad)))
        self.assertEqual(report["status"], "failed")

    def test_missing_readiness_blocks_execute_flag_before_worker_creation(self):
        plan = self.plan(); plan["bns"]["offer"] = None
        file = Path(self.tmp.name) / "incomplete.json"; file.write_text(json.dumps(plan))
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["probe", "--plan", str(file), "--execute", "bns"]), \
                patch.object(smoke, "execute_bounded", side_effect=AssertionError("not ready")), \
                redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as stopped:
            smoke.main()
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(json.loads(output.getvalue())["reason"], "preflight_blocked")
        self.assertEqual(self.wire, [])

    def test_existing_receipt_blocks_execution_before_any_provider_request(self):
        plan_file = Path(self.tmp.name) / "case.json"
        plan_file.write_text(json.dumps(self.plan()))
        receipt = Path(self.tmp.name) / "already-run.json"
        receipt.write_text("previous result")
        with patch.dict(os.environ, self.env(), clear=True), \
                patch("sys.argv", ["probe", "--plan", str(plan_file), "--execute", "psa", "--output", str(receipt)]), \
                patch.object(smoke, "execute_bounded", side_effect=AssertionError("receipt exists")), \
                self.assertRaises(FileExistsError):
            smoke.main()
        self.assertEqual(receipt.read_text(), "previous result")
        self.assertEqual(self.wire, [])


if __name__ == "__main__":
    unittest.main()
