"""Offline exact-copy research fixtures, with every socket and DNS call denied."""
import copy
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index.commerce_loop import CommerceError, CommerceLoop
from pokemon_index import commerce_service
from pokemon_index.listing_evidence import CatalogIdentityLookup, FIELDS, photo_url
from pokemon_index.marketplace_crawl import Crawler
from tests.test_marketplace_crawl import FixtureFetch

STAMP = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)
CARD = "en:BASE:4/102:holo_1st_edition"
URL = "https://jp.mercari.com/item/m1001"
PHOTO = "https://static.mercdn.net/item/detail/orig/photos/m1001_1.jpg"
CLAIMS = {"language": "en", "set_code": "BASE", "collector_number": "4/102", "finish": "holo", "edition": "first_edition"}


def catalog(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE card(card_id TEXT PRIMARY KEY,language TEXT,set_code TEXT,collector_number TEXT,variant TEXT,provenance TEXT,match_eligible INTEGER,display_allowed INTEGER)")
    db.execute("INSERT INTO card VALUES(?,?,?,?,?,?,1,1)", (CARD, "en", "BASE", "4/102", "holo_1st_edition", "offline-fixture:trusted-catalog-row"))
    db.commit(); db.close()


def document(claims=CLAIMS, *, title="Charizard 4/102 PSA 10 graded card", image=PHOTO, sold=False, **changes):
    offered = {"@type": "Product", "url": URL, "additionalProperty": [{"name": field, "value": value} for field, value in claims.items()]}
    offer = {"@type": "Offer", "url": URL, "itemOffered": offered, "image": image,
             "price": 12000, "priceCurrency": "JPY", "availability": "https://schema.org/OutOfStock" if sold else "https://schema.org/InStock"}
    product = {"@type": "Product", "name": title, "url": URL, "offers": offer}
    product.update(changes)
    return "<html><script type='application/ld+json'>" + json.dumps(product) + "</script></html>"


class ListingEvidenceTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(name, side_effect=AssertionError("offline exact-listing fixture only"))
            guard.start(); self.addCleanup(guard.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "catalog.sqlite3"; catalog(self.path)
        self.lookup = CatalogIdentityLookup(self.path)
        self.fetch = FixtureFetch({URL: document()})
        self.clock = STAMP
        self.crawler = Crawler(self.fetch, now=lambda: self.clock)
        self.loop = CommerceLoop(self.crawler, now=lambda: self.clock.isoformat(), catalog_lookup=self.lookup)

    def research(self, *, card=CARD, query="anything", loop=None):
        return (loop or self.loop).research("fixture-owner", {"card_id": card, "query": query, "platforms": ["mercari"], "product_urls": [URL]})

    def change_page(self, body):
        self.fetch.pages[URL] = body

    def selected(self):
        offer = self.research()["offers"][0]
        return self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def handoff(self, selected):
        return self.loop.handoff("fixture-owner", {"selection_id": selected["selection_id"], "forwarder": "other", "destination": {"country": "HK"}})

    def update_catalog(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(sql, args)
            db.commit()

    def test_all_structured_dimensions_match_real_server_lookup_and_bound_photos(self):
        report = self.research()
        offer = report["offers"][0]; proof = offer["identity_evidence"]
        self.assertEqual(offer["identity_status"], "exact_match")
        self.assertEqual(offer["card_id"], CARD)
        self.assertEqual(proof["status"], "exact_match")
        self.assertEqual(proof["claims"], CLAIMS)
        self.assertEqual(set(proof["matched_fields"]), set(FIELDS))
        self.assertEqual(proof["missing_fields"], []); self.assertEqual(proof["conflicting_fields"], [])
        self.assertTrue(proof["target"]["evidence_ref"].startswith("catalog-row:sha256:"))
        self.assertFalse(proof["authenticity_verified"])
        self.assertEqual(offer["listing_photos"][0]["url"], PHOTO)
        self.assertEqual(offer["listing_photos"][0]["listing_url"], URL)
        self.assertEqual(offer["listing_photos"][0]["evidence_ref"], offer["evidence_ref"])
        self.assertEqual(report["coverage"], {"returned_listings": 1, "exact_match_listings": 1, "candidate_listings": 0, "conflicting_listings": 0, "sold_listings": 0, "listings_with_photos": 1, "search_limit_per_source": None, "exhaustive": False, "live_coverage_verified": False})

    def test_request_query_and_forged_raw_card_id_never_supply_target_truth(self):
        for card in ("en:BASE:99/102:holo_1st_edition", "whatever-the-browser-claims"):
            offer = self.research(card=card, query="English BASE 4/102 holo first edition")["offers"][0]
            self.assertEqual(offer["identity_evidence"]["status"], "candidate")
            self.assertIsNone(offer["identity_evidence"]["target"]); self.assertIsNone(offer["card_id"])
        raw = self.crawler.detail(URL); raw["card_id"] = CARD; raw["identity_status"] = "exact_match"
        raw.pop("listing_identity")
        normalized = self.loop._offer(raw, "mercari", STAMP, self.lookup(CARD))
        self.assertEqual(normalized["identity_status"], "unverified_candidate")

    def test_title_only_matching_numbers_and_query_remain_candidate(self):
        self.change_page(document({}, title="English BASE Charizard 4/102 holo 1st edition PSA10"))
        offer = self.research(query="English BASE 4/102 holo first edition")["offers"][0]
        self.assertEqual(offer["identity_evidence"]["status"], "candidate")
        self.assertEqual(offer["identity_evidence"]["matched_fields"], [])
        self.assertEqual(set(offer["identity_evidence"]["missing_fields"]), set(FIELDS))

    def test_each_missing_dimension_blocks_exact_match(self):
        for field in FIELDS:
            with self.subTest(field=field):
                claims = CLAIMS.copy(); claims.pop(field)
                self.change_page(document(claims))
                proof = self.research()["offers"][0]["identity_evidence"]
                self.assertEqual(proof["status"], "candidate"); self.assertEqual(proof["missing_fields"], [field])

    def test_each_conflicting_dimension_blocks_selection(self):
        alternatives = {"language": "ja", "set_code": "JUNGLE", "collector_number": "5/102", "finish": "normal", "edition": "unlimited"}
        for field, value in alternatives.items():
            with self.subTest(field=field):
                self.change_page(document(CLAIMS | {field: value}))
                offer = self.research()["offers"][0]
                self.assertEqual(offer["identity_status"], "identity_conflict")
                self.assertIn(field, offer["identity_evidence"]["conflicting_fields"])
                with self.assertRaises(CommerceError) as error:
                    self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
                self.assertEqual(error.exception.code, "identity_conflict")

    def test_explicit_title_contradictions_cannot_be_overridden_by_structured_attributes(self):
        cases = (("Charizard 5/102 PSA10", "collector_number"), ("Japanese Charizard 4/102 PSA10", "language"),
                 ("Charizard 005 / 102 PSA10", "collector_number"), ("日版 Charizard 4/102 PSA10", "language"),
                 ("Charizard 4/102 unlimited PSA10", "edition"), ("Charizard 4/102 non-holo PSA10", "finish"),
                 ("Charizard SV2A 4/102 PSA10", "set_code"))
        for title, field in cases:
            with self.subTest(title=title):
                self.change_page(document(title=title))
                self.assertIn(field, self.research()["offers"][0]["identity_evidence"]["conflicting_fields"])

    def test_negated_edition_and_language_cannot_form_exact_or_selectable_cohorts(self):
        cases = (("NOT 1st edition", "edition"), ("Non-1st Edition", "edition"),
                 ("without 1st edition stamp", "edition"), ("no 1st edition", "edition"),
                 ("not a first edition", "edition"), ("first edition is not", "edition"),
                 ("NOT (1st edition)", "edition"), ("not [English]", "language"), ("English [not]", "language"),
                 ("Not English", "language"), ("Non-English", "language"),
                 ("NOT 4/102", "collector_number"), ("NOT (4 / 102)", "collector_number"),
                 ("not (holo)", "finish"), ("NOT BASE", "set_code"),
                 ("not actually English", "language"), ("英語ではない", "language"))
        for claim, field in cases:
            with self.subTest(claim=claim):
                self.change_page(document(title="Charizard 4/102 " + claim + " PSA10 graded card"))
                offer = self.research()["offers"][0]
                self.assertEqual(offer["identity_status"], "identity_conflict")
                self.assertIn(field, offer["identity_evidence"]["conflicting_fields"])
                with self.assertRaises(CommerceError):
                    self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"],
                        "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def test_negated_grade_claims_require_review_and_cannot_be_selected(self):
        for claim in ("NOT PSA10", "not PSA 10", "Non-PSA10", "without PSA10", "not certified as PSA 10", "PSA 10 is not", "ＰＳＡ１０ではない", "Not (PSA10)", "not, PSA10", "PSA10 [not]"):
            with self.subTest(claim=claim):
                self.change_page(document(title="Charizard 4/102 " + claim + " graded card"))
                offer = self.research()["offers"][0]
                self.assertTrue(offer["grade"]["review_required"])
                self.assertIn("conflicting_grade_claims", offer["grade"]["review_reasons"])
                with self.assertRaises(CommerceError):
                    self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"],
                        "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def test_negated_compound_finishes_conflict_while_positive_non_holo_is_normal(self):
        for finish, phrase in (("reverse", "reverse holo"), ("normal", "non-holo"),
                               ("reverse_masterball", "Master Ball reverse holo")):
            with self.subTest(finish=finish):
                self.update_catalog("UPDATE card SET variant=?", (finish + "_1st_edition",))
                self.change_page(document(CLAIMS | {"finish": finish}, title="Charizard 4/102 " + phrase + " PSA10 graded card"))
                self.assertEqual(self.research()["offers"][0]["identity_status"], "exact_match")
                self.change_page(document(CLAIMS | {"finish": finish}, title="Charizard 4/102 NOT (" + phrase + ") PSA10 graded card"))
                offer = self.research()["offers"][0]
                self.assertEqual(offer["identity_status"], "identity_conflict")
                self.assertIn("finish", offer["identity_evidence"]["conflicting_fields"])
                with self.assertRaises(CommerceError):
                    self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"],
                        "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def test_positive_claims_still_match_without_text_becoming_proof(self):
        self.change_page(document(title="English Charizard 4/102 Holo 1st edition PSA10 graded card"))
        offer = self.research()["offers"][0]
        self.assertEqual(offer["identity_status"], "exact_match")
        self.assertFalse(offer["grade"]["review_required"])
        self.assertIsNotNone(self.selected()["selection_id"])
        # Missing certificate/condition data is not a negated seller grade.
        # A claimed grade stays a claim; the certificate remains unchecked.
        for suffix in ("no certificate number shown", "no scratches reported"):
            self.change_page(document(title="English Charizard 4/102 Holo 1st edition PSA10 " + suffix + " graded card"))
            offer = self.research()["offers"][0]
            self.assertEqual(offer["identity_status"], "exact_match")
            self.assertFalse(offer["grade"]["review_required"])
            self.assertEqual(offer["certificate"]["status"], "number_missing")

    def test_explicit_specific_finish_names_do_not_become_generic_reverse_holo_conflicts(self):
        cases = (("reverse_masterball", "Master Ball reverse holo"), ("reverse_pokeball", "Poke Ball reverse holo"),
                 ("cosmos_holo", "Cosmos holo"), ("alternate_holo", "Alternate holo"))
        for finish, title in cases:
            with self.subTest(finish=finish):
                self.update_catalog("UPDATE card SET variant=?", (finish + "_1st_edition",))
                self.change_page(document(CLAIMS | {"finish": finish}, title="Charizard 4/102 " + title + " PSA10 graded card"))
                self.assertEqual(self.research()["offers"][0]["identity_evidence"]["status"], "exact_match")

    def test_all_supported_explicit_title_languages_contradict_english_claims(self):
        for language in ("German", "Korean", "한국어", "French", "Spanish", "Italian", "Portuguese", "Simplified Chinese", "Traditional Chinese", "中文"):
            with self.subTest(language=language):
                self.change_page(document(title=language + " Charizard 4/102 PSA10 graded card"))
                self.assertIn("language", self.research()["offers"][0]["identity_evidence"]["conflicting_fields"])
        self.change_page(document(title="English Charizard 4/102 PSA10 graded card"))
        self.assertEqual(self.research()["offers"][0]["identity_evidence"]["status"], "exact_match")

    def test_non_foil_and_holo_negation_titles_contradict_holo_claims(self):
        for finish in ("Non-Foil", "nonfoil", "non foil", "No Holo", "not holo", "nonholo"):
            with self.subTest(finish=finish):
                self.change_page(document(title=finish + " Charizard 4/102 PSA10 graded card"))
                self.assertIn("finish", self.research()["offers"][0]["identity_evidence"]["conflicting_fields"])
        self.update_catalog("UPDATE card SET variant='normal_1st_edition'")
        self.change_page(document(CLAIMS | {"finish": "normal"}, title="Non-Foil Charizard 4/102 PSA10 graded card"))
        self.assertEqual(self.research()["offers"][0]["identity_evidence"]["status"], "exact_match")

    def test_separate_alternative_finishes_remain_conflicting_after_compound_phrase_stripping(self):
        for finish, title in (("normal", "Holo / Non-Holo"), ("holo", "Holo / Reverse Holo"),
                ("reverse_masterball", "Masterball / reverse holo"), ("cosmos_holo", "Cosmos holo / Holo")):
            with self.subTest(title=title):
                self.update_catalog("UPDATE card SET variant=?", (finish + "_1st_edition",))
                self.change_page(document(CLAIMS | {"finish": finish}, title=title + " Charizard 4/102 PSA10 graded card"))
                self.assertIn("finish", self.research()["offers"][0]["identity_evidence"]["conflicting_fields"])

    def test_catalog_missing_edition_ineligible_or_held_never_implies_exact(self):
        self.update_catalog("UPDATE card SET variant='holo'")
        proof = self.research()["offers"][0]["identity_evidence"]
        self.assertIsNone(proof["target"]["edition"]); self.assertEqual(proof["status"], "candidate")
        for update in ("UPDATE card SET match_eligible=0", "UPDATE card SET match_eligible=1,display_allowed=0"):
            self.update_catalog(update)
            self.assertIsNone(self.research()["offers"][0]["identity_evidence"]["target"])
        self.update_catalog("UPDATE card SET match_eligible=1,display_allowed=1")
        self.update_catalog("CREATE TABLE catalog_identity_quarantine(quarantine_id TEXT, record_json TEXT)")
        self.update_catalog("INSERT INTO catalog_identity_quarantine VALUES('variant-dimension-hold:fixture',?)", (json.dumps({"identity": {"card_id": CARD}}),))
        self.assertIsNone(self.lookup(CARD))

    def test_legacy_producer_and_missing_catalog_keep_candidate_compatibility(self):
        loop = CommerceLoop(self.crawler, now=lambda: STAMP.isoformat())
        offer = self.research(loop=loop)["offers"][0]
        self.assertEqual(offer["identity_status"], "unverified_candidate")
        self.assertIsNone(offer["card_id"])
        raw = self.crawler.detail(URL); raw.pop("listing_identity"); raw.pop("listing_photos")
        offer = self.loop._offer(raw, "mercari", STAMP, self.lookup(CARD))
        self.assertEqual(offer["listing_photos"], []); self.assertEqual(offer["identity_evidence"]["status"], "candidate")

    def test_generic_product_image_og_image_related_items_and_wrong_offer_urls_are_not_copy_evidence(self):
        self.change_page(document({}, image=None, imageUrl=PHOTO, additionalProperty=[{"name": k, "value": v} for k, v in CLAIMS.items()]))
        offer = self.research()["offers"][0]
        self.assertEqual(offer["listing_photos"], []); self.assertEqual(offer["identity_evidence"]["status"], "candidate")
        product = json.loads(document().split("application/ld+json'>")[1].split("</script>")[0])
        product["offers"]["url"] = URL + "0"
        self.change_page("<script type='application/ld+json'>" + json.dumps(product) + "</script>")
        raw = self.crawler.detail(URL)
        self.assertIsNone(raw["listing_identity"]); self.assertEqual(raw["listing_photos"], [])

    def test_ambiguous_multiple_offers_do_not_choose_a_photo_or_identity(self):
        product = json.loads(document().split("application/ld+json'>")[1].split("</script>")[0])
        product["offers"] = [product["offers"], copy.deepcopy(product["offers"])]
        self.change_page("<script type='application/ld+json'>" + json.dumps(product) + "</script>")
        raw = self.crawler.detail(URL)
        self.assertIsNone(raw["listing_identity"]); self.assertEqual(raw["listing_photos"], [])

    def test_duplicate_or_unsupported_structured_claims_are_conflicts(self):
        product = json.loads(document().split("application/ld+json'>")[1].split("</script>")[0])
        product["offers"]["itemOffered"]["additionalProperty"].append({"name": "edition", "value": "unlimited"})
        self.change_page("<script type='application/ld+json'>" + json.dumps(product) + "</script>")
        self.assertEqual(self.research()["offers"][0]["identity_evidence"]["conflicting_fields"], ["edition"])
        self.change_page(document(CLAIMS | {"finish": "rare-looking shiny"}))
        self.assertEqual(self.research()["offers"][0]["identity_evidence"]["conflicting_fields"], ["finish"])

    def test_exact_snkr_flight_item_binds_attributes_photos_without_catalog_or_related_art(self):
        url = "https://snkrdunk.com/apparels/128089/used/30335981"
        photo = "https://images.snkrdunk.com/used/30335981/front.jpg"
        def flight(item_id=30335981):
            item = {"id": item_id, "apparel": {"id": 128089, "images": [photo.replace("front", "catalog")]},
                "price": 12000, "commaPrice": "¥12,000", "attributes": CLAIMS, "images": [photo], "displayWearCount": "PSA10"}
            record = ["$", "$L59", None, {"apparelId": 128089, "listingId": item_id, "usedApparelData": {"apparelUsedItem": item},
                "relatedProduct": {"images": [photo.replace("front", "related")], "attributes": CLAIMS}}]
            return "<html><title>Charizard 4/102 PSA10</title><script>self.__next_f.push(" + json.dumps([1, "4c:" + json.dumps(record) + "\n"]) + ")</script></html>"
        crawler = Crawler(FixtureFetch({url: flight()}), now=lambda: STAMP)
        raw = crawler.detail(url)
        self.assertEqual(raw["listing_identity"]["attributes"], CLAIMS)
        self.assertEqual([value["url"] for value in raw["listing_photos"]], [photo])
        raw = Crawler(FixtureFetch({url: flight(30335982)}), now=lambda: STAMP).detail(url)
        self.assertIsNone(raw["listing_identity"]); self.assertEqual(raw["listing_photos"], [])

    def test_unsafe_photo_urls_are_dropped_without_any_image_request(self):
        invalid = ("http://static.mercdn.net/item/detail/orig/photos/a.jpg", "https://127.0.0.1/a.jpg", "https://static.mercdn.net.evil.test/a.jpg", PHOTO + "?url=https://evil.test/a.jpg", PHOTO + "#fragment", "https://static.mercdn.net/item/detail/orig/photos/%2e%2e/a.jpg", "https://u:p@static.mercdn.net/item/detail/orig/photos/a.jpg", "https://static.mercdn.net/item/detail/orig/photos/a.svg")
        for url in invalid:
            self.assertIsNone(photo_url(url, "mercari"))
        self.change_page(document(image=[*invalid, PHOTO, PHOTO]))
        offers = self.research()["offers"]
        self.assertEqual([p["url"] for p in offers[0]["listing_photos"]], [PHOTO])
        self.assertTrue(all("robots.txt" in call or "/item/" in call for call in self.fetch.calls))

    def test_normalized_photos_and_identity_must_bind_exact_listing_and_capture_time(self):
        raw = self.crawler.detail(URL)
        for changed in (("listing_photos", "listing_url", URL + "0"), ("listing_identity", "native_id", "m2002"), ("listing_identity", "observed_at", (STAMP + timedelta(seconds=1)).isoformat())):
            value = copy.deepcopy(raw)
            field, key, wrong = changed
            if field == "listing_photos": value[field][0][key] = wrong
            else: value[field][key] = wrong
            with self.subTest(field=field, key=key), self.assertRaises(ValueError):
                self.loop._offer(value, "mercari", STAMP, self.lookup(CARD))

    def test_identity_photo_and_catalog_semantic_changes_invalidate_selection(self):
        mutations = (document(CLAIMS | {"edition": "unlimited"}), document(image=PHOTO.replace("_1", "_2")), document(image=[]))
        for body in mutations:
            self.change_page(document()); selected = self.selected(); self.change_page(body)
            with self.assertRaises(CommerceError) as error:
                self.handoff(selected)
            self.assertEqual(error.exception.code, "offer_changed")
        self.change_page(document()); selected = self.selected()
        self.update_catalog("UPDATE card SET variant='holo_unlimited'")
        with self.assertRaises(CommerceError) as error: self.handoff(selected)
        self.assertEqual(error.exception.code, "offer_changed")

    def test_new_capture_timestamp_hash_and_photo_order_do_not_change_semantic_selection(self):
        second = PHOTO.replace("_1", "_2")
        self.change_page(document(image=[PHOTO, second])); selected = self.selected()
        self.clock += timedelta(seconds=1)
        self.change_page(document(image=[second, PHOTO]) + "<!-- new capture -->")
        result = self.handoff(selected)
        self.assertEqual(result["offer"]["identity_status"], "exact_match")
        self.assertEqual(result["status"], "manual_handoff_required")

    def test_sold_exact_match_is_visible_and_counted_but_cannot_be_selected(self):
        self.change_page(document(sold=True)); report = self.research(); offer = report["offers"][0]
        self.assertEqual(offer["identity_evidence"]["status"], "exact_match")
        self.assertEqual(report["coverage"]["sold_listings"], 1)
        with self.assertRaises(CommerceError):
            self.loop.select("fixture-owner", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})

    def test_exact_projection_preserves_listing_fields_but_does_not_promote_quote_identity(self):
        offer = self.research()["offers"][0]
        projected = self.loop._url_quote_offer(CARD, offer)
        self.assertEqual(projected["identity_status"], "unverified_candidate")
        self.assertEqual(offer["identity_status"], "exact_match")
        for field in ("url", "native_id", "title", "grade", "price_minor", "currency", "observed_at", "seller"):
            self.assertEqual(projected[field], offer[field])
        for field in ("identity_evidence", "listing_photos", "card_id"):
            self.assertNotIn(field, projected)

    def test_stale_mismatched_and_forged_projection_proof_rejected(self):
        offer = self.research()["offers"][0]
        for field, wrong in (("target_card_id", "other-card"), ("listing_url", URL + "0"), ("status", "candidate"), ("missing_fields", ["edition"]), ("authenticity_verified", True), ("observed_at", (STAMP - timedelta(minutes=6)).isoformat())):
            value = copy.deepcopy(offer); value["identity_evidence"][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError): self.loop._url_quote_offer(CARD, value)
        self.update_catalog("UPDATE card SET variant='holo_unlimited'")
        with self.assertRaises(ValueError): self.loop._url_quote_offer(CARD, offer)

    def test_exact_offer_reaches_unchanged_frozen_url_quote_using_only_fixture_transport(self):
        from tests.test_bns_url_preview import Producer, URLPreviewTests
        helper = URLPreviewTests(methodName="runTest")
        helper.setUp(); self.addCleanup(helper.doCleanups)
        helper.row["title"] = "Charizard 4/102 PSA 10 graded card"
        helper.row["availability"], helper.row["status"] = "in_stock", "on_sale"
        helper.row["listing_identity"] = {"source": "mercari", "native_id": "m1001", "listing_url": helper.row["url"],
            "attributes": CLAIMS.copy(), "conflicting_fields": [], "basis": "exact_listing_structured",
            "evidence_ref": "offline:structured-listing", "observed_at": helper.row["observed_at"]}
        helper.fixture["resolve"]["product"]["name"] = helper.row["title"]
        helper.fixture["quote"]["items"][0]["name"] = helper.row["title"]
        loop = CommerceLoop(Producer(helper.row), forwarders={"buyship": helper.forwarder()}, catalog_lookup=self.lookup,
                            now=lambda: helper.row["observed_at"])
        offer = loop.research("owner", {"card_id": CARD, "query": "not identity proof", "platforms": ["mercari"]})["offers"][0]
        selected = loop.select("owner", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
        result = loop.handoff("owner", {"selection_id": selected["selection_id"], "forwarder": "buyship", "destination": {"country": "HK"}})
        self.assertEqual(result["status"], "quote_ready_for_review")
        self.assertEqual(result["offer"]["identity_status"], "exact_match")
        self.assertEqual(result["quote"]["listing"]["identity_status"], "unverified_candidate")
        self.assertEqual(result["quote"]["evidence"]["identity_status"], "unverified_candidate")
        self.assertNotIn("identity_evidence", result["quote"]["listing"])
        self.assertNotIn("listing_photos", result["quote"]["listing"])
        self.assertEqual(len(helper.wire), 3)
        self.assertEqual(json.loads(helper.wire[1]["body"]), {"url": helper.row["url"]})
        self.assertFalse(result["purchasable"]); self.assertFalse(result["order_created"])
        if os.environ.get("POT_FRONTEND_CONTRACT_ROOT"):
            script = """
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=process.argv[1],p=JSON.parse(fs.readFileSync(0,'utf8'));
require(path.join(root,'creator/src/lib/pokemon/commerceContract.cjs')).validateCommerceResponse('handoff',p.result);
const {handoffMatches}=require(path.join(root,'creator/src/lib/pokemon/bnsChatState.cjs'));
const args=[p.result,p.offer,p.card,'buyship',{country:'HK'},undefined,p.expires,Date.parse(p.result.quote.buyship.quoted_at)];
assert.equal(handoffMatches(...args),true);
p.offer.identity_evidence.claims.edition='unlimited';
assert.equal(handoffMatches(...args),false);
"""
            completed = subprocess.run(["node", "-e", script, os.environ["POT_FRONTEND_CONTRACT_ROOT"]],
                input=json.dumps({"result": result, "offer": offer, "card": CARD, "expires": selected["expires_at"], "now": helper.row["observed_at"]}),
                text=True, capture_output=True, timeout=10, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_service_cli_accepts_explicit_read_only_catalog_dependency_without_provider_enablement(self):
        with patch.object(sys, "argv", ["commerce_service", "--fixture", "--catalog-db", str(self.path)]), \
                patch.dict(os.environ, {"POKEMON_COMMERCE_TOKEN": "fixture-server-token-long-enough"}, clear=True), \
                patch.object(commerce_service, "CommerceLoop", wraps=CommerceLoop) as build, \
                patch.object(commerce_service, "create_server") as server, redirect_stdout(io.StringIO()):
            server.return_value.__enter__.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.return_value.__enter__.return_value.server_port = 0
            commerce_service.main()
        lookup = build.call_args.kwargs["catalog_lookup"]
        self.assertIsInstance(lookup, CatalogIdentityLookup)
        self.assertEqual(lookup(CARD)["edition"], "first_edition")
        self.assertEqual(build.call_args.kwargs["forwarders"], {})

    def test_http_service_handler_runs_same_authenticated_catalog_comparison_without_socket(self):
        # Exercise real JSON parsing/auth/dispatch, without opening even localhost.
        class StubServer:
            def __init__(self, address, handler): self.RequestHandlerClass = handler
        with patch.object(commerce_service, "ThreadingHTTPServer", StubServer):
            server = commerce_service.create_server(self.loop, token="fixture-server-token-long-enough")
        payload = json.dumps({"card_id": CARD, "query": "arbitrary", "platforms": ["mercari"], "product_urls": [URL]}).encode()
        request = b"POST /commerce/research HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer fixture-server-token-long-enough\r\nX-Commerce-Owner: fixture-owner\r\nContent-Type: application/json\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
        class Wire:
            output = bytearray()
            def makefile(self, *args): return io.BytesIO(request)
            def settimeout(self, value): pass
            def sendall(self, value): self.output.extend(value)
        wire = Wire(); server.RequestHandlerClass(wire, ("127.0.0.1", 1), server)
        headers, body = bytes(wire.output).split(b"\r\n\r\n", 1)
        self.assertIn(b"200 OK", headers)
        self.assertEqual(json.loads(body)["offers"][0]["identity_status"], "exact_match")


if __name__ == "__main__":
    unittest.main()
