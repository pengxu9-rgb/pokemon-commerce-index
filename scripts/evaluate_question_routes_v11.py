"""Evaluate unseen source posts against unchanged v7, with explicit denominators."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scripts import evaluate_question_routes_v7 as baseline
from scripts.public_question_sandbox import sha_file


def evaluate(frozen: Path, catalog: Path, facts: Path, expectations: Path) -> dict:
    manifest = json.loads((frozen / 'manifest.json').read_text())
    if manifest.get('evaluation_role') != 'fresh source-post diagnostic for unchanged v7':
        raise ValueError('fresh evaluation requires a fresh-source manifest')
    for key, path in [('evaluator_sha256', Path(__file__)),
                      ('source_index_sha256', frozen / 'source_index.jsonl'),
                      ('source_evidence_sha256', frozen / 'source_evidence.jsonl'),
                      ('collection_lock_sha256', frozen / 'collection_lock.json')]:
        if manifest.get(key) != sha_file(path):
            raise ValueError(f'frozen evaluation input changed: {key}')
    lock = json.loads((frozen / 'collection_lock.json').read_text())
    for path, expected in lock['code_sha256'].items():
        if sha_file(Path(path)) != expected:
            raise ValueError(f'collection-locked code changed: {path}')
    report = baseline.evaluate(frozen, catalog, facts, expectations)
    report.update(schema='pokemon.question-v11-fresh-diagnostic.v1',
                  evaluation_role='fresh source-condensed posts against unchanged v7; AI researcher expectations, not human truth or answer accuracy')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-dir', required=True, type=Path)
    parser.add_argument('--catalog-db', required=True, type=Path)
    parser.add_argument('--facts', required=True, type=Path)
    parser.add_argument('--expectations', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('evaluation output must be new')
    result = evaluate(args.frozen_dir, args.catalog_db, args.facts, args.expectations)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='results'}))


if __name__ == '__main__':
    main()
