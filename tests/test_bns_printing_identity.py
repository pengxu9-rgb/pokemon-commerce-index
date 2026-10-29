"""Printing contradictions cannot become quote-review receipts (offline only)."""
import copy
import json
import sys
import unittest

from pokemon_index import bns_url_preview as preview
from pokemon_index.bns_errors import BNSRefusal
from tests import test_bns_url_preview as fixtures
from tests.live_offer_rehearsal import Pilot


CLAIMS = {"language": "en", "set_code": "BASE", "collector_number": "173/165",
          "finish": "holo", "edition": "first_edition"}


def printing_report():
    """Actual HTTP/source/worker journey, suitable for frontend contract checks."""
    rows = []
    for label, wrong in (("Edition", "Unlimited"), ("Language", "Japanese"), ("Finish", "Non-Holo"),
                         ("product_name", "Japanese BASE Charizard 4/102 holo Unlimited PSA 10")):
        with Pilot() as pilot:
            if label != "product_name":
                options = {label: wrong}
                pilot.fixture["resolve"]["variants"][0]["options"] = options
                pilot.fixture["quote"]["items"][0]["variant_options"] = options
            status, research = pilot.research()
            assert status == 200 and research["offers"][0]["identity_status"] == "exact_match"
            status, selection = pilot.select(research["offers"][0])
            assert status == 200
            status, choices = pilot.handoff(selection)
            assert status == 200 and choices["status"] == "variant_selection_required"
            if label == "product_name":
                pilot.fixture["resolve"]["product"]["name"] = wrong
                pilot.fixture["quote"]["items"][0]["name"] = wrong
            pilot.provider_paths.clear()
            status, handoff = pilot.handoff(selection, variant_key="fixture-card")
            assert status == 200 and handoff["quote_status"] == "product_mismatch", handoff
            assert handoff["quote"] is None
            assert len(pilot.provider_paths) == 2  # token + resolve; no quote
            assert not handoff["purchasable"] and not handoff["order_created"] and handoff["purchase_action"] is None
            assert not pilot.external_attempts
            rows.append({"case": label, "research": research, "selection": selection, "choices": choices,
                         "handoff": handoff, "provider_paths": list(pilot.provider_paths),
                         "external_attempts": list(pilot.external_attempts)})
    return {"evidence_mode": "synthetic_offline", "cases": rows, "external_network_calls": 0}


class PrintingHTTPJourneyTests(unittest.TestCase):
    def test_exact_http_journey_rejects_all_four_adversarial_cases(self):
        report = printing_report()
        self.assertEqual({row["case"] for row in report["cases"]},
                         {"Edition", "Language", "Finish", "product_name"})


class PrintingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.URLPreviewTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.fx.offer["source_printing_evidence"] = {
            "claims": copy.deepcopy(CLAIMS), "listing_url": self.fx.offer["url"],
            "evidence_ref": "offline:exact-listing-printing", "observed_at": self.fx.offer["observed_at"],
            "basis": "exact_listing_structured"}

    def options(self, values):
        self.fx.fixture["resolve"]["variants"][0]["options"] = values
        self.fx.fixture["quote"]["items"][0]["variant_options"] = values

    def assert_unverified(self, quote):
        self.assertEqual(quote["status"], "quote_ready_for_review")
        self.assertFalse(quote["purchasable"])
        self.assertFalse(quote["order_created"])
        self.assertIsNone(quote["purchase_action"])
        self.assertEqual(quote["listing"]["identity_status"], "unverified_candidate")
        self.assertFalse(quote["evidence"]["certificate_verified"])
        self.assertFalse(quote["evidence"]["authenticity_verified"])
        self.assertNotIn("source_printing_evidence", quote["listing"])

    def test_resolve_and_quote_names_reject_printing_conflicts_and_negations(self):
        for name in ("Japanese Pikachu 173/165 PSA 10", "Pikachu 173/165 Unlimited PSA 10",
                     "Pikachu 173/165 non-holo PSA 10", "Pikachu 173/165 reverse holo PSA 10",
                     "Pikachu 173/165 no English PSA 10", "Pikachu 173/165 not first edition PSA 10",
                     "日本語 ピカチュウ 173/165 PSA 10", "Pikachu SV2A 173/165 PSA 10",
                     "Pikachu Set: JUNGLE", "Pikachu Language: ja", "Pikachu Language: zh-Hant", "Pikachu Finish: normal",
                     "Pikachu 173/165 1st_edition unlimited PSA 10"):
            for stage in ("resolve", "quote"):
                with self.subTest(name=name, stage=stage):
                    original = copy.deepcopy(self.fx.fixture)
                    self.fx.wire.clear()
                    item = self.fx.fixture["resolve"]["product"] if stage == "resolve" else self.fx.fixture["quote"]["items"][0]
                    item["name"] = name
                    with self.assertRaises(BNSRefusal) as raised:
                        self.fx.quote()
                    self.assertEqual(raised.exception.code, "product_mismatch")
                    self.assertEqual(len(self.fx.wire), 2 if stage == "resolve" else 3)
                    self.fx.fixture = original

    def test_selected_options_compare_structured_claims_in_both_directions(self):
        for options in ({"Edition": "Unlimited"}, {"Japanese": "Language"}, {"Finish": "Non-Holo"},
                        {"Language": "ja"}, {"Set Code": "JUNGLE"}, {"Card Number": "174"},
                        {"Edition": "not first edition"}, {"language": "not English"},
                        {"finish": "reverse_masterball"}, {"finish": "Ｎｏｎ-Ｈｏｌｏ"},
                        {"edition": "unlimited edition"}, {"仕上げ": "ノンホロ"}):
            with self.subTest(options=options):
                self.options(options)
                self.fx.wire.clear()
                with self.assertRaises(BNSRefusal) as raised:
                    self.fx.quote()
                self.assertEqual(raised.exception.code, "product_mismatch")
                self.assertEqual(len(self.fx.wire), 2)

    def test_matching_synonyms_missing_data_and_token_boundaries_stay_unverified(self):
        for options in ({}, {"Language": "English", "Edition": "first-edition", "Finish": "Holographic"},
                        {"Language": "en", "Set Code": "BASE", "Card Number": "0173/0165"},
                        {"初版": "Edition"}, {"notes": "Englishman holofoil unlimitedness Japaneseish"},
                        {"size": "normal", "style": "standard"}):
            with self.subTest(options=options):
                self.options(options)
                self.assert_unverified(self.fx.quote())
        # Non-holo consumes its complete negative phrase, not a matching holo
        # substring. The source's explicit normal claim is still unverified.
        self.fx.offer["source_printing_evidence"]["claims"]["finish"] = "normal"
        self.options({"Finish": "Non-Holo"})
        self.assert_unverified(self.fx.quote())

    def test_absent_dimensions_are_not_inferred_from_catalog_id_or_script(self):
        for remove in (False, True):
            with self.subTest(remove=remove):
                if remove:
                    self.fx.offer.pop("source_printing_evidence")
                else:
                    self.fx.offer["source_printing_evidence"]["claims"] = dict.fromkeys(CLAIMS)
                self.options({"Language": "Japanese", "Edition": "Unlimited", "Finish": "Non-Holo"})
                self.assert_unverified(self.fx.quote())

    def test_partial_structured_claims_still_reject_known_conflicts(self):
        self.fx.offer["source_printing_evidence"]["claims"] = dict.fromkeys(CLAIMS) | {"language": "en"}
        self.fx.offer["title"] = "Pikachu 173/165 PSA 10"  # no title language
        self.options({"Language": "Japanese"})
        with self.assertRaises(BNSRefusal) as raised:
            self.fx.quote()
        self.assertEqual(raised.exception.code, "product_mismatch")

    def test_private_proof_binding_and_noncanonical_claims_fail_before_provider(self):
        for field, value in (("listing_url", "https://jp.mercari.com/item/m9999"),
                             ("basis", "title_guess"), ("claims", CLAIMS | {"language": "English"}),
                             ("claims", {"language": "en"}), ("evidence_ref", "")):
            with self.subTest(field=field):
                offer = copy.deepcopy(self.fx.offer)
                offer["source_printing_evidence"][field] = value
                with self.assertRaises(BNSRefusal):
                    self.fx.quote(offer=offer)
                self.assertEqual(self.fx.wire, [])

    def test_parent_revalidates_selected_printing_options_and_private_claim_hash(self):
        quote = self.fx.quote()
        tampered = copy.deepcopy(quote)
        tampered["buyship"]["variant_options"] = {"Edition": "Unlimited"}
        tampered["evidence"]["binding_sha256"] = preview._binding(tampered)
        with self.assertRaises(BNSRefusal) as raised:
            preview.validate_quote(tampered, fixtures.CARD, self.fx.offer, {"country": "HK"})
        self.assertEqual(raised.exception.code, "product_mismatch")
        changed_offer = copy.deepcopy(self.fx.offer)
        changed_offer["source_printing_evidence"]["claims"]["language"] = "ja"
        with self.assertRaises(BNSRefusal) as raised:
            preview.validate_quote(quote, fixtures.CARD, changed_offer, {"country": "HK"})
        self.assertEqual(raised.exception.code, "quote_binding_invalid")

    def test_raw_claim_rejects_explicit_graded_provider_names_and_options(self):
        self.fx.offer["grade"] = {"company": None, "value": None, "certificate_verified": False,
            "kind": "raw", "evidence": "structured_raw_claim", "review_required": False,
            "review_reasons": [], "special_label": None}
        self.fx.offer["title"] = "Pikachu 173/165 Ungraded"
        for stage in ("resolve", "quote"):
            with self.subTest(stage=stage):
                with self.assertRaises(BNSRefusal) as raised:
                    self.fx.quote()
                self.assertEqual(raised.exception.code, "product_mismatch")
                self.fx.fixture["resolve"]["product"]["name"] = "Pikachu 173/165 Ungraded"
        self.fx.fixture["quote"]["items"][0]["name"] = "Pikachu 173/165 未鑑定"
        for options in ({"grade": "PSA 10"}, {"PSA": "10"}, {"grade": "10"}, {"condition": "Graded"},
                        {"form": "Slab"}, {"form": "not raw"}):
            with self.subTest(options=options):
                self.options(options)
                with self.assertRaises(BNSRefusal) as raised:
                    self.fx.quote()
                self.assertEqual(raised.exception.code, "product_mismatch")
        for options in ({}, {"condition": "Ungraded"}, {"form": "Raw"}, {"form": "未鑑定"}):
            self.options(options)
            self.assert_unverified(self.fx.quote())

    def test_slab_claim_rejects_explicit_raw_names_and_options(self):
        for raw in ("Raw", "Ungraded", "未鑑定", "鑑定前"):
            for stage in ("resolve", "quote", "options"):
                with self.subTest(raw=raw, stage=stage):
                    original = copy.deepcopy(self.fx.fixture)
                    if stage == "options":
                        self.options({"condition": raw})
                    else:
                        item = self.fx.fixture["resolve"]["product"] if stage == "resolve" else self.fx.fixture["quote"]["items"][0]
                        item["name"] = "Pikachu 173/165 " + raw
                    with self.assertRaises(BNSRefusal) as raised:
                        self.fx.quote()
                    self.assertEqual(raised.exception.code, "product_mismatch")
                    self.fx.fixture = original


if __name__ == "__main__":
    if sys.argv[1:] == ["--report"]:
        print(json.dumps(printing_report(), ensure_ascii=False))
    else:
        unittest.main()
