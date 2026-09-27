"""No inferred source record may silently stand in for an exact card image."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_relationship_image_gaps import classify_jp
from scripts.official_jp_image_evidence import OfficialJPImageIndex


class ImageGapDiagnosisTests(unittest.TestCase):
    def test_total_conflict_is_not_an_exact_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "record.json"
            path.write_text(json.dumps({
                "name": "カード名", "set_name": "S1", "number": "007",
                "set_total": "054",
                "url": "https://www.pokemon-card.com/card-search/details.php/card/123",
                "img": "https://www.pokemon-card.com/assets/images/card_images/large/S1/000123_CARD.jpg",
            }), encoding="utf-8")
            source = OfficialJPImageIndex.__new__(OfficialJPImageIndex)
            source.paths = {("S1", "007"): [path]}
            result = classify_jp("ja:S1:007/056:normal", "カード名", source)
            self.assertEqual(result["cause"], "official_set_total_conflict")
            self.assertEqual(result["usable_exact_records"], 0)


if __name__ == "__main__":
    unittest.main()
