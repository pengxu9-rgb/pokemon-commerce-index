"""Compile stock-image readings, retaining outcomes for the entire frozen 100."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3,tarfile
from collections import Counter
from pathlib import Path
from pokemon_index import core,number_evidence,source_image_facts as facts
from scripts.compile_source_image_facts import keyed
from scripts.freeze_relationship_identity_review import digest,source_bytes

def compile_reviews(db,archive,targets,assets,cohort,first,second,expected_targets=100):
    if expected_targets<1 or len(targets)!=expected_targets or set(targets)!=set(assets):raise ValueError('complete frozen cohort required')
    available={tid for tid,a in assets.items() if a['status']=='source_asset_frozen'}
    if set(cohort)!=available or set(first)!=available or set(second)!=available:raise ValueError('complete available-image reviews required')
    events=[];outcomes=[];fact_cohort=[]
    for tid,c in sorted(targets.items()):
        if digest({k:v for k,v in c.items() if k!='snapshot_sha256'})!=c['snapshot_sha256']:raise ValueError('target changed')
        endpoint=c['endpoint_snapshot'];cid=endpoint['card_id'];a=assets[tid]
        if number_evidence.snapshot(db,cid)!=endpoint or digest(endpoint)!=c['identity_sha256']:raise ValueError('endpoint drift')
        if source_bytes(endpoint['provenance'],archive)!=c['source_audit']:raise ValueError('source bytes changed')
        if c['prior_number_event_id'] is not None:raise ValueError('new subjects only; do not replace an existing review')
        if tid not in available:
            outcomes.append(dict(target_id=tid,card_id=cid,status='held',reason='source_asset_unavailable',number_event_id=None));continue
        image=cohort[tid]
        if digest({k:v for k,v in image.items() if k!='snapshot_sha256'})!=image['snapshot_sha256']:raise ValueError('image cohort changed')
        if any(image[k]!=c[k] for k in ['endpoint_snapshot','identity_sha256','source_audit']):raise ValueError('image endpoint substituted')
        if hashlib.sha256(Path(a['path']).read_bytes()).hexdigest()!=a['image_sha256']:raise ValueError('image bytes changed')
        if any(image[k]!=a[k] for k in ['source_ref','image_sha256']):raise ValueError('image cohort substituted')
        number_evidence._source(a['source_ref'])
        if a['source_ref'].startswith('https://www.pokemon-card.com/') and a['source_ref'] not in {ref['source_url'] for ref in c['official_coordinate_refs']}:
            raise ValueError('publisher reference outside frozen coordinate')
        raw=[first[tid],second[tid]]
        if any(r['status']!='reviewed' for r in raw):
            outcomes.append(dict(target_id=tid,card_id=cid,status='held',reason='model_review_incomplete',number_event_id=None));continue
        bound=[]
        for r in raw:
            facts.validate_reading(r['reading'])
            if r['source_ref']!=a['source_ref'] or r['image_sha256']!=a['image_sha256']:raise ValueError('review image substituted')
            if r['prior_verdicts_visible'] is not False:raise ValueError('prior verdict exposed before number inspection')
            reading=r['reading']
            bound.append({k:r[k] for k in ['actor','model_family','model_version','reviewed_at','source_ref','image_sha256','prior_verdicts_visible']}|
                dict(observed_number_text=reading['observed_number_text'],observed_name=facts.title_interpretation(reading)['canonical_candidate'],review_record_sha256=digest(r)))
        status=number_evidence.classify(endpoint['collector_number'],[r['observed_number_text'] for r in bound],expected_name=endpoint['name'],observed_names=[r['observed_name'] for r in bound])
        event=dict(schema=number_evidence.SCHEMA,revision=1,card_id=cid,endpoint_snapshot=endpoint,identity_sha256=c['identity_sha256'],source_ref=a['source_ref'],image_sha256=a['image_sha256'],
            review_groups=[dict(candidate_id=tid,cohort_snapshot_sha256=image['snapshot_sha256'],reviews=bound)],status=status,recorded_at=max((r['reviewed_at'] for r in bound),key=core.parse_time),**{k:False for k in number_evidence.FALSE_CLAIMS})
        event['event_id']=number_evidence.event_id(event);number_evidence.validate(event);events.append(event)
        outcomes.append(dict(target_id=tid,card_id=cid,status=status,number_event_id=event['event_id'],catalog_number=endpoint['collector_number'],observed_number_texts=[r['observed_number_text'] for r in bound],observed_names=[r['observed_name'] for r in bound]))
        fc=dict(image);fc['prior_image_cohort_snapshot_sha256']=fc.pop('snapshot_sha256');fc['prior_number_event_id']=event['event_id'];fc['snapshot_sha256']=digest(fc);fact_cohort.append(fc)
    return events,outcomes,fact_cohort

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['db','archive','targets','assets','cohort','first','second','output','summary','fact-cohort']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--expected-targets',type=int,default=100)
    a=p.parse_args()
    if any(f.exists() for f in [a.output,a.summary,a.fact_cohort]):raise FileExistsError('use fresh compilation outputs')
    aset=json.loads(a.assets.read_text());assets={r['target_id']:r for r in aset}
    if len(assets)!=len(aset):raise ValueError('duplicate asset target')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row;events,outcomes,cohort=compile_reviews(db,archive,keyed(a.targets),assets,keyed(a.cohort),keyed(a.first),keyed(a.second),a.expected_targets)
    def write(path,rows):path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    write(a.output,events);write(a.fact_cohort,cohort)
    summary=dict(schema='pokemon.cross-release-number-compilation.v1',targets=len(outcomes),number_evidence_events=len(events),statuses=dict(Counter(r['status'] for r in outcomes)),outcomes=outcomes,
        review_input_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.targets,a.assets,a.cohort,a.first,a.second]},evidence_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),source_and_image_bytes_verified=True,
        independence_or_marketplace_accuracy_established=False,physical_or_commerce_approvals_added=False,scope='Stock-image title and collector text. Catalog coordinates and graph decisions unchanged; unavailable images retain explicit holds.')
    a.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:summary[k] for k in ['targets','number_evidence_events','statuses']}))
