"""Synthetic full HTTP journey. No marketplace, BNS, order or payment calls."""
from contextlib import ExitStack
import copy
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from pokemon_index.approved_sources import ApprovedSources
from pokemon_index.bns_errors import BNSRefusal
from pokemon_index import bns_url_preview
from pokemon_index.commerce_loop import CommerceLoop
from pokemon_index.commerce_service import create_server
from pokemon_index.dispatch_budget import DispatchBudget
from pokemon_index.ebay_official import BrowseClient

CARD = "en:BASE:4/102:holo_1st_edition"
TITLE = "English BASE Charizard 4/102 holo 1st edition PSA 10"
URL = "https://www.ebay.com/itm/123456789012"
BASE = "https://bns.partner.example.com"


def policy(**changes):
    return {"mode": "api_only", "api_approved": True, "crawl_approved": False,
            "access_approval": "synthetic-operator-record", "photo_display_approved": True,
            "partner_handoff_allowed": True, **changes}


class Pilot:
    """Real parsers/HTTP service, with in-memory HTTPS and BNS boundaries."""
    def __init__(self, **policy_changes):
        self.instant = datetime.now(timezone.utc).replace(microsecond=0)
        self.rows = []
        for index in range(2):
            self.rows.append({"itemId": f"v1|{123456789012 + index}|0",
                "itemWebUrl": f"https://www.ebay.com/itm/{123456789012 + index}",
                "title": TITLE, "buyingOptions": ["FIXED_PRICE"],
                "price": {"value": str(120 + index * 10), "currency": "USD"},
                "seller": {"username": f"synthetic_seller_{index}"},
                "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 1}],
                "image": {"imageUrl": f"https://i.ebayimg.com/images/g/fixture{index}/card.jpg"},
                "localizedAspects": [{"name": key, "value": value} for key, value in
                    [("Professional Grader", "PSA"), ("Grade", "10"), ("Language", "en"),
                     ("Set Code", "BASE"), ("Card Number", "4/102"), ("Finish", "holo"),
                     ("Edition", "first_edition")]]})
        self.provider_paths, self.marketplace_paths, self.external_attempts = [], [], []
        self.on_connect = lambda: None
        self.after_search_response = lambda: None
        self.after_worker = lambda: None
        self.fixture = json.loads((Path(__file__).parents[1] / "examples/buyship_partner_preview.json").read_text())
        resolved, quoted = self.fixture["resolve"], self.fixture["quote"]
        resolved.update(url=URL, product={"name": TITLE, "images": []})
        resolved["merchant"]["domain"] = "www.ebay.com"
        first = {"availability": "in_stock", "options": {"purchase": "card"},
                 "price": {"currency": "USD", "subunit_amount": 12000}, "variant_key": "fixture-card"}
        resolved["variants"] = [first, {**copy.deepcopy(first), "variant_key": "fixture-card-case", "options": {"purchase": "card with case"}}]
        quoted["expires_at"] = (self.instant + timedelta(minutes=15)).isoformat()
        quoted["items"][0].update(name=TITLE, variant_key="fixture-card", variant_options=first["options"])
        self.budget = DispatchBudget(max_requests=50, seconds=600)
        self.api = BrowseClient("synthetic-client-id", "synthetic-client-secret", allow_network=True,
            production_approved=True, display_approved=True, read_until=self.instant + timedelta(minutes=10),
            request_budget=20, now=lambda: self.instant, dispatch_budget=self.budget)
        self.sources = ApprovedSources(policies={"ebay_us": policy(**policy_changes)}, budget=self.budget,
                                       ebay_client=self.api, enabled=True, public_listing_urls=(URL,))
        self.forwarder = bns_url_preview.URLBuyShipForwarder(BASE, "synthetic-bns-client", "synthetic-bns-secret",
                                                          live_authorized=True, runner=self.runner)
        target = {"card_id": CARD, "language": "en", "set_code": "BASE", "collector_number": "4/102",
                  "finish": "holo", "edition": "first_edition", "evidence_ref": "synthetic:trusted-catalog"}
        self.loop = CommerceLoop(self.sources, forwarders={"buyship": self.forwarder},
                                 now=lambda: self.instant.isoformat(), catalog_lookup=lambda _: target)

    def __enter__(self):
        self.stack = ExitStack()
        outer = self
        class Sock:
            def settimeout(self, value): pass
        class Reply:
            status = 200
            def __init__(self, value): self.value = value
            def read(self, size): return json.dumps(self.value).encode()
        class HTTPS:
            def __init__(self, host, timeout): self.sock = Sock()
            def connect(self): outer.on_connect()
            def request(self, method, path, headers, body):
                outer.marketplace_paths.append(path); self.method, self.path = method, path
            def getresponse(self):
                if self.method == "POST": return Reply({"access_token": "synthetic-browse-token", "expires_in": 3600})
                if "/search?" in self.path:
                    # Real Browse discovery returns summaries, not getItem's
                    # grader/printing aspects or detailed stock evidence.
                    summaries = [{key: copy.deepcopy(value) for key, value in row.items()
                                  if key not in {"localizedAspects", "estimatedAvailabilities", "additionalImages"}}
                                 for row in outer.rows]
                    outer.after_search_response()
                    return Reply({"itemSummaries": summaries, "total": len(summaries)})
                native = parse_qs(urlsplit(self.path).query)["legacy_item_id"][0]
                return Reply(copy.deepcopy(next(row for row in outer.rows if native in row["itemId"])))
            def close(self): pass
        self.stack.enter_context(patch("pokemon_index.ebay_official.http.client.HTTPSConnection", HTTPS))
        native_connect = socket.socket.connect
        def only_loopback(sock, address):
            if not isinstance(address, tuple) or address[0] != "127.0.0.1":
                self.external_attempts.append(repr(address))
                raise AssertionError("external network forbidden in synthetic rehearsal")
            return native_connect(sock, address)
        self.stack.enter_context(patch("socket.socket.connect", only_loopback))
        native_connect_ex = socket.socket.connect_ex
        def only_loopback_ex(sock, address):
            if not isinstance(address, tuple) or address[0] != "127.0.0.1":
                self.external_attempts.append(repr(address))
                raise AssertionError("external network forbidden in synthetic rehearsal")
            return native_connect_ex(sock, address)
        native_dns = socket.getaddrinfo
        def only_loopback_dns(host, *args, **kwargs):
            if host != "127.0.0.1":
                self.external_attempts.append(repr(host))
                raise AssertionError("external DNS forbidden in synthetic rehearsal")
            return native_dns(host, *args, **kwargs)
        self.stack.enter_context(patch("socket.socket.connect_ex", only_loopback_ex))
        self.stack.enter_context(patch("socket.getaddrinfo", only_loopback_dns))
        self.server = create_server(self.loop, token="synthetic-private-loopback-token", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.stack.close()
        assert not self.external_attempts, "An external network attempt was caught; rehearsal is invalid"

    def transport(self, request, **bounds):
        path = request.full_url.removeprefix(BASE)
        self.provider_paths.append(path)
        if path.endswith("/token"):
            data = {"access_token": "synthetic-bns-token", "expires_in": 3600}
        else:
            data = self.fixture["resolve" if path.endswith("/resolve") else "quote"]
        return {"status": 200, "body": copy.deepcopy(data)}

    def runner(self, args, **kwargs):
        try:
            quote = bns_url_preview._preview(json.loads(kwargs["input"]), env=kwargs["env"], transport=self.transport)
            result = {"schema": bns_url_preview.RESULT_SCHEMA, "quote": quote}
        except BNSRefusal as exc:
            result = {"schema": bns_url_preview.RESULT_SCHEMA, "refusal": exc.result}
        self.after_worker()
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    def post(self, path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("POST", "/commerce/" + path, json.dumps(payload),
            {"Content-Type": "application/json", "Authorization": "Bearer synthetic-private-loopback-token", "X-Commerce-Owner": "synthetic-owner"})
        response = connection.getresponse(); data = json.loads(response.read()); connection.close()
        return response.status, data

    def research(self):
        return self.post("research", {"card_id": CARD, "query": TITLE, "platforms": ["ebay_us"]})

    def select(self, offer):
        return self.post("select", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"],
                                   "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def handoff(self, selected, **changes):
        return self.post("handoff", {"selection_id": selected["selection_id"], "forwarder": "buyship",
                                     "destination": {"country": "HK"}, **changes})


def rehearsal():
    with Pilot() as pilot:
        _, research = pilot.research()
        _, selection = pilot.select(research["offers"][0])
        _, variant = pilot.handoff(selection)
        _, handoff = pilot.handoff(selection, variant_key="fixture-card")
        assert variant.get("status") == "variant_selection_required", variant
        assert handoff.get("status") == "quote_ready_for_review", handoff
        result = {"schema": "pokemon.live-offer-rehearsal.v1", "evidence_mode": "synthetic_offline",
                  "external_network_calls": len(pilot.external_attempts), "now": pilot.instant.isoformat(), "research": research,
                  "selection": selection, "variant_required": variant, "handoff": handoff,
                  "provider_paths": pilot.provider_paths, "blocked": []}
    for scenario in ("price_changed", "sold", "identity_changed"):
        with Pilot() as pilot:
            _, research = pilot.research(); _, selected = pilot.select(research["offers"][0])
            pilot.instant += timedelta(seconds=1)
            if scenario == "price_changed": pilot.rows[0]["price"]["value"] = "999.00"
            elif scenario == "sold": pilot.rows[0]["estimatedAvailabilities"][0]["estimatedAvailabilityStatus"] = "OUT_OF_STOCK"
            else: pilot.rows[0]["seller"]["username"] = "replacement_seller"
            status, body = pilot.handoff(selected)
            assert status != 200 and not pilot.provider_paths
            result["blocked"].append({"scenario": scenario, "code": body["error"]})
    result["now"] = datetime.now(timezone.utc).isoformat()
    return result


if __name__ == "__main__":
    print(json.dumps(rehearsal(), ensure_ascii=False))
