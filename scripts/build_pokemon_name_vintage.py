"""Compile the next 100-Japanese/25-English batch after conservative size holds."""
import argparse,json
from pathlib import Path
from scripts import build_pokemon_name_followup as compiler

PROFILE=compiler.FollowupProfile('pokemon-name-vintage','catalog/international-pokemon-vintage-v1',
    'catalog/international-pokemon-classic-v1/next-batch-plan.json',
    '658a8197a3286553ff8049dd05f84422988aad8cf1616b5f7b55a9b9980f1170',
    '39e3eb70c595a5480e1e78def0a41ea9c19d304b271ccccc9bfa0601a09218b5',
    ('PMCG1','PMCG2','PMCG3','E3','E5'),100,'pokemon.followup-next-batch-plan.v1',strict_variant_dimensions=True)


def build(db_path,repo,root,output,inspected_at):return compiler.build(db_path,repo,root,output,inspected_at,profile=PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
