"""Keep calibration results separate; append only qualified difference evidence.

Existing positive controls never create new approvals. Uncertain identities,
disagreement, missing images or model failures become holds, not rejections.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from pokemon_index import core,discovery_graph
from scripts.freeze_relationship_identity_review import FIELDS,check_current,digest
from scripts.compile_relationship_identity_reviews import checked_review,keyed

def adjudicate(db,cohort,first,second,assets):
    if set(cohort)!=set(first) or set(cohort)!=set(second):raise ValueError('complete independent control reviews required')
    events=[];results=[]
    for cid,frozen in sorted(cohort.items()):
        check_current(db,frozen);a,b=first[cid],second[cid]
        for r in (a,b):
            if r.get('cohort_snapshot_sha256')!=frozen['cohort_snapshot_sha256']:raise ValueError('control snapshot differs')
        reason=None
        pair_assets=[r for r in assets if r['candidate_id']==cid]
        if len(pair_assets)!=2 or {r['side'] for r in pair_assets}!={'ja','en'} or any(r['status']!='source_hash_verified' for r in pair_assets):reason='source_asset_unavailable'
        elif any(next(r for r in pair_assets if r['side']==c['language']).get(k)!=c[k] for c in frozen['endpoints'] for k in ['image_sha256']) or any(next(r for r in pair_assets if r['side']==c['language']).get('source_ref')!=c['image_ref'] for c in frozen['endpoints']):reason='source_asset_substitution'
        elif any(r.get('status')!='reviewed' for r in (a,b)):reason='model_review_incomplete'
        elif any(r.get('endpoint_coordinate_identity_checked') is not True for r in (a,b)):reason='printed_coordinate_identity_unconfirmed'
        elif a['decision']!=b['decision']:reason='review_disagreement'
        elif a['decision'] not in {'same_artwork','different_artwork'}:reason='artwork_uncertain'
        if reason:
            results.append(dict(candidate_id=cid,status='held',reason=reason,first_decision=a.get('decision'),second_decision=b.get('decision')));continue
        art_a,finish_a=checked_review(a,frozen,decision=a['decision']);art_b,finish_b=checked_review(b,frozen,decision=b['decision'])
        if a['reviewer'].casefold()==b['reviewer'].casefold() or b.get('first_review_verdicts_visible') is not False:raise ValueError('separate reviewers/verdicts required')
        if any(not isinstance(r.get('model_family'),str) or not r['model_family'].strip() for r in (a,b)):raise ValueError('both model families required')
        if any(c['identity_blockers'] for c in frozen['endpoints']):raise ValueError('held endpoint cannot qualify')
        if frozen['pair_scope']!='new_source_qualified_control':
            results.append(dict(candidate_id=cid,status='positive_control_agreement' if a['decision']=='same_artwork' else 'positive_control_conflict',graph_event_created=False));continue
        if a['decision']!='different_artwork':
            results.append(dict(candidate_id=cid,status='held',reason='challenge_did_not_establish_difference'));continue
        ordered=sorted((a,b),key=lambda r:core.parse_time(r['reviewed_at']))
        def binding(r):
            keys=['reviewer','decision','reviewed_at','model_family','model_version','model_version_note','protocol_sha256','prompt_sha256','response_sha256','inspection_sheet_sha256']
            return dict({k:r[k] for k in keys if k in r},review_record_sha256=digest(r))
        eid=f'relpilot-v2:{cid}:r1:same_artwork';left,right=sorted(c['card_id'] for c in frozen['endpoints'])
        evidence=dict(schema='pokemon.relationship_review.v1',review_kind='source_qualified_artwork_difference',review_event_id=eid,
            source_snapshot_sha256=frozen['cohort_snapshot_sha256'],review_fingerprint=digest(dict(cohort=frozen,reviews=ordered)),expected_pair_head=frozen['expected_pair_head'],
            cards=[dict(card_id=c['card_id'],source_ref=c['image_ref'],source_kind='source-bound coordinate stock image',identity_checked=True,
                identity_scope='Printed name and full scoped number only; physical source-label assignment unverified',source_provenance=c['provenance'],image_sha256=c['image_sha256'],identity_snapshot={k:c[k] for k in FIELDS}) for c in frozen['endpoints']],
            first_review=binding(ordered[0]),second_review=binding(ordered[1]),artwork=dict(outcome='different',note=art_a['note']+' Second separate inspection: '+art_b['note']),
            finish=dict(outcome='not_comparable',note=finish_a['note']+' '+finish_b['note']),
            rationale='Two source-hashed stock images show different illustrated scenes despite the shared single-Pokemon identity. Only this exact endpoint pair is reviewed; no physical-copy, counterpart or price fact follows.',
            independence_scope='Verdicts recorded separately with model-family provenance; shared source and model error risks remain. This selected engineering cohort is not a population accuracy measure.',
            physical_printing_verified=False,price_comparable=False,automatic_offer_join_allowed=False,display_allowed=False)
        event=dict(assertion_id=eid,left_card_id=left,right_card_id=right,relation_type='same_artwork',review_status='rejected',evidence_ref=json.dumps(evidence,ensure_ascii=False,sort_keys=True),rights_reference='Internal stock-image evidence; no image redistribution or market permission',asserted_by='relationship-pilot-v2',reviewer=ordered[1]['reviewer'],asserted_at=ordered[1]['reviewed_at'])
        discovery_graph._validate_artwork_difference_evidence(event,left,right);events.append(event)
        results.append(dict(candidate_id=cid,status='qualified_artwork_difference',graph_event_id=eid))
    return events,results

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('db','cohort','first','second','assets','output','summary'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.summary.exists():raise FileExistsError('use fresh adjudication outputs')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;events,results=adjudicate(db,keyed(a.cohort),keyed(a.first),keyed(a.second),json.loads(a.assets.read_text()))
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    summary=dict(schema='pokemon.artwork-control-adjudication.v1',pairs=len(results),statuses=dict(Counter(r['status'] for r in results)),new_difference_events=len(events),new_positive_events=0,physical_and_price_permissions_added=False,results=results)
    a.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}))

if __name__=='__main__':main()
