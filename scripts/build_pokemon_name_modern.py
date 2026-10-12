"""Compile the explicit 100-Japanese/25-English modern-set discovery batch."""
import argparse
import json
from pathlib import Path

from scripts import build_pokemon_name_followup as compiler

PROFILE = compiler.FollowupProfile('pokemon-name-modern','catalog/international-pokemon-modern-v1',
    'catalog/international-pokemon-followup-v1/next-batch-plan.json',
    '3cac2536391818844afcf5aa96ae268964fef354a811be76d96fb7cff3e2a158',
    '216f0b0411fb06dc801cceebd9fb15e90e5f0c82863968454b53b05b27b2be24',
    ('S9A','S8','S11','S12','SM6A','SM1M','M2','M5','SV9','SV6A'),100,'pokemon.followup-next-batch-plan.v1')


def build(db_path,repo,root,output,inspected_at):
    return compiler.build(db_path,repo,root,output,inspected_at,profile=PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
