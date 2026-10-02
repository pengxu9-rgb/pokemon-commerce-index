"""Source-led comparison replay, optionally through private staging and Node caller.

The six frozen authored questions are development checks, not held-out accuracy.
Full original responses are retained. Credentials stay in subprocess memory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import threading
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pokemon_index import core, card_comparison, collector_discovery, collector_journey
from pokemon_index.cli import create_server


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic(value):
    """Normalize only build application time of imported AI proposals."""
    value = json.loads(json.dumps(value))
    def walk(item):
        if isinstance(item, dict):
            if item.get('asserted_by') == 'ai-artwork-review-v1' and item.get('review_status') == 'proposed':
                core.parse_time(item['asserted_at']); item.pop('asserted_at')
            for child in item.values():walk(child)
        elif isinstance(item, list):
            for child in item:walk(child)
    walk(value)
    return value


def run(db_path, output, *, cloud=False):
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1]
    directory=root/'catalog/two-card-comparison-v1'
    questions=directory/'questions-frozen-v1.jsonl'
    lock=json.loads((directory/'questions-freeze-v1.json').read_text())
    if sha(questions)!=lock['sha256']:raise ValueError('frozen comparison questions changed')
    rows=list(map(json.loads,questions.read_text().splitlines()))
    before=sha(db_path);server=None;thread=None;token=None;deployment=None;revision=None;completed=False
    if cloud:
        def gcloud(*args):
            return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
        service=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1')
        iam=gcloud('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
        if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):
            raise ValueError('public invoker binding')
        revision=service['status']['latestReadyRevisionName']
        if sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==revision)!=100:
            raise ValueError('new revision does not have all traffic')
        detail=gcloud('run','revisions','describe',revision,'--region=us-west1')
        deployment=dict(revision=revision,url=service['status']['url'],image=detail['status']['imageDigest'],private_iam_verified=True)
        base=service['status']['url'];token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    else:
        server=create_server(str(db_path),'127.0.0.1',0,True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
    transport_errors=[];checks=[]
    def query(path, *, payload=None, params=None, authenticated=True):
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
                transport_errors.append(dict(path=path,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            for row in rows:
                natural=collector_discovery.execute(db,row['question'])
                comp=natural['comparison'];edges=comp['artwork']['reviewed_links']
                pairs=[sorted([e['left_card_id'],e['right_card_id']]) for e in edges]
                assert row['expected_reviewed_endpoint_pair'] in pairs
                assert natural['task']==row['expected_task']
                assert (comp['status']=='scope_confirmation_needed')==row['expected_scope_confirmation']
                left,right=row['expected_reviewed_endpoint_pair']
                payload=dict(left=dict(card_id=left),right=dict(card_id=right))
                direct=card_comparison.compare(db,payload)
                journey_request=dict(turns=[dict(type='ask',question=row['question'])])
                journey=collector_journey.replay(db,journey_request,revision=revision)
                assert not journey['selection_allowed'] and journey['target_intent'] is None
                for route,args,expected in [('/card-comparison',dict(payload=payload),direct),
                        ('/collector-discovery',dict(params={'q':row['question']}),natural),
                        ('/collector-journey',dict(payload=journey_request),journey)]:
                    code,actual=query(route,**args)
                    passed=code==200 and semantic(actual)==semantic(expected)
                    checks.append(dict(id=row['question_id'],route=route,passed=passed,local=expected,actual=actual))
                    if not passed:raise AssertionError('response differs: '+row['question_id']+' '+route)
            malformed=[dict(left=dict(card_id=left),right=dict(card_id=left)),
                dict(payload,price_comparable=True),dict(left=dict(language='ja',collector_number='18/60'),right=payload['right'])]
            for index,invalid in enumerate(malformed):
                code,actual=query('/card-comparison',payload=invalid)
                checks.append(dict(id='invalid:'+str(index),route='/card-comparison',passed=code==400,status=code,result=actual))
                assert code==400
            for question in ['Japanese card 151/165','English card 151/165']:
                code,actual=query('/collector-discovery',params={'q':question})
                passed=code==200 and actual['task']=='need_release_scope' and not actual['cards']
                checks.append(dict(id=question,route='/collector-discovery',passed=passed,result=actual));assert passed
            code,actual=query('/catalog-status')
            expected=core.catalog_status(db)
            passed=code==200 and actual==expected
            checks.append(dict(id='catalog-status',passed=passed,result=actual));assert passed
            if cloud:
                for route,args in [('/card-comparison',dict(payload=payload)),('/health',{})]:
                    code,_=query(route,authenticated=False,**args)
                    checks.append(dict(id='unauthenticated:'+route,passed=code==403,status=code));assert code==403
            # Real connector receives complete journey responses. A fixture
            # proves protocol compatibility only, not live Pivota registration.
            inputs=dict(baseUrl=base,token=token,allowLoopback=not cloud,
                journeys=[dict(id=r['question_id'],steps=[dict(action=dict(type='ask',question=r['question']))]) for r in rows])
            node=subprocess.run(['node',str(root/'integrations/pivota/replay.cjs')],input=json.dumps(inputs),
                text=True,capture_output=True,check=True)
            calls=json.loads(node.stdout)
            assert len(calls)==len(rows)
            for row,call in zip(rows,calls):
                expected=collector_journey.replay(db,dict(turns=[dict(type='ask',question=row['question'])],limit=20),revision=revision)
                actual=call.get('call',{}).get('result')
                passed=semantic(actual)==semantic(expected)
                checks.append(dict(id=call['id'],route='node-collector-client',passed=passed,result=call))
                assert passed
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        unchanged=sha(db_path)==before
        report=dict(schema='pokemon.card-comparison-rehearsal.v1',environment='private-staging' if cloud else 'local-http',
            completed=completed,planned_checks=32 if cloud else 30,
            checks=len(checks),passed=sum(c['passed'] for c in checks),results=checks,
            transport_errors=transport_errors,catalog_bytes_unchanged=unchanged,catalog_sha256=before,
            questions_sha256=sha(questions),catalog_revision=revision,deployment=deployment,
            runtime_sha256={name:sha(root/'pokemon_index'/name) for name in ('card_comparison.py','collector_discovery.py','collector_journey.py','cli.py')},
            connector_sha256=sha(root/'integrations/pivota/collectorClient.cjs'),
            real_user_accuracy_established=False,pivota_registration_established=False,
            live_price_readiness_established=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not unchanged:raise ValueError('read-only comparison changed catalog')
    return dict(checks=report['checks'],passed=report['passed'],transport_errors=len(transport_errors),deployment=deployment)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cloud',action='store_true');args=parser.parse_args()
    print(json.dumps(run(args.db,args.output,cloud=args.cloud)))
