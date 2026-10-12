"""Compile the explicit 300-Japanese/75-English offline retrieval batch."""
import argparse,json
from pathlib import Path
from scripts import build_pokemon_name_followup as compiler

PROFILE=compiler.FollowupProfile('pokemon-name-expanded','catalog/international-pokemon-expanded-v1',
    'catalog/international-pokemon-expanded-plan-v1/plan.json',
    'd2ddacfdfdfbb15399484cdeda567842cf4facd278fe2f6b924861a26485255e',
    '0f030b433fb5a285d3c9bd7acc15cd73a3ff09bbf10bf9767e49346d85cccfe6',
    ('PMCG1', 'PMCG3', 'NEO1', 'NEO2', 'NEO3', 'NEO4', 'WEB1', 'PCG2', 'PCG3', 'PCG4', 'PCG5', 'PCG6', 'CP2', 'SM1P', 'SM2K', 'SM2L', 'SM2P', 'SM3N', 'SM3P', 'SM4A', 'SM4S', 'SM4P', 'SM5M', 'SM5S', 'SM5P', 'SM6', 'SM6B', 'SM7A', 'SM7B', 'SM8', 'SM8A', 'SM10A', 'SM11', 'SM11A', 'SM12', 'S6H', 'S7D', 'S10P', 'SV1S', 'SV1A', 'SV2D', 'SV2P', 'SV3A', 'SV4K', 'SV4M', 'SV5K', 'SV5M', 'SV5A', 'SV6A', 'SV7', 'SVK', 'SVLN', 'SVLS', 'SV7A', 'SV8', 'SV9', 'SV9A', 'SV10'),300,'pokemon.followup-next-batch-plan.v1',strict_variant_dimensions=True,english=75,expanded_batch=True)


def build(db_path,repo,root,output,inspected_at):return compiler.build(db_path,repo,root,output,inspected_at,profile=PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
