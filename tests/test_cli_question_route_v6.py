import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pokemon_index import core, question_routing_v6
from tests.test_question_routing_v6 import facts

ROOT = Path(__file__).resolve().parents[1]


class QuestionRouteV6CliTests(unittest.TestCase):
    def test_cli_checks_cohort_evidence_in_read_only_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, source, cohort_file = root / "catalog.sqlite3", root / "facts.json", root / "cohort.json"
            db = core.connect(catalog)
            try:
                core.init_db(db)
                core.import_cards(db, [{"language": "ja", "set_code": "SV4A", "collector_number": "347/190",
                    "variant": "holo", "name": "ミュウex", "provenance": "fixture", "rights_reference": "fixture"}])
                unit = core._unit(db, "ja:SV4A:347/190:holo", "RAW", "raw", "a")
                db.commit()
                cohort = question_routing_v6.build_sale_cohort(db, [unit])
            finally:
                db.close()
            source.write_text(json.dumps(facts(channel="marketplace_listing")))
            cohort_file.write_text(json.dumps(cohort))
            command = [sys.executable, "-m", "pokemon_index", "question-route-plan-v6", str(source),
                       "--catalog-db", str(catalog), "--sale-cohort", str(cohort_file)]
            before = hashlib.sha256(catalog.read_bytes()).hexdigest()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["sale_cohort"], cohort)
            self.assertEqual(next(s for s in plan["steps"] if s["action"] == "retrieve_live_offers")["status"], "blocked")
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), before)
            cohort_file.write_text(json.dumps({**cohort, "evidence_ref": "catalog-unit-cohort-sha256:" + "0" * 64}))
            stale = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("sale cohort evidence changed", stale.stderr)


if __name__ == "__main__":
    unittest.main()
