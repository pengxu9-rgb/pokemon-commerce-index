"""Compile the explicit 100-Japanese/25-English classic-scope discovery batch."""
import argparse
import json
from pathlib import Path

from scripts import build_pokemon_name_followup as compiler

PROFILE = compiler.FollowupProfile('pokemon-name-classic','catalog/international-pokemon-classic-v1',
    'catalog/international-pokemon-classic-plan-v1/plan.json',
    '01c9a9c943ef4b30f4c6bd646b13b53d820fa467321bf59f301d91124cd8d260',
    'f044b1a5333945bddd6a7d667fca4fcd031231158901b0524ff455fa11b48c48',
    ('PCG1','E1','E4','PMCG4','PMCG2'),100,'pokemon.followup-next-batch-plan.v1',strict_variant_dimensions=True)


def build(db_path,repo,root,output,inspected_at):
    return compiler.build(db_path,repo,root,output,inspected_at,profile=PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
