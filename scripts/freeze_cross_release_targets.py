"""Freeze a larger source-fact cohort without claiming images or reviews."""
from __future__ import annotations
import argparse,json,sqlite3,tarfile
from collections import Counter
from pathlib import Path
from pokemon_index import number_evidence
from scripts.freeze_relationship_identity_review import digest,source_bytes

def freeze(db,archive,prior_queue,release_summary,per_release):
    excluded={(r['endpoint_snapshot']['language'],r['endpoint_snapshot']['set_code'],r['endpoint_snapshot']['collector_number']) for r in prior_queue}
    for (data,) in db.execute('SELECT record_json FROM card_number_reading_evidence'):
        e=json.loads(data)['endpoint_snapshot'];excluded.add((e['language'],e['set_code'],e['collector_number']))
    buckets=[('missing_source_rarity',lambda e:e['rarity'] in {None,'None','Unknown'}),('named_mechanic_marker',lambda e:e['name'].casefold().endswith(('ex','gx','v','vmax','vstar'))),('known_source_rarity',lambda e:e['rarity'] not in {None,'None','Unknown'}),('alternate_source_label',lambda e:e['variant']!='normal'),('baseline',lambda e:True)]
    if per_release<5 or per_release%5:raise ValueError('equal bucket allocation requires a positive multiple of five')
    rows=[];releases=[]
    for release in release_summary['release_selection']:
        language=release['language'];set_code=release['set_code'];used=set(excluded);picked=[]
        candidates=[number_evidence.snapshot(db,r[0]) for r in db.execute("SELECT card_id FROM card WHERE language=? AND set_code=? AND match_eligible=1 AND provenance LIKE 'tcgdex:%' ORDER BY collector_number,CASE WHEN variant='normal' THEN 0 ELSE 1 END,variant,card_id",(language,set_code))]
        for bucket,predicate in buckets:
            for _ in range(per_release//5):
                available=[e for e in candidates if (e['language'],e['set_code'],e['collector_number']) not in used]
                selected=next((e for e in available if predicate(e)),None);reason=bucket
                if selected is None:selected=next(iter(available),None);reason+=':baseline_fallback'
                if selected is None:raise ValueError('insufficient distinct unreviewed release coordinates')
                key=(selected['language'],selected['set_code'],selected['collector_number']);used.add(key);excluded.add(key)
                row=dict(schema='pokemon.next-cross-release-source-fact-target.v1',target_id=f'cross-scale-{len(rows)+1:04}',endpoint_snapshot=selected,identity_sha256=digest(selected),source_audit=source_bytes(selected['provenance'],archive),selection_bucket=reason,
                    release_selection_basis='Reuse frozen twenty release namespaces; equal bucket allocation within each, with explicit fallback. Not random sampling, market demand or GMV.',prior_number_event_id=None,status='awaiting_source_image_acquisition_and_inspection',source_image_verified=False,number_qualification_established=False,physical_or_market_approval=False)
                row['snapshot_sha256']=digest(row);rows.append(row);picked.append(row['target_id'])
        releases.append(dict(language=language,set_code=set_code,targets=picked))
    return rows,dict(targets=len(rows),releases=len(releases),languages=dict(Counter(r['endpoint_snapshot']['language'] for r in rows)),release_selection=releases,pinned_source_bytes_verified=True,images_acquired=0,root_or_vertex_reviews=0,new_evidence_imported=0,market_or_physical_approvals=0,prior_coordinates_excluded=True,selection_is_random=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['db','archive','prior-queue','release-summary','output','summary']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--per-release',type=int,default=50);a=p.parse_args()
    if a.output.exists() or a.summary.exists():raise FileExistsError('use fresh target outputs')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row;rows,summary=freeze(db,archive,list(map(json.loads,a.prior_queue.read_text().splitlines())),json.loads(a.release_summary.read_text()),a.per_release)
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows));a.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:summary[k] for k in ['targets','releases','languages','images_acquired','root_or_vertex_reviews']}))
