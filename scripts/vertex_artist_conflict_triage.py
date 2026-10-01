"""Search-assisted advisory triage; never approve aliases or physical identity."""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL='gemini-3.8-flash'


def run(queue,output):
    if output.exists():raise FileExistsError(output)
    rows=[json.loads(l) for l in queue.read_text().splitlines()]
    token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True,timeout=30).strip()
    endpoint='https://aiplatform.googleapis.com/v1/projects/pivota-staging/locations/global/publishers/google/models/'+MODEL+':generateContent'
    def review(row):
        prompt=('Investigate this exact Japanese Pokemon TCG illustrator-credit conflict. '
            'Use Google Search to find independent exact-card evidence, prioritizing the rights-holder official page or a readable printed-card credit. '
            'An artist-string similarity, marketplace name or AI memory alone cannot resolve this conflict. '
            'The official website may have a typography error; a different promo may have a different illustrator. '
            'Return JSON with diagnosis, proposed_credit, evidence_urls, evidence_limits, and confidence (low/medium/high). '
            'Explicitly say unresolved if evidence is absent. Do not approve artist aliases, physical printing, counterpart or price equivalence. '
            'This is advisory research only. Exact case: '+json.dumps(row,ensure_ascii=False))
        request=dict(contents=[dict(role='user',parts=[dict(text=prompt)])],tools=[dict(googleSearch={})],
                     generationConfig=dict(temperature=0,maxOutputTokens=1600))
        data=json.dumps(request,ensure_ascii=False).encode()
        result=dict(card_id=row['card_id'],model=MODEL,project='pivota-staging',
            queue_sha256=hashlib.sha256(queue.read_bytes()).hexdigest(),
            request_sha256=hashlib.sha256(data).hexdigest(),automatic_import_allowed=False)
        try:
            req=urllib.request.Request(endpoint,data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=45) as response:
                raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('model response exceeds bound')
            body=json.loads(raw);candidates=body.get('candidates') or []
            if not candidates:raise ValueError('no model candidate')
            c=candidates[0]
            text=''.join(p.get('text','') for p in c.get('content',{}).get('parts',[]) if not p.get('thought'))
            result.update(status='advisory_response',response_sha256=hashlib.sha256(raw).hexdigest(),
                finish_reason=c.get('finishReason'),response_text=text,
                grounding_metadata=c.get('groundingMetadata'),usage_metadata=body.get('usageMetadata'))
        except Exception as e:
            result.update(status='unavailable',error_type=type(e).__name__,error=str(e)[:240])
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(review,rows))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in results))
    summary=dict(model=MODEL,cases=len(results),advisory_responses=sum(r['status']=='advisory_response' for r in results),
        unavailable=sum(r['status']=='unavailable' for r in results),automatic_import_allowed=False,
        review_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('queue','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.queue,a.output)))
