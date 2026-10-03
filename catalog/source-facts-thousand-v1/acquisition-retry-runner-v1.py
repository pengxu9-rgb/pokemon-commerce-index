import json,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from scripts.freeze_promo_number_reviews import fetch
from scripts.recover_cross_release_assets import recover
from scripts.freeze_relationship_identity_review import digest
root=Path('catalog/source-facts-thousand-v1'); rows={r['target_id']:r for r in map(json.loads,(root/'bound-targets-v1.jsonl').read_text().splitlines())};old=json.loads((root/'assets-v2.json').read_text());cache=Path('/tmp/pokemon-source-facts-thousand-v1-retry-images');cache.mkdir(exist_ok=True)
def decode(a):
 if a['status']=='source_asset_frozen':
  try:
   if hashlib.sha256(Path(a['path']).read_bytes()).hexdigest()!=a['image_sha256']:raise ValueError('image hash drift')
   with Image.open(a['path']) as im:im.load();size=list(im.size)
   return dict(a,decode_status='decoded',image_size=size)
  except Exception as e:return dict(a,status='asset_hold',decode_status='decode_failed',decode_error=str(e))
 return a
first=list(map(decode,old));(root/'assets-v3.json').write_text(json.dumps(first,ensure_ascii=False,indent=2)+'\n')
def retry(a):
 if a['status']=='source_asset_frozen':return a
 row=rows[a['target_id']]
 try:
  if a.get('source_ref','').startswith('https://www.pokemon-card.com/'):
   b=recover(row,a,cache)
  else:
   b=fetch(row,cache)
   if b['status']!='source_asset_frozen':b=recover(row,b,cache)
  b=decode(b);b['prior_asset_sha256']=digest(a)
  return b
 except Exception as e:return dict(a,retry_error_type=type(e).__name__)
with ThreadPoolExecutor(max_workers=4) as pool:final=list(pool.map(retry,first))
(root/'assets-v4.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(targets=len(final),decoded=sum(a.get('decode_status')=='decoded' for a in final),holds=sum(a['status']!='source_asset_frozen' for a in final))))
