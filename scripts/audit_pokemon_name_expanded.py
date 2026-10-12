"""Audit the larger frozen retrieval batch and retain every identity hold."""
import argparse,json,tempfile
from contextlib import closing
from pathlib import Path
from pokemon_index import core,variant_dimension_hold
from scripts import audit_pokemon_name_followup as audit,audit_international_coverage_expansion as history
from scripts import audit_variant_dimension_holds as hold_audit
from scripts.build_international_coverage_expansion import RetrievalScope
from scripts.build_pokemon_name_expanded import PROFILE

MANIFEST='catalog-build-manifest-international-pokemon-expanded-v1.json'
AUDIT_PROFILE=history.AuditProfile('catalog-build-manifest-international-pokemon-vintage-v1.json',MANIFEST,
    PROFILE.directory+'/locales.jsonl',78,RetrievalScope(PROFILE.name,PROFILE.sets,PROFILE.japanese,PROFILE.english,PROFILE.expanded_batch),True)


def inputs(root):return audit.inputs(root,profile=PROFILE,audit_profile=AUDIT_PROFILE)


def installed(paths,root):
    rows=hold_audit.inputs(root);checks={}
    for path in paths:
        with closing(core.connect(path,readonly=True)) as db:
            hold_audit.installed(db,rows)
            for row in rows:
                cid=row['identity']['card_id'];flags=db.execute('SELECT match_eligible,display_allowed FROM card WHERE card_id=?',(cid,)).fetchone()
                if tuple(flags)!=(0,0) or variant_dimension_hold.context(db,cid)['status']!='held_legacy_variant_dimensions':
                    raise ValueError('retained variant-dimension hold changed')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('expanded snapshot integrity differs')
            checks[str(path)]=dict(held_ids=len(rows),exact_ledger_and_guard_definitions=True,hold_flags_and_sources_current=True)
    return checks


def append(before_path,output,root):
    if output.exists():raise FileExistsError('expanded snapshot exists')
    installed([before_path],root)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        pending=Path(directory)/'candidate.sqlite3'
        result=audit.append(before_path,pending,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)
        installed([pending],root)
        with output.open('xb') as f:f.write(pending.read_bytes())
    return result


def run(before_path,after_path,rebuilt_path,root):
    guards=installed([before_path,after_path,rebuilt_path],root)
    result=audit.run(before_path,after_path,rebuilt_path,root,profile=PROFILE,audit_profile=AUDIT_PROFILE)
    if installed([before_path,after_path,rebuilt_path],root)!=guards:raise ValueError('expanded hold guards drifted during audit')
    result['retained_variant_dimension_holds']=guards
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as f:f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__=='__main__':main()
