"""Selected URL previews use injected wire responses, never a provider or DB."""
import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pokemon_index import bns_url_preview as preview
from pokemon_index.bns_errors import BNSRefusal, refusal
from pokemon_index.commerce_loop import CommerceError, CommerceLoop

CARD = "ja:SV2A:173/165:holo"
BASE = "https://bns.partner.example.com"
SECRET = "offline-private-bns-secret"
TOKEN = "offline-private-access-token"


class Producer:
    def __init__(self, row):
        self.row, self.calls = row, []

    def search(self, source, query, limit=3):
        self.calls.append(("search", source))
        return {"status": "ok", "listings": [copy.deepcopy(self.row)]}

    def detail(self, url):
        self.calls.append(("detail", url))
        return copy.deepcopy(self.row)


class URLPreviewTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline only: external I/O forbidden"))
            guard.start(); self.addCleanup(guard.stop)
        self.instant = datetime.now(timezone.utc).replace(microsecond=0)
        self.row = {"source": "mercari", "native_id": "m1001", "url": "https://jp.mercari.com/item/m1001",
            "title": "Pikachu 173/165 PSA 10", "price_minor": 12000, "currency": "JPY",
            "availability": "unknown", "status": "unknown", "grade_company": "PSA", "grade_value": "10",
            "scope": "listing", "observed_at": self.instant.isoformat(), "evidence_ref": "offline:public-pdp"}
        self.offer = CommerceLoop(object())._offer(self.row, "mercari", self.instant)
        self.fixture = json.loads((Path(__file__).parents[1] / "examples/buyship_partner_preview.json").read_text())
        r, q = self.fixture["resolve"], self.fixture["quote"]
        r["url"], r["product"]["name"] = self.row["url"], self.row["title"]
        r["merchant"]["domain"] = "jp.mercari.com"
        r["variants"][0]["price"] = {"currency": "JPY", "subunit_amount": 12000}
        q["expires_at"] = (self.instant + timedelta(minutes=15)).isoformat()
        q["items"][0]["name"] = self.row["title"]
        self.wire, self.workers = [], []
        self.fail_stage, self.fail_body, self.fail_status = None, None, 422

    def env(self):
        return {"BNS_PARTNER_BASE_URL": BASE, "BNS_PARTNER_CLIENT_ID": "offline-client-id",
                "BNS_PARTNER_CLIENT_SECRET": SECRET}

    def payload(self, **changes):
        return {"schema": preview.REQUEST_SCHEMA, "card_id": CARD, "offer": copy.deepcopy(self.offer),
            "destination": {"country": "HK"}, "variant": None, "deadline": time.monotonic() + 18} | changes

    def transport(self, request, **bounds):
        path = request.full_url.removeprefix(BASE)
        self.wire.append({"path": path, "body": request.data.decode(), "bounds": bounds})
        stage = "oauth" if path.endswith("/token") else "resolve" if path.endswith("/resolve") else "quote"
        if stage == self.fail_stage:
            return {"status": self.fail_status, "body": self.fail_body}
        value = {"access_token": TOKEN, "expires_in": 3600} if stage == "oauth" else self.fixture[stage]
        return {"status": 200, "body": copy.deepcopy(value)}

    def quote(self, **changes):
        return preview._preview(self.payload(**changes), env=self.env(), transport=self.transport)

    def runner(self, args, **kwargs):
        self.workers.append((args, kwargs))
        try:
            quote = preview._preview(json.loads(kwargs["input"]), env=kwargs["env"], transport=self.transport)
            value = {"schema": preview.RESULT_SCHEMA, "quote": quote}
        except BNSRefusal as exc:
            value = {"schema": preview.RESULT_SCHEMA, "refusal": exc.result}
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr=SECRET)

    def forwarder(self, **kwargs):
        return preview.URLBuyShipForwarder(BASE, "offline-client-id", SECRET, live_authorized=True,
                                           runner=kwargs.pop("runner", self.runner), **kwargs)

    def loop(self, provider=None):
        self.producer = Producer(self.row)
        return CommerceLoop(self.producer, forwarders={"buyship": provider or self.forwarder()})

    def select(self, loop, owner="owner-a"):
        o = loop.research(owner, {"card_id": CARD, "query": "Pikachu 173/165", "platforms": ["mercari"]})["offers"][0]
        return loop.select(owner, {"card_id": CARD, "offer_id": o["offer_id"], "expected_observed_at": o["observed_at"],
                                   "expected_price_minor": o["price_minor"], "currency": o["currency"]})

    def handoff(self, loop, selected, owner="owner-a", **changes):
        return loop.handoff(owner, {"selection_id": selected["selection_id"], "forwarder": "buyship",
                                   "destination": {"country": "HK"}} | changes)

    def multiple_variants(self):
        first = copy.deepcopy(self.fixture["resolve"]["variants"][0])
        second = copy.deepcopy(first); second["variant_key"] = "another-variant"; second["options"] = {"size": "L"}
        self.fixture["resolve"]["variants"] = [first, second]
        return first, second

    def test_fresh_unknown_stock_url_quotes_without_database_or_identity_promotion(self):
        loop = self.loop(); result = self.handoff(loop, self.select(loop))
        self.assertEqual(result["status"], "quote_ready_for_review")
        self.assertEqual(len(self.wire), 3)
        self.assertEqual([v["path"] for v in self.wire], list(preview.BNS_PATHS))
        self.assertEqual(json.loads(self.wire[1]["body"]), {"url": self.row["url"]})
        sent_quote = json.loads(self.wire[2]["body"])
        self.assertEqual(len(sent_quote["items"]), 1); self.assertEqual(sent_quote["items"][0]["quantity"], 1)
        self.assertNotIn("delivery_address", sent_quote)
        quote = result["quote"]
        self.assertNotIn("unit_id", quote)
        self.assertEqual(quote["listing"]["identity_status"], "unverified_candidate")
        self.assertFalse(quote["listing"]["grade"]["certificate_verified"])
        self.assertEqual(quote["buyship"]["resolved_availability"], "in_stock")
        self.assertEqual(result["offer"]["availability"], "unknown")
        self.assertFalse(result["purchasable"]); self.assertFalse(result["order_created"])
        self.assertIsNone(result["purchase_action"])
        self.assertNotIn(SECRET, json.dumps(result)); self.assertNotIn(TOKEN, json.dumps(result))
        self.assertFalse(any("database" in kwargs["input"] for _, kwargs in self.workers))

    def test_resolve_price_change_is_explicit_and_source_ask_is_preserved(self):
        self.fixture["resolve"]["variants"][0]["price"]["subunit_amount"] = 13000
        quote = self.quote()
        self.assertEqual(quote["listing"]["ask"]["subunit_amount"], 12000)
        self.assertEqual(quote["buyship"]["resolve_price"]["subunit_amount"], 13000)
        self.assertTrue(quote["buyship"]["resolve_price_differs_from_observation"])

    def test_unknown_source_price_can_be_resolved_without_making_up_a_source_ask(self):
        self.offer["price_minor"] = self.offer["currency"] = None
        quote = self.quote()
        self.assertIsNone(quote["listing"]["ask"])
        self.assertFalse(quote["buyship"]["resolve_price_differs_from_observation"])

    def test_multiple_variants_need_explicit_owner_bound_selection_and_fresh_resolve(self):
        first, _ = self.multiple_variants()
        loop = self.loop(); selected = self.select(loop)
        first_result = self.handoff(loop, selected)
        self.assertEqual(first_result["status"], "variant_selection_required")
        self.assertIsNone(first_result["quote"]); self.assertEqual(len(self.wire), 2)
        self.wire.clear()
        result = self.handoff(loop, selected, variant_key=first["variant_key"])
        self.assertEqual(result["status"], "quote_ready_for_review")
        self.assertEqual([v["path"] for v in self.wire], list(preview.BNS_PATHS))
        self.assertEqual(result["quote"]["buyship"]["variant_options"], first["options"])

    def test_browser_cannot_supply_unoffered_variant_or_change_destination(self):
        first, _ = self.multiple_variants(); loop = self.loop(); selected = self.select(loop)
        for changes in ({"variant_key": first["variant_key"]}, {"product_url": self.row["url"]},
                        {"reference_id": "arbitrary"}, {"price": 1}):
            with self.subTest(changes=changes), self.assertRaises(CommerceError): self.handoff(loop, selected, **changes)
        self.assertEqual(self.wire, [])
        self.handoff(loop, selected)
        self.wire.clear(); calls = len(self.producer.calls)
        for changes in ({"variant_key": "not-offered"}, {"variant_key": first["variant_key"], "destination": {"country": "US", "state": "CA"}}):
            with self.subTest(changes=changes), self.assertRaises(CommerceError): self.handoff(loop, selected, **changes)
        self.assertEqual(self.wire, []); self.assertEqual(len(self.producer.calls), calls)
        with self.assertRaises(CommerceError): self.handoff(loop, selected, owner="other-owner", variant_key=first["variant_key"])
        self.assertEqual(self.wire, [])

    def test_changed_variant_price_options_or_stock_requires_new_choice_before_quote(self):
        for field in ("price", "options", "availability"):
            with self.subTest(field=field):
                self.wire.clear(); self.fixture["resolve"]["variants"] = [self.fixture["resolve"]["variants"][0]]
                first, _ = self.multiple_variants(); loop = self.loop(); selected = self.select(loop)
                self.handoff(loop, selected); self.wire.clear()
                v = self.fixture["resolve"]["variants"][0]
                if field == "price": v[field] = {"currency": "JPY", "subunit_amount": v[field]["subunit_amount"] + 1}
                elif field == "options": v[field] = {"size": "changed"}
                else: v[field] = "out_of_stock"
                result = self.handoff(loop, selected, variant_key=first["variant_key"])
                self.assertEqual(result["quote_status"], "variant_changed")
                self.assertIsNone(result["quote"]); self.assertEqual(len(self.wire), 2)

    def test_refusal_codes_and_safe_reasons_reach_chat_without_raw_provider_text(self):
        cases = [("resolve", 422, "product_not_eligible", ["MERCHANT_NOT_SUPPORTED"], False, {}),
            ("quote", 422, "currency_unsupported", ["CURRENCY_UNSUPPORTED"], False, {"supported_currencies": ["HKD", "USD"]}),
            ("quote", 424, "merchant_unreachable", [], True, {}),
            ("quote", 400, "invalid_request", [], False, {"field_errors": [{"field": "destination.state", "message": SECRET}]}),
            ("quote", 422, "quote_limit_exceeded", ["VALUE_EXCEEDS_CEILING"], False, {}),
            ("quote", 422, "destination_unsupported", ["DESTINATION_UNSUPPORTED"], False, {}),
            ("quote", 422, "product_not_quotable", [], False, {})]
        for stage, status, code, reasons, retryable, details in cases:
            with self.subTest(code=code):
                self.wire.clear(); self.fail_stage, self.fail_status = stage, status
                self.fail_body = {"error": {"code": code, "message": SECRET, "reason_codes": reasons,
                                           "retryable": retryable, "details": details}}
                loop = self.loop(); result = self.handoff(loop, self.select(loop))
                self.assertEqual(result["provider_result"]["code"], code)
                self.assertEqual(result["provider_result"]["reason_codes"], reasons)
                self.assertEqual(result["provider_result"]["retryable"], retryable)
                self.assertNotIn(SECRET, json.dumps(result)); self.assertIsNone(result["quote"])
                self.assertEqual(len(self.wire), 2 if stage == "resolve" else 3)

    def test_wrong_resolved_url_card_number_or_grade_stops_before_quote(self):
        for field, value in (("url", "https://jp.mercari.com/item/m9999"), ("name", "Pikachu 174/165 PSA 10"),
                             ("name", "Pikachu 173/165 PSA 9")):
            with self.subTest(field=field, value=value):
                original = copy.deepcopy(self.fixture["resolve"]); self.wire.clear()
                if field == "url": self.fixture["resolve"][field] = value
                else: self.fixture["resolve"]["product"][field] = value
                with self.assertRaises(BNSRefusal) as raised: self.quote()
                self.assertEqual(raised.exception.code, "product_mismatch"); self.assertEqual(len(self.wire), 2)
                self.fixture["resolve"] = original

    def test_sold_out_resolve_variant_never_quotes(self):
        self.fixture["resolve"]["variants"][0]["availability"] = "out_of_stock"
        with self.assertRaises(BNSRefusal) as raised: self.quote()
        self.assertEqual(raised.exception.code, "variant_unavailable"); self.assertEqual(len(self.wire), 2)

    def test_quote_binding_money_expiry_and_false_flags_are_validated(self):
        original = copy.deepcopy(self.fixture["quote"])
        mutations = [lambda q: q.update(destination={"country": "US", "state": "CA"}),
            lambda q: q.update(status="CLOSED"), lambda q: q.update(expires_at="2000-01-01T00:00:00Z"),
            lambda q: q["items"][0].update(reference_id="wrong"), lambda q: q["items"][0].update(variant_key="wrong"),
            lambda q: q["items"][0].update(quantity=2), lambda q: q["items"][0].update(variant_options={"size": "wrong"}),
            lambda q: q["totals"]["grand_total"].update(subunit_amount=1),
            lambda q: q["totals"]["items"].update(currency="USD")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.fixture["quote"] = copy.deepcopy(original); mutate(self.fixture["quote"]); self.wire.clear()
                with self.assertRaises((BNSRefusal, ValueError)): self.quote()
                self.assertLessEqual(len(self.wire), 3)

    def test_parent_rejects_tampered_ipc_and_selection_mismatch_even_with_rehashed_quote(self):
        original = self.quote()
        mutations = [lambda q: q.update(card_id="different"), lambda q: q.update(purchasable=True),
            lambda q: q.update(order_created=True), lambda q: q.update(purchase_action={"order": True}),
            lambda q: q["listing"].update(url="https://jp.mercari.com/item/m9999"),
            lambda q: q["evidence"].update(certificate_verified=True),
            lambda q: q["buyship"].update(destination={"country": "US", "state": "CA"})]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                q = copy.deepcopy(original); mutate(q); q["evidence"]["binding_sha256"] = preview._binding(q)
                runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({"schema": preview.RESULT_SCHEMA, "quote": q}), stderr=SECRET)
                with self.assertRaises(BNSRefusal): self.forwarder(runner=runner).preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 18)
        bad = refusal("provider_unavailable"); bad["message"] = SECRET
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({"schema": preview.RESULT_SCHEMA, "refusal": bad}), stderr=SECRET)
        with self.assertRaises(BNSRefusal) as raised: self.forwarder(runner=runner).preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 18)
        self.assertNotIn(SECRET, str(raised.exception))

    def test_provider_credentials_or_token_in_variant_hints_are_suppressed(self):
        self.multiple_variants()
        for secret in (SECRET, TOKEN, "offline-client-id"):
            with self.subTest(secret=secret):
                self.fixture["resolve"]["variants"][0]["options"] = {"size": secret}
                with self.assertRaises(BNSRefusal) as raised: self.quote()
                self.assertNotIn(secret, json.dumps(raised.exception.result))

    def test_escaped_credentials_and_tokens_cannot_escape_in_provider_ids_or_nested_keys(self):
        secret = 'private"escaped\\secret'
        for field in ("quote_id", "reference_id"):
            with self.subTest(field=field):
                original = copy.deepcopy(self.fixture)
                if field == "quote_id": self.fixture["quote"][field] = secret
                else:
                    self.fixture["resolve"][field] = secret
                    self.fixture["quote"]["items"][0][field] = secret
                with self.assertRaises(BNSRefusal) as raised:
                    preview._preview(self.payload(), env=self.env() | {"BNS_PARTNER_CLIENT_SECRET": secret}, transport=self.transport)
                self.assertEqual(raised.exception.code, "invalid_provider_response")
                self.assertNotIn(secret, str(raised.exception.result))
                self.fixture = original
        for value in ({secret: "value"}, {"details": [secret]}, ["prefix" + secret]):
            with self.subTest(value=value), self.assertRaises(BNSRefusal): preview._no_secrets(value, [secret])
        self.fixture["quote"]["quote_id"] = TOKEN
        with self.assertRaises(BNSRefusal): self.quote()

    def test_foreign_owner_expired_or_changed_source_never_starts_provider(self):
        loop = self.loop(); selected = self.select(loop)
        with self.assertRaises(CommerceError): self.handoff(loop, selected, owner="another-owner")
        self.assertEqual(self.wire, [])
        self.row["price_minor"] += 1
        with self.assertRaises(CommerceError): self.handoff(loop, selected)
        self.assertEqual(self.wire, [])

    def test_unsafe_scope_destination_synthetic_stale_and_disabled_are_zero_request_failures(self):
        changes = [{"offer": self.offer | {"synthetic": True}}, {"offer": self.offer | {"scope": "product_summary"}},
            {"offer": self.offer | {"availability": "sold_out"}}, {"destination": {"country": "SG"}},
            {"destination": {"country": "US"}}, {"destination": {"country": "HK", "address": SECRET}},
            {"offer": self.offer | {"observed_at": "2000-01-01T00:00:00Z"}},
            {"deadline": time.monotonic() - 1}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises((BNSRefusal, ValueError)): self.quote(**change)
        denied = preview.URLBuyShipForwarder(BASE, "offline-client-id", SECRET, runner=self.runner)
        with self.assertRaises(BNSRefusal): denied.preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 18)
        self.assertEqual(self.wire, []); self.assertEqual(self.workers, [])

    def test_worker_args_keep_credentials_server_side_and_deadlines_bounded(self):
        self.forwarder().preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 6)
        args, kwargs = self.workers[0]
        self.assertNotIn(SECRET, repr(args)); self.assertNotIn(SECRET, kwargs["input"])
        self.assertEqual(kwargs["env"]["BNS_PARTNER_CLIENT_SECRET"], SECRET)
        self.assertGreater(kwargs["timeout"], 0); self.assertLessEqual(kwargs["timeout"], 6)

    def test_deadline_cannot_start_a_late_worker_and_real_timeout_kills_and_reaps(self):
        calls = []
        def timeout(args, **kwargs):
            calls.append(kwargs)
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=SECRET, stderr=SECRET)
        provider = self.forwarder(runner=timeout)
        for _ in range(2):
            with self.assertRaises(BNSRefusal) as raised: provider.preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 1)
            self.assertEqual(raised.exception.code, "provider_timeout")
        with self.assertRaises(BNSRefusal): provider.preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() - 1)
        self.assertEqual(len(calls), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pid"
            def local_runner(args, **kwargs):
                code = "import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)"
                return subprocess.run([sys.executable, "-c", code, str(path)], timeout=kwargs["timeout"], capture_output=True, text=True)
            with self.assertRaises(BNSRefusal): self.forwarder(runner=local_runner).preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + .35)
            pid = int(path.read_text())
            with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
            with self.assertRaises(ChildProcessError): os.waitpid(pid, os.WNOHANG)

    def test_service_url_mode_is_explicit_off_by_default_and_excludes_indexed_database(self):
        from pokemon_index import commerce_service
        server = Mock(); server.__enter__ = Mock(return_value=server); server.__exit__ = Mock(return_value=False); server.server_port = 8766
        env = self.env() | {"POKEMON_COMMERCE_TOKEN": "offline-session-token-long-enough"}
        with patch.dict(os.environ, env, clear=True), patch.object(commerce_service, "create_server", return_value=server) as create, patch("sys.argv", ["sidecar"]), redirect_stdout(io.StringIO()):
            commerce_service.main()
        self.assertEqual(create.call_args.args[0].forwarders, {})
        with patch.dict(os.environ, env, clear=True), patch.object(commerce_service, "create_server", return_value=server) as create, patch("sys.argv", ["sidecar", "--allow-live-buyship", "--buyship-url-preview"]), redirect_stdout(io.StringIO()):
            commerce_service.main()
        self.assertIsInstance(create.call_args.args[0].forwarders["buyship"], preview.URLBuyShipForwarder)
        for args in (["--buyship-url-preview"], ["--allow-live-buyship", "--buyship-url-preview", "--quote-db", "anything"], ["--fixture", "--buyship-url-preview"]):
            with self.subTest(args=args), patch.dict(os.environ, env, clear=True), patch("sys.argv", ["sidecar", *args]), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit): commerce_service.main()
        self.assertEqual(self.wire, []); self.assertEqual(self.workers, [])


if __name__ == "__main__":
    unittest.main()
