"""Freeze pending promo endpoints and source assets without identity approvals."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib,json,re,sqlite3,tarfile
from pathlib import Path
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen
from pokemon_index import number_evidence
from scripts.freeze_relationship_identity_review import source_bytes,digest


def candidate(endpoint, audit):
    path=Path(audit['path']);local=path.stem
    if local.casefold()!=endpoint['collector_number'].split('/')[0].casefold():
        raise ValueError('source file and catalog numerator differ')
    if endpoint['language']=='ja':
        family,release=path.parts[1:3]
    else:
        families={'HeartGold & SoulSilver':'hgss','Mega Evolution':'me','Miscellaneous':'misc','Sun & Moon':'sm'}
        family=families[path.parts[1]];release=endpoint['set_code'].lower()
    return f"https://assets.tcgdex.net/{endpoint['language']}/{family}/{release}/{local}/high.webp"


def fetch(row,cache):
    endpoint=row['endpoint_snapshot'];audit=row['source_audit'];local=Path(audit['path']).stem
    api='https://api.tcgdex.net/v2/'+endpoint['language']+'/cards/'+quote(endpoint['set_code']+'-'+local)
    attempts=[];image_url=None
    result=dict(target_id=row['target_id'],api_url=api,status='asset_hold',attempts=attempts)
    def get(url,limit):
        with urlopen(Request(url,headers={'User-Agent':'pokemon-internal-number-audit/1'}),timeout=20) as r:
            if urlparse(r.url).hostname not in {'api.tcgdex.net','assets.tcgdex.net'}:raise ValueError('unexpected asset redirect')
            body=r.read(limit+1)
        if len(body)>limit:raise ValueError('source too large')
        return body
    try:
        body=get(api,2_000_000);detail=json.loads(body)
        result['api_sha256']=hashlib.sha256(body).hexdigest()
        result['api_details']=detail
        if str(detail.get('localId','')).casefold()!=local.casefold() or str(detail.get('set',{}).get('id','')).casefold()!=endpoint['set_code'].casefold() or detail.get('name')!=endpoint['name']:
            raise ValueError('API card identity differs from pinned source')
        base=detail.get('image')
        if not isinstance(base,str):raise ValueError('API image missing')
        image_url=base.rstrip('/')+'/high.webp';number_evidence._source(image_url)
        attempts.append(dict(route='detail_api',status='source_metadata_bound'))
    except Exception as error:
        attempts.append(dict(route='detail_api',status='unavailable',error_type=type(error).__name__))
        # Convention URL is a candidate, never a claim about its printed text.
        image_url=candidate(endpoint,audit)
        attempts.append(dict(route='pinned_source_path_convention',status='candidate_only'))
    try:
        number_evidence._source(image_url);body=get(image_url,7_000_000)
        if body[:4]!=b'RIFF' or body[8:12]!=b'WEBP':raise ValueError('not a WebP scan')
        path=cache/(row['target_id']+'.webp');path.write_bytes(body)
        result.update(status='source_asset_frozen',source_ref=image_url,image_sha256=hashlib.sha256(body).hexdigest(),image_bytes=len(body),path=str(path.resolve()))
    except Exception as error:
        result.update(source_ref=image_url,error_type=type(error).__name__)
    result['fetched_at']=datetime.now(timezone.utc).isoformat()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','archive','queue','output','assets','cache']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.assets.exists():raise FileExistsError('use fresh outputs')
    a.cache.mkdir(parents=True,exist_ok=True);queue=list(map(json.loads,a.queue.read_text().splitlines()));rows=[]
    if len(queue)!=50 or len({r['card_id'] for r in queue})!=50:raise ValueError('frozen fifty unique targets required')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row
        for i,target in enumerate(queue):
            endpoint=number_evidence.snapshot(db,target['card_id'])
            if any(endpoint[k]!=target[k] for k in ['language','set_code','collector_number','variant','name','provenance','match_eligible']):raise ValueError('research target drift')
            row=dict(schema='pokemon.promo-number-cohort.v1',target_id=f'promo-{i+1:03}',endpoint_snapshot=endpoint,
                source_audit=source_bytes(endpoint['provenance'],archive),identity_sha256=digest(endpoint),
                queue_sha256=hashlib.sha256(a.queue.read_bytes()).hexdigest(),expected_number_observation_supplied_to_reviewers=False)
            row['snapshot_sha256']=digest(row);rows.append(row)
    # Freeze selection before fetching or reviewing assets.
    a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    with ThreadPoolExecutor(max_workers=4) as pool:assets=list(pool.map(lambda r:fetch(r,a.cache),rows))
    a.assets.write_text(json.dumps(assets,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(targets=len(rows),frozen_assets=sum(r['status']=='source_asset_frozen' for r in assets),asset_holds=sum(r['status']=='asset_hold' for r in assets))))
