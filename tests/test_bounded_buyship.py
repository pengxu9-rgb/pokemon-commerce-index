"""Chat BNS previews use disposable bounded workers; no external I/O is allowed."""
import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pokemon_index import bounded_buyship as bounded, core
from pokemon_index import buyship_partner
from pokemon_index.bns_transport import OneShotBNSSender
from pokemon_index.commerce_loop import CommerceError, CommerceLoop

CARD = "ja:SV2A:173/165:standard"
BASE = "https://bns.partner.example.com"
SECRET = "private-bounded-fixture-secret-never-print"


class Producer:
    def __init__(self, row):
        self.row, self.calls, self.after_refresh = row, [], None

    def search(self, source, query, limit=3):
        self.calls.append(("search", source))
        return {"status": "ok", "listings": [copy.deepcopy(self.row)]}

    def detail(self, url):
        self.calls.append(("detail", url))
        if self.after_refresh:
            self.after_refresh()
        return copy.deepcopy(self.row)


class BoundedBuyShipTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect"):
            guard = patch(target, side_effect=AssertionError("offline regression: no network"))
            guard.start(); self.addCleanup(guard.stop)
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
        self.instant = datetime.now(timezone.utc).replace(microsecond=0)
        self.now = lambda: self.instant.isoformat()
        self.row = {"source": "mercari", "native_id": "m1001", "url": "https://jp.mercari.com/item/m1001",
            "title": "Pikachu SV2a 173/165 PSA 10 graded card", "price_minor": 12000, "currency": "JPY",
            "availability": "in_stock", "status": "on_sale", "grade_company": "PSA", "grade_value": "10",
            "scope": "listing", "observed_at": self.now(), "language": "ja", "evidence_ref": "offline:binding"}
        core.import_observations(self.db, [self.row]); self.db.commit()
        self.offer = CommerceLoop(object(), now=self.now)._offer(self.row, "mercari", self.instant)
        self.fixture = json.loads((Path(__file__).parents[1] / "examples/buyship_partner_preview.json").read_text())
        self.fixture["resolve"]["url"] = self.row["url"]
        self.fixture["resolve"]["product"]["name"] = self.row["title"]
        self.fixture["resolve"]["variants"][0]["price"] = {"currency": "JPY", "subunit_amount": 12000}
        self.fixture["quote"]["expires_at"] = (self.instant + timedelta(minutes=10)).isoformat()
        self.wire, self.workers = [], []

    def env(self):
        return {"BNS_PARTNER_BASE_URL": BASE, "BNS_PARTNER_CLIENT_ID": "fixture-client",
                "BNS_PARTNER_CLIENT_SECRET": SECRET}

    def payload(self, **changes):
        return {"schema": "pokemon.bounded-buyship-request.v1", "database": str(self.path),
                "card_id": CARD, "offer": copy.deepcopy(self.offer), "destination": {"country": "HK"},
                "deadline": time.monotonic() + 18} | changes

    def transport(self, request, **bounds):
        self.wire.append((request.full_url, bounds))
        if request.full_url.endswith("/oauth/token"):
            result = {"access_token": "private-ephemeral-fixture-token", "expires_in": 300}
        else:
            result = self.fixture["resolve" if request.full_url.endswith("/resolve") else "quote"]
        return {"status": 200, "body": copy.deepcopy(result)}

    def quote(self, payload=None, transport=None):
        return bounded._preview(payload or self.payload(), env=self.env(), transport=transport or self.transport)

    def runner(self, args, **kwargs):
        self.workers.append((args, kwargs))
        quote = bounded._preview(json.loads(kwargs["input"]), env=kwargs["env"], transport=self.transport)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"schema": "pokemon.bounded-buyship-result.v1", "quote": quote}), stderr="")

    def forwarder(self, runner=None, **kwargs):
        return bounded.BoundedBuyShipForwarder(self.path, BASE, "fixture-client", SECRET,
            live_authorized=True, runner=runner or self.runner, **kwargs)

    def loop(self, forwarder=None, **kwargs):
        self.producer = Producer(self.row)
        return CommerceLoop(self.producer, now=self.now,
                            forwarders={"buyship": forwarder or self.forwarder()}, **kwargs)

    def select(self, loop, owner="owner-a"):
        offer = loop.research(owner, {"card_id": CARD, "query": "Pikachu 173/165", "platforms": ["mercari"]})["offers"][0]
        return loop.select(owner, {"card_id": CARD, "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"],
            "currency": offer["currency"]})

    def handoff(self, loop, selected, owner="owner-a"):
        return loop.handoff(owner, {"selection_id": selected["selection_id"], "forwarder": "buyship",
                                   "destination": {"country": "HK"}})

    def test_two_chat_handoffs_each_start_fresh_token_and_three_call_sequence(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        loop = self.loop()
        for _ in range(2):
            result = self.handoff(loop, self.select(loop))
            self.assertEqual(result["status"], "quote_ready_for_review", result)
            self.assertFalse(result["order_created"]); self.assertFalse(result["purchasable"])
            self.assertIsNone(result["purchase_action"])
        self.assertEqual([url.removeprefix(BASE) for url, _ in self.wire],
            ["/v1/oauth/token", "/v1/products/resolve", "/v1/quotes"] * 2)
        self.assertEqual(len(self.workers), 2)
        self.assertTrue(all(bounds["timeout"] <= 5 and bounds["max_bytes"] == 65536 for _, bounds in self.wire))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_every_stage_rejects_401_redirect_and_rate_limit_without_retry(self):
        for stage in range(3):
            for status in (401, 302, 429):
                with self.subTest(stage=stage, status=status):
                    self.wire.clear()
                    def rejected(request, **bounds):
                        if len(self.wire) == stage:
                            self.wire.append((request.full_url, bounds))
                            return {"status": status, "body": SECRET}
                        return self.transport(request, **bounds)
                    with self.assertRaises(ValueError) as raised:
                        self.quote(transport=rejected)
                    self.assertEqual(len(self.wire), stage + 1)
                    self.assertNotIn(SECRET, str(raised.exception))

    def test_child_revalidates_policy_grade_and_price_before_any_request(self):
        changes = [("UPDATE source_policy SET partner_handoff_allowed=0", "UPDATE source_policy SET partner_handoff_allowed=1"),
                   ("UPDATE listing SET current_price_minor=13000", "UPDATE listing SET current_price_minor=12000"),
                   ("UPDATE priceable_unit SET grade_value='9'", "UPDATE priceable_unit SET grade_value='10'")]
        for mutation, restore in changes:
            with self.subTest(mutation=mutation):
                self.db.execute(mutation); self.db.commit()
                with self.assertRaises(ValueError): self.quote()
                self.assertEqual(self.wire, [])
                self.db.execute(restore); self.db.commit()

    def test_quality_change_after_resolve_prevents_quote_dispatch(self):
        from pokemon_index import marketplace_ingest
        marketplace_ingest.initialize(self.db)
        def mutate(request, **bounds):
            result = self.transport(request, **bounds)
            if request.full_url.endswith("/resolve"):
                metadata = {"grade_company": "PSA", "grade_value": "10", "grade_evidence": "structured_seller_claim",
                    "seller_condition": "case cracked", "evidence_ref": "offline:binding",
                    "certificate_verified": False, "authenticity_verified": False}
                self.db.execute("INSERT INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                    ("mercari", "m1001", self.now(), json.dumps(metadata), "offline:binding"))
                self.db.commit()
            return result
        with self.assertRaises(ValueError): self.quote(transport=mutate)
        self.assertEqual([url.removeprefix(BASE) for url, _ in self.wire], ["/v1/oauth/token", "/v1/products/resolve"])

    def test_mutation_during_oauth_blocks_resolve_before_second_wire_call(self):
        changes = [("UPDATE source_policy SET partner_handoff_allowed=0", "UPDATE source_policy SET partner_handoff_allowed=1"),
                   ("UPDATE listing SET current_price_minor=13000", "UPDATE listing SET current_price_minor=12000"),
                   ("UPDATE priceable_unit SET grade_value='9'", "UPDATE priceable_unit SET grade_value='10'")]
        for mutation, restore in changes:
            with self.subTest(mutation=mutation):
                self.wire.clear()
                def mutate(request, **bounds):
                    result = self.transport(request, **bounds)
                    if request.full_url.endswith("/oauth/token"):
                        self.db.execute(mutation); self.db.commit()
                    return result
                try:
                    with self.assertRaises(ValueError): self.quote(transport=mutate)
                    self.assertEqual([url.removeprefix(BASE) for url, _ in self.wire], ["/v1/oauth/token"])
                finally:
                    self.db.execute(restore); self.db.commit()

    def test_policy_or_quality_change_after_worker_result_is_rejected_by_parent(self):
        from pokemon_index import marketplace_ingest
        marketplace_ingest.initialize(self.db)
        for change in ("policy", "quality"):
            with self.subTest(change=change):
                def mutate_after_worker(args, **kwargs):
                    result = self.runner(args, **kwargs)
                    if change == "policy":
                        self.db.execute("UPDATE source_policy SET partner_handoff_allowed=0")
                    else:
                        metadata = {"grade_company": "PSA", "grade_value": "10", "grade_evidence": "structured_seller_claim",
                            "seller_condition": "case cracked", "evidence_ref": "offline:binding",
                            "certificate_verified": False, "authenticity_verified": False}
                        self.db.execute("INSERT INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                            ("mercari", "m1001", self.now(), json.dumps(metadata), "offline:binding"))
                    self.db.commit()
                    return result
                try:
                    with self.assertRaises(ValueError):
                        self.forwarder(runner=mutate_after_worker).preview(CARD, self.offer, {"country": "HK"})
                    # The child completed the valid three-request quote; the
                    # independent parent validation suppresses its stale DTO.
                    self.assertEqual(len(self.wire), 3)
                finally:
                    self.db.execute("UPDATE source_policy SET partner_handoff_allowed=1")
                    self.db.execute("DELETE FROM marketplace_observation_quality")
                    self.db.commit(); self.wire.clear()

    def test_wrong_owner_and_unconfirmed_stock_never_start_worker(self):
        loop = self.loop(); selected = self.select(loop)
        with self.assertRaises(CommerceError): self.handoff(loop, selected, "owner-b")
        self.assertEqual(len(self.producer.calls), 1)
        self.row["availability"], self.row["status"] = "unknown", "unknown"
        result = self.handoff(loop, self.select(loop))
        self.assertEqual(result["quote_status"], "stock_not_confirmed")
        self.assertEqual(self.workers, []); self.assertEqual(self.wire, [])

    def test_refresh_exhausts_absolute_handoff_budget_before_worker(self):
        initial = time.monotonic(); clock = [initial]
        forwarder = self.forwarder(monotonic=lambda: clock[0])
        loop = self.loop(forwarder, monotonic=lambda: clock[0]); selected = self.select(loop)
        self.producer.after_refresh = lambda: clock.__setitem__(0, initial + 23.0)
        try:
            result = self.handoff(loop, selected)
        except CommerceError:
            result = None
        if result is not None: self.assertIsNone(result["quote"])
        self.assertEqual(self.workers, []); self.assertEqual(self.wire, [])

    def test_refresh_consumption_reduces_the_worker_budget_to_remaining_seven_seconds(self):
        initial = time.monotonic(); clock = [initial]
        def record_runner(args, **kwargs):
            self.workers.append((args, kwargs))
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        forwarder = self.forwarder(runner=record_runner, monotonic=lambda: clock[0])
        loop = self.loop(forwarder, monotonic=lambda: clock[0]); selected = self.select(loop)
        self.producer.after_refresh = lambda: clock.__setitem__(0, initial + 15.0)
        result = self.handoff(loop, selected)
        self.assertIsNone(result["quote"]); self.assertEqual(len(self.workers), 1)
        kwargs = self.workers[0][1]
        self.assertGreater(kwargs["timeout"], 0)
        # Monotonic clock origins differ across platforms; subtracting float
        # timestamps can produce 7.000000000000007 for this exact fake delay.
        self.assertAlmostEqual(kwargs["timeout"], 7.0, places=6)
        self.assertAlmostEqual(json.loads(kwargs["input"])["deadline"], initial + 22.0)
        self.assertEqual(self.wire, [])

    def test_parent_sends_secrets_only_in_child_environment_and_limits_remaining_time(self):
        clock = [100.0]
        # A failed runner still exposes its timeout and IPC arguments to assertions.
        def runner(args, **kwargs):
            self.workers.append((args, kwargs))
            return SimpleNamespace(returncode=1, stdout=SECRET, stderr=SECRET)
        forwarder = self.forwarder(runner=runner, monotonic=lambda: clock[0])
        with self.assertRaises(ValueError) as raised:
            forwarder.preview_before(CARD, self.offer, {"country": "HK"}, deadline=106.5)
        args, kwargs = self.workers[0]
        self.assertGreater(kwargs["timeout"], 0); self.assertLessEqual(kwargs["timeout"], 6.5)
        self.assertLessEqual(kwargs["timeout"], 18)
        self.assertNotIn(SECRET, repr(args)); self.assertNotIn(SECRET, kwargs["input"])
        self.assertEqual(kwargs["env"]["BNS_PARTNER_CLIENT_SECRET"], SECRET)
        self.assertTrue(kwargs["capture_output"])
        self.assertNotIn(SECRET, str(raised.exception))

    def test_worker_timeout_is_redacted_and_following_preview_can_start(self):
        calls = []
        def timeout(args, **kwargs):
            calls.append(kwargs)
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=SECRET, stderr=SECRET)
        forwarder = self.forwarder(runner=timeout)
        for _ in range(2):
            with self.assertRaises(ValueError) as raised:
                forwarder.preview(CARD, self.offer, {"country": "HK"})
            self.assertNotIn(SECRET, str(raised.exception))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(0 < call["timeout"] <= 18 for call in calls))

    def test_actual_timeout_kills_and_reaps_local_child_before_returning(self):
        pid_file = Path(self.tmp.name) / "local-worker.pid"
        def local_runner(_args, **kwargs):
            # Exercise subprocess.run's real kill/wait path with a local child.
            # This child never imports provider code or performs network I/O.
            code = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
            return subprocess.run([sys.executable, "-c", code, str(pid_file)],
                timeout=kwargs["timeout"], capture_output=True, text=True, check=False)
        forwarder = self.forwarder(runner=local_runner)
        with self.assertRaises(ValueError):
            forwarder.preview_before(CARD, self.offer, {"country": "HK"}, deadline=time.monotonic() + 0.35)
        self.assertTrue(pid_file.is_file(), "the real child must have started")
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        # It is already reaped, so no zombie or child remains for this test.
        with self.assertRaises(ChildProcessError): os.waitpid(pid, os.WNOHANG)
        self.assertEqual(self.wire, [])

    def test_absolute_sender_deadline_spent_after_resolve_prevents_quote_request(self):
        clock = [100.0]
        sender = OneShotBNSSender(BASE, authorized=True, transport=self.transport,
                                 monotonic=lambda: clock[0], deadline=106.0)
        client = buyship_partner.PartnerClient(BASE, "fixture-client", SECRET,
                                               sender=sender, live_authorized=True)
        resolved = client.resolve(self.offer["url"])
        clock[0] = 106.01
        with self.assertRaises(ValueError):
            client.quote(resolved["reference_id"], resolved["variants"][0]["variant_key"], {"country": "HK"})
        self.assertEqual([url.removeprefix(BASE) for url, _ in self.wire], ["/v1/oauth/token", "/v1/products/resolve"])

    def test_one_active_worker_across_forwarders_does_not_queue_second_preview(self):
        entered, release = threading.Event(), threading.Event()
        calls, failures = [], []
        def held(args, **kwargs):
            calls.append(kwargs); entered.set()
            if not release.wait(2): raise AssertionError("test worker was not released")
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        forwarder = self.forwarder(runner=held)
        another_forwarder = self.forwarder(runner=held)
        def first():
            try: forwarder.preview(CARD, self.offer, {"country": "HK"})
            except ValueError as exc: failures.append(exc)
        thread = threading.Thread(target=first); thread.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(ValueError): another_forwarder.preview(CARD, self.offer, {"country": "HK"})
            self.assertEqual(len(calls), 1)
        finally:
            release.set(); thread.join(2)
        self.assertFalse(thread.is_alive()); self.assertEqual(len(failures), 1)

    def test_parent_rejects_invalid_or_tampered_worker_quotes(self):
        original = self.quote()
        mutations = [lambda q: q.update(card_id="another-card"),
            lambda q: q["buyship"].update(destination={"country": "US", "state": "CA"}),
            lambda q: q.update(order_created=True), lambda q: q.update(purchasable=True),
            lambda q: q.update(purchase_action={"url": "https://example.com/order"}),
            lambda q: q["evidence"].update(binding_sha256="0" * 64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                quote = copy.deepcopy(original); mutate(quote)
                # A self-consistent local digest is not evidence that this DTO
                # belongs to the selected card/destination or is quote-only.
                if quote["evidence"]["binding_sha256"] != "0" * 64:
                    quote["evidence"]["binding_sha256"] = buyship_partner._preview_digest(quote)
                envelope = {"schema": "pokemon.bounded-buyship-result.v1", "quote": quote}
                forwarder = self.forwarder(runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr=SECRET))
                with self.assertRaises(ValueError) as raised: forwarder.preview(CARD, self.offer, {"country": "HK"})
                self.assertNotIn(SECRET, str(raised.exception))
        for raw in ("not json", "[]", json.dumps({"schema": "unknown", "quote": original}),
                    json.dumps({"schema": "pokemon.bounded-buyship-result.v1", "quote": original, "unexpected": SECRET})):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.forwarder(runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw, stderr=SECRET)).preview(CARD, self.offer, {"country": "HK"})

    def test_nested_provider_fields_are_bounded_and_money_objects_have_exact_fields(self):
        original = self.quote()
        cases = [lambda q: q["buyship"].update(merchant_domain={"secret": SECRET}),
            lambda q: q["buyship"].update(quote_id="q" * 301),
            lambda q: q["buyship"].update(reference_id="r" * 301),
            lambda q: q["buyship"].update(variant_key="v" * 301),
            lambda q: q.update(unit_id="u" * 301),
            lambda q: q["buyship"]["resolve_price"].update(extra=SECRET),
            lambda q: q["buyship"]["unit_price"].update(extra=SECRET),
            lambda q: q["buyship"]["grand_total"].update(extra=SECRET),
            lambda q: q["buyship"]["components"]["items"].update(extra=SECRET)]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                quote = copy.deepcopy(original); mutate(quote)
                quote["evidence"]["binding_sha256"] = buyship_partner._preview_digest(quote)
                envelope = {"schema": "pokemon.bounded-buyship-result.v1", "quote": quote}
                runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr="")
                with self.assertRaises(ValueError) as raised:
                    self.forwarder(runner=runner).preview(CARD, self.offer, {"country": "HK"})
                self.assertNotIn(SECRET, str(raised.exception))

    def test_nested_merchant_and_oversized_provider_ids_are_rejected_in_child(self):
        original = copy.deepcopy(self.fixture)
        for field in ("merchant", "quote_id", "reference_id", "variant_key"):
            with self.subTest(field=field):
                self.fixture = copy.deepcopy(original); self.wire.clear()
                if field == "merchant": self.fixture["resolve"]["merchant"]["domain"] = {"secret": SECRET}
                elif field == "quote_id": self.fixture["quote"]["quote_id"] = "q" * 301
                elif field == "reference_id":
                    self.fixture["resolve"]["reference_id"] = self.fixture["quote"]["items"][0]["reference_id"] = "r" * 301
                else:
                    self.fixture["resolve"]["variants"][0]["variant_key"] = self.fixture["quote"]["items"][0]["variant_key"] = "v" * 301
                with self.assertRaises(ValueError) as raised: self.quote()
                self.assertNotIn(SECRET, str(raised.exception))
                self.assertLessEqual(len(self.wire), 3)

    def test_missing_authorization_and_invalid_input_are_zero_request_failures(self):
        denied = bounded.BoundedBuyShipForwarder(self.path, BASE, "fixture-client", SECRET, runner=self.runner)
        with self.assertRaises(ValueError): denied.preview(CARD, self.offer, {"country": "HK"})
        for changes in ({"card_id": "another-card"}, {"destination": {"country": "HK", "address": SECRET}},
                        {"deadline": time.monotonic() - 1}, {"unknown": SECRET},
                        {"offer": self.offer | {"availability": "unknown"}},
                        {"offer": self.offer | {"grade": {"company": "PSA", "value": "9", "certificate_verified": False}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.quote(self.payload(**changes))
        self.assertEqual(self.workers, []); self.assertEqual(self.wire, [])

    def test_service_uses_bounded_provider_only_after_explicit_enable(self):
        from pokemon_index import commerce_service
        server = Mock()
        server.__enter__ = Mock(return_value=server); server.__exit__ = Mock(return_value=False)
        server.server_port = 8766
        common = {"POKEMON_COMMERCE_TOKEN": "offline-token-at-least-24-characters", **self.env()}
        with patch.dict(os.environ, common, clear=True), patch.object(commerce_service, "create_server", return_value=server) as create, \
                patch("sys.argv", ["sidecar"]), redirect_stdout(io.StringIO()):
            commerce_service.main()
        self.assertEqual(create.call_args.args[0].forwarders, {})
        with patch.dict(os.environ, common, clear=True), patch.object(commerce_service, "create_server", return_value=server) as create, \
                patch("sys.argv", ["sidecar", "--allow-live-buyship", "--quote-db", str(self.path)]), redirect_stdout(io.StringIO()):
            commerce_service.main()
        provider = create.call_args.args[0].forwarders["buyship"]
        self.assertIsInstance(provider, bounded.BoundedBuyShipForwarder)
        self.assertEqual(self.wire, []); self.assertEqual(self.workers, [])


if __name__ == "__main__":
    unittest.main()
