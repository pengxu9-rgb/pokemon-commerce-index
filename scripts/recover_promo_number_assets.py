import concurrent.futures,datetime,hashlib,json,pathlib,re,sqlite3,urllib.request
root=pathlib.Path.cwd();p=root/'catalog/promo-number-expansion-v1';cohort=list(map(json.loads,(p/'cohort-v1.jsonl').read_text().splitlines()));assets=json.loads((p/'assets-v1.json').read_text());c=sqlite3.connect('/tmp/pokemon-number-readings-v1.sqlite3')
from scripts.freeze_relationship_identity_review import digest
if (p/'cohort-v2.jsonl').exists() or (p/'assets-v2.json').exists():raise FileExistsError('official recovery outputs already exist; use a new batch directory')
for row in cohort:
 e=row['endpoint_snapshot'];row['official_coordinate_refs']=[dict(native_id=r[0],source_url='https://www.pokemon-card.com/card-search/details.php/card/'+r[0]) for r in c.execute('SELECT native_id FROM effective_card_reference WHERE set_code=? AND collector_number=? ORDER BY native_id',(e['set_code'],e['collector_number']))] if e['language']=='ja' else []
 row['prior_cohort_snapshot_sha256']=row.pop('snapshot_sha256');row['snapshot_sha256']=digest(row)
(p/'cohort-v2.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in cohort))
def recover(pair):
 row,old=pair
 if old['status']=='source_asset_frozen' or not row['official_coordinate_refs']:return old
 out=dict(old);out['prior_asset_sha256']=digest(old);out['attempts']=list(old['attempts']);ref=row['official_coordinate_refs'][0]
 out['official_coordinate_reference_count']=len(row['official_coordinate_refs']);out['reference_selection_scope']='First sorted existing coordinate reference only; no physical source-variant assignment or completeness.'
 try:
  def get(url,limit):
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'pokemon-internal-number-audit/1'}),timeout=30) as r:
    if not r.url.startswith('https://www.pokemon-card.com/'):raise ValueError('unexpected publisher redirect')
    body=r.read(limit+1)
   if len(body)>limit:raise ValueError('publisher asset too large')
   return body
  page=get(ref['source_url'],2_000_000);out['official_page_sha256']=hashlib.sha256(page).hexdigest()
  imgs={m.decode() for m in re.findall(rb'(?:https://www.pokemon-card.com)?(/assets/images/card_images/(?:large|legend)/[^"\s<>]+\.jpg)',page)}
  if len(imgs)!=1:raise ValueError('ambiguous publisher image')
  image_url='https://www.pokemon-card.com'+next(iter(imgs))
  if not image_url.rsplit('/',1)[-1].startswith(ref['native_id'].zfill(6)+'_'):raise ValueError('publisher image ID differs')
  body=get(image_url,7_000_000)
  if not body.startswith(b'\xff\xd8\xff'):raise ValueError('not publisher JPEG')
  path=pathlib.Path('/tmp/promo-number-expansion-v1-images')/(row['target_id']+'.jpg');path.write_bytes(body)
  out.update(status='source_asset_frozen',source_ref=ref['source_url'],image_url=image_url,image_sha256=hashlib.sha256(body).hexdigest(),image_bytes=len(body),path=str(path.resolve()),fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat());out.pop('error_type',None)
  out['attempts'].append(dict(route='existing_official_coordinate_reference',status='source_image_id_bound'))
 except Exception as e:out['attempts'].append(dict(route='existing_official_coordinate_reference',status='asset_hold',error_type=type(e).__name__))
 return out
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:final=list(pool.map(recover,zip(cohort,assets)))
(p/'assets-v2.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n');print('frozen',sum(a['status']=='source_asset_frozen' for a in final),'holds',sum(a['status']=='asset_hold' for a in final));c.close()
