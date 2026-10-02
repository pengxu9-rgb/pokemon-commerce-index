"""Replay frozen authored comparisons and exact source-bound artwork additions."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pokemon_index import core,card_comparison,collector_discovery,collector_journey
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha,semantic


def run(db_path,output,*,cloud=False):
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1];directory=root/'catalog/relationship-expansion-v3'
    questions_path=directory/'questions-frozen-v1.jsonl';lock=json.loads((directory/'question-freeze.json').read_text())
    if sha(questions_path)!=lock['sha256']:raise ValueError('frozen questions changed')
    questions=list(map(json.loads,questions_path.read_text().splitlines()))
    events=list(map(json.loads,(directory/'verified-artwork-events.jsonl').read_text().splitlines()))
    event_pairs={tuple(sorted((r['left_card_id'],r['right_card_id']))):r['assertion_id'] for r in events}
    before=sha(db_path);server=None;thread=None;token=None;deployment=None;completed=False
    transport_errors=[];error_lock=threading.Lock();checks=[]
    if cloud:
        def gcloud(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
        service=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1')
        iam=gcloud('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
        if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):raise ValueError('public invoker binding')
        ready=service['status']['latestReadyRevisionName']
        if sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==ready)!=100:raise ValueError('partial revision traffic')
        detail=gcloud('run','revisions','describe',ready,'--region=us-west1')
        deployment=dict(revision=ready,url=service['status']['url'],image=detail['status']['imageDigest'],private_iam_verified=True)
        base=service['status']['url'];token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    else:
        server=create_server(str(db_path),'127.0.0.1',0,True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_address[1])
    def query(path,params=None,payload=None,authenticated=True):
        headers={'Authorization':'Bearer '+token} if token and authenticated else {}
        body=json.dumps(payload).encode() if payload is not None else None
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
                with error_lock:transport_errors.append(dict(path=path,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    revision=None
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db);expected_questions=[];directs=[]
            for question in questions:
                result=collector_discovery.execute(db,question['question']);comparison=result.get('comparison',{})
                assert result['task']==question['expected_task'] and (comparison['status']=='scope_confirmation_needed')==question['expected_scope_confirmation']
                assert not result['prices'] and not result['live_offers'] and not result['complete_answer_established']
                if question['kind']=='qualified_pair':
                    pair=tuple(question['expected_pair']);eid=event_pairs.get(pair)
                    matches=[e for e in comparison['artwork']['reviewed_links'] if e['assertion_id']==eid]
                    assert len(matches)==1 if eid else not matches
                    left,right=pair;payload=dict(left=dict(card_id=left),right=dict(card_id=right))
                    direct=card_comparison.compare(db,payload)
                    if eid:assert any(e['assertion_id']==eid for e in direct['artwork']['reviewed_links'])
                    assert not direct['same_physical_printing_established'] and not direct['price_comparable']
                    directs.append(dict(id=question['id'],payload=payload,expected=direct))
                else:
                    assert comparison['right']['requested']['set_code']=='SM999' and comparison['right']['status']=='not_found'
                    assert not comparison['artwork']['reviewed_links']
                expected_questions.append(dict(id=question['id'],question=question['question'],expected=result))
            def natural(item):
                code,actual=query('/collector-discovery',params=dict(q=item['question']))
                return dict(id=item['id'],route='natural-comparison',passed=code==200 and semantic(actual)==semantic(item['expected']),actual=actual,local=item['expected'])
            def structured(item):
                code,actual=query('/card-comparison',payload=item['payload'])
                return dict(id=item['id'],route='exact-source-pair',passed=code==200 and semantic(actual)==semantic(item['expected']),actual=actual,local=item['expected'])
            with ThreadPoolExecutor(max_workers=3) as pool:checks.extend(pool.map(natural,expected_questions))
            with ThreadPoolExecutor(max_workers=3) as pool:checks.extend(pool.map(structured,directs))
            assert all(c['passed'] for c in checks)
            representative=[questions[i] for i in [0,6,17,28,33,38]]
            inputs=dict(baseUrl=base,token=token,allowLoopback=not cloud,
                journeys=[dict(id=r['id'],steps=[dict(action=dict(type='ask',question=r['question']))]) for r in representative])
            node=subprocess.run(['node',str(root/'integrations/pivota/replay.cjs')],input=json.dumps(inputs),text=True,capture_output=True,check=True)
            calls=json.loads(node.stdout);assert len(calls)==6
            for item,call in zip(representative,calls):
                expected=collector_journey.replay(db,dict(turns=[dict(type='ask',question=item['question'])],limit=20),revision=revision)
                actual=call.get('call',{}).get('result');passed=semantic(actual)==semantic(expected)
                checks.append(dict(id=call['id'],route='node-caller',passed=passed,result=call));assert passed
            for q in ['Japanese card 151/165','English card 151/165','Japanese SV-P 154/SV-P']:
                expected=collector_discovery.execute(db,q);code,actual=query('/collector-discovery',params=dict(q=q))
                passed=code==200 and actual==expected;checks.append(dict(id=q,route='legacy-source-guard',passed=passed,result=actual));assert passed
            code,actual=query('/catalog-status');passed=code==200 and actual==core.catalog_status(db)
            checks.append(dict(id='catalog-status',passed=passed,result=actual));assert passed
            invalid=[dict(left=dict(card_id=left),right=dict(card_id=left)),dict(payload,price_comparable=True)]
            for i,item in enumerate(invalid):
                code,actual=query('/card-comparison',payload=item);checks.append(dict(id='invalid:'+str(i),passed=code==400,result=actual));assert code==400
            if cloud:
                for path,payload in [('/health',None),('/card-comparison',payload)]:
                    code,_=query(path,payload=payload,authenticated=False)
                    checks.append(dict(id='unauthenticated:'+path,passed=code==403,status=code));assert code==403
                after=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1')
                assert after['status']['latestReadyRevisionName']==ready
                deployment['revision_unchanged_after_verification']=True
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        unchanged=sha(db_path)==before
        report=dict(schema='pokemon.artwork-expansion-rehearsal.v1',completed=completed,
            planned_checks=104 if cloud else 102,checks=len(checks),passed=sum(c['passed'] for c in checks),results=checks,
            source_led_questions=50,exact_reviewed_pairs=40,node_caller_journeys=6,
            environment='private-staging' if cloud else 'local-http',deployment=deployment,
            catalog_sha256=before,catalog_bytes_unchanged=unchanged,catalog_revision=revision,transport_errors=transport_errors,
            questions_sha256=sha(questions_path),reviewed_events_sha256=sha(directory/'verified-artwork-events.jsonl'),
            runtime_sha256={name:sha(root/'pokemon_index'/name) for name in ['card_comparison.py','collector_discovery.py','collector_journey.py','cli.py']},
            real_user_or_marketplace_accuracy_established=False,pivota_registration_established=False,
            prices_and_physical_copy_approvals_added=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not unchanged:raise ValueError('read-only rehearsal changed catalog')
    return dict(checks=report['checks'],passed=report['passed'],completed=completed,transport_errors=len(transport_errors),deployment=deployment)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.db,a.output,cloud=a.cloud)))
