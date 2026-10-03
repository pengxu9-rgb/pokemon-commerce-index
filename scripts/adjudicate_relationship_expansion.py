"""Compile positive expansion agreements; retain uncertainty/conflicts as holds.

All frozen memberships require two actual reviewer records. Missing assets,
different-artwork findings or disagreeing identities never create verified
edges. This avoids converting an incomplete review into a negative fact.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from scripts.compile_relationship_identity_reviews import compile_reviews, keyed, bind_source_images
from scripts.freeze_relationship_identity_review import check_current


def adjudicate(db,cohort,first,second,assets):
    if set(first)!=set(cohort) or set(second)!=set(cohort):
        raise ValueError('every frozen candidate requires two independent review records')
    qualified={};holds=[]
    for cid,frozen in cohort.items():
        check_current(db,frozen)
        a,b=first[cid],second[cid]
        for review in (a,b):
            if review.get('cohort_snapshot_sha256',review.get('source_snapshot_sha256'))!=frozen['cohort_snapshot_sha256']:
                raise ValueError('review snapshot differs')
        pair_assets=[r for r in assets if r['candidate_id']==cid]
        try:bind_source_images(pair_assets,frozen['endpoints']);asset_binding_valid=True
        except ValueError:asset_binding_valid=False
        if len(pair_assets)!=2 or any(r['status']!='source_hash_verified' for r in pair_assets):
            reason='source_asset_unavailable'
        elif not asset_binding_valid:
            reason='source_asset_hash_or_identity_mismatch'
        elif a['reviewer'].strip().casefold()==b['reviewer'].strip().casefold():
            reason='reviewers_not_distinct'
        elif b.get('first_review_verdicts_visible') is not False:
            reason='independent_verdict_separation_not_recorded'
        elif a['decision']!=b['decision']:
            reason='independent_review_disagreement'
        elif a['decision']!='same_artwork':
            reason='different_artwork_or_uncertain'
        else:
            # Complete positive evidence, exact image hashes, finish scope and
            # current source head are checked by the existing compiler.
            qualified[cid]=frozen
            continue
        holds.append(dict(candidate_id=cid,cohort_snapshot_sha256=frozen['cohort_snapshot_sha256'],status='held',reason=reason,
                          first_review=a,second_review=b,price_comparable=False,physical_printing_verified=False))
    events=compile_reviews(db,qualified,{cid:first[cid] for cid in qualified},{cid:second[cid] for cid in qualified})
    return events,holds


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('db','cohort','first','second','assets','output','holds','summary'):p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args()
    if any(p.exists() for p in (args.output,args.holds,args.summary)):raise FileExistsError('outputs must be new')
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        events,holds=adjudicate(db,keyed(args.cohort),keyed(args.first),keyed(args.second),json.loads(args.assets.read_text()))
    args.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    args.holds.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in holds))
    summary=dict(frozen_pairs=len(keyed(args.cohort)),qualified_artwork_events=len(events),held_pairs=len(holds),
        hold_reasons=dict(Counter(r['reason'] for r in holds)),rejected_graph_events=0,
        physical_printings_approved=0,price_comparability_approved=0,live_offer_permissions=0,public_display_permissions=0,
        independence_scope='Distinct AI reviewer identities with separated verdicts; model-family provenance is retained per positive event. Shared source and error risks remain, not population accuracy.',
        file_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.summary.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
