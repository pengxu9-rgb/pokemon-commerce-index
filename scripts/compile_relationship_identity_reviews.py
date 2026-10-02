"""Compile two independent coordinate-artwork reviews against frozen current heads.

Physical printing, finish, display and market permissions remain false. Two AI
agents are distinct reviewers under the existing policy, not a population
accuracy measurement or proof of independent model errors.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3

from pokemon_index import core, discovery_graph
from scripts.freeze_relationship_identity_review import FIELDS, check_current, digest


def keyed(path):
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({row['candidate_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate reviewed candidate')
    return {row['candidate_id']:row for row in rows}


def checked_review(review, frozen):
    snapshot = review.get('cohort_snapshot_sha256',review.get('source_snapshot_sha256'))
    if snapshot != frozen['cohort_snapshot_sha256']:
        raise ValueError('review source snapshot differs')
    if review['decision'] != 'same_artwork':
        raise ValueError('non-agreeing review requires adjudication')
    artwork=review.get('artwork') or {'outcome':review.get('artwork_outcome'),'note':review.get('artwork_note')}
    finish=review.get('finish') or {'outcome':review.get('finish_outcome'),'note':review.get('finish_note')}
    if artwork['outcome']!='same' or not artwork.get('note'):
        raise ValueError('missing artwork evidence')
    if finish['outcome']!='not_comparable' or not finish.get('note'):
        raise ValueError('coordinate review cannot verify finish')
    identity = review.get('endpoint_coordinate_identity_checked',review.get('identity_check',{}).get('endpoint_coordinate_checked'))
    if identity is not True:raise ValueError('coordinate identity not checked')
    if review.get('physical_printing_verified') is not False or review.get('price_comparable') is not False:
        raise ValueError('review overclaims physical or price evidence')
    for flag in ('automatic_offer_join_allowed','display_allowed'):
        if review.get(flag,False) is not False:raise ValueError('review widens permission')
    images=review['image_evidence']
    if len(images)!=2 or {image['side'] for image in images}!={'ja','en'}:
        raise ValueError('review needs both image sources')
    for card in frozen['endpoints']:
        side=card['language'];image=next(image for image in images if image['side']==side)
        if image['image_sha256']!=card['image_sha256'] or image['source_ref']!=card['image_ref']:
            raise ValueError('review image evidence drifted')
    if not review.get('reviewer') or review['reviewer']!=review['reviewer'].strip():raise ValueError('invalid reviewer')
    core.parse_time(review['reviewed_at'])
    return artwork,finish


def compile_reviews(db, cohort, first, second):
    if set(first)!=set(second) or not set(first).issubset(cohort):
        raise ValueError('independent review memberships differ')
    rows=[]
    for cid in sorted(first):
        frozen=cohort[cid];check_current(db,frozen)
        if frozen['status']!='awaiting_independent_artwork_reviews' or any(c['identity_blockers'] for c in frozen['endpoints']):
            raise ValueError('held endpoint identity cannot become verified artwork')
        a,b=first[cid],second[cid]
        art_a,finish_a=checked_review(a,frozen);art_b,finish_b=checked_review(b,frozen)
        if a['reviewer'].casefold()==b['reviewer'].casefold():raise ValueError('distinct reviewers required')
        if b.get('first_review_verdicts_visible') is not False:
            raise ValueError('second review must record verdict separation')
        ordered=sorted((a,b),key=lambda r:core.parse_time(r['reviewed_at']))
        fingerprint=digest({'cohort':frozen,'reviews':ordered})
        event_id=f'relpilot-v2:{cid}:r1:same_artwork'
        evidence=dict(schema='pokemon.relationship_review.v1',review_event_id=event_id,
            source_snapshot_sha256=frozen['cohort_snapshot_sha256'],review_fingerprint=fingerprint,
            expected_pair_head=frozen['expected_pair_head'],
            cards=[dict(card_id=c['card_id'],source_ref=c['image_ref'],source_kind='source-bound coordinate stock image',identity_checked=True,
                        identity_scope='printed name and scoped number only; physical version assignment unverified',source_provenance=c['provenance'],image_sha256=c['image_sha256'],identity_snapshot={field:c[field] for field in FIELDS}) for c in frozen['endpoints']],
            first_review={k:ordered[0][k] for k in ('reviewer','decision','reviewed_at')},
            second_review={k:ordered[1][k] for k in ('reviewer','decision','reviewed_at')},
            artwork=dict(outcome='same',note=art_a['note']+' Independent second review: '+art_b['note']),
            finish=dict(outcome='not_comparable',note=finish_a['note']+' '+finish_b['note']),
            rationale='Two distinct AI agents inspected the same source-hashed stock images separately. Artwork composition and printed coordinate agree; physical variant, regional printing equivalence and price comparison remain unverified.',
            independence_scope='Distinct agents with inherited parent model; second did not see first verdicts. Shared model risk remains; not a blind marketplace benchmark or accuracy score.',
            physical_printing_verified=False,price_comparable=False,automatic_offer_join_allowed=False,display_allowed=False)
        left,right=sorted(c['card_id'] for c in frozen['endpoints'])
        row=dict(assertion_id=event_id,left_card_id=left,right_card_id=right,relation_type='same_artwork',review_status='verified',
                 asserted_by='relationship-pilot-v2',reviewer=ordered[1]['reviewer'],asserted_at=ordered[1]['reviewed_at'],
                 rights_reference='internal source-stock-image analysis only; no card image redistribution or live-offer permission',
                 evidence_ref=json.dumps(evidence,ensure_ascii=False,sort_keys=True))
        discovery_graph._validate_verified_evidence(row,left,right)
        rows.append(row)
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','cohort','first','second','output','summary'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists() or args.summary.exists():raise FileExistsError('outputs must be new')
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;rows=compile_reviews(db,keyed(args.cohort),keyed(args.first),keyed(args.second))
    args.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    summary=dict(qualified_artwork_events=len(rows),physical_printings_approved=0,price_comparability_approved=0,
                 live_offer_permissions=0,public_display_permissions=0,identity_holds=sum(r['status']=='identity_hold' for r in keyed(args.cohort).values()),
                 independence_scope='Two distinct AI agents, same inherited model. No population accuracy claim.',
                 file_sha256=__import__('hashlib').sha256(args.output.read_bytes()).hexdigest())
    args.summary.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
