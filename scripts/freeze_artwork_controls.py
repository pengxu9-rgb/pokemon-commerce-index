"""Freeze source-qualified challenge pairs; selection labels are not verdicts."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
from pokemon_index import discovery_graph
from scripts.freeze_relationship_identity_review import FIELDS, digest, source_bytes, check_current
from scripts.freeze_relationship_expansion import fetch_asset

NAMES=('Altaria','Bidoof','Bulbasaur','Breloom','Ceruledge','Cleffa',
       'Dhelmise','Exeggcute','Gengar','Helioptile','Raichu','Snorlax')
POSITIVE_NAMES=('Altaria','Bidoof','Bulbasaur','Ceruledge','Raichu','Snorlax')

def freeze(db,archive):
    heads=[];images={}
    for row in db.execute("""SELECT a.* FROM card_relationship_assertion a
       WHERE relation_type='same_artwork' AND NOT EXISTS(SELECT 1 FROM card_relationship_assertion b
       WHERE b.left_card_id=a.left_card_id AND b.right_card_id=a.right_card_id AND
       b.relation_type=a.relation_type AND b.rowid>a.rowid) ORDER BY a.assertion_id"""):
        evidence=json.loads(row['evidence_ref'])
        cards=[dict(db.execute('SELECT * FROM card WHERE card_id=?',(cid,)).fetchone()) for cid in (row['left_card_id'],row['right_card_id'])]
        if any(discovery_graph.endpoint_identity_blockers(db,c['card_id']) for c in cards):continue
        if {c['language'] for c in cards}!={'ja','en'}:continue
        for c in cards:
            src=next((x for x in evidence.get('cards',[]) if isinstance(x,dict) and x.get('card_id')==c['card_id']),None)
            ref=src.get('source_ref') if src else evidence.get(c['language']+'_image_ref')
            sha=src.get('image_sha256') if src else evidence.get(c['language']+'_image_sha256')
            if ref and sha:images[c['card_id']]=(ref,sha)
        ja=next(c for c in cards if c['language']=='ja');en=next(c for c in cards if c['language']=='en')
        heads.append((dict(row),ja,en))
    def endpoint(card):
        c={field:card[field] for field in FIELDS};ref,sha=images[card['card_id']]
        c.update(source_audit=source_bytes(c['provenance'],archive),identity_blockers=[],image_ref=ref,image_sha256=sha,
                 image_scope='Coordinate source stock image; physical variant/copy identity unverified')
        return c
    def single_dex(c):
        return tuple(r[0] for r in db.execute("SELECT DISTINCT value FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id' ORDER BY value",(c['card_id'],)))
    def record(ja,en,head,selection):
        left,right=sorted([ja['card_id'],en['card_id']]);cid=hashlib.sha256(('relationship-pilot-v1\0'+left+'\0'+right).encode()).hexdigest()[:20]
        row=dict(schema='pokemon.relationship-identity-cohort.v1',candidate_id=cid,
            expected_pair_head=head['assertion_id'] if head else None,
            source_evidence_sha256=hashlib.sha256(head['evidence_ref'].encode()).hexdigest() if head else None,
            original_source_snapshot_sha256=digest([ja['provenance'],en['provenance']]),
            pair_scope='existing_pair_control' if head else 'new_source_qualified_control',
            selection_reason=selection,status='awaiting_independent_artwork_reviews',
            endpoints=[endpoint(ja),endpoint(en)],relation_type='same_artwork',
            price_comparable=False,physical_printing_verified=False,automatic_offer_join_allowed=False,display_allowed=False)
        row['cohort_snapshot_sha256']=digest(row);check_current(db,row);return row
    rows=[]
    for name in NAMES:
        bases=[x for x in heads if x[0]['review_status']=='verified' and x[2]['name']==name]
        if not bases:raise ValueError('missing reviewed base '+name)
        head,ja,en=min(bases,key=lambda x:x[0]['assertion_id'])
        dex=single_dex(ja)
        if len(dex)!=1 or dex!=single_dex(en):raise ValueError('ambiguous base character')
        choices=[]
        for other,j,e in heads:
            if e['name']!=name or e['card_id']==en['card_id'] or single_dex(e)!=dex:continue
            if (e['set_code'],e['collector_number'])==(en['set_code'],en['collector_number']):continue
            if images[e['card_id']][1]==images[en['card_id']][1]:continue
            a,b=sorted((ja['card_id'],e['card_id']))
            if db.execute('SELECT 1 FROM card_relationship_assertion WHERE left_card_id=? AND right_card_id=?',(a,b)).fetchone():continue
            choices.append(e)
        if not choices:raise ValueError('missing cross-art challenge '+name)
        other=min(choices,key=lambda c:digest({'seed':'cross-art-controls-20261002-v1','card_id':c['card_id']}))
        rows.append(record(ja,other,None,'same_single_character_different_coordinate_challenge'))
        if name in POSITIVE_NAMES:rows.append(record(ja,en,head,'previously_reviewed_same_artwork_control'))
    if len(rows)!=18 or len({r['candidate_id'] for r in rows})!=18:raise ValueError('control membership differs')
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('db','source-archive','output','assets','image-cache'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.assets.exists():raise FileExistsError('use fresh evidence outputs')
    a.image_cache.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.source_archive) as archive:
        db.row_factory=sqlite3.Row;rows=freeze(db,archive)
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    with ThreadPoolExecutor(max_workers=4) as pool:assets=list(pool.map(lambda job:fetch_asset(job,a.image_cache),[(r['candidate_id'],c) for r in rows for c in r['endpoints']]))
    a.assets.write_text(json.dumps(assets,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(pairs=len(rows),image_successes=sum(a['status']=='source_hash_verified' for a in assets),image_attempts=len(assets))))

if __name__=='__main__':main()
