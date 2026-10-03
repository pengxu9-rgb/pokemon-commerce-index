"""Bind complete image fact reviews to immutable source/image bytes."""
from __future__ import annotations
import argparse,json,hashlib,tarfile,sqlite3,re
from collections import Counter
from pathlib import Path
from pokemon_index import core,number_evidence,source_image_facts as facts
from scripts.freeze_relationship_identity_review import digest,source_bytes,SOURCE

def keyed(p):
    rows=list(map(json.loads,p.read_text().splitlines()))
    if len({r['target_id'] for r in rows})!=len(rows):raise ValueError('duplicate fact cohort member')
    return {r['target_id']:r for r in rows}

def compile_reviews(db,archive,cohort,first,second):
    if set(cohort)!=set(first) or set(first)!=set(second):raise ValueError('complete source fact cohort required')
    rows=[]
    for tid,c in sorted(cohort.items()):
        if digest({k:v for k,v in c.items() if k!='snapshot_sha256'})!=c['snapshot_sha256']:raise ValueError('fact cohort changed')
        snap=c['endpoint_snapshot'];cid=snap['card_id']
        if number_evidence.snapshot(db,cid)!=snap:raise ValueError('fact endpoint drift')
        prior=db.execute('SELECT record_json FROM card_number_reading_evidence WHERE event_id=?',
            (c['prior_number_event_id'],)).fetchone()
        if prior is None:raise ValueError('prior source image binding missing')
        bound_source=json.loads(prior[0]);number_evidence.validate(bound_source)
        if any(bound_source[k]!=c[k] for k in ['source_ref','image_sha256','endpoint_snapshot','identity_sha256']):
            raise ValueError('fact cohort substituted the prior exact source image')
        audit=source_bytes(snap['provenance'],archive)
        if audit!=c['source_audit']:raise ValueError('fact source bytes changed')
        m=SOURCE.fullmatch(snap['provenance']);body=archive.extractfile('cards-database-'+m[1]+'/'+m[2]).read().decode()
        hp=re.findall(r'^\s*hp:\s*(\d+)\s*,?\s*$',body,re.M)
        if len(hp)>1 or (int(hp[0]) if hp else None)!=c['pinned_source_hp']:raise ValueError('HP differs from pinned source bytes')
        if hashlib.sha256(Path(c['image_path']).read_bytes()).hexdigest()!=c['image_sha256']:raise ValueError('fact image bytes changed')
        bound=[]
        for r in [first[tid],second[tid]]:
            if r['status']!='reviewed':raise ValueError('incomplete source fact inspection')
            if r['source_ref']!=c['source_ref'] or r['image_sha256']!=c['image_sha256']:raise ValueError('fact inspection image changed')
            facts.validate_reading(r['reading'])
            bound.append({k:r[k] for k in facts.REVIEW_FIELDS if k!='review_record_sha256'}|dict(review_record_sha256=digest(r)))
        row=dict(schema=facts.SCHEMA,revision=1,card_id=cid,endpoint_snapshot=snap,identity_sha256=c['identity_sha256'],
            source_ref=c['source_ref'],image_sha256=c['image_sha256'],source_file_sha256=audit['sha256'],pinned_source_hp=c['pinned_source_hp'],
            cohort_snapshot_sha256=c['snapshot_sha256'],reviews=bound,recorded_at=max((r['reviewed_at'] for r in bound),key=core.parse_time),**{k:False for k in facts.FALSE_CLAIMS})
        row['event_id']=facts.event_id(row);facts.validate(row);rows.append(row)
    return rows

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','archive','cohort','first','second','output','summary']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.summary.exists():raise FileExistsError('use fresh fact evidence outputs')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row;rows=compile_reviews(db,archive,keyed(a.cohort),keyed(a.first),keyed(a.second))
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    result=dict(schema='pokemon.source-image-fact-compilation.v1',subjects=len(rows),outcomes=[dict(card_id=r['card_id'],**facts.outcomes(r)) for r in rows],
        image_and_source_bytes_verified=True,review_input_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.cohort,a.first,a.second]},
        evidence_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),independent_review_agreement_established=False,number_reading_qualification_changed=False)
    a.summary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(subjects=len(rows),name_statuses=dict(Counter(facts.outcomes(r)['name_status'] for r in rows)),hp_statuses=dict(Counter(facts.outcomes(r)['hp_status'] for r in rows)))))
