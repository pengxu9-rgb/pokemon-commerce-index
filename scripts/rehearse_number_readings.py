"""Check exact number-readings through private HTTP; retain original evidence."""
from __future__ import annotations
import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pokemon_index import core, card_comparison, collector_journey
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha, semantic


def run(db_path, output, cloud=False):
    if output.exists(): raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1]
    evidence_path=root/'catalog/number-readings-v1/evidence-v1.jsonl'
    rows=list(map(json.loads,evidence_path.read_text().splitlines()))
    cohort=list(map(json.loads,(root/'catalog/artwork-controls-v1/cohort.jsonl').read_text().splitlines()))
    controls=json.loads((root/'catalog/artwork-controls-v1/variant-controls.json').read_text())
    before=sha(db_path); server=None; thread=None; deployment=None; token=None
    checks=[]; errors=[]; completed=False; revision=None
    def gcloud(*args): return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
    if cloud:
        service=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1')
        iam=gcloud('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
        if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):raise ValueError('public invoker')
        ready=service['status']['latestReadyRevisionName']
        if sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==ready)!=100:raise ValueError('partial traffic')
        detail=gcloud('run','revisions','describe',ready,'--region=us-west1'); base=service['status']['url']
        deployment=dict(revision=ready,url=base,image=detail['status']['imageDigest'],private_iam_verified=True)
        token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    else:
        server=create_server(str(db_path),'127.0.0.1',0,True)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
    def query(route, params=None, payload=None, auth=True):
        headers={'Authorization':'Bearer '+token} if auth and token else {}
        if payload is not None:headers['Content-Type']='application/json'
        req=Request(base+route+('?' + urlencode(params) if params else ''),headers=headers,
                    data=json.dumps(payload).encode() if payload is not None else None)
        for attempt in range(1,4):
            try:
                with urlopen(req,timeout=30) as r:return r.status,json.load(r)
            except HTTPError as e:
                try:body=json.load(e)
                except ValueError:body=None
                return e.code,body
            except (URLError,TimeoutError) as e:
                errors.append(dict(route=route,attempt=attempt,error_type=type(e).__name__))
                if attempt==3:raise
    def check(key, passed, actual):
        checks.append(dict(id=key,passed=bool(passed),actual=actual))
        if not passed:raise AssertionError(key)
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses=list(pool.map(lambda r:query('/catalog-card',{'card_id':r['card_id']}),rows))
            for row,(code,actual) in zip(rows,responses):
                expected=core.catalog_card_internal(db,row['card_id'])
                reading=actual['number_context']['observed_printed_number']
                check('exact:'+row['card_id'],code==200 and semantic(actual)==semantic(expected)
                      and reading['visible_text_agreement'] and not reading['catalog_identity_confirmed']
                      and actual['number_context']['catalog_number']==row['endpoint_snapshot']['collector_number'],
                      dict(card_id=row['card_id'],number_context=actual['number_context']))
            for pair in cohort:
                request=dict(left=dict(card_id=pair['endpoints'][0]['card_id']),right=dict(card_id=pair['endpoints'][1]['card_id']))
                code,actual=query('/card-comparison',payload=request)
                check('comparison:'+pair['candidate_id'],code==200 and semantic(actual)==semantic(card_comparison.compare(db,request))
                      and not actual['numbering']['printed_number_equivalence_established']
                      and not actual['price_comparable'] and not actual['purchase_ready'],
                      dict(numbering=actual['numbering'],left=actual['left']['observed_printed_numbers'],right=actual['right']['observed_printed_numbers']))
            # These exact sibling labels were frozen before the number layer.
            for control in controls:
                cid=control['changed_card_id']
                code,actual=query('/catalog-card',{'card_id':cid})
                check('sibling:'+cid,code==200 and actual['number_context']['observed_printed_number'] is None,
                      dict(card_id=cid,observed_printed_number=actual['number_context']['observed_printed_number']))
            code,actual=query('/catalog-status')
            check('catalog-status',code==200 and actual==core.catalog_status(db) and actual['display_approved']==0,
                  dict(printings=actual['printings'],number_reading_evidence=actual['number_reading_evidence']))
            if cloud:
                for route in ['/catalog-status','/catalog-card']:
                    code,_=query(route,{'card_id':rows[0]['card_id']} if route=='/catalog-card' else None,auth=False)
                    check('unauthenticated:'+route,code==403,dict(status=code))
                after=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1')
                assert after['status']['latestReadyRevisionName']==ready
                deployment['revision_unchanged_after_verification']=True
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        unchanged=sha(db_path)==before
        report=dict(schema='pokemon.number-readings-rehearsal.v1',completed=completed,planned_checks=57 if cloud else 55,
            checks=len(checks),passed=sum(r['passed'] for r in checks),results=checks,transport_errors=errors,
            deployment=deployment,catalog_sha256=before,catalog_bytes_unchanged=unchanged,catalog_revision=revision,
            evidence_sha256=sha(evidence_path),runtime_sha256={name:sha(root/'pokemon_index'/name) for name in
            ['number_evidence.py','number_graph.py','card_comparison.py','collector_journey.py','core.py','cli.py']},
            real_marketplace_precision_established=False,physical_or_market_approvals_added=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not unchanged:raise ValueError('number diagnostic changed catalog')
    return {k:report[k] for k in ['completed','checks','passed','deployment']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.db,a.output,a.cloud)))
