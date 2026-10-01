"""Exercise the Node caller against the actual private catalog HTTP contract.

Source-led scenarios are developer diagnostics; typed follow-ups are synthetic.
The caller adapter is tested through real HTTP, not mocked discovery responses.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,threading
from collections import Counter
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_journey
from pokemon_index.cli import create_server


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def run(db_path,suite_path,output,*,cloud=False):
    if output.exists():raise FileExistsError(output)
    suite=json.loads(suite_path.read_text());journeys=suite['journeys']
    if suite['schema']!='pokemon.pivota-collector-diagnostic.v1':raise ValueError('unknown suite')
    before=sha(db_path)
    if cloud:
        service=json.loads(subprocess.check_output(['gcloud','run','services','describe','pokemon-commerce-index',
            '--project=pivota-staging','--region=us-west1','--format=json'],text=True))
        base=service['status']['url']
        token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
        config=dict(baseUrl=base,token=token,journeys=journeys)
        returned=json.loads(subprocess.check_output(['node','integrations/pivota/replay.cjs'],
            input=json.dumps(config),text=True,timeout=240))
        environment=dict(kind='private_staging',project='pivota-staging',
            revision=service['status']['latestReadyRevisionName'],url=base)
    else:
        with create_server(str(db_path),'127.0.0.1',0,True) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                config=dict(baseUrl='http://127.0.0.1:'+str(server.server_address[1]),allowLoopback=True,journeys=journeys)
                returned=json.loads(subprocess.check_output(['node','integrations/pivota/replay.cjs'],
                    input=json.dumps(config),text=True,timeout=240))
            finally:server.shutdown();thread.join(timeout=5)
        environment=dict(kind='local_http_readonly_catalog')
    returned={r['id']:r for r in returned};results=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        for journey in journeys:
            turns=[]
            for i,step in enumerate(journey['steps'],1):
                turns.append(step['action']);key=journey['id']+':'+str(i);row=returned.get(key,{})
                call=row.get('call');actual=call.get('result') if call else None;errors=[]
                equivalent=False
                if not actual:
                    errors.append(row.get('error_code') or 'not_executed_after_prior_error')
                else:
                    expected=step['expect'];cards=actual['candidate_cards'];task=actual['discovery']['task']
                    if 'status_in' in expected and actual['status'] not in expected['status_in']:errors.append('status differs')
                    if 'task_in' in expected and task not in expected['task_in']:errors.append('intent task differs')
                    if expected.get('has_candidates') and not cards:errors.append('catalog partial absent')
                    if expected.get('selection_blocked') and actual['selection_allowed']:errors.append('selection should be blocked')
                    if 'only_language' in expected and (not cards or {c['language'] for c in cards}!={expected['only_language']}):errors.append('language scope differs')
                    selected=actual['selected_catalog_target']['card_id'] if actual['selected_catalog_target'] else None
                    if 'target_id' in expected and selected!=expected['target_id']:errors.append('target differs')
                    local=collector_journey.replay(db,dict(turns=list(turns),limit=20),revision=revision)
                    equivalent=digest(actual)==digest(local)
                    if not equivalent:errors.append('HTTP/caller response differs from local replay')
                    if call['session']['turns']!=turns or call['session']['expected_revision']!=revision:
                        errors.append('caller session lost transcript or revision')
                results.append(dict(id=key,expect=step['expect'],action=step['action'],passed=not errors,errors=errors,
                    direct_replay_equivalent=equivalent,call=call,error_code=row.get('error_code')))
    if sha(db_path)!=before:raise ValueError('caller mutated catalog')
    report=dict(schema='pokemon.pivota-collector-diagnostic-report.v1',environment=environment,
        journeys=len(journeys),planned_steps=len(results),executed_steps=len(returned),
        passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),
        task_counts=dict(Counter(r['call']['result']['discovery']['task'] for r in results if r['call'] and r['call']['result'])),
        catalog_sha256=before,catalog_revision=revision,suite_sha256=sha(suite_path),
        connector_sha256=sha('integrations/pivota/collectorClient.cjs'),
        runtime_sha256={p:sha(p) for p in ['pokemon_index/collector_journey.py','pokemon_index/collector_discovery.py','pokemon_index/collector_inventory.py','pokemon_index/cli.py']},
        catalog_bytes_unchanged=True,real_user_accuracy_established=False,source_selection_independent=False,
        inventory_assertions_synthetic=True,public_display_allowed=False,live_market_ready=False,
        interpretation=suite['scope'],results=results)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['journeys','planned_steps','executed_steps','passed','failed','task_counts']}))
    print(json.dumps([dict(id=r['id'],errors=r['errors'],status=r['call']['result']['status'] if r['call'] and r['call']['result'] else None) for r in results if not r['passed']]))
    if report['failed']:raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True)
    p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cloud',action='store_true');a=p.parse_args();run(a.db,a.suite,a.output,cloud=a.cloud)
