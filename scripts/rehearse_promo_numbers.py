"""Verify all fifty promo outcomes through private read-only catalog HTTP."""
from __future__ import annotations
import argparse,json,subprocess,threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pokemon_index import core,collector_discovery,collector_journey
from pokemon_index.cli import create_server
from scripts.rehearse_card_comparison import sha,semantic


def run(db_path,output,cloud=False):
    if output.exists():raise FileExistsError(output)
    root=Path(__file__).resolve().parents[1];directory=root/'catalog/promo-number-expansion-v1'
    summary_path=directory/'adjudication-v1.json';summary=json.loads(summary_path.read_text())
    questions_path=directory/'questions-v1.jsonl';questions=list(map(json.loads,questions_path.read_text().splitlines()))
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
    def query(route,params=None,auth=True):
        request=Request(base+route+('?' + urlencode(params) if params else ''),headers={'Authorization':'Bearer '+token} if token and auth else {})
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
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses=list(pool.map(lambda r:query('/catalog-card',dict(card_id=r['card_id'])),summary['results']))
            for result,(code,actual) in zip(summary['results'],responses):
                cid=result['card_id'];expected=core.catalog_card_internal(db,cid);reading=actual['number_context']['observed_printed_number']
                valid=code==200 and semantic(actual)==semantic(expected) and actual['number_context']['catalog_number']==expected['card']['collector_number']
                if result['status']=='held':valid=valid and reading is None
                else:
                    valid=valid and reading['status']==result['status'] and reading['current_endpoint']
                    valid=valid and reading['visible_text_agreement']==(result['status']!='reading_hold')
                    valid=valid and not reading['catalog_identity_confirmed'] and not reading['automatic_offer_join_allowed']
                    if result['status']=='reading_hold':valid=valid and reading['observed_number_texts']==[]
                    if result['status']=='catalog_denominator_not_observed':valid=valid and not reading['printed_denominator_observed']
                record('exact:'+result['target_id'],valid,dict(card_id=cid,catalog_number=actual['number_context']['catalog_number'],
                    structural_match_eligible=actual['card']['match_eligible'],number_evidence=reading))
            for q in questions:
                code,actual=query('/collector-discovery',dict(q=q['question']))
                expected=collector_discovery.execute(db,q['question'])
                comparison=actual.get('comparison',{})
                record(q['id'],code==200 and semantic(actual)==semantic(expected) and actual['task']=='two_card_comparison'
                    and not actual['complete_answer_established'] and not comparison['purchase_ready']
                    and not comparison['price_comparable'] and not comparison['numbering']['printed_number_equivalence_established'],actual)
            code,actual=query('/catalog-status')
            record('catalog-status',code==200 and actual==core.catalog_status(db) and actual['display_approved']==0,
                dict(printings=actual['printings'],number_reading_evidence=actual['number_reading_evidence']))
            if cloud:
                for route in ['/catalog-card','/collector-discovery']:
                    code,_=query(route,auth=False);record('unauthenticated:'+route,code==403,dict(status=code))
                after=gcloud('run','services','describe','pokemon-commerce-index','--region=us-west1');assert after['status']['latestReadyRevisionName']==ready
                deployment['revision_unchanged_after_verification']=True
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        report=dict(schema='pokemon.promo-number-rehearsal.v1',completed=completed,planned_checks=59 if cloud else 57,
            checks=len(checks),passed=sum(r['passed'] for r in checks),results=checks,transport_errors=errors,
            deployment=deployment,catalog_sha256=before,catalog_bytes_unchanged=sha(db_path)==before,catalog_revision=revision,
            summary_sha256=sha(summary_path),questions_sha256=sha(questions_path),
            runtime_sha256={name:sha(root/'pokemon_index'/name) for name in ['number_graph.py','number_evidence.py','card_comparison.py','collector_discovery.py','collector_journey.py','core.py','cli.py']},
            real_user_or_marketplace_precision_established=False,physical_or_market_approvals_added=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if not report['catalog_bytes_unchanged']:raise ValueError('promo diagnostic changed snapshot')
    return {k:report[k] for k in ['completed','checks','passed','deployment']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.db,a.output,a.cloud)))
