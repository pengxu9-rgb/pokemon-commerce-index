"""Source-led control diagnostic through local/private HTTP and actual Node caller."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pokemon_index import core,card_comparison,collector_discovery,collector_journey,discovery_graph
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha,semantic

def run(db_path,output,*,cloud=False):
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1];directory=root/'catalog/artwork-controls-v1'
    questions_path=directory/'questions-frozen-v1.jsonl';lock=json.loads((directory/'question-freeze.json').read_text())
    if sha(questions_path)!=lock['sha256']:raise ValueError('frozen questions changed')
    correction=json.loads((directory/'question-contract-correction-v1.json').read_text())
    if correction['original_questions_sha256']!=sha(questions_path) or correction['actual_public_task_label']!='two_card_comparison':raise ValueError('diagnostic task correction changed')
    questions=list(map(json.loads,questions_path.read_text().splitlines()));cohort={r['candidate_id']:r for r in map(json.loads,(directory/'cohort.jsonl').read_text().splitlines())}
    outcomes={r['candidate_id']:r for r in json.loads((directory/'review-summary-final.json').read_text())['results']}
    events=list(map(json.loads,(directory/'qualified-difference-events-final.jsonl').read_text().splitlines()))
    before=sha(db_path);server=None;thread=None;token=None;deployment=None;completed=False;revision=None;checks=[];errors=[];error_lock=threading.Lock()
    def gcloud(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
    if cloud:
        service=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1');iam=gcloud('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
        if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):raise ValueError('public invoker')
        ready=service['status']['latestReadyRevisionName']
        if sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==ready)!=100:raise ValueError('partial traffic')
        detail=gcloud('run','revisions','describe',ready,'--region=us-west1');base=service['status']['url']
        deployment=dict(revision=ready,url=base,image=detail['status']['imageDigest'],private_iam_verified=True)
        token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    else:
        server=create_server(str(db_path),'127.0.0.1',0,True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_address[1])
    def query(path,params=None,payload=None,authenticated=True):
        headers={'Authorization':'Bearer '+token} if token and authenticated else {};body=json.dumps(payload).encode() if payload is not None else None
        if body is not None:headers['Content-Type']='application/json'
        request=Request(base+path+('?' + urlencode(params) if params else ''),headers=headers,data=body)
        for attempt in range(1,4):
            try:
                with urlopen(request,timeout=30) as response:return response.status,json.load(response)
            except HTTPError as error:
                try:value=json.load(error)
                except (ValueError,UnicodeDecodeError):value=None
                return error.code,value
            except (URLError,TimeoutError) as error:
                with error_lock:errors.append(dict(path=path,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    def qualification(q,comparison):
        assert comparison['status']=='catalog_partial'
        assert not comparison['same_physical_printing_established'] and not comparison['price_comparable'] and not comparison['purchase_ready']
        assert not comparison['prices'] and not comparison['live_offers'] and not comparison['complete_answer_established']
        art=comparison['artwork']
        if q['kind']=='visual_control':
            result=outcomes[q['candidate_id']]
            if result['status']=='qualified_artwork_difference':
                assert any(e['assertion_id']==result['graph_event_id'] for e in art['reviewed_difference_links'])
                assert not art['reviewed_links']
            elif result['status']=='positive_control_agreement':
                assert any(sorted([e['left_card_id'],e['right_card_id']])==q['pair'] for e in art['reviewed_links'])
                assert not art['reviewed_difference_links']
            else:assert not art['reviewed_links'] and not art['reviewed_difference_links']
        else:
            assert not art['reviewed_links'] and not art['reviewed_difference_links']
            if q['kind']=='identity_hold':assert any(e['endpoint_identity_blockers'] for e in art['other_pair_states'])
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db);expected=[];exact={}
            for q in questions:
                result=collector_discovery.execute(db,q['question'])
                assert result['task']==correction['actual_public_task_label'] and not result['complete_answer_established']
                qualification(q,result['comparison']);expected.append(dict(question=q,local=result))
                pair=tuple(q['pair'])
                if pair not in exact:
                    payload=dict(left=dict(card_id=pair[0]),right=dict(card_id=pair[1]));value=card_comparison.compare(db,payload);qualification(q,value)
                    exact[pair]=dict(question=q,payload=payload,local=value)
            def natural(item):
                code,actual=query('/collector-discovery',params=dict(q=item['question']['question']))
                return dict(id=item['question']['id'],route='natural-comparison',passed=code==200 and semantic(actual)==semantic(item['local']),actual=actual,local=item['local'])
            def structured(item):
                code,actual=query('/card-comparison',payload=item['payload'])
                return dict(id=item['question']['id'],route='structured-comparison',passed=code==200 and semantic(actual)==semantic(item['local']),actual=actual,local=item['local'])
            with ThreadPoolExecutor(max_workers=3) as pool:checks.extend(pool.map(natural,expected))
            with ThreadPoolExecutor(max_workers=3) as pool:checks.extend(pool.map(structured,exact.values()))
            assert all(c['passed'] for c in checks)
            representatives=[questions[i] for i in [0,3,18,24,36,48]]
            inputs=dict(baseUrl=base,token=token,allowLoopback=not cloud,journeys=[dict(id=q['id'],steps=[dict(action=dict(type='ask',question=q['question']))]) for q in representatives])
            node=subprocess.run(['node',str(root/'integrations/pivota/replay.cjs')],input=json.dumps(inputs),text=True,capture_output=True,check=True);calls=json.loads(node.stdout);assert len(calls)==6
            for q,call in zip(representatives,calls):
                local=collector_journey.replay(db,dict(turns=[dict(type='ask',question=q['question'])],limit=20),revision=revision)
                passed=semantic(call.get('call',{}).get('result'))==semantic(local)
                checks.append(dict(id=q['id'],route='node-caller',passed=passed,result=call))
            assert all(c['passed'] for c in checks)
            for event in events:
                card_id=event['left_card_id'];local=discovery_graph.card_neighborhood(db,card_id)
                assert any(e['assertion_id']==event['assertion_id'] for e in local['reviewed_artwork_differences'])
                assert not any(e['assertion_id']==event['assertion_id'] for e in local['relationships'])
                code,actual=query('/catalog-neighborhood',params=dict(card_id=card_id))
                passed=code==200 and semantic(actual)==semantic(local);checks.append(dict(id=event['assertion_id'],route='negative-neighborhood',passed=passed,actual=actual,local=local));assert passed
            code,actual=query('/catalog-status');passed=code==200 and actual==core.catalog_status(db);checks.append(dict(id='catalog-status',passed=passed,result=actual));assert passed
            first=next(iter(exact.values()))['payload']
            for i,payload in enumerate([dict(first,price_comparable=True),dict(left=first['left'],right=first['left']),dict(left=dict(first['left'],reviewed_difference=True),right=first['right'])]):
                code,actual=query('/card-comparison',payload=payload);checks.append(dict(id='invalid:'+str(i),passed=code==400,result=actual));assert code==400
            if cloud:
                for route,payload in [('/health',None),('/card-comparison',first)]:
                    code,_=query(route,payload=payload,authenticated=False);checks.append(dict(id='unauthenticated:'+route,passed=code==403,status=code));assert code==403
                after=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1');assert after['status']['latestReadyRevisionName']==ready
                deployment['revision_unchanged_after_verification']=True
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        unchanged=sha(db_path)==before
        report=dict(schema='pokemon.artwork-controls-rehearsal.v1',completed=completed,planned_checks=107 if cloud else 105,checks=len(checks),passed=sum(c['passed'] for c in checks),results=checks,
            source_led_authored_questions=54,unique_structured_pairs=30,node_caller_journeys=6,negative_neighborhoods=11,environment='private-staging' if cloud else 'local-http',deployment=deployment,catalog_sha256=before,catalog_bytes_unchanged=unchanged,catalog_revision=revision,transport_errors=errors,
            questions_sha256=sha(questions_path),diagnostic_contract_correction_sha256=sha(directory/'question-contract-correction-v1.json'),difference_events_sha256=sha(directory/'qualified-difference-events-final.jsonl'),
            runtime_sha256={name:sha(root/'pokemon_index'/name) for name in ['card_comparison.py','discovery_graph.py','collector_discovery.py','collector_journey.py','cli.py']},
            population_or_real_marketplace_accuracy_established=False,pivota_registration_established=False,physical_or_market_approvals_added=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not unchanged:raise ValueError('rehearsal changed catalog bytes')
    return dict(checks=report['checks'],passed=report['passed'],completed=completed,transport_errors=len(errors),deployment=deployment)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.db,a.output,cloud=a.cloud)))
