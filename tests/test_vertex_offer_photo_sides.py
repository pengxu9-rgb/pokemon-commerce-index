import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import core
from scripts.vertex_offer_photo_sides import _parse, run


def response(front=1, back=0):
    return {"modelVersion": "gemini-3.8-flash", "candidates": [{
        "finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
            "front_index": front, "back_index": back,
            "rationale": "visible front text and standard card back",
        })}]}}]}


class PhotoSideTests(unittest.TestCase):
    def test_invalid_or_same_side_abstains(self):
        with self.assertRaisesRegex(ValueError, "cannot prove both"):
            _parse(response(0, 0), 2)
        with self.assertRaisesRegex(ValueError, "invalid"):
            _parse(response(3, 0), 2)
        self.assertIsNone(_parse(response(None, None), 2)["front_index"])

    def test_ai_routes_unordered_photos_and_keeps_hash_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            back, front = root / "back.jpg", root / "front.jpg"
            back.write_bytes(b"\xff\xd8\xffback")
            front.write_bytes(b"\xff\xd8\xfffront")
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            core.init_db(db)
            core.register_source(db, {"source": "fixture", "rights_reference": "fixture",
                                      "ingest_allowed": True, "display_allowed": True,
                                      "media_ai_allowed": True, "retention_days": 30,
                                      "listing_ttl_hours": 24})
            core.import_cards(db, [{"language": "ja", "set_code": "S1",
                                    "collector_number": "001/100", "name": "カード",
                                    "provenance": "fixture", "rights_reference": "fixture",
                                    "display_allowed": True}])
            core.import_observations(db, [{"source": "fixture", "native_id": "x1",
                                           "title": "カード", "url": "https://example.invalid/x1",
                                           "observed_at": "2026-09-25T09:00:00Z",
                                           "status": "on_sale", "price_minor": 1000,
                                           "currency": "JPY", "evidence_ref": "fixture"}])
            item = {"source": "fixture", "native_id": "x1",
                    "observed_at": "2026-09-25T09:00:00Z",
                    "card_id": "ja:S1:001/100:standard",
                    "rights_reference": "fixture permits AI", "photos": [
                        {"ref": "https://example.invalid/back", "path": str(back)},
                        {"ref": "https://example.invalid/front", "path": str(front)}]}
            with patch("scripts.vertex_offer_photo_sides.subprocess.check_output", return_value="token"), \
                    patch("scripts.vertex_offer_photo_sides._call_model", return_value=response()):
                media, review, audit = run(db, [item], "fixture-project", "global")
            self.assertEqual(media[0]["front_ref"], "https://example.invalid/front")
            self.assertEqual(media[0]["back_ref"], "https://example.invalid/back")
            self.assertEqual(review[0]["front_path"], str(front))
            self.assertTrue(audit[0]["evidence_ref"].startswith("vertex:response-sha256:"))
            db.close()


if __name__ == "__main__":
    unittest.main()
