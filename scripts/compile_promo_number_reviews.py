"""Adjudicate the complete promo cohort; incomplete assets/reviews stay held."""
from __future__ import annotations
import argparse,json,hashlib,sqlite3,tarfile
from collections import Counter
from pathlib import Path
from pokemon_index import core,number_evidence
from scripts.freeze_relationship_identity_review import digest,source_bytes


def keyed(path):
    rows=list(map(json.loads,path.read_text().splitlines()))
    if len({r['target_id'] for r in rows})!=len(rows):raise ValueError('duplicate promo member')
    return {r['target_id']:r for r in rows}


def compile_reviews(db,cohort,assets,first,second,archive):
    if set(cohort)!=set(assets) or set(cohort)!=set(first) or set(first)!=set(second):raise ValueError('complete fifty-member promo reviews required')
    events=[];results=[]
    for tid,c in sorted(cohort.items()):
        if digest({k:v for k,v in c.items() if k!='snapshot_sha256'})!=c['snapshot_sha256']:raise ValueError('promo cohort hash differs')
        endpoint=c['endpoint_snapshot'];cid=endpoint['card_id'];a=assets[tid];reviews=[first[tid],second[tid]]
        if number_evidence.snapshot(db,cid)!=endpoint or digest(endpoint)!=c['identity_sha256']:raise ValueError('promo endpoint stale')
        if source_bytes(endpoint['provenance'],archive)!=c['source_audit']:raise ValueError('promo source bytes differ')
        reason=None
        if a['status']!='source_asset_frozen':reason='source_asset_unavailable'
        elif any(r['status']!='reviewed' for r in reviews):reason='model_review_incomplete'
        if reason:
            results.append(dict(target_id=tid,card_id=cid,status='held',reason=reason,graph_decisions_changed=False));continue
        body=Path(a['path']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=a['image_sha256']:raise ValueError('promo image hash differs')
        number_evidence._source(a['source_ref'])
        if a['source_ref'].startswith('https://www.pokemon-card.com/'):
            if a['source_ref'] not in {ref['source_url'] for ref in c['official_coordinate_refs']}:raise ValueError('publisher reference is outside frozen coordinate')
        bound=[]
        for r in reviews:
            if r['source_ref']!=a['source_ref'] or r['image_sha256']!=a['image_sha256']:raise ValueError('promo reviewer image substituted')
            if any(r[k] is not False for k in number_evidence.FALSE_CLAIMS):raise ValueError('promo review overclaims identity or commerce')
            if r['reading_status'] not in {'readable','partial','unreadable'}:raise ValueError('invalid original reading status')
            if r['reading_status']=='readable' and (r['observed_name'] is None or r['observed_number_text'] is None):raise ValueError('readable review is incomplete')
            bound.append({k:r[k] for k in ['actor','model_family','model_version','reviewed_at','source_ref','image_sha256','observed_number_text','observed_name','prior_verdicts_visible']}|dict(review_record_sha256=digest(r)))
        status=number_evidence.classify(endpoint['collector_number'],[r['observed_number_text'] for r in bound],
            expected_name=endpoint['name'],observed_names=[r['observed_name'] for r in bound])
        row=dict(schema=number_evidence.SCHEMA,revision=1,card_id=cid,endpoint_snapshot=endpoint,
            identity_sha256=c['identity_sha256'],source_ref=a['source_ref'],image_sha256=a['image_sha256'],
            review_groups=[dict(candidate_id=tid,cohort_snapshot_sha256=c['snapshot_sha256'],reviews=bound)],
            status=status,recorded_at=max((r['reviewed_at'] for r in bound),key=core.parse_time),**{k:False for k in number_evidence.FALSE_CLAIMS})
        row['event_id']=number_evidence.event_id(row);number_evidence.validate(row);events.append(row)
        results.append(dict(target_id=tid,card_id=cid,status=status,number_event_id=row['event_id'],
            recorded_number_texts=[r['observed_number_text'] for r in bound],recorded_name_texts=[r['observed_name'] for r in bound],
            name_text_matches_source=all(r['observed_name'] is not None and core._compact_identity_text(r['observed_name'])==core._compact_identity_text(endpoint['name']) for r in bound),
            source_catalog_name=endpoint['name'],graph_decisions_changed=False))
    return events,results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','archive','cohort','assets','first','second','output','summary']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.summary.exists():raise FileExistsError('use fresh promo adjudication outputs')
    assets=json.loads(a.assets.read_text())
    if len({r['target_id'] for r in assets})!=len(assets):raise ValueError('duplicate promo asset')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row;events,results=compile_reviews(db,keyed(a.cohort),{r['target_id']:r for r in assets},keyed(a.first),keyed(a.second),archive)
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    summary=dict(schema='pokemon.promo-number-adjudication.v1',targets=len(results),number_evidence_events=len(events),
        statuses=dict(Counter(r['status'] for r in results)),results=results,
        source_and_image_bytes_verified=True,review_input_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.cohort,a.assets,a.first,a.second]},
        independent_ground_truth_or_marketplace_precision_established=False,graph_decisions_changed=False,
        observation_scope='Stock-image name and number text only; holds include unreadable, disagreeing or source-name-unconfirmed readings. No physical variant or catalog-ID remapping.',
        output_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest())
    a.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}))
