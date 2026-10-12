"""Audit the explicit 100-Japanese/25-English offline coverage batch."""
import argparse
import json
from pathlib import Path

from scripts import audit_international_coverage_expansion as expansion
from scripts.build_international_coverage_hundred import SCOPE

PROFILE = expansion.AuditProfile(
    'catalog-build-manifest-international-coverage-expansion-v1.json',
    'catalog-build-manifest-international-coverage-hundred-v1.json',
    'catalog/international-coverage-hundred-v1/locales.jsonl', 69, SCOPE)


def append(before_path, output, root):
    return expansion.append(before_path, output, root, profile=PROFILE)


def run(before_path, after_path, rebuilt_path, root):
    return expansion.run(before_path, after_path, rebuilt_path, root, profile=PROFILE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--rebuilt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.before, args.after, args.rebuilt, Path.cwd())
    with args.output.open('x') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('new_localized_bindings', 'translated_gaps_closed', 'idempotent_reimport')}))


if __name__ == '__main__':
    main()
