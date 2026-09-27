import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.official_jp_image_evidence import OfficialJPImageIndex, _valid_official_url


class _ImageResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, _):
        return b"\xff\xd8\xffcard-image"


class OfficialImageEvidenceTests(unittest.TestCase):
    def test_official_legend_image_path_is_supported(self):
        self.assertTrue(_valid_official_url(
            "https://www.pokemon-card.com/assets/images/card_images/legend/M6a/050728_CARD.jpg",
            image=True))
        self.assertFalse(_valid_official_url(
            "https://other.example/assets/images/card_images/legend/M6a/050728_CARD.jpg",
            image=True))

    def test_exact_set_number_total_and_name_required_before_image_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "data_jp" / "S1" / "123.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "name": "カード名", "set_name": "S1", "number": "007",
                "set_total": "100", "url": "https://www.pokemon-card.com/card-search/details.php/card/123",
                "img": "https://www.pokemon-card.com/assets/images/card_images/large/S1/000123_CARD.jpg",
            }), encoding="utf-8")
            index = OfficialJPImageIndex.__new__(OfficialJPImageIndex)
            index.repo = root
            index.revision = "a" * 40
            index.paths = {("S1", "007"): [path]}
            with patch("urllib.request.urlopen", return_value=_ImageResponse()) as fetch:
                image, evidence = index.get("ja:S1:007/100:normal", "カード名")
                self.assertIsNotNone(image)
                self.assertEqual(evidence["status"], "included")
                self.assertEqual(evidence["mime_type"], "image/jpeg")
                fetch.assert_called_once()
            with patch("urllib.request.urlopen") as fetch:
                image, evidence = index.get("ja:S1:007/101:normal", "カード名")
                self.assertIsNone(image)
                self.assertEqual(evidence["status"], "no_exact_official_record")
                fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
