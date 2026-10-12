"""Verify the bounded localized-name append after the 44-record hold migration."""
import argparse,json
from pathlib import Path
from scripts import audit_pokemon_name_followup as audit,audit_international_coverage_expansion as history
from scripts.build_international_coverage_expansion import RetrievalScope
from scripts.build_pokemon_name_vintage import PROFILE

MANIFEST='catalog-build-manifest-international-pokemon-vintage-v1.json'
AUDIT_PROFILE=history.AuditProfile('catalog-build-manifest-international-image-fix-v1.json',MANIFEST,
    PROFILE.directory+'/locales.jsonl',77,RetrievalScope(PROFILE.name,PROFILE.sets,PROFILE.japanese),True)


def inputs(root):return audit.inputs(root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def append(before_path,output,root):return audit.append(before_path,output,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def run(before_path,after_path,rebuilt_path,root):return audit.run(before_path,after_path,rebuilt_path,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as f:f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__=='__main__':main()
