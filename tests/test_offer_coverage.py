"""Synthetic offline evidence only; none of these are inventory or approvals."""
import copy
import socket
import unittest
from unittest.mock import patch

from pokemon_index.offer_coverage import build_scorecard

NOW = "2026-10-28T14:00:00Z"
AT = "2026-10-28T13:59:00Z"
FRESH = "2026-10-28T14:04:00Z"


def offer(number="12345678901", seller="seller-a", price=10000):
    url = "https://jp.mercari.com/item/m" + number
    evidence = "fixture-capture:" + number
    claims = {"language":"ja", "set_code":"SV2A", "collector_number":"173/165", "finish":"holo", "edition":"standard"}
    return {"source":"mercari", "native_id":"m"+number, "scope":"listing", "url":url,
            "observed_at":AT,"fresh_until":FRESH,"evidence_ref":evidence,
            "source_provenance":{"source":"mercari","method":"crawl","observed_at":AT},
            "availability":"available","listing_status":"on_sale","listing_quantity":1,
            "price_minor":price,"currency":"JPY","seller_condition":"Mint seller claim",
            "grade":{"kind":"slab","company":"PSA","value":"10","review_required":False,
                     "certificate_verified":False,"special_label":None},
            "certificate_number_claim":"12345678",
            "certificate":{"number_claim":"12345678","status":"not_checked","physical_authenticity":"not_verified"},
            "seller":{"id":seller,"display_name":seller,"url":None,"evidence_ref":evidence,"observed_at":AT,"reputation":None},
            "identity_evidence":{"status":"candidate","claims":claims,"conflicting_fields":[],"listing_url":url,
                                 "evidence_ref":evidence,"observed_at":AT,"basis":"exact_listing_structured","authenticity_verified":False},
            "listing_photos":[{"url":"https://static.mercdn.net/item/detail/orig/photos/m"+number+"_1.jpg",
                               "role":"listing_photo","listing_url":url,"evidence_ref":evidence,"observed_at":AT}]}


def photo_audit(item, view="front"):
    p=item["listing_photos"][0]
    return {"source":item["source"],"native_id":item["native_id"],"listing_url":item["url"],
            "offer_observed_at":item["observed_at"],"photo_url":p["url"],"evidence_ref":p["evidence_ref"],
            "observed_at":p["observed_at"],"sha256":"a"*64,"rights_reference":"offline-fixture-grant",
            "expires_at":FRESH,"view":view,"depiction":"actual_copy","authorized":True}


class CoverageTests(unittest.TestCase):
    def test_missing_is_unknown_and_empty_is_zero(self):
        missing=build_scorecard(now=NOW)
        self.assertEqual(missing["inventory_status"],"not_ingested")
        self.assertTrue(all(v is None for v in missing["metrics"].values()))
        empty=build_scorecard([],now=NOW,photo_audits=[])
        self.assertEqual(empty["inventory_status"],"evaluated_empty")
        self.assertTrue(all(v==0 for v in empty["metrics"].values()))

    def test_two_sellers_same_platform_form_claim_group_only(self):
        a,b=offer(),offer("12345678902","seller-b",9000)
        result=build_scorecard([a,b],now=NOW)
        self.assertEqual(result["metrics"]["distinct_listings"],2)
        self.assertEqual(result["metrics"]["unique_sellers"],2)
        self.assertEqual(result["metrics"]["multi_seller_claim_groups"],1)
        group=result["groups"][0]
        self.assertEqual(group["grade_claim"]["value"],"10")
        self.assertEqual([x["price_minor"] for x in group["listings"]],[9000,10000])
        self.assertFalse(group["catalog_match_approved"])
        self.assertFalse(result["source_access_authorized"])
        self.assertFalse(result["authenticity_verified"])
        self.assertIsNone(result["metrics"]["authorized_copy_photo_listings"])

    def test_same_seller_multiple_listings_not_multiple_sellers(self):
        result=build_scorecard([offer(),offer("12345678902")],now=NOW)
        self.assertEqual(result["metrics"]["claimed_product_price_groups"],1)
        self.assertEqual(result["metrics"]["unique_sellers"],1)
        self.assertEqual(result["metrics"]["multi_seller_claim_groups"],0)

    def test_identity_claim_from_another_capture_cannot_form_a_group(self):
        a, b = offer(), offer("12345678902", "seller-b")
        b["identity_evidence"]["evidence_ref"] = "another-capture"
        result = build_scorecard([a, b], now=NOW)
        self.assertEqual(result["groups"], [])
        self.assertIn("identity_claims_incomplete_or_conflicting", result["listing_gaps"][1]["gaps"])

    def test_far_future_expiry_cannot_make_old_inventory_current(self):
        a, b = offer(), offer("12345678902", "seller-b")
        for item in (a, b):
            item["fresh_until"] = "2099-01-01T00:00:00Z"
        result = build_scorecard([a, b], now=NOW)
        self.assertEqual(result["metrics"]["current_active_listings"], 0)
        self.assertEqual(result["groups"], [])
        self.assertIn("freshness_window_exceeds_report_limit", result["listing_gaps"][0]["gaps"])
        for value in (0, 901, True):
            with self.assertRaises(ValueError):
                build_scorecard([a], now=NOW, freshness_seconds=value)

    def test_grade_raw_finish_currency_and_condition_never_pool(self):
        a=offer()
        for mutate in [lambda o:o["grade"].update(value="9"),lambda o:o["grade"].update(company="CGC"),
                       lambda o:o["grade"].update(kind="raw",company=None,value=None),
                       lambda o:o["identity_evidence"]["claims"].update(finish="reverse"),
                       lambda o:o.update(currency="USD"),lambda o:o.update(seller_condition="Played")]:
            with self.subTest(mutate=mutate):
                b=offer("12345678902","seller-b");mutate(b)
                self.assertEqual(build_scorecard([a,b],now=NOW)["groups"],[])

    def test_unknown_or_conflicting_identity_and_grade_excluded(self):
        for mutate in [lambda o:o["identity_evidence"]["claims"].update(edition=None),
                       lambda o:o["identity_evidence"].update(conflicting_fields=["finish"]),
                       lambda o:o["identity_evidence"].update(basis="title_guess"),
                       lambda o:o["grade"].update(review_required=True),
                       lambda o:o["grade"].update(special_label="black_label"),
                       lambda o:o["grade"].update(value="0"),
                       lambda o:o["grade"].update(value="9.5"),
                       lambda o:o["grade"].update(company="BGS",value="9.5"),
                       lambda o:o["grade"].update(certificate_verified=True),
                       lambda o:o.update(listing_quantity=None), lambda o:o.update(listing_quantity=2)]:
            b=offer("12345678902","seller-b");mutate(b)
            self.assertEqual(build_scorecard([offer(),b],now=NOW)["groups"],[])

    def test_claim_presence_is_distinct_from_reviewed_comparison_grade(self):
        a=offer();a["grade"].update(company="BGS",value="9.5")
        result=build_scorecard([a],now=NOW)
        self.assertEqual(result["metrics"]["listings_with_grade_claim"],1)
        self.assertEqual(result["metrics"]["listings_with_reviewed_comparison_grade"],0)

    def test_sold_unknown_stale_and_conflicting_stock_excluded(self):
        for change in [{"availability":"sold_out","listing_status":"sold_out"},
                       {"availability":"unknown"},{"fresh_until":NOW},
                       {"listing_status":"sold_out"}]:
            b=offer("12345678902","seller-b");b.update(change)
            result=build_scorecard([offer(),b],now=NOW)
            self.assertEqual(result["metrics"]["current_active_listings"],1)
            self.assertEqual(result["groups"],[])

    def test_newest_observation_wins_and_conflict_does_not_inflate(self):
        a=offer(); newer=copy.deepcopy(a);newer.update(observed_at="2026-10-28T13:59:30Z",price_minor=9000)
        newer["seller"]["observed_at"]=newer["observed_at"]
        same_time=copy.deepcopy(a);same_time["price_minor"]=1
        result=build_scorecard([a,a,newer],now=NOW)
        self.assertEqual(result["metrics"]["distinct_listings"],1)
        conflict=build_scorecard([a,same_time],now=NOW)
        self.assertEqual(conflict["metrics"]["distinct_listings"],0)
        self.assertIn("conflicting_listing_observations",conflict["listing_gaps"][0]["gaps"])

    def test_photo_reference_is_not_authorized_actual_copy(self):
        a=offer()
        refs=build_scorecard([a],now=NOW)
        self.assertEqual(refs["metrics"]["bound_photo_reference_listings"],1)
        self.assertIsNone(refs["metrics"]["authorized_copy_photo_listings"])
        self.assertEqual(build_scorecard([a],now=NOW,photo_audits=[])["metrics"]["authorized_copy_photo_listings"],0)
        for mutate in [lambda p:p.update(depiction="stock"),lambda p:p.update(authorized=False),
                       lambda p:p.update(native_id="m999"),lambda p:p.update(evidence_ref="wrong"),
                       lambda p:p.update(expires_at=NOW),lambda p:p.update(sha256="bad"),
                       lambda p:p.update(revoked=True),lambda p:p.update(revoked_at=AT)]:
            audit=photo_audit(a);mutate(audit)
            self.assertEqual(build_scorecard([a],now=NOW,photo_audits=[audit])["metrics"]["authorized_copy_photo_listings"],0)

    def test_front_back_needs_two_explicit_bound_photos(self):
        a=offer(); audit=photo_audit(a)
        result=build_scorecard([a],now=NOW,photo_audits=[audit])
        self.assertEqual(result["metrics"]["authorized_copy_photo_listings"],1)
        self.assertEqual(result["metrics"]["front_back_photo_listings"],0)
        back=copy.deepcopy(a["listing_photos"][0]);back["url"]=back["url"].replace("_1.jpg","_2.jpg")
        a["listing_photos"].append(back)
        second=copy.deepcopy(audit);second.update(photo_url=back["url"],view="back",sha256="b"*64)
        self.assertEqual(build_scorecard([a],now=NOW,photo_audits=[audit,second])["metrics"]["front_back_photo_listings"],1)

    def test_conflicting_or_revoked_photo_audit_cannot_be_ignored(self):
        a=offer();audit=photo_audit(a)
        for update in [{"view":"back"},{"authorized":False},{"sha256":"b"*64}]:
            other=copy.deepcopy(audit);other.update(update)
            result=build_scorecard([a],now=NOW,photo_audits=[audit,other])
            self.assertEqual(result["metrics"]["authorized_copy_photo_listings"],0)
            self.assertEqual(result["metrics"]["front_back_photo_listings"],0)

    def test_same_image_bytes_cannot_establish_front_and_back(self):
        a=offer();front=photo_audit(a)
        back=copy.deepcopy(a["listing_photos"][0]);back["url"]=back["url"].replace("_1.jpg","_2.jpg")
        a["listing_photos"].append(back)
        review=copy.deepcopy(front);review.update(photo_url=back["url"],view="back")
        result=build_scorecard([a],now=NOW,photo_audits=[front,review])
        self.assertEqual(result["metrics"]["front_back_photo_listings"],0)

    def test_complete_multi_seller_group_requires_photo_evidence_for_both(self):
        a,b=offer(),offer("12345678902","seller-b")
        result=build_scorecard([a,b],now=NOW,photo_audits=[photo_audit(a)])
        self.assertEqual(result["metrics"]["photo_supported_multi_seller_claim_groups"],0)
        result=build_scorecard([a,b],now=NOW,photo_audits=[photo_audit(a),photo_audit(b)])
        self.assertEqual(result["metrics"]["photo_supported_multi_seller_claim_groups"],1)
        self.assertEqual(result["metrics"]["front_back_supported_multi_seller_claim_groups"],0)

    def test_invalid_source_method_cannot_form_comparison_group(self):
        a,b=offer(),offer("12345678902","seller-b")
        b["source_provenance"]={"source":"ebay_us","method":"api","observed_at":AT}
        result=build_scorecard([a,b],now=NOW)
        self.assertEqual(result["groups"],[])
        self.assertEqual(result["source_method_statuses"],{"crawl":1,"invalid":1})
        b.pop("source_provenance")
        result=build_scorecard([a,b],now=NOW)
        self.assertEqual(result["groups"],[])
        self.assertIn("source_method_missing",result["listing_gaps"][1]["gaps"])

    def test_stock_or_wrong_listing_photo_never_counted(self):
        for mutate in [lambda o:o["listing_photos"][0].update(role="catalog_art"),
                       lambda o:o["listing_photos"][0].update(listing_url="https://jp.mercari.com/item/m999"),
                       lambda o:o["listing_photos"][0].update(evidence_ref="other-capture")]:
            a=offer();mutate(a)
            self.assertEqual(build_scorecard([a],now=NOW)["metrics"]["bound_photo_reference_listings"],0)

    def test_certificate_claim_never_becomes_check_or_authenticity(self):
        a=offer();a["certificate"]["status"]="verified"
        r=build_scorecard([offer(),a],now=NOW)
        self.assertEqual(r["groups"],[])
        a["native_id"]="m12345678902";a["url"]="https://jp.mercari.com/item/m12345678902"
        r=build_scorecard([a],now=NOW)
        self.assertEqual(r["certificate_statuses"],{"unsupported_verification_claim":1})
        self.assertFalse(r["authenticity_verified"])

    def test_untrusted_url_bad_price_and_seller_do_not_inflate(self):
        a=offer();a["url"]="http://169.254.169.254/latest/meta-data"
        self.assertEqual(build_scorecard([a],now=NOW)["metrics"]["distinct_listings"],0)
        for bad in [True,-1,1.5,"100"]:
            a=offer();a["price_minor"]=bad
            self.assertEqual(build_scorecard([a],now=NOW)["metrics"]["listings_with_price"],0)
        a=offer();a["seller"]["id"]=None;a["seller"]["url"]=None
        self.assertEqual(build_scorecard([a],now=NOW)["metrics"]["unique_sellers"],0)

    def test_synthetic_observations_do_not_count_as_real_coverage(self):
        r=build_scorecard([offer(),offer("12345678902","seller-b")],now=NOW,input_kind="synthetic_fixture")
        self.assertEqual(r["observations_evaluated"],2)
        self.assertEqual(r["metrics"]["distinct_listings"],0)
        self.assertEqual(r["metrics"]["current_active_listings"],0)
        self.assertEqual(r["metrics"]["unique_sellers"],0)
        self.assertEqual(r["groups"],[])

    def test_report_does_not_mutate_or_fetch(self):
        a=offer();before=copy.deepcopy(a)
        with patch.object(socket,"socket",side_effect=AssertionError("network forbidden")):
            result=build_scorecard([a],now=NOW)
        self.assertEqual(a,before)
        self.assertFalse(result["orders_enabled"])
        self.assertFalse(result["payments_enabled"])


if __name__ == "__main__":
    unittest.main()
