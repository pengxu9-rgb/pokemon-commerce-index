"""Freeze a diverse source-hashed artwork-review expansion without graph writes.

Selection is a bounded engineering review cohort, not market popularity or
population accuracy. Failed asset checks remain explicit holds.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tarfile
import urllib.request
from urllib.parse import urlparse

from pokemon_index import card_metadata, discovery_graph
from scripts.freeze_relationship_identity_review import FIELDS, CONTROLS, check_current, digest, source_bytes

RELEASES=('SM1M','SM2K','SM3N','SM9','SM10','SM11','SM12',
          'S5I','S6K','S8','S9','S10A','S11A','S12A',
          'SV2A','SV4A','SV8A','M1L','M1S','M2A')


def freeze(db, archive, *, pairs_per_release=1, seed='artwork-expansion-20261002-v1'):
    if type(pairs_per_release) is not int or not 1 <= pairs_per_release <= 5:
        raise ValueError('pairs per release must be 1–5')
    if not isinstance(seed,str) or not seed.strip():raise ValueError('selection seed is required')
    by_set={key:[] for key in RELEASES}
    for row in db.execute('''SELECT a.* FROM card_relationship_assertion a
        WHERE review_status='proposed' AND relation_type='same_artwork'
        AND NOT EXISTS(SELECT 1 FROM card_relationship_assertion b
          WHERE b.left_card_id=a.left_card_id AND b.right_card_id=a.right_card_id
          AND b.relation_type=a.relation_type AND b.rowid>a.rowid) ORDER BY a.assertion_id'''):
        evidence=json.loads(row['evidence_ref']);cid=evidence.get('candidate_id')
        if cid in CONTROLS:continue
        cards=[dict(db.execute('SELECT * FROM card WHERE card_id=?',(cid,)).fetchone()) for cid in (row['left_card_id'],row['right_card_id'])]
        ja=next((c for c in cards if c['language']=='ja'),None)
        if ja is None or ja['set_code'] not in by_set:continue
        if any(discovery_graph.endpoint_identity_blockers(db,c['card_id']) for c in cards):continue
        if any(c['variant'] not in {'normal','holo','reverse','reverse_pokeball','reverse_masterball','standard'} for c in cards):continue
        if any((card_metadata.context(db,c['card_id']) or {}).get('page_kind')=='numbered_parts' for c in cards):continue
        facets=tuple(r[0] for r in db.execute("SELECT value FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id' ORDER BY value",(ja['card_id'],)))
        signature=facets or (ja['name'],)
        by_set[ja['set_code']].append((row,evidence,cards,signature))
    rows=[];seen=set()
    for release in RELEASES:
        available=list(by_set[release])
        if len(available)<pairs_per_release:raise ValueError('insufficient qualified candidates for release '+release)
        for _ in range(pairs_per_release):
            row,evidence,cards,signature=min(available,key=lambda x:(x[3] in seen, any(c['variant'] not in {'normal','holo','standard'} for c in x[2]), digest({'seed':seed,'candidate':x[1]['candidate_id']})))
            available.remove((row,evidence,cards,signature));seen.add(signature)
            endpoints=[]
            for card in cards:
                side=card['language'];c={field:card[field] for field in FIELDS}
                c.update(source_audit=source_bytes(c['provenance'],archive),identity_blockers=[],image_ref=evidence[side+'_image_ref'],
                         image_sha256=evidence[side+'_image_sha256'],image_scope='coordinate artwork stock image; physical variant assignment unverified')
                endpoints.append(c)
            item=dict(schema='pokemon.relationship-identity-cohort.v1',candidate_id=evidence['candidate_id'],
                expected_pair_head=row['assertion_id'],source_evidence_sha256=hashlib.sha256(row['evidence_ref'].encode()).hexdigest(),
                original_source_snapshot_sha256=evidence['source_snapshot_sha256'],selection_reason='distinct_release_character_expansion',
                status='awaiting_independent_artwork_reviews',endpoints=endpoints,relation_type='same_artwork',
                price_comparable=False,physical_printing_verified=False,automatic_offer_join_allowed=False,display_allowed=False)
            item['cohort_snapshot_sha256']=digest(item);check_current(db,item);rows.append(item)
    return rows


def fetch_asset(job, cache):
    cid,card=job;side=card['language'];ref=card['image_ref'];url=ref;page_sha=None
    result=dict(candidate_id=cid,side=side,source_ref=ref,expected_image_sha256=card['image_sha256'],status='asset_hold')
    try:
        parsed=urlparse(ref)
        official=parsed.hostname=='www.pokemon-card.com' and re.fullmatch('/card-search/details.php/card/[0-9]+',parsed.path)
        tcgdex=parsed.hostname=='assets.tcgdex.net' and parsed.path.endswith('/high.webp')
        pokemontcg=parsed.hostname=='images.pokemontcg.io' and re.fullmatch(r'/[a-z0-9]+/[0-9]+_hires\.png',parsed.path)
        if parsed.scheme!='https' or parsed.query or parsed.fragment or not(official or tcgdex or pokemontcg):raise ValueError('unapproved stock image source')
        if official:
            with urllib.request.urlopen(urllib.request.Request(ref,headers={'User-Agent':'pokemon-internal-artwork-audit/1'}),timeout=30) as r:page=r.read(2_000_001)
            if len(page)>2_000_000:raise ValueError('page too large')
            page_sha=hashlib.sha256(page).hexdigest()
            matches=set(m.decode() for m in re.findall(rb'(?:https://www.pokemon-card.com)?(/assets/images/card_images/(?:large|legend)/[^"\s<>]+\.jpg)',page))
            if len(matches)!=1:raise ValueError('official image identity ambiguous')
            url='https://www.pokemon-card.com'+next(iter(matches))
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'pokemon-internal-artwork-audit/1'}),timeout=30) as r:body=r.read(7_000_001)
        if len(body)>7_000_000:raise ValueError('asset too large')
        if not (body.startswith(b'\xff\xd8\xff') or body.startswith(b'\x89PNG\r\n\x1a\n') or body[:4]==b'RIFF' and body[8:12]==b'WEBP'):raise ValueError('unknown image type')
        sha=hashlib.sha256(body).hexdigest()
        if sha!=card['image_sha256']:raise ValueError('previous source image hash drifted')
        suffix='.webp' if body[:4]==b'RIFF' else '.png' if body.startswith(b'\x89PNG') else '.jpg'
        path=cache/(cid+'-'+side+suffix);path.write_bytes(body)
        result.update(status='source_hash_verified',image_url=url,image_sha256=sha,image_bytes=len(body),page_sha256=page_sha,path=str(path.resolve()))
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error=str(exc))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('db','source-archive','output','summary','assets','image-cache'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--pairs-per-release',type=int,default=1)
    p.add_argument('--seed',default='artwork-expansion-20261002-v1')
    args=p.parse_args()
    if any(p.exists() for p in (args.output,args.summary,args.assets)):raise FileExistsError('outputs must be new')
    args.image_cache.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(args.source_archive) as archive:
        db.row_factory=sqlite3.Row;rows=freeze(db,archive,pairs_per_release=args.pairs_per_release,seed=args.seed)
    jobs=[(r['candidate_id'],c) for r in rows for c in r['endpoints']]
    with ThreadPoolExecutor(max_workers=4) as pool:assets=list(pool.map(lambda job:fetch_asset(job,args.image_cache),jobs))
    args.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    args.assets.write_text(json.dumps(assets,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    summary=dict(schema='pokemon.relationship-expansion-audit.v1',pairs=len(rows),japanese_releases=len(RELEASES),
        unique_source_files=len({c['provenance'] for r in rows for c in r['endpoints']}),source_byte_checks=len(jobs),
        image_statuses=dict(Counter(a['status'] for a in assets)),qualified_assets_pairs=sum(all(a['status']=='source_hash_verified' for a in assets if a['candidate_id']==r['candidate_id']) for r in rows),
        verified_events_created=0,scope='Frozen engineering cohort and current source bytes, not visual agreement or population accuracy.',
        cohort_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.summary.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
