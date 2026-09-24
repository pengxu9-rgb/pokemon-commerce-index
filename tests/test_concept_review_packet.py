import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core
from scripts import concept_review_packet


class ConceptReviewPacketTests(unittest.TestCase):
    def test_existing_concept_table_gets_review_link_column(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE bilingual_concept_revision (
            concept_id TEXT, revision INTEGER, category TEXT, name_ja TEXT, name_en TEXT,
            source_ja TEXT, source_en TEXT, rights_reference TEXT, reviewer TEXT,
            reviewed_at TEXT, status TEXT, PRIMARY KEY(concept_id, revision))""")
        core.init_db(db)
        self.assertIn("review_event_id", {
            row["name"] for row in db.execute("PRAGMA table_info(bilingual_concept_revision)")})
        db.close()

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
            provenance = f"tcgdex:{'a'*40}:data/{language}/{set_code}/{number.split('/')[0]}.ts:sha256:{'b'*64}"
            core.import_cards(self.db, [dict(
                language=language, set_code=set_code, collector_number=number,
                variant="normal", name=name,
                provenance=provenance,
                rights_reference="https://example.invalid/license", display_allowed=False)])
            core.import_card_classifications(self.db, [dict(
                card_id=card_id, category=category, subtype=subtype,
                provenance=provenance, rights_reference="fixture")])
            core.import_card_facets(self.db, [dict(
                card_id=card_id, facet_type="illustrator", value=artist,
                provenance=provenance, rights_reference="fixture")])

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
            bundle, audit = concept_review_packet.compile_sheet(packet, path)
            self.assertEqual(bundle["concept_revisions"], [])
            self.assertEqual(audit["decisions"], {"pending": 2})
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0].update(decision="approve", reviewer="real-reviewer",
                           reviewed_at="2026-09-24T01:00:00Z",
                           ja_identity_checked="yes", en_identity_checked="yes",
                           translation_checked="yes", evidence_note="Compared two card sources",
                           extra_source_ja="https://example.invalid/official-ja")
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            bundle, _ = concept_review_packet.compile_sheet(packet, path)
            self.assertEqual(len(bundle["concept_revisions"]), 1)
            self.assertEqual(bundle["concept_revisions"][0]["status"], "approved")
            self.assertEqual(bundle["review_events"][0]["review"]["evidence_note"],
                             "Compared two card sources")
            self.assertEqual(bundle["review_events"][0]["review"]["extra_source_ja"],
                             "https://example.invalid/official-ja")
            self.assertEqual(core.import_concept_review_bundle(self.db, bundle),
                             {"review_events": 1, "concept_revisions": 1})
            self.assertEqual(core.import_concept_review_bundle(self.db, bundle),
                             {"review_events": 0, "concept_revisions": 0})
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM bilingual_concept_revision").fetchone()[0], 1)
            self.assertIn("Compared two card sources", self.db.execute(
                "SELECT record_json FROM concept_review_event").fetchone()[0])
            self.assertEqual(self.db.execute(
                "SELECT review_event_id FROM bilingual_concept_revision").fetchone()[0],
                bundle["review_events"][0]["event_id"])
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
            rows[0].update(reviewer="real-reviewer", reviewed_at="2026-09-24T01:00:00Z",
                           evidence_note="Effects and names describe different cards")
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            bundle, audit = concept_review_packet.compile_sheet(packet, path)
            self.assertEqual(audit["retained_review_events"], 1)
            self.assertEqual(bundle["concept_revisions"], [])
            self.assertEqual(core.import_concept_review_bundle(self.db, bundle),
                             {"review_events": 1, "concept_revisions": 0})
            self.assertEqual(self.db.execute(
                "SELECT decision FROM concept_review_event").fetchone()[0], "reject")

    def test_bundle_import_is_atomic_and_disabled_printing_can_supply_name_evidence(self):
        self.db.execute("UPDATE card SET match_eligible=0 WHERE card_id='en:E1:002/010:normal'")
        packet, _ = concept_review_packet.build(self.db, set(), 1, 0)
        phoebe = next(row for row in packet if row["name_en"] == "Phoebe")
        self.assertEqual(phoebe["en_match_eligible"], 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            concept_review_packet.write_sheet(path, packet)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row.update(decision="approve" if row["name_en"] == "Phoebe" else "reject",
                           reviewer="real-reviewer", reviewed_at="2026-09-24T01:00:00Z",
                           evidence_note="Card-specific source comparison")
                if row["decision"] == "approve":
                    row.update(ja_identity_checked="yes", en_identity_checked="yes",
                               translation_checked="yes")
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=concept_review_packet.SHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            bundle, _ = concept_review_packet.compile_sheet(packet, path)
            changed_source = json.loads(json.dumps(bundle))
            event = next(row for row in changed_source["review_events"]
                         if row["review"]["decision"] == "approve")
            event["proposal"]["source_snapshot"]["frozen"]["name_en"] = "Tampered Name"
            event["event_id"] = hashlib.sha256(json.dumps({
                key: value for key, value in event.items() if key != "event_id"
            }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            changed_source["concept_revisions"][0]["review_event_id"] = event["event_id"]
            with self.assertRaisesRegex(ValueError, "source snapshot mismatch"):
                core.import_concept_review_bundle(self.db, changed_source)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM concept_review_event").fetchone()[0], 0)
            bundle["concept_revisions"][0]["name_en"] = "Tampered Name"
            with self.assertRaisesRegex(ValueError, "does not match retained"):
                core.import_concept_review_bundle(self.db, bundle)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM concept_review_event").fetchone()[0], 0)

    def test_v2_pool_keeps_old_candidate_and_adds_disabled_gallery_name(self):
        rows = [
            ("ja", "J2", "001/010", "ルリナ", "Artist Wrong", True),
            ("ja", "J2", "002/010", "ルリナ", "Artist Right", True),
            ("en", "E2", "003/010", "Unrelated Supporter", "Artist Wrong", True),
            ("en", "E2", "004/010", "Nessa", "Artist Right", False),
        ]
        for language, set_code, number, name, artist, match_eligible in rows:
            card_id = f"{language}:{set_code}:{number}:normal"
            provenance = f"tcgdex:{'a'*40}:data/{language}/{set_code}/{number.split('/')[0]}.ts:sha256:{'b'*64}"
            core.import_cards(self.db, [dict(
                language=language, set_code=set_code, collector_number=number,
                variant="normal", name=name, provenance=provenance,
                rights_reference="https://example.invalid/license",
                display_allowed=False, match_eligible=match_eligible)])
            core.import_card_classifications(self.db, [dict(
                card_id=card_id, category="Trainer", subtype="Supporter",
                provenance=provenance, rights_reference="fixture")])
            core.import_card_facets(self.db, [dict(
                card_id=card_id, facet_type="illustrator", value=artist,
                provenance=provenance, rights_reference="fixture")])
        packet, audit = concept_review_packet.build(
            self.db, set(), trainer_limit=1, energy_limit=0,
            include_names={"ルリナ"},
            preserve_pairs={("Trainer", "ルリナ", "Unrelated Supporter")})
        self.assertEqual({row["name_en"] for row in packet},
                         {"Unrelated Supporter", "Nessa"})
        nessa = next(row for row in packet if row["name_en"] == "Nessa")
        self.assertEqual(nessa["en_match_eligible"], 0)
        self.assertEqual(nessa["proposal_signal"], "editorial_name_hint_and_illustrator")
        self.assertEqual(self.db.execute(
            "SELECT match_eligible FROM card WHERE card_id=?",
            (nessa["en_card_id"],)).fetchone()[0], 0)
        self.assertEqual(audit["by_category"]["Trainer"]["candidate_rows"], 2)


if __name__ == "__main__":
    unittest.main()
