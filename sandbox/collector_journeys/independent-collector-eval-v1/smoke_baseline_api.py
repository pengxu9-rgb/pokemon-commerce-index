"""Smoke the evaluator against a synthetic DB and real baseline API, not the 30-case evaluation."""
import argparse
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--synthetic-suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo_root.resolve()))
    from pokemon_index import core, collector_journey, collector_character_affiliation
    from scripts.rehearse_collector_recommendations import create_fixture
    spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('run.py'))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    source = args.synthetic_suite
    with tempfile.TemporaryDirectory() as temp:
        db_path = Path(temp) / 'synthetic.sqlite3'
        create_fixture(db_path, json.loads(source.read_text()))
        before = runner.sha(db_path)
        with closing(core.connect(db_path, readonly=True)) as db:
            expected = {'printings': db.execute('SELECT COUNT(*) FROM card').fetchone()[0]}
            validation = runner.verify_snapshot(db, {'expected': expected, 'steps': []},
                {'manifest_sha256': 'synthetic-smoke-only', 'output': str(db_path), 'steps': 0, **expected},
                db_path, 'synthetic-smoke-only')
            c = {'id': 'SMOKE-ONLY', 'category': 'synthetic_harness', 'question': 'Recommend Japanese Pikachu cards',
                 'limit': 5, 'steps': [
                     {'action': {'type': 'ask', 'question': 'Recommend Japanese Pikachu cards'}},
                     {'action': {'type': 'feedback', 'card_id': {'$bind': 'shown'}, 'reaction': 'like'},
                      'bind': {'shown': {'from_step': 0, 'candidate_index': 0}}}],
                 'expected': {'automatable_checks': [{'check': 'minimum_candidates', 'value': 1},
                                                      {'check': 'candidate_provenance_present'}]}}
            result = runner.execute_case(c, db, collector_journey.replay, collector_journey.catalog_revision(db),
                                         collector_character_affiliation.affiliations(db), 10)
        unchanged = before == runner.sha(db_path)
        passed = result['execution_status'] == 'executed' and result['mechanical_constraints_met'] and not result['safety_violations'] and unchanged
        report = {'schema': 'pokemon.independent-eval-harness-smoke.v1', 'passed': passed,
                  'synthetic_catalog_only': True, 'independent_30_cases_executed': 0,
                  'collector_usefulness_measured': False, 'real_user_testing': False,
                  'runner_sha256': runner.sha(Path(__file__).with_name('run.py')),
                  'synthetic_fixture_sha256': runner.sha(source),
                  'snapshot_validator_smoke': validation, 'catalog_bytes_unchanged': unchanged,
                  'prefixes_executed': len(result['prefixes']), 'result': result}
        runner.save_new(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k not in {'result', 'snapshot_validator_smoke'}}))
        return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
