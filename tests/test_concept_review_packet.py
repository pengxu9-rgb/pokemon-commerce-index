import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core
from scripts import concept_review_packet


class ConceptReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        values = [
            ("ja", "J1", "001/010", "フヨウ", "Trainer", "Supporter", "Artist A"),
            ("en", "E1", "002/010", "Phoebe", "Trainer", "Supporter", "Artist A"),
            ("en", "E1", "003/010", "Wrong Name", "Trainer", "Supporter", "Artist A"),
            ("ja", "J1", "004/010", "ミストエネルギー", "Energy", "Special", "Artist B"),
            ("en", "E1", "005/010", "Mist Energy", "Energy", "Special", "Artist C"),
        ]
        for language, set_code, number, name, category, subtype, artist in values:
            card_id = f"{language}:{set_code}:{number}:normal"
            core.import_cards(self.db, [dict(
                language=language, set_code=set_code, collector_number=number,
                variant="normal", name=name,
                provenance=f"tcgdex:{'a'*40}:data/{language}/{set_code}/{number.split('/')[0]}.ts:sha256:{'b'*64}",
                rights_reference="https://example.invalid/license", display_allowed=False)])
            core.import_card_classifications(self.db, [dict(
                card_id=card_id, category=category, subtype=subtype,
                provenance="fixture", rights_reference="fixture")])
            core.import_card_facets(self.db, [dict(
                card_id=card_id, facet_type="illustrator", value=artist,
                provenance="fixture", rights_reference="fixture")])

    def tearDown(self):
        self.db.close()

    def test_packet_excludes_blind_names_and_energy_hint_uses_card_sources(self):
        packet, audit = concept_review_packet.build(self.db, set(), 1, 1)
        self.assertEqual(len(packet), 3)
        self.assertEqual(audit["by_category"]["Energy"]["candidate_rows"], 1)
        energy = next(row for row in packet if row["category"] == "Energy")
        self.assertEqual(energy["name_en"], "Mist Energy")
        self.assertEqual(energy["proposal_signal"], "editorial_name_hint")
        self.assertTrue(energy["source_ja"].startswith("https://github.com/tcgdex/cards-database/blob/"))
        hidden, _ = concept_review_packet.build(self.db, {"ja:J1:001/010:normal"}, 1, 1)
        self.assertTrue(all(row["name_ja"] != "フヨウ" for row in hidden))

    def test_approval_requires_human_attestation_and_preserves_evidence(self):
        packet, _ = concept_review_packet.build(self.db, set(), 1, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            concept_review_packet.write_sheet(path, packet)
            imports, audit = concept_review_packet.compile_sheet(packet, path)
            self.assertEqual(imports, [])
            self.assertEqual(audit["decisions"], {"pending": 2})
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0].update(decision="approve", reviewer="real-reviewer",
                           reviewed_at="2026-09-24T01:00:00Z",
                           ja_identity_checked="yes", en_identity_checked="yes",
                           translation_checked="yes", evidence_note="Compared two card sources")
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            imports, _ = concept_review_packet.compile_sheet(packet, path)
            self.assertEqual(len(imports), 1)
            self.assertEqual(imports[0]["status"], "approved")
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM bilingual_concept_revision").fetchone()[0], 0)
            rows[0]["source_ja"] = "https://example.invalid/changed"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "frozen evidence changed"):
                concept_review_packet.compile_sheet(packet, path)

    def test_rejection_requires_attributed_reason(self):
        packet, _ = concept_review_packet.build(self.db, set(), 1, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            concept_review_packet.write_sheet(path, packet)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["decision"] = "reject"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "review decision requires"):
                concept_review_packet.compile_sheet(packet, path)


if __name__ == "__main__":
    unittest.main()
