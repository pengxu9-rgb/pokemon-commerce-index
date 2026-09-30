"""Replay frozen v6 facts against a catalog and pre-call researcher expectations.

This measures extraction validity, qualitative agreement and evidence gates;
researcher expectations are not blind human ground truth or answer accuracy.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from contextlib import closing
from pathlib import Path

from pokemon_index import catalog_question_resolver_v2 as resolver, core
from pokemon_index import question_routing_v6 as routing
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts import vertex_public_question_facts_v6 as extractor

MARKET_ACTIONS = {"retrieve_live_offers", "retrieve_verified_sale_series",
                  "retrieve_verified_sales", "retrieve_landed_quotes",
                  "retrieve_buyback_quotes", "retrieve_buyback_terms",
                  "retrieve_selling_fees", "retrieve_shipping_costs"}


def evaluate(frozen: Path, catalog: Path, facts_path: Path,
             expectations: Path) -> dict:
    manifest = json.loads((frozen / 'manifest.json').read_text())
    bindings = [('blind_sha256', frozen / 'blind_questions.jsonl'),
                ('catalog_snapshot_sha256', catalog),
                ('researcher_expectations_sha256', expectations),
                ('v6_planner_sha256', Path(routing.__file__)),
                ('v6_fact_extractor_sha256', Path(extractor.__file__)),
                ('catalog_resolver_sha256', Path(resolver.__file__))]
    for key, path in bindings:
        if sha_file(path) != manifest.get(key):
            raise ValueError(f'frozen evaluation input changed: {key}')
    for path, expected in manifest.get('runtime_dependency_sha256', {}).items():
        if sha_file(Path(path)) != expected:
            raise ValueError(f'frozen runtime dependency changed: {path}')
    questions = read_jsonl(frozen / 'blind_questions.jsonl')
    facts = read_jsonl(facts_path)
    labels = read_jsonl(expectations)
    by_id = {row['id']: row for row in facts}
    label_by_id = {row['id']: row for row in labels}
    ids = {row['id'] for row in questions}
    if (len(ids) != len(questions) or len(by_id) != len(facts) or
            set(by_id) != ids or len(label_by_id) != len(labels) or
            not ids <= label_by_id.keys()):
        raise ValueError('evaluation IDs do not match frozen questions')
    results = []
    with closing(core.connect(catalog, readonly=True)) as db:
        for question in questions:
            row, expected = by_id[question['id']], label_by_id[question['id']]
            if (row.get('question_sha256') != question['question_sha256'] or
                    row.get('model_family') != 'google' or
                    row.get('requested_model') != extractor.MODEL or
                    row.get('prompt_version') != extractor.PROMPT_VERSION or
                    row.get('prompt_sha256') != extractor._request(question)[1]):
                raise ValueError('extraction question, prompt or model changed')
            if row['status'] != 'ok':
                results.append({'id': row['id'], 'status': 'extraction_error',
                                'errors': row.get('attempt_errors', [])})
                continue
            structured, _, _ = extractor.validate_answer(
                {'facts': row['facts'], 'evidence_spans': row['evidence_spans'],
                 'rationale': row['rationale']}, question)
            lookup = resolver.resolve_question(db, routing.catalog_projection(structured))
            plan = routing.plan_question(structured, resolution=lookup['resolution'],
                                         capabilities={'internal_catalog'})
            actions = {step['action'] for step in plan['steps']}
            formats = expected.get('explicit_sale_formats')
            results.append({'id': row['id'], 'status': 'ok',
                'primary_goal': structured['primary_goal'],
                'allowed_goals': expected['allowed_goals'],
                'goal_agrees_with_researcher': structured['primary_goal'] in expected['allowed_goals'],
                'sale_scope': structured['sale_scope'],
                'sale_formats': structured['sale_formats'],
                'expected_formats': formats,
                'formats_agree_with_researcher': None if formats is None else
                    set(formats) == set(structured['sale_formats']),
                'missing_expected_actions': sorted(set(expected['required_actions']) - actions),
                'market_action_ready': any(step['action'] in MARKET_ACTIONS and
                    step['status'] == 'ready' for step in plan['steps']),
                'catalog_status': lookup['resolution']['status'], 'catalog_reason': lookup['reason'],
                'plan': plan})
    valid = [row for row in results if row['status'] == 'ok']
    return {'schema': 'pokemon.question-v6-fresh-diagnostic.v1',
        'evaluation_role': 'fresh source-condensed questions; researcher silver expectations; not answer accuracy',
        'manifest_sha256': sha_file(frozen / 'manifest.json'),
        'facts_sha256': sha_file(facts_path),
        'questions': len(results), 'valid': len(valid), 'errors': len(results) - len(valid),
        'goal_agreement': sum(row['goal_agrees_with_researcher'] for row in valid),
        'formats_evaluated': sum(row['formats_agree_with_researcher'] is not None for row in valid),
        'formats_agreement': sum(row['formats_agree_with_researcher'] is True for row in valid),
        'missing_action_cases': sum(bool(row['missing_expected_actions']) for row in valid),
        'market_ready_cases': sum(row['market_action_ready'] for row in valid),
        'goals': dict(sorted(Counter(row['primary_goal'] for row in valid).items())),
        'results': results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-dir', type=Path, required=True)
    parser.add_argument('--catalog-db', type=Path, required=True)
    parser.add_argument('--facts', type=Path, required=True)
    parser.add_argument('--expectations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('evaluation output must be new')
    report = evaluate(args.frozen_dir, args.catalog_db, args.facts, args.expectations)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))


if __name__ == '__main__':
    main()
