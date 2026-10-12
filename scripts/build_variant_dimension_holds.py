"""Compile the fixed 44 source-size omissions from existing authorized bytes."""
import argparse,hashlib,json,os,shutil,tempfile
from contextlib import closing
from pathlib import Path
from pokemon_index import core,catalog_locale,variant_dimension_hold as holds
from scripts.qualify_international_product_documents import git_tree,checked_source,REVISION

BEFORE_SHA='ebb883552bce5aaf7d2553f9f60d9e927c39a9ef8e849cee0b955063c3622b87'
AUDIT='catalog/international-pokemon-classic-v1/variant-size-audit.json'
AUDIT_SHA='5639c7464d3fffc245416b4a8db03c1657c34cd79825082ad81ba2a6bdbfa213'


def compile(db_path,repo,root,inspected_at):
    core.parse_time(inspected_at)
    if hashlib.sha256(db_path.read_bytes()).hexdigest()!=BEFORE_SHA:raise ValueError('immutable pre-hold snapshot differs')
    audit_raw=(root/AUDIT).read_bytes()
    if hashlib.sha256(audit_raw).hexdigest()!=AUDIT_SHA:raise ValueError('fixed size audit differs')
    audit=json.loads(audit_raw)
    if audit['input_database_sha256']!=BEFORE_SHA or audit['source_revision']!=REVISION or len(audit['affected'])!=44:raise ValueError('fixed audit scope differs')
    paths={r['native_id'] for r in audit['affected']}|{'LICENSE'}
    blobs=git_tree(repo,sorted(paths),revision=REVISION)
    if set(blobs)!=paths:raise ValueError('pinned hold source unavailable')
    raws={p:checked_source(repo,p,blobs[p]) for p in sorted(paths)}
    licence=(root/'catalog/TCGDEX-LICENSE').read_bytes()
    if raws['LICENSE']!=licence:raise ValueError('metadata licence differs')
    licence_sha=hashlib.sha256(licence).hexdigest();rows=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        db.execute('BEGIN')
        for finding in audit['affected']:
            cid=finding['identity']['card_id'];identity=catalog_locale.snapshot(db,cid)
            if identity!=finding['identity'] or holds.held(db,cid):raise ValueError('legacy identity changed or already held')
            path=finding['native_id'];raw=raws[path];sha=hashlib.sha256(raw).hexdigest()
            if (finding['git_blob']!=blobs[path] or finding['metadata_source_sha256']!=sha
                    or finding['license_sha256']!=licence_sha):raise ValueError('frozen source witness differs')
            eligible=bool(db.execute('SELECT match_eligible FROM card WHERE card_id=?',(cid,)).fetchone()[0])
            if eligible!=finding['baseline_structural_match_eligible']:raise ValueError('legacy eligibility changed')
            reason=f"source-declared size '{finding['source_size']}' omitted by legacy variant '{identity['variant']}'; dimension-complete printing identity unresolved; no standard-size or edition fallback"
            row=dict(schema=holds.SCHEMA,revision=1,identity=identity,legacy_variant=identity['variant'],declared_size=finding['source_size'],
                prior_structural_match_eligible=eligible,parent_audit_sha256=AUDIT_SHA,recorded_at=inspected_at,reason=reason,
                confidence=dict(pinned_source_bytes=1.0,physical_size=None,canonical_identity=None),unresolved_conflicts=[reason],
                source=dict(provider='tcgdex',language=identity['language'],region='ZZ',native_id=path,revision=REVISION,
                    git_blob=blobs[path],sha256=sha,text=raw.decode(),rights_reference=identity['rights_reference'],
                    rights_status='metadata_internal_reviewed',license_sha256=licence_sha,retrieved_at=None,
                    retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,physical_distribution_region=None),
                **{k:False for k in catalog_locale.FALSE_CLAIMS})
            row['event_id']=holds.event_id(row);holds.validate(db,row);rows.append(row)
    if len({r['identity']['card_id'] for r in rows})!=44 or sum(r['prior_structural_match_eligible'] for r in rows)!=9:raise ValueError('fixed 44/9 cohort differs')
    if (hashlib.sha256(db_path.read_bytes()).hexdigest()!=BEFORE_SHA or (root/AUDIT).read_bytes()!=audit_raw
            or git_tree(repo,sorted(paths),revision=REVISION)!=blobs or any(checked_source(repo,p,blobs[p])!=raw for p,raw in raws.items())
            or (root/'catalog/TCGDEX-LICENSE').read_bytes()!=licence):raise ValueError('hold inputs drifted')
    receipt=dict(schema='pokemon.variant-dimension-hold-selection.v1',input_database_sha256=BEFORE_SHA,parent_audit_sha256=AUDIT_SHA,
        source_revision=REVISION,inspected_at=inspected_at,held_ids=44,eligibility_withdrawal_target=9,ids_renamed=0,canonical_replacements=0,
        source_inventory={p:dict(git_blob=blobs[p],sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in raws.items()},
        **{k:False for k in catalog_locale.FALSE_CLAIMS})
    return rows,receipt,licence


def build(db_path,repo,root,output,inspected_at):
    if output.exists():raise FileExistsError('hold output exists')
    rows,receipt,licence=compile(db_path,repo,root,inspected_at)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        pending=Path(directory)/'bundle';pending.mkdir()
        (pending/'holds.jsonl').write_text(''.join(catalog_locale.encoded(r)+'\n' for r in rows))
        (pending/'selection.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        (pending/'TCGDEX-LICENSE').write_bytes(licence)
        if output.exists():raise FileExistsError('hold output exists')
        os.rename(pending,output)
    return dict(held_ids=44,eligibility_withdrawal_target=9)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
