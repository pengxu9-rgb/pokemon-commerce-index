from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,hashlib,subprocess,base64
from scripts.vertex_concept_review import _call_model,MODEL
from scripts.vertex_relationship_artwork_triage import _mime
r=Path('catalog/cross-release-artwork-v1');pairs=[json.loads(s) for s in Path('/tmp/pokemon-blind-cross-artwork-v1/pairs-v2.jsonl').read_text().splitlines() if json.loads(s)['target_id'] in ['cross-artwork-014']]
prompt='''Inspect both attached source images, labeled left and right. No catalog identities or prior verdicts supplied. Compare illustrated scene details and classify artwork_decision same/different/uncertain. Similar character/composition alone insufficient; ignore translated frame text, cropping and foil effects without assuming scenes identical. Read literal title and full collector text separately, preserving absent denominators and symbols as uncertainty. Return exactly artwork_decision, rationale (specific shared/different scene), uncertainties (string), readings (two objects side left/right, name, collector_number). Do not establish finish, physical variant, condition, identity, scarcity, or price.'''
p=dict(schema='pokemon.blind-same-language-artwork-protocol.v1',model=MODEL,model_family='google',prompt=prompt,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),expected_catalog_context_visible=False,prior_verdicts_visible=False,selection='3 same-language controls; old cross-language runner cannot bind two same-language images',pairs=pairs)
(r/'gemini-controls-protocol-v2.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n');token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True,stderr=subprocess.DEVNULL).strip()
def one(pair):
 out=dict(target_id=pair['target_id'],actor='vertex:'+MODEL+':blind-artwork-control-v1',model_family='google',model_version=MODEL,expected_catalog_context_visible=False,prior_verdicts_visible=False,protocol_sha256=hashlib.sha256((r/'gemini-controls-protocol-v2.json').read_bytes()).hexdigest(),status='review_failed')
 try:
  parts=[dict(text=prompt)]
  for im in pair['images']:
   body=Path(im['image_path']).read_bytes();assert hashlib.sha256(body).hexdigest()==im['image_sha256'];parts+=[dict(text=im['side']),dict(inlineData=dict(mimeType=_mime(body),data=base64.b64encode(body).decode()))]
  response=_call_model('pivota-staging','global',token,dict(contents=[dict(role='user',parts=parts)],generationConfig=dict(responseMimeType='application/json',maxOutputTokens=2000)));out['model_response']=response;assert response['modelVersion']==MODEL and response['candidates'][0]['finishReason']=='STOP';raw=''.join(x.get('text','') for x in response['candidates'][0]['content']['parts']);finding=json.loads(raw);assert set(finding)=={'artwork_decision','rationale','uncertainties','readings'};assert finding['artwork_decision'] in ['same','different','uncertain'];assert {x['side'] for x in finding['readings']}=={'left','right'};out.update(finding,status='reviewed',response_sha256=hashlib.sha256(raw.encode()).hexdigest())
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc)[:200])
 out['reviewed_at']=datetime.now(timezone.utc).isoformat();return out
with ThreadPoolExecutor(max_workers=3) as ex,(r/'gemini-controls-review-v2.jsonl').open('x') as f:
 for out in ex.map(one,pairs):f.write(json.dumps(out,ensure_ascii=False,sort_keys=True)+'\n');f.flush();print(json.dumps(dict(target_id=out['target_id'],status=out['status'])),flush=True)
