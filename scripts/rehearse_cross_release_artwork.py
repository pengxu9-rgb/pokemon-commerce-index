"""Replay each frozen pair's current artwork state through the actual API."""
from __future__ import annotations
import argparse,json,subprocess,threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.request import Request
from pokemon_index import core,card_comparison,collector_journey
from pokemon_index.cli import create_server
from scripts.rehearse_source_image_facts import fetch_json
from scripts.rehearse_card_comparison import sha,semantic


def run(db_path,directory,output,cloud=False):
    if output.exists():raise FileExistsError('fresh report required')
    root=Path(__file__).resolve().parents[1];directory=directory.resolve()
    if not directory.is_relative_to(root/'catalog'):raise ValueError('diagnostics must be within catalog')
    cohort=[json.loads(x) for x in (directory/'cohort-v1.jsonl').read_text().splitlines()]
    pos=[json.loads(x) for x in (directory/'verified-artwork-events-v2.jsonl').read_text().splitlines()]
    neg=[json.loads(x) for x in (directory/'qualified-difference-events-v2.jsonl').read_text().splitlines()]
    known={(x['left_card_id'],x['right_card_id']):x for x in pos+neg}
    if len(cohort)!=14 or len(known)!=len(pos+neg):raise ValueError('frozen unique pair membership required')
    server=None;thread=None;token=None;deployment=None;errors=[];results=[];before=sha(db_path);completed=False
    if cloud:
        def gc(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
        service=gc('run','services','describe','pokemon-commerce-index','--region=us-west1');iam=gc('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
        if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):raise ValueError('public invoker')
        rev=service['status']['latestReadyRevisionName']
        if sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==rev)!=100:raise ValueError('partial traffic')
        image=gc('run','revisions','describe',rev,'--region=us-west1')['status']['imageDigest'];base=service['status']['url'];deployment=dict(revision=rev,url=base,image=image,private_iam_verified=True)
        token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    else:
        server=create_server(str(db_path),'127.0.0.1',0,True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_address[1])
    def one(c):
        ids=sorted(e['card_id'] for e in c['endpoints']);payload=dict(left=dict(card_id=ids[0]),right=dict(card_id=ids[1]));headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        code,actual=fetch_json(Request(base+'/card-comparison',data=json.dumps(payload).encode(),headers=headers),errors,'/card-comparison')
        return c,ids,payload,code,actual
    try:
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            with ThreadPoolExecutor(max_workers=3) as ex:responses=list(ex.map(one,cohort))
            for c,ids,payload,code,actual in responses:
                expected=card_comparison.compare(db,payload);event=known.get(tuple(ids));valid=code==200 and semantic(actual)==semantic(expected)
                if event:
                    field='reviewed_links' if event['review_status']=='verified' else 'reviewed_difference_links'
                    valid=valid and event['assertion_id'] in {x['assertion_id'] for x in actual['artwork'][field]}
                else:valid=valid and not actual['artwork']['reviewed_links'] and not actual['artwork']['reviewed_difference_links']
                valid=valid and all(actual[k] is False for k in ['same_physical_printing_established','physical_finish_verified','copy_condition_verified','price_comparable','price_series_merge_allowed','automatic_offer_join_allowed','purchase_ready','public_display_allowed'])
                results.append(dict(candidate_id=c['candidate_id'],passed=valid,expected_graph_state=event['review_status'] if event else 'held',actual=actual))
                if not valid:raise AssertionError(c['candidate_id'])
            if cloud:
                if gc('run','services','describe','pokemon-commerce-index','--region=us-west1')['status']['latestReadyRevisionName']!=rev:raise ValueError('revision changed')
            completed=True
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        report=dict(schema='pokemon.cross-release-artwork-rehearsal.v1',completed=completed,planned_checks=14,checks=len(results),passed=sum(x['passed'] for x in results),results=results,transport_errors=errors,deployment=deployment,catalog_revision=revision,catalog_sha256=before,catalog_bytes_unchanged=sha(db_path)==before,input_sha256={name:sha(directory/name) for name in ['cohort-v1.jsonl','verified-artwork-events-v2.jsonl','qualified-difference-events-v2.jsonl']},rehearsal_script_sha256=sha(Path(__file__)),physical_or_commerce_approvals_added=False,population_accuracy_established=False)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ['completed','checks','passed','deployment']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','directory','output']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--cloud',action='store_true');a=p.parse_args();print(json.dumps(run(a.db,a.directory,a.output,a.cloud)))
