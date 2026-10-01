"""Verify the private staging collector against a source-qualified local replay."""
from __future__ import annotations
import argparse
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from scripts.public_question_sandbox import sha_file


def verify(local_report: Path, output: Path):
    if output.exists():raise FileExistsError('deployment evidence must be new')
    project='pivota-staging';region='us-west1';name='pokemon-commerce-index'
    def gcloud(*args):
        return json.loads(subprocess.check_output(['gcloud',*args,'--project='+project,'--format=json'],text=True))
    service=gcloud('run','services','describe',name,'--region='+region)
    iam=gcloud('run','services','get-iam-policy',name,'--region='+region)
    revision=service['status']['latestReadyRevisionName']
    detail=gcloud('run','revisions','describe',revision,'--region='+region)
    if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):
        raise ValueError('public invoker binding')
    assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==revision)==100
    token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    url=service['status']['url']
    transient_errors=[]; error_lock=threading.Lock()
    def query(path,params=None,auth=True):
        request=Request(url+path+('?' + urlencode(params) if params else ''),
                        headers={'Authorization':'Bearer '+token} if auth else {})
        for attempt in range(1,4):
            try:
                with urlopen(request,timeout=30) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,None
            except (URLError,TimeoutError) as error:
                with error_lock:transient_errors.append(dict(path=path,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    assert query('/health')[0]==200
    code,status=query('/catalog-status');assert code==200 and status['printings']==55167 and status['display_approved']==0
    code,support=query('/supported-status');assert code==200 and support['current_supported_targets']==100 and support['automatic_offer_join_ready']==0
    assert query('/health',auth=False)[0]==403
    assert query('/collector-discovery',{'q':'Eevee','limit':101})[0]==400
    for q in ['Japanese card 151/165','English card 151/165']:
        code,guard=query('/collector-discovery',{'q':q})
        assert code==200 and guard['task']=='need_release_scope' and not guard['cards']
    local=json.loads(local_report.read_text())
    assert local['cases'] and local['failed']==0
    def case(expected):
        offset=0;cards=[];requests=0;first=None
        while True:
            code,page=query('/collector-discovery',{'q':expected['question'],'limit':100,'offset':offset})
            assert code==200
            requests+=1
            if first is None:first=page
            cards.extend(c['card_id'] for c in page['cards'])
            assert not page['prices'] and not page['live_offers'] and not page['public_display_allowed']
            assert not page['complete_answer_established']
            if not page.get('coverage',{}).get('has_more'):break
            offset+=100
            if offset>100000:raise ValueError('unbounded cloud pagination')
        assert cards==expected['returned_card_ids'],expected['id']
        for key in ['task','status','unfulfilled_constraints','next_question']:
            assert first.get(key)==expected['first_page'].get(key),(expected['id'],key)
        return dict(id=expected['id'],task=first['task'],matched_records=len(cards),requests=requests,passed=True)
    with ThreadPoolExecutor(max_workers=3) as pool:checks=list(pool.map(case,local['results']))
    # Detect another rollout during the diagnostic instead of attributing mixed results.
    assert gcloud('run','services','describe',name,'--region='+region)['status']['latestReadyRevisionName']==revision
    report=dict(project=project,region=region,service=name,revision=revision,url=url,
                image_digest=detail['status']['imageDigest'],private_iam_verified=True,
                unauthenticated_http_status=403,catalog_status=status,supported_status=support,
                collector_checks=checks,authenticated_http_requests=3+sum(c['requests'] for c in checks)+3,
                numeric_release_guard_checks=2,
                invalid_pagination_http_status=400,source_replay_sha256=sha_file(local_report),
                transport_errors=transient_errors,transport_attempts_per_request_max=3,
                deployed_source_files_sha256={p:sha_file(Path(p)) for p in ['pokemon_index/collector_discovery.py','pokemon_index/core.py','pokemon_index/supported_catalog.py','Dockerfile','catalog-build-manifest-discovery-v1.json']},
                verified_date='2026-10-01',real_market_observations=0,live_feed_enabled=False,
                interpretation='Private staging logical equivalence against a development replay; no live marketplace or complete user-answer accuracy is established.')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(revision=revision,collector_cases=len(checks),authenticated_http_requests=report['authenticated_http_requests'],unauthenticated_status=403)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();verify(a.local_report,a.output)
