"""Compile the explicit 100-Japanese/25-English extended-scope discovery batch."""
import argparse
import json
from pathlib import Path

from scripts import build_pokemon_name_followup as compiler

PROFILE = compiler.FollowupProfile('pokemon-name-extended','catalog/international-pokemon-extended-v1',
    'catalog/international-pokemon-modern-v1/next-batch-plan.json',
    'f38f454fa008a832a9b587f122d91b868480bd4fb92f073c7368c3992c7db692',
    '5ff06372499767b769e8c6d30bcfff9fefa30ad30161d4355ce6ef382d72b2e3',
    ('SM2K','SM3N','SM11','SM4A','SM3H','SM3P','SV5A','M1S','M4','S5I','S6K','MF'),100,'pokemon.followup-next-batch-plan.v1')


def build(db_path,repo,root,output,inspected_at):
    return compiler.build(db_path,repo,root,output,inspected_at,profile=PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
