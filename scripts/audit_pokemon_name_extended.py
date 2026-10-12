"""Verify the explicit extended-scope hundred-record discovery batch offline."""
import argparse
import json
from pathlib import Path

from scripts import audit_pokemon_name_followup as audit
from scripts import audit_international_coverage_expansion as history
from scripts.build_international_coverage_expansion import RetrievalScope
from scripts.build_pokemon_name_extended import PROFILE

MANIFEST='catalog-build-manifest-international-pokemon-extended-v1.json'
AUDIT_PROFILE=history.AuditProfile('catalog-build-manifest-international-pokemon-modern-v1.json',MANIFEST,
    PROFILE.directory+'/locales.jsonl',74,RetrievalScope(PROFILE.name,PROFILE.sets,PROFILE.japanese),True)


def inputs(root):return audit.inputs(root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def append(before_path,output,root):
    return audit.append(before_path,output,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def run(before_path,after_path,rebuilt_path,root):
    return audit.run(before_path,after_path,rebuilt_path,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();report=run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__=='__main__':main()
