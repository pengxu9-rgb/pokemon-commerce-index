"""Compile exactly 100 existing Japanese IDs and 25 English comparison IDs offline."""
import argparse
import json
from pathlib import Path

from scripts import build_international_coverage_expansion as expansion

# This is an explicit scope expansion requested on 2026-10-12. Preserve the
# previous five-set compiler default and its historical artifacts unchanged.
SCOPE = expansion.RetrievalScope('hundred-ja-v1', (
    'SV1A', 'SV5A', 'SV6', 'SV7', 'SV9',
    'S9A', 'S10A', 'S6K',
    'M2A', 'M4', 'M1S', 'M3', 'M5', 'MF', 'MC',
    'SV10', 'SV1V', 'SV4K', 'SV5M'), 100)


def build(db_path, repo, root, output, inspected_at):
    return expansion.build(db_path, repo, root, output, inspected_at, scope=SCOPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--source-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inspected-at', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.source_repo, Path.cwd(), args.output, args.inspected_at)))


if __name__ == '__main__':
    main()
