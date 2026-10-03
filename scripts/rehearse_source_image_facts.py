"""Engineering checks for image-fact advisories through HTTP and Node caller."""
from __future__ import annotations
import argparse,json,subprocess,threading
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pokemon_index import core,collector_discovery,collector_journey,source_image_facts,number_evidence
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha,semantic

def run(db_path,output,cloud=False):
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1];p=root/'catalog/source-image-facts-v1'
    evidence_path=p/'evidence-v1.jsonl';events=list(map(json.loads,evidence_path.read_text().splitlines()))
    questions_path=p/'questions-v1.jsonl';questions=list(map(json.loads,questions_path.read_text().splitlines()))
    before=sha(db_path);server=None;thread=None;deployment=None;token=None;checks=[];errors=[];completed=False;revision=None
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
    def query(route,params=None,payload=None,auth=True):
        headers={'Authorization':'Bearer '+token} if token and auth else {};body=json.dumps(payload).encode() if payload is not None else None
        if body is not None:headers['Content-Type']='application/json'
        request=Request(base+route+('?' + urlencode(params) if params else ''),headers=headers,data=body)
        for attempt in range(1,4):
            try:
                with urlopen(request,timeout=30) as response:return response.status,json.load(response)
            except HTTPError as error:
                try:value=json.load(error)
                except ValueError:value=None
                return error.code,value
            except (URLError,TimeoutError) as error:
                errors.append(dict(route=route,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    def record(key,passed,actual):
        checks.append(dict(id=key,passed=bool(passed),actual=actual))
        if not passed:raise AssertionError(key)
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            for row in events:
                cid=row['card_id'];expected=core.catalog_card_internal(db,cid);code,actual=query('/catalog-card',dict(card_id=cid))
                fact=actual['source_image_facts']
                valid=code==200 and semantic(actual)==semantic(expected) and fact['current_endpoint']
                valid=valid and all(fact[k] is False for k in source_image_facts.FALSE_CLAIMS) and not fact['number_reading_qualification_changed']
                valid=valid and fact['reviews'][0]['prior_verdicts_visible'] and not fact['reviews'][1]['prior_verdicts_visible']
                number=actual['number_context']['observed_printed_number']
                if cid in {q['held_card_id'] for q in questions if 'held_card_id' in q}:
                    valid=valid and number['status']=='reading_hold' and not number['visible_text_agreement']
                record('card:'+cid,valid,dict(card_id=cid,source_image_facts=fact,number_reading=number))
            for q in questions:
                expected=collector_discovery.execute(db,q['question']);code,actual=query('/collector-discovery',dict(q=q['question']))
                comp=actual.get('comparison',{})
                valid=code==200 and semantic(actual)==semantic(expected) and actual['task']=='two_card_comparison' and not actual['complete_answer_established'] and not comp['price_comparable'] and not comp['purchase_ready']
                if q['kind']=='hp_conflict':valid=valid and 'source_image_metadata_resolution' in comp['required_evidence'] and any('source_hp_conflict' in w['warnings'] for w in comp['source_metadata_warnings'])
                record(q['id'],valid,actual)
            selected=[questions[i] for i in [0,2,5]]
            inputs=dict(baseUrl=base,token=token,allowLoopback=not cloud,journeys=[dict(id=q['id'],steps=[dict(action=dict(type='ask',question=q['question']))]) for q in selected])
            run=subprocess.run(['node',str(root/'integrations/pivota/replay.cjs')],input=json.dumps(inputs),text=True,capture_output=True,check=True)
            calls=json.loads(run.stdout);assert len(calls)==3
            for q,call in zip(selected,calls):
                expected=collector_journey.replay(db,dict(turns=[dict(type='ask',question=q['question'])],limit=20),revision=revision)
                record('node:'+q['id'],semantic(call.get('call',{}).get('result'))==semantic(expected),call)
            code,actual=query('/catalog-status');record('catalog-status',code==200 and actual==core.catalog_status(db),dict(source_image_facts=actual['source_image_facts'],number_readings=actual['number_reading_evidence']))
            first=dict(left=dict(card_id=events[0]['card_id']),right=dict(card_id=events[1]['card_id']))
            for i,payload in enumerate([dict(first,source_image_facts=dict(catalog_identity_confirmed=True)),dict(first,independent_review_agreement_established=True)]):
                code,actual=query('/card-comparison',payload=payload);record('invalid:'+str(i),code==400,actual)
            if cloud:
                for route in ['/catalog-card','/collector-discovery']:
                    code,_=query(route,auth=False);record('unauthenticated:'+route,code==403,dict(status=code))
                after=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1');assert after['status']['latestReadyRevisionName']==ready
                deployment['revision_unchanged_after_verification']=True
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        report=dict(schema='pokemon.source-image-fact-rehearsal.v1',completed=completed,planned_checks=23 if cloud else 21,checks=len(checks),passed=sum(c['passed'] for c in checks),results=checks,transport_errors=errors,deployment=deployment,catalog_sha256=before,catalog_bytes_unchanged=sha(db_path)==before,catalog_revision=revision,evidence_sha256=sha(evidence_path),questions_sha256=sha(questions_path),runtime_sha256={n:sha(root/'pokemon_index'/n) for n in ['source_image_facts.py','number_evidence.py','card_comparison.py','collector_discovery.py','collector_journey.py','core.py','cli.py','schema.sql']},independent_real_user_or_marketplace_accuracy_established=False,physical_or_market_approvals_added=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not report['catalog_bytes_unchanged']:raise ValueError('facts rehearsal changed snapshot')
    return {k:report[k] for k in ['completed','checks','passed','deployment']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true');a=p.parse_args();print(json.dumps(run(a.db,a.output,a.cloud)))
