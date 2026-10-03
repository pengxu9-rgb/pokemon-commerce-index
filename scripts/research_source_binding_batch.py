from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import json,sqlite3,hashlib,re,subprocess
from scripts.audit_japanese_metadata_batch import fetch,parse_page
from scripts.vertex_concept_review import _call_model,MODEL
from pokemon_index import number_evidence as n,supported_catalog
root=Path('catalog/source-binding-v1');root.mkdir(exist_ok=False)
queue=[json.loads(l) for l in Path('catalog/source-notation-v1/next-source-targets-v1.jsonl').read_text().splitlines()]
db=sqlite3.connect('file:/tmp/pokemon-source-notation-v1.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row
frozen=[]
for q in queue:
 snap=n.snapshot(db,q['card_id'])
 refs=[dict(r) for r in db.execute('SELECT * FROM card_reference WHERE set_code=? AND collector_number=?',(snap['set_code'],snap['collector_number']))] if snap['language']=='ja' else []
 fact=db.execute('SELECT record_json FROM source_image_fact_evidence WHERE card_id=? ORDER BY revision DESC LIMIT 1',(q['card_id'],)).fetchone()
 frozen.append(dict(priority=q,endpoint_snapshot=snap,identity_sha256=supported_catalog.digest(snap),references=refs,latest_fact=json.loads(fact[0]) if fact else None))
(root/'frozen-cohort-v1.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in frozen))
cache=root/'publisher';cache.mkdir()
def one(q):
 result=dict(card_id=q['priority']['card_id'],reason=q['priority']['reason'],official_attempts=[])
 for ref in q['references']:
  url='https://www.pokemon-card.com/card-search/details.php/card/'+ref['native_id']
  try:
   raw,receipt=fetch(url,cache);parsed=parse_page(raw);body=raw.decode()
   image_urls=re.findall(r'(?:src|content)="([^"]*/assets/images/card_images/[^"]+)"',body)
   result['official_attempts'].append(dict(receipt=receipt,parsed=parsed,image_urls=sorted(set(image_urls)),
    prism_rule_present='（プリズムスター）のカードは' in re.sub('<[^>]+>','',body),
    title_symbol_present='icon-prism' in body or 'プリズムスター' in body,
    exact_number=sum(e['set_code']==q['endpoint_snapshot']['set_code'] and e['collector_number']==q['endpoint_snapshot']['collector_number'] for e in parsed['numbered_entries'])==1))
  except Exception as e:result['official_attempts'].append(dict(url=url,status='fetch_or_parse_hold',error_type=type(e).__name__,error=str(e)[:200]))
 return result
with ThreadPoolExecutor(max_workers=4) as pool:
 rows=list(pool.map(one,frozen))
(root/'official-audit-v1.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rows))
print(json.dumps(dict(subjects=len(rows),official_requests=sum(len(x['official_attempts']) for x in rows),parsed=sum('parsed' in a for x in rows for a in x['official_attempts']),exact_coordinates=sum(a.get('exact_number',False) for x in rows for a in x['official_attempts']))),flush=True)
prompts=[
"Find primary pokemon-card.com sources explaining Prism Star title symbols and identify official source support for SM8b Lunala047/150 and SM12a Shaymin011/173. Give exact page URLs, distinguish base name from the mechanic symbol, and any gaps. No market prices or physical printing approval.",
"Find primary pokemon-card.com or 30th.pokemon-card.com sources for M6a Pikachu017/103 also showing01/30: what does the second numbering namespace mean? Also seek exact official M6a104-121/103,124/103 and Mew G/R images. Do not substitute MF011/040 or another same-name card. Give exact URLs and unresolved gaps, not inferred answers."
]
token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True,stderr=subprocess.DEVNULL).strip()
for i,prompt in enumerate(prompts,1):
 protocol=dict(model=MODEL,prompt=prompt,google_search_grounding_enabled=True,catalog_context_visible=True,prior_verdicts_visible=False,scope='Source discovery; not independent image review or label',requested_at=datetime.now(timezone.utc).isoformat())
 (root/f'grounded-protocol-{i}-v1.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
 try:
  response=_call_model('pivota-staging','global',token,dict(contents=[dict(role='user',parts=[dict(text=prompt)])],tools=[dict(googleSearch={})],generationConfig=dict(maxOutputTokens=8192)))
  (root/f'grounded-response-{i}-v1.json').write_text(json.dumps(dict(response=response,completed_at=datetime.now(timezone.utc).isoformat()),ensure_ascii=False,indent=2)+'\n')
  print(json.dumps(dict(research=i,model=response.get('modelVersion'),finish=[c.get('finishReason') for c in response.get('candidates',[])])),flush=True)
 except Exception as e:
  (root/f'grounded-error-{i}-v1.json').write_text(json.dumps(dict(error_type=type(e).__name__,error=str(e)[:300]))+'\n')
  print(json.dumps(dict(research=i,error_type=type(e).__name__)),flush=True)

