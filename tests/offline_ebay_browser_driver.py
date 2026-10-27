"""Test-only JSONL driver: actual catalog/Browse/commerce with five fake captures.

No account, credential, marketplace, BNS or PSA request is possible. The wire
response is explicitly synthetic so the real UI suppresses external actions.
"""
from contextlib import ExitStack
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IDS = [str(123456789010 + n) for n in range(5)]
URLS = ["https://www.ebay.com/itm/" + item for item in IDS]


def main():
    counters = {"network_attempts": 0, "ebay_fixture_requests": 0, "catalog_replays": 0,
                "bns_fixture_requests": 0, "psa_fixture_requests": 0}

    def deny(*_args, **_kwargs):
        counters["network_attempts"] += 1
        raise AssertionError("offline browser fixture prohibits external IO")

    with ExitStack() as stack:
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                       "socket.getaddrinfo", "subprocess.Popen"):
            stack.enter_context(patch(target, side_effect=deny))
        spec = importlib.util.spec_from_file_location("offline_browser_catalog", ROOT / "tests/test_collector_recommendation.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.SUITE = ROOT / "tests/fixtures/offline-chat-catalog-v1.json"
        catalog = module.RecommendationTests()
        catalog.setUp()
        stack.callback(catalog.tearDown)
        card = catalog.replay(catalog.start(), limit=5)["candidate_cards"][0]
        from pokemon_index.commerce_loop import CommerceError, CommerceLoop
        from pokemon_index.ebay_official import BrowseClient, EbayOfficialCrawler

        controls = {"ttl_seconds": 300, "price_delta": 0}

        def instant():
            return datetime.now(timezone.utc)

        def item(native):
            return {"itemId": f"v1|{native}|0", "itemWebUrl": "https://www.ebay.com/itm/" + native,
                    "title": f"SYNTHETIC FIXTURE Pikachu FIX 001/100 PSA 10 seller {native[-1]}",
                    "listingMarketplaceId": "EBAY_US", "buyingOptions": ["FIXED_PRICE"],
                    "price": {"value": f"{25 + IDS.index(native) * 3 + controls['price_delta']}.00", "currency": "USD"},
                    "seller": {"username": "fixture-seller-" + native[-1]},
                    "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 1}],
                    "localizedAspects": [{"name": "Professional Grader", "value": "PSA"}, {"name": "Grade", "value": "10"}]}

        def transport(method, path, **_bounds):
            counters["ebay_fixture_requests"] += 1
            if method == "POST" and path == "/identity/v1/oauth2/token":
                return {"access_token": "offline-fixture-token", "expires_in": 3600}
            if method == "GET" and path.startswith("/buy/browse/v1/item/get_item_by_legacy_id?"):
                from urllib.parse import parse_qs, urlsplit
                native = parse_qs(urlsplit(path).query).get("legacy_item_id", [None])[0]
                if native in IDS:
                    return item(native)
            raise ValueError("offline fixture transport route unavailable")

        class Fallback:
            mode = "on_demand_research"

            def search(self, *_args, **_kwargs):
                return {"status": "unavailable", "listings": []}

            def detail(self, _url):
                raise ValueError("offline fixture URL unavailable")

        client = BrowseClient("offline-id", "offline-secret", allow_network=True, production_approved=True,
                              display_approved=True, read_until=instant() + timedelta(minutes=30),
                              request_budget=20, transport=transport)
        loop = CommerceLoop(EbayOfficialCrawler(Fallback(), client))

        def synthetic(value):
            result = copy.deepcopy(value)
            result["mode"] = "synthetic_fixture"
            for offer in result.get("offers", []):
                offer["synthetic"] = True
            if isinstance(result.get("offer"), dict):
                result["offer"]["synthetic"] = True
            if "marketplace_connections" in result:
                result["marketplace_connections"] = [
                    {"source": "ebay_us", "status": "not_configured", "message": "Offline synthetic eBay captures only; no marketplace account is connected."},
                    {"source": "fanatics_collect", "status": "not_configured", "message": "Fanatics Collect is not connected."}]
            if "forwarders" in result:
                result["forwarders"] = []
            for platform in result.get("platforms", []):
                if platform["source"] == "ebay_us":
                    platform.update(status="synthetic_fixture", message="Five synthetic fixed-price captures; no live eBay request or price verification.")
            return result

        def dispatch(message):
            op, payload = message["operation"], message.get("payload", {})
            if op == "bootstrap":
                return {"card": card, "now": instant().isoformat(), "synthetic_fixture": True, "product_urls": URLS}
            if op == "catalog":
                counters["catalog_replays"] += 1
                return catalog.replay(payload["turns"], limit=payload.get("limit", 5))
            if op == "configure":
                if set(payload) - set(controls):
                    raise ValueError("unsupported fixture control")
                if "ttl_seconds" in payload and (type(payload["ttl_seconds"]) is not int or not 1 <= payload["ttl_seconds"] <= 300):
                    raise ValueError("unsupported fixture TTL")
                if "price_delta" in payload and (type(payload["price_delta"]) is not int or not 0 <= payload["price_delta"] <= 10):
                    raise ValueError("unsupported fixture price delta")
                controls.update(payload)
                loop.freshness_seconds = controls["ttl_seconds"]
                return {"now": instant().isoformat(), "card": card}
            if op == "counters":
                return counters | {"external_calls": 0, "orders": 0, "payments": 0}
            if op in {"psa", "handoff"}:
                raise CommerceError("read_only_scope", "Provider operations are disabled in this offline browser fixture.", 403)
            if op not in {"research", "select"}:
                raise ValueError("unsupported offline operation")
            if op == "research":
                # Five explicit detail URLs preserve the normal three-result
                # search cap; this fixture never broadens production discovery.
                if payload.get("product_urls") != URLS:
                    raise CommerceError("invalid_request", "Use the five explicit synthetic URLs for this fixture.")
            return synthetic(getattr(loop, op)(message["owner"], payload))

        for line in sys.stdin:
            try:
                message = json.loads(line)
                result = {"id": message["id"], "value": dispatch(message)}
            except CommerceError as exc:
                result = {"id": message["id"], "error": exc.code, "status": exc.status}
            except Exception:
                result = {"id": message.get("id"), "error": "offline_browser_fixture_unavailable", "status": 400}
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
