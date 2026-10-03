"""Engineering checks for image-fact advisories through HTTP and Node caller."""
from __future__ import annotations
import argparse,json,subprocess,threading
from http.client import IncompleteRead,RemoteDisconnected
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pokemon_index import core,collector_discovery,collector_journey,source_image_facts,number_evidence
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha,semantic
from scripts.verify_collector_cloud import catalog_card_semantic_response

def fetch_json(request,errors,route):
    """Three bounded attempts for read-only rehearsal transport failures."""
    for attempt in range(1,4):
        try:
            with urlopen(request,timeout=30) as response:return response.status,json.load(response)
        except HTTPError as error:
            try:value=json.load(error)
            except ValueError:value=None
            return error.code,value
        except (URLError,TimeoutError,IncompleteRead,RemoteDisconnected,ConnectionResetError) as error:
            errors.append(dict(route=route,attempt=attempt,error_type=type(error).__name__))
            if attempt==3:raise

def run(db_path,output,cloud=False,cohort_dir=None,evidence_filename='evidence-v1.jsonl',outcomes_filename=None,detail_concurrency=4):
    if type(detail_concurrency)!=int or not 1<=detail_concurrency<=4:raise ValueError('detail concurrency must be one to four')
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1]
    p=(cohort_dir or root/'catalog/source-image-facts-v1').resolve()
    if not p.is_relative_to(root/'catalog'):raise ValueError('fact diagnostic directory must be within catalog')
    evidence_path=p/evidence_filename
    if not evidence_path.resolve().is_relative_to(p):raise ValueError('evidence must be within diagnostic directory')
    events=list(map(json.loads,evidence_path.read_text().splitlines()));missing=[];outcomes_path=None
    if outcomes_filename:
        outcomes_path=p/outcomes_filename
        if not outcomes_path.resolve().is_relative_to(p):raise ValueError('outcomes must be within diagnostic directory')
        outcomes=json.loads(outcomes_path.read_text())['outcomes']
        missing=[r for r in outcomes if r['number_event_id'] is None]
        if len({r['card_id'] for r in outcomes})!=len(outcomes) or {r['card_id'] for r in outcomes}!={r['card_id'] for r in events}|{r['card_id'] for r in missing}:
            raise ValueError('complete source-fact and held-subject outcomes required')
    questions_path=p/'questions-v1.jsonl';questions=list(map(json.loads,questions_path.read_text().splitlines()))
    if len(questions)<6 or len({q['id'] for q in questions})!=len(questions):raise ValueError('six or more unique authored questions required')
    planned=len(events)+len(missing)+len(questions)+6+(2 if cloud else 0)
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
        return fetch_json(request,errors,route)
    def record(key,passed,actual):
        checks.append(dict(id=key,passed=bool(passed),actual=actual))
        if not passed:raise AssertionError(key)
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            # Only independent HTTP reads run concurrently. Expected values are
            # evaluated on the calling thread's read-only connection.
            subjects=events+missing
            expected_cards={r['card_id']:core.catalog_card_internal(db,r['card_id']) for r in subjects}
            with ThreadPoolExecutor(max_workers=detail_concurrency) as pool:
                detail_results=dict(zip((r['card_id'] for r in subjects),pool.map(
                    lambda r:query('/catalog-card',dict(card_id=r['card_id'])),subjects)))
            for row in events:
                cid=row['card_id'];expected=expected_cards[cid];code,actual=detail_results[cid]
                fact=actual['source_image_facts']
                valid=code==200 and semantic(catalog_card_semantic_response(actual))==semantic(catalog_card_semantic_response(expected)) and fact['current_endpoint']
                valid=valid and all(fact[k] is False for k in source_image_facts.FALSE_CLAIMS) and not fact['number_reading_qualification_changed']
                valid=valid and [r['prior_verdicts_visible'] for r in fact['reviews']]==[r['prior_verdicts_visible'] for r in row['reviews']]
                valid=valid and not fact['reviews'][1]['prior_verdicts_visible']
                number=actual['number_context']['observed_printed_number']
                if cid in {q['held_card_id'] for q in questions if 'held_card_id' in q}:
                    valid=valid and number['status']=='reading_hold' and not number['visible_text_agreement']
                record('card:'+cid,valid,dict(card_id=cid,source_image_facts=fact,number_reading=number,
                    rarity_correction=actual.get('rarity_correction'),
                    expected_rarity_correction_applied_at=(expected.get('rarity_correction') or {}).get('applied_at')))
            for q in questions:
                expected=collector_discovery.execute(db,q['question']);code,actual=query('/collector-discovery',dict(q=q['question']))
                comp=actual.get('comparison',{})
                valid=code==200 and semantic(actual)==semantic(expected) and actual['task']=='two_card_comparison' and not actual['complete_answer_established'] and not comp['price_comparable'] and not comp['purchase_ready']
                if q['kind']=='hp_conflict':valid=valid and 'source_image_metadata_resolution' in comp['required_evidence'] and any('source_hp_conflict' in w['warnings'] for w in comp['source_metadata_warnings'])
                record(q['id'],valid,actual)
            for row in missing:
                cid=row['card_id'];expected=expected_cards[cid];code,actual=detail_results[cid]
                record('unavailable-image:'+cid,code==200 and semantic(catalog_card_semantic_response(actual))==semantic(catalog_card_semantic_response(expected)) and actual['source_image_facts'] is None and actual['number_context']['observed_printed_number'] is None,actual)
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
        report=dict(schema='pokemon.source-image-fact-rehearsal.v1',completed=completed,planned_checks=planned,detail_concurrency=detail_concurrency,checks=len(checks),passed=sum(c['passed'] for c in checks),results=checks,transport_errors=errors,deployment=deployment,catalog_sha256=before,catalog_bytes_unchanged=sha(db_path)==before,catalog_revision=revision,evidence_sha256=sha(evidence_path),questions_sha256=sha(questions_path),runtime_sha256={n:sha(root/'pokemon_index'/n) for n in ['source_image_facts.py','number_evidence.py','card_comparison.py','collector_discovery.py','collector_journey.py','core.py','cli.py','schema.sql']},independent_real_user_or_marketplace_accuracy_established=False,physical_or_market_approvals_added=False)
        if outcomes_path:report.update(outcomes_sha256=sha(outcomes_path),unavailable_image_subjects=len(missing))
        report['catalog_card_excluded_bookkeeping_paths']=['/rarity_correction/applied_at']
        report['rehearsal_script_sha256']=sha(Path(__file__))
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not report['catalog_bytes_unchanged']:raise ValueError('facts rehearsal changed snapshot')
    return {k:report[k] for k in ['completed','checks','passed','deployment']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true');p.add_argument('--cohort-dir',type=Path);p.add_argument('--evidence-filename',default='evidence-v1.jsonl');p.add_argument('--outcomes-filename');a=p.parse_args();print(json.dumps(run(a.db,a.output,a.cloud,a.cohort_dir,a.evidence_filename,a.outcomes_filename)))
