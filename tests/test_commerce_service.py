import http.client
import json
import threading
import unittest

from pokemon_index.commerce_loop import CommerceLoop, FixtureCrawler, SCHEMA
from pokemon_index.commerce_service import create_server

TOKEN = "server-test-token-kept-out-of-browser"


class CommerceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.loop = CommerceLoop(FixtureCrawler())
        self.server = create_server(self.loop, token=TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def call(self, path, payload, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = {"Authorization": "Bearer " + TOKEN, "X-Commerce-Owner": "trusted-proxy-owner", "Content-Type": "application/json"}
        request_headers.update(headers or {})
        connection.request("POST", path, body=raw if raw is not None else json.dumps(payload), headers=request_headers)
        response = connection.getresponse()
        status, response_headers, body = response.status, dict(response.getheaders()), json.loads(response.read())
        connection.close()
        return status, response_headers, body

    def research(self):
        return self.call("/commerce/research", {"card_id": "ja:SV2A:173/165:standard", "query": "Pikachu"})

    def test_actual_http_loop_and_private_response_headers(self):
        status, headers, report = self.research()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn(TOKEN, json.dumps(report))
        offer = report["offers"][0]
        status, _, selected = self.call("/commerce/select", {"card_id": report["card_id"], "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
        self.assertEqual(status, 200)
        status, _, handoff = self.call("/commerce/handoff", {"selection_id": selected["selection_id"],
            "forwarder": "other", "destination": {"country": "KR"}})
        self.assertEqual(status, 200)
        self.assertEqual(handoff["schema"], SCHEMA)
        self.assertEqual(handoff["mode"], "synthetic_fixture")
        self.assertEqual(handoff["product_url"], offer["url"])
        self.assertEqual(handoff["status"], "manual_handoff_required")

    def test_auth_and_browser_origin_are_denied_before_research(self):
        for headers, expected in (({"Authorization": "Bearer wrong"}, 401), ({"X-Commerce-Owner": ""}, 401),
                                  ({"Origin": "http://localhost:3000"}, 403), ({"Sec-Fetch-Site": "same-origin"}, 403)):
            with self.subTest(headers=headers):
                status, _, body = self.call("/commerce/research", {}, headers=headers)
                self.assertEqual(status, expected)
                self.assertNotIn(TOKEN, json.dumps(body))
        self.assertEqual(self.loop._offers, {})

    def test_ambiguous_nonfinite_deep_and_nonobject_json_are_rejected(self):
        for raw in ('{"query":"a","query":"b"}', '{"value":NaN}', '[]', '[' * 17 + '0' + ']' * 17):
            with self.subTest(raw=raw):
                status, _, body = self.call("/commerce/research", {}, raw=raw)
                self.assertEqual(status, 400)
                self.assertEqual(body["error"], "invalid_request")

    def test_http_owner_cannot_use_another_owners_selection(self):
        _, _, report = self.research()
        offer = report["offers"][0]
        status, _, body = self.call("/commerce/select", {"card_id": report["card_id"], "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]},
            headers={"X-Commerce-Owner": "another-owner"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "offer_unavailable")

    def test_binding_and_token_configuration_refuse_public_exposure(self):
        with self.assertRaises(ValueError):
            create_server(self.loop, token=TOKEN, host="0.0.0.0", port=0)
        with self.assertRaises(ValueError):
            create_server(self.loop, token="short", port=0)

    def test_psa_route_is_authenticated_read_only_and_explicitly_disabled(self):
        status, _, result = self.call("/commerce/psa", {"certificate_number": "12345678"})
        self.assertEqual(status, 200)
        self.assertEqual(result["verification"]["status"], "unavailable")
        self.assertEqual(result["verification"]["reason"], "live_disabled")
        self.assertFalse(result["verification"]["certificate_verified"])
        self.assertFalse(result["verification"]["physical_authenticity_verified"])
        self.assertFalse(result["order_created"])
        self.assertEqual(self.call("/commerce/psa", {"certificate_number": "12345678"},
                                   headers={"Authorization": "Bearer wrong"})[0], 401)
        for path in ("/commerce/order", "/commerce/payment", "/commerce/checkout"):
            self.assertEqual(self.call(path, {})[0], 404)


if __name__ == "__main__":
    unittest.main()
