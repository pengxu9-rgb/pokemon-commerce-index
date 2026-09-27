"""A photo-gated listing is priceable only for its approved observation."""

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from pokemon_index import core, offer_comparison


class VisualResolutionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.register_source(self.db, {
            "source": "ebay_us", "rights_reference": "synthetic fixture",
            "ingest_allowed": True, "display_allowed": True,
            "media_ai_allowed": True, "photo_resolution_required": False,
            "retention_days": 1, "listing_ttl_hours": 6,
        })
        self.assertEqual(self.db.execute(
            "SELECT photo_resolution_required FROM source_policy WHERE source='ebay_us'"
        ).fetchone()[0], 1)
        core.import_cards(self.db, [{
            "language": "en", "set_code": "SV1", "collector_number": "001/100",
            "variant": "holo", "name": "Pikachu", "provenance": "fixture",
            "rights_reference": "fixture", "display_allowed": True,
        }])
        self.card = "en:SV1:001/100:holo"
        self.at = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        self.later = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self._observation(self.at)

    def tearDown(self):
        self.db.close()

    def _observation(self, at):
        core.import_observations(self.db, [{
            "source": "ebay_us", "native_id": "v1|123|0",
            "title": "Pokemon Pikachu SV1 001/100 Holo",
            "url": "https://www.ebay.com/itm/123", "observed_at": at,
            "status": "on_sale", "price_minor": 1200, "currency": "USD",
            "card_id": self.card, "evidence_ref": "fixture:observation",
        }])

    def _media_and_reviews(self, at, finish="holo"):
        offer_comparison.import_media(self.db, [{
            "source": "ebay_us", "native_id": "v1|123|0", "observed_at": at,
            "front_ref": "https://example.invalid/front", "front_sha256": "a" * 64,
            "back_ref": "https://example.invalid/back", "back_sha256": "b" * 64,
            "rights_reference": "synthetic photo fixture",
        }])
        rows = []
        for family, prefix in (("google", "vertex"), ("openai", "openai")):
            rows.append({
                "review_id": f"{at}:{family}", "source": "ebay_us",
                "native_id": "v1|123|0", "observed_at": at, "card_id": self.card,
                "model_family": family, "model_version": family + "-fixture",
                "reviewed_at": core.utcnow(), "front_sha256": "a" * 64,
                "back_sha256": "b" * 64, "identity_decision": "match",
                "observed_finish": finish, "finish_decision": "match",
                "condition_bucket": "near_mint", "condition_decision": "assessed",
                "evidence_ref": prefix + ":response-sha256:" + "c" * 64,
                "rationale": "Synthetic identity, finish, front and back check",
            })
        offer_comparison.import_visual_reviews(self.db, rows)

    def test_approval_is_snapshot_bound_and_manual_override_is_blocked(self):
        unit = self.card + "|RAW|raw|near_mint"
        self.assertEqual(core.resolve(self.db, {"source": "ebay_us", "title": "Pikachu",
                                                "card_id": self.card})[0], None)
        with self.assertRaisesRegex(ValueError, "snapshot-bound"):
            core.override_resolution(self.db, "ebay_us", "v1|123|0", unit,
                                     "operator", "fixture")
        with self.assertRaisesRegex(ValueError, "not ready"):
            offer_comparison.approve_visual_resolution(
                self.db, "ebay_us", "v1|123|0", self.at, self.card)
        self._media_and_reviews(self.at)
        result = offer_comparison.approve_visual_resolution(
            self.db, "ebay_us", "v1|123|0", self.at, self.card)
        self.assertEqual(result["unit_id"], unit)
        self.assertEqual(len(core.offers(self.db, self.card)), 1)
        self.assertEqual(offer_comparison.approve_visual_resolution(
            self.db, "ebay_us", "v1|123|0", self.at, self.card)["status"],
            "already_approved")
        self._observation(self.later)
        self.assertEqual(core.offers(self.db, self.card), [])
        with self.assertRaisesRegex(ValueError, "not ready"):
            offer_comparison.approve_visual_resolution(
                self.db, "ebay_us", "v1|123|0", self.later, self.card)
        self._media_and_reviews(self.later)
        offer_comparison.approve_visual_resolution(
            self.db, "ebay_us", "v1|123|0", self.later, self.card)
        self.assertEqual(len(core.offers(self.db, self.card)), 1)

    def test_wrong_finish_and_stale_snapshot_cannot_be_approved(self):
        self._media_and_reviews(self.at, finish="normal")
        with self.assertRaisesRegex(ValueError, "does not match catalog printing"):
            offer_comparison.approve_visual_resolution(
                self.db, "ebay_us", "v1|123|0", self.at, self.card)
        self._observation(self.later)
        with self.assertRaisesRegex(ValueError, "latest on-sale"):
            offer_comparison.approve_visual_resolution(
                self.db, "ebay_us", "v1|123|0", self.at, self.card)

    def test_expired_snapshot_approval_is_purged_with_observation(self):
        self._media_and_reviews(self.at)
        offer_comparison.approve_visual_resolution(
            self.db, "ebay_us", "v1|123|0", self.at, self.card)
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        removed = core.purge_expired(self.db, future)
        self.assertEqual(removed["visual_resolution_approval"], 1)
        self.assertEqual(removed["observation"], 1)


if __name__ == "__main__":
    unittest.main()
