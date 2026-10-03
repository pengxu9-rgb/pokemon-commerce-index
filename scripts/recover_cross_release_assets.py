"""Freeze coordinate references before recovering unavailable Japanese scans."""
from __future__ import annotations
import argparse,datetime,hashlib,json,re,sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse
from scripts.freeze_relationship_identity_review import digest

def recover(row,old,cache):
    if old['status']=='source_asset_frozen' or not row['official_coordinate_refs']:return old
    out=dict(old,prior_asset_sha256=digest(old),attempts=list(old['attempts']))
    ref=row['official_coordinate_refs'][0]
    out.update(official_coordinate_reference_count=len(row['official_coordinate_refs']),
        reference_selection_scope='First sorted existing coordinate reference only; no physical source-variant assignment or completeness.')
    try:
        def get(url,limit):
            with urlopen(Request(url,headers={'User-Agent':'pokemon-internal-source-audit/1'}),timeout=30) as response:
                if urlparse(response.url).scheme!='https' or urlparse(response.url).netloc!='www.pokemon-card.com':raise ValueError('unexpected publisher redirect')
                body=response.read(limit+1)
            if len(body)>limit:raise ValueError('publisher source too large')
            return body
        page=get(ref['source_url'],2_000_000);out['official_page_sha256']=hashlib.sha256(page).hexdigest()
        imgs={m.decode() for m in re.findall(rb'(?:https://www.pokemon-card.com)?(/assets/images/card_images/(?:large|legend)/[^"\s<>]+\.jpg)',page)}
        if len(imgs)!=1:raise ValueError('ambiguous publisher image')
        image_url='https://www.pokemon-card.com'+next(iter(imgs))
        if not image_url.rsplit('/',1)[-1].startswith(ref['native_id'].zfill(6)+'_'):raise ValueError('publisher image ID differs')
        body=get(image_url,7_000_000)
        if not body.startswith(b'\xff\xd8\xff'):raise ValueError('publisher JPEG missing')
        path=cache/(row['target_id']+'.jpg');path.write_bytes(body)
        out.update(status='source_asset_frozen',source_ref=ref['source_url'],image_url=image_url,image_sha256=hashlib.sha256(body).hexdigest(),image_bytes=len(body),path=str(path.resolve()),fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        out.pop('error_type',None)
        out['attempts'].append(dict(route='existing_official_coordinate_reference',status='source_image_id_bound'))
    except Exception as error:out['attempts'].append(dict(route='existing_official_coordinate_reference',status='asset_hold',error_type=type(error).__name__))
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['db','queue','prior-assets','bound-targets','assets','cache']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--expected-targets',type=int,default=100)
    a=p.parse_args()
    if a.bound_targets.exists() or a.assets.exists():raise FileExistsError('use new recovery outputs')
    rows=list(map(json.loads,a.queue.read_text().splitlines()));old=json.loads(a.prior_assets.read_text())
    if a.expected_targets<1 or len(rows)!=a.expected_targets or len({r['target_id'] for r in rows})!=a.expected_targets or len(old)!=a.expected_targets or {r['target_id'] for r in rows}!={r['target_id'] for r in old}:raise ValueError('complete frozen cohort required')
    old={r['target_id']:r for r in old}
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db:
        for row in rows:
            if digest({k:v for k,v in row.items() if k!='snapshot_sha256'})!=row['snapshot_sha256']:raise ValueError('target hash changed')
            e=row['endpoint_snapshot']
            row['official_coordinate_refs']=[dict(native_id=r[0],source_url='https://www.pokemon-card.com/card-search/details.php/card/'+r[0]) for r in db.execute('SELECT native_id FROM effective_card_reference WHERE set_code=? AND collector_number=? ORDER BY native_id',(e['set_code'],e['collector_number']))] if e['language']=='ja' else []
            row['prior_target_snapshot_sha256']=row.pop('snapshot_sha256');row['snapshot_sha256']=digest(row)
    a.bound_targets.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    a.cache.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:out=list(pool.map(lambda r:recover(r,old[r['target_id']],a.cache),rows))
    a.assets.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(targets=len(out),frozen_assets=sum(r['status']=='source_asset_frozen' for r in out),asset_holds=sum(r['status']=='asset_hold' for r in out))))
