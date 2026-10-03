from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json,re,hashlib,urllib.request,tarfile
from scripts.freeze_relationship_identity_review import source_bytes
root=Path('catalog/source-binding-v1');s=(root/'publisher-m6a-page-bundle-v1.js').read_text()
matches=re.findall(r"JSON.parse\('(\[.*?\])'\)",s)
arrays=[]
for raw in matches:
 try:
  x=json.loads(raw)
  if isinstance(x,list) and x and isinstance(x[0],dict) and 'fileName' in x[0]:arrays.append(x)
 except ValueError:pass
assert len(arrays)==1
rows=arrays[0];assert len(rows)==len({r['no'] for r in rows})
(root/'official-m6a-card-list-v1.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
queue=[json.loads(l) for l in (root/'frozen-cohort-v1.jsonl').read_text().splitlines()]
selected=[];held=[]
with tarfile.open('../../work/tcgdex-complete-a211f11f3ba57d56c65c5ac33be35b77d3280757.tar.gz') as archive:
 for q in queue:
  if q['priority']['reason']!='missing_source_asset':continue
  snap=q['endpoint_snapshot'];num=snap['collector_number'].split('/')[0]
  hits=[r for r in rows if r['no']==num and r['name']==snap['name'] and snap['set_code']=='M6A']
  if len(hits)!=1:
   held.append(dict(card_id=snap['card_id'],status='no_exact_product_list_candidate'));continue
  r=hits[0];url='https://www.30th.pokemon-card.com/images/m6a/cards/'+r['fileName']+'.png'
  assert re.fullmatch(r'https://www\.30th\.pokemon-card\.com/images/m6a/cards/m6a_\d{3}_[a-z0-9]+\.png',url)
  item=dict(target_id=f"recovered-{len(selected)+1:02}",endpoint_snapshot=snap,identity_sha256=q['identity_sha256'],source_audit=source_bytes(snap['provenance'],archive),
    product_list_record=r,product_list_sha256=hashlib.sha256((root/'official-m6a-card-list-v1.json').read_bytes()).hexdigest(),
    bundle_sha256=hashlib.sha256((root/'publisher-m6a-page-bundle-v1.js').read_bytes()).hexdigest(),image_candidate_url=url)
  item['snapshot_sha256']=hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest();selected.append(item)
(root/'recovered-cohort-v1.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in selected))
cache=Path('/tmp/pokemon-source-binding-images-v1');cache.mkdir(exist_ok=True)
def one(row):
 try:
  with urllib.request.urlopen(row['image_candidate_url'],timeout=30) as response:
   assert response.geturl()==row['image_candidate_url'];b=response.read(7000001)
  assert len(b)<7000001 and b.startswith(b'\x89PNG\r\n\x1a\n')
  p=cache/(row['target_id']+'.png');p.write_bytes(b)
  return dict(target_id=row['target_id'],image_url=row['image_candidate_url'],image_sha256=hashlib.sha256(b).hexdigest(),path=str(p),status='acquired_candidate',fetched_at=datetime.now(timezone.utc).isoformat())
 except Exception as e:return dict(target_id=row['target_id'],status='asset_hold',error_type=type(e).__name__)
with ThreadPoolExecutor(max_workers=4) as pool:assets=list(pool.map(one,selected))
(root/'recovered-assets-v1.json').write_text(json.dumps(dict(assets=assets,held=held),ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(product_records=len(rows),selected=len(selected),acquired=sum(x['status']=='acquired_candidate' for x in assets),held=len(held))))

