"""Printing contradictions cannot become quote-review receipts (offline only)."""
import copy
from datetime import timedelta
import json
import sys
import unittest

from pokemon_index import bns_url_preview as preview
from pokemon_index.bns_errors import BNSRefusal
from tests import test_bns_url_preview as fixtures
from tests.live_offer_rehearsal import Pilot


CLAIMS = {"language": "en", "set_code": "BASE", "collector_number": "173/165",
          "finish": "holo", "edition": "first_edition"}


REVIEW_OPTIONS = (
    ("negative_first_edition_boolean", {"First Edition": "No"}),
    ("negative_foil_boolean", {"Foil": "No"}),
    ("negative_holographic_boolean", {"Holographic": "No"}),
    ("alternate_language_key_canonical_value", {"Card Language": "ja"}),
    ("canonical_language_key_suffix", {"language_code": "ja"}),
    ("alternate_set_key_canonical_value", {"Set Name": "JUNGLE"}),
    ("alternate_collector_key_canonical_value", {"Collector No.": "5"}),
    ("negative_finish_ordinary_phrase", {"Finish": "No Foil"}),
    ("negative_finish_holofoil_alias", {"Finish": "Non Holofoil"}),
    ("language_jp_alias", {"Language": "JP"}),
    ("ordinary_language_negation", {"Language": "Not English"}),
    ("ordinary_edition_negation", {"Edition": "Non First Edition"}),
    ("canonical_wrong_language", {"Language": "ja"}),
    ("canonical_wrong_set", {"Set Code": "JUNGLE"}),
    ("canonical_wrong_collector", {"Card Number": "5"}),
    ("canonical_wrong_finish", {"Finish": "non_holo"}),
    ("reverse_finish_negation", {"Finish": "No Holo"}))
NAME_ASSERTIONS = (("language", "ja"), ("set", "JUNGLE"), ("finish", "normal"), ("edition", "standard"))


def _printing_journey(label, *, options=None, stage="selected_options", name=None, raw=False,
                      expected="product_mismatch"):
    """Actual HTTP/source/worker journey with denied/audited external sockets."""
    with Pilot() as pilot:
        if raw:
            for row in pilot.rows:
                row["title"] = row["title"].replace(" PSA 10", "")
                row.update(condition="Ungraded", conditionId="4000", categoryId="183454",
                           categoryPath="Collectibles|Collectible Card Games|CCG Individual Cards")
                row["conditionDescriptors"] = [{"name": "Card Condition", "values": [{"content": "Near mint or better"}]}]
                row["localizedAspects"] = [a for a in row["localizedAspects"] if a["name"] not in {"Professional Grader", "Grade"}]
            for item in (pilot.fixture["resolve"]["product"], pilot.fixture["quote"]["items"][0]):
                item["name"] = pilot.rows[0]["title"] + " Ungraded"
        if options is not None:
            pilot.fixture["resolve"]["variants"][0]["options"] = options
            pilot.fixture["quote"]["items"][0]["variant_options"] = options
        status, research = pilot.research()
        assert status == 200 and research["offers"][0]["identity_status"] == "exact_match"
        if raw:
            assert research["offers"][0]["grade"]["kind"] == "raw"
        status, selection = pilot.select(research["offers"][0])
        assert status == 200
        status, choices = pilot.handoff(selection)
        assert status == 200 and choices["status"] == "variant_selection_required", choices
        if name is not None:
            item = pilot.fixture["resolve"]["product"] if stage == "resolve_name" else pilot.fixture["quote"]["items"][0]
            item["name"] = name
        pilot.provider_paths.clear()
        status, handoff = pilot.handoff(selection, variant_key="fixture-card")
        actual = "quote_ready_for_review" if handoff.get("quote") else handoff.get("quote_status")
        assert status == 200 and actual == expected, (label, handoff)
        paths = 3 if stage == "quote_name" or expected == "quote_ready_for_review" else 2
        assert len(pilot.provider_paths) == paths, (label, pilot.provider_paths)
        assert not handoff["purchasable"] and not handoff["order_created"] and handoff["purchase_action"] is None
        if handoff.get("quote"):
            quote = handoff["quote"]
            assert quote["listing"]["identity_status"] == "unverified_candidate"
            assert not quote["evidence"]["authenticity_verified"] and not quote["evidence"]["certificate_verified"]
            assert not quote["listing"]["grade"]["certificate_verified"]
            assert quote["listing"]["certificate"]["physical_authenticity"] == "not_verified"
            assert "source_printing_evidence" not in quote["listing"]
        assert not pilot.external_attempts
        return {"case": label, "stage": stage, "expected": expected, "raw": raw,
                "expected_provider_paths": paths, "research": research, "selection": selection, "choices": choices,
                "handoff": handoff, "provider_paths": list(pilot.provider_paths), "external_attempts": list(pilot.external_attempts)}


def printing_report():
    rows = [_printing_journey(label, options={label: wrong})
            for label, wrong in (("Edition", "Unlimited"), ("Language", "Japanese"), ("Finish", "Non-Holo"))]
    rows.append(_printing_journey("product_name", stage="resolve_name",
                name="Japanese BASE Charizard 4/102 holo Unlimited PSA 10"))
    rows.extend(_printing_journey(label, options=options) for label, options in REVIEW_OPTIONS)
    for stage in ("resolve_name", "quote_name"):
        rows.extend(_printing_journey(stage + "_" + label + "_with_suffix", stage=stage,
                    name=f"Charizard 4/102 {label}: {wrong} PSA 10") for label, wrong in NAME_ASSERTIONS)
    rows.extend((_printing_journey("raw_explicit_graded", raw=True, options={"condition": "Graded"}),
                 _printing_journey("raw_explicit_psa10", raw=True, options={"condition": "PSA 10"}),
                 _printing_journey("slab_explicit_raw", options={"condition": "Raw"}),
                 _printing_journey("raw_explicit_not_raw", raw=True, options={"condition": "Not Raw"})))
    return {"evidence_mode": "synthetic_offline", "cases": rows, "external_network_calls": 0}


def compatible_raw_report():
    rows = [_printing_journey("raw_positive_ungraded", raw=True, options={"condition": "Ungraded"}, expected="quote_ready_for_review"),
            _printing_journey("raw_compatible_not_graded_option", raw=True, options={"condition": "not graded"}, expected="quote_ready_for_review")]
    for stage in ("resolve_name", "quote_name"):
        for label, suffix in (("not_graded", "not graded"), ("psa_ready", "PSA ready")):
            rows.append(_printing_journey("raw_compatible_" + label + "_" + stage, raw=True, stage=stage,
                        name="English BASE Charizard 4/102 holo 1st edition - " + suffix, expected="quote_ready_for_review"))
    return {"evidence_mode": "synthetic_offline", "cases": rows, "external_network_calls": 0}


class PrintingHTTPJourneyTests(unittest.TestCase):
    def test_exact_http_journey_rejects_original_and_fresh_review_cases(self):
        report = printing_report()
        self.assertEqual(len(report["cases"]), 33)
        self.assertEqual(sum(row["stage"] == "quote_name" for row in report["cases"]), 4)

    def test_native_raw_compatible_negative_and_readiness_wording_still_quotes(self):
        self.assertEqual(len(compatible_raw_report()["cases"]), 6)

    def test_slab_positive_control_from_fresh_review(self):
        row = _printing_journey("slab_positive_correct_grade", options={"Grade": "10", "Language": "en"}, expected="quote_ready_for_review")
        self.assertIsNotNone(row["handoff"]["quote"])


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

    def test_common_contextual_key_aliases_and_boolean_exclusions(self):
        for _, options in REVIEW_OPTIONS:
            with self.subTest(options=options):
                self.options(options)
                with self.assertRaises(BNSRefusal) as raised:
                    self.fx.quote()
                self.assertEqual(raised.exception.code, "product_mismatch")
        for options in ({"First Edition": "Yes", "Foil": "true"}, {"Holographic": "1"},
                        {"CardLanguage": "en"}, {"card_language": "English"}, {"card-language": "EN"},
                        {"language_code": "en"}, {"SetName": "BASE"}, {"Collector No.": "173"},
                        {"CollectorNo": "173/165"}, {"First Edition": "not sure"},
                        {"First Edition": "no preference"}, {"Holographic": "no preference"},
                        {"Set Name": "unknown"}, {"Set Code": "not sure"}, {"SetName": "not provided"},
                        {"preferred_language_notes": "ja"}, {"LanguageNotes": "ja"}):
            with self.subTest(options=options):
                self.options(options)
                self.assert_unverified(self.fx.quote())
        self.options({"Edition": "not_applicable"})
        with self.assertRaises(BNSRefusal) as raised:
            self.fx.quote()
        self.assertEqual(raised.exception.code, "product_mismatch")

    def test_boolean_exclusions_respect_known_compatible_and_unknown_dimensions(self):
        claims = self.fx.offer["source_printing_evidence"]["claims"]
        for edition in ("unlimited", "standard", None):
            claims["edition"] = edition
            for finish in ("normal", None):
                claims["finish"] = finish
                for options in ({"First Edition": "No", "Foil": "No"}, {"Holographic": "False"},
                                {"Edition": "not first edition"}, {"Finish": "No Foil"}):
                    with self.subTest(edition=edition, finish=finish, options=options):
                        self.options(options)
                        self.assert_unverified(self.fx.quote())
        for finish in ("holo", "reverse", "reverse_masterball", "cosmos_holo", None):
            claims["finish"] = finish
            self.options({"Foil": "Yes"})
            self.assert_unverified(self.fx.quote())
        claims["language"] = "ja"
        self.options({"Language": "not English"})
        self.assert_unverified(self.fx.quote())

    def test_labelled_prose_consumes_bounded_value_and_checks_suffix_independently(self):
        for stage in ("resolve", "quote"):
            for field, wrong in NAME_ASSERTIONS:
                with self.subTest(stage=stage, field=field):
                    original = copy.deepcopy(self.fx.fixture)
                    item = self.fx.fixture["resolve"]["product"] if stage == "resolve" else self.fx.fixture["quote"]["items"][0]
                    item["name"] = f"Pikachu 173/165 {field}: {wrong} PSA 10"
                    with self.assertRaises(BNSRefusal) as raised:
                        self.fx.quote()
                    self.assertEqual(raised.exception.code, "product_mismatch")
                    self.fx.fixture = original
            for name in ("Language: en PSA 10", "Finish: holo (PSA 10)", "Edition: first edition, PSA 10",
                         "Set: BASE; PSA 10", "Collector No.: 173 PSA 10", "Language: jaPSA10",
                         "Finish: normality PSA 10", "Edition: standardized PSA 10"):
                with self.subTest(stage=stage, name=name):
                    original = copy.deepcopy(self.fx.fixture)
                    item = self.fx.fixture["resolve"]["product"] if stage == "resolve" else self.fx.fixture["quote"]["items"][0]
                    item["name"] = "Pikachu 173/165 " + name
                    self.assert_unverified(self.fx.quote())
                    self.fx.fixture = original
        self.options({"Language": "English Japanese"})
        with self.assertRaises(BNSRefusal):
            self.fx.quote()

    def test_partial_collector_number_compares_only_explicit_parts(self):
        for value in ("173", "0173", "173/165"):
            self.options({"Collector No.": value})
            self.assert_unverified(self.fx.quote())
        for value in ("174", "173/164"):
            self.options({"Collector No.": value})
            with self.assertRaises(BNSRefusal) as raised:
                self.fx.quote()
            self.assertEqual(raised.exception.code, "product_mismatch")

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
                             ("claims", {"language": "en"}), ("evidence_ref", ""),
                             ("observed_at", (self.fx.instant - timedelta(seconds=301)).isoformat()),
                             ("observed_at", (self.fx.instant + timedelta(seconds=1)).isoformat())):
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
        for mutate in (lambda offer: offer["source_printing_evidence"]["claims"].update(language="ja"),
                       lambda offer: offer["source_printing_evidence"]["claims"].update(edition="unlimited"),
                       lambda offer: offer.pop("source_printing_evidence"),
                       lambda offer: offer["source_printing_evidence"].update(evidence_ref="offline:other")):
            changed_offer = copy.deepcopy(self.fx.offer)
            mutate(changed_offer)
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
        for raw in ("Raw", "Ungraded", "not graded", "未鑑定", "鑑定前"):
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

    def test_raw_marketing_and_negation_are_scoped_to_their_own_grade_claim(self):
        raw = copy.deepcopy(self.fx.offer)
        raw["grade"].update(kind="raw", company=None, value=None)
        for name in ("not graded", "non-graded", "PSA ready", "PSA-ready", "not PSA graded", "Ungraded", "Pikachu"):
            with self.subTest(name=name):
                preview._identity(name, raw, fixtures.CARD)
        for name in ("PSA ready; PSA 10", "not graded; slabbed", "Ungraded; condition:Graded", "Not Raw", "PSA10"):
            with self.subTest(name=name):
                with self.assertRaises(BNSRefusal) as raised:
                    preview._identity(name, raw, fixtures.CARD)
                self.assertEqual(raised.exception.code, "product_mismatch")
        slab = copy.deepcopy(self.fx.offer)
        slab["grade"].update(company="BGS", value="10")
        preview._identity("not PSA graded; BGS 10", slab, fixtures.CARD)


if __name__ == "__main__":
    if sys.argv[1:] == ["--report"]:
        print(json.dumps(printing_report(), ensure_ascii=False))
    else:
        unittest.main()
