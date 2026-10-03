from pathlib import Path
import json,hashlib,subprocess
from datetime import datetime,timezone
r=Path('catalog/source-facts-escalation-v1');a=Path('catalog/cross-release-artwork-v1');root=Path.cwd()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
paths=[r/'local-replay-v2.json',r/'prior-facts-local-v2.json',r/'private-cloud-replay-v1.json',r/'prior-facts-cloud-v1.json',a/'local-replay-v1.json',a/'private-cloud-replay-v1.json'];reports={str(p):json.loads(p.read_text()) for p in paths};snapshot=Path('/tmp/pokemon-source-facts-escalation-v1.sqlite3')
for path,x in reports.items():
 assert x['completed'] and x['checks']==x['planned_checks']==x['passed'],path
 assert x['catalog_bytes_unchanged'] and x['catalog_sha256']==sha(snapshot)
 for n,h in x.get('runtime_sha256',{}).items():assert sha(root/'pokemon_index'/n)==h
 assert sha(root/'scripts'/('rehearse_cross_release_artwork.py' if 'artwork-v1' in path else 'rehearse_source_image_facts.py'))==x['rehearsal_script_sha256']
 if 'evidence_sha256' in x:
  p=r/'evidence-v1.jsonl' if 'prior-facts' not in path else Path('catalog/source-image-facts-v1/evidence-v1.jsonl');assert sha(p)==x['evidence_sha256']
  q=r/'questions-v2.jsonl' if 'prior-facts' not in path else Path('catalog/source-image-facts-v1/questions-v1.jsonl');assert sha(q)==x['questions_sha256']
 if 'input_sha256' in x:
  for name,h in x['input_sha256'].items():assert sha(a/name)==h
 assert not x['physical_or_market_approvals_added'] if 'physical_or_market_approvals_added' in x else not x['physical_or_commerce_approvals_added']
manifest=Path('catalog-build-manifest-source-facts-escalation-v1.json');new=json.loads(manifest.read_text());old=json.loads(Path('catalog-build-manifest-source-facts-thousand-v1.json').read_text());assert len(new['steps'])==61 and new['steps'][:57]==old['steps'];assert all(sha(s['path'])==s['sha256'] for s in new['steps'])
build=json.loads((r/'build-result-v2.json').read_text());assert build['manifest_sha256']==sha(manifest);assert all(build[k]==v for k,v in new['expected'].items())
preservation=json.loads((r/'preservation-v1.json').read_text());assert preservation['base_tables_preserved']==41 and preservation['prior_number_events_preserved']==1154 and preservation['prior_source_fact_events_preserved']==1124 and preservation['prior_graph_history_preserved']==731
cloud=reports[str(r/'private-cloud-replay-v1.json')]['deployment']
for path,x in reports.items():
 if 'cloud' in path:assert all(x['deployment'][k]==cloud[k] for k in ['revision','url','image','private_iam_verified'])
def gc(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
service=gc('run','services','describe','pokemon-commerce-index','--region=us-west1');iam=gc('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1');assert service['status']['latestReadyRevisionName']==cloud['revision'];assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==cloud['revision'])==100;assert not any(m in ['allUsers','allAuthenticatedUsers'] for b in iam.get('bindings',[]) for m in b['members']);revision=gc('run','revisions','describe',cloud['revision'],'--region=us-west1');assert revision['status']['imageDigest']==cloud['image']
py=Path('/tmp/pokemon-source-escalation-tests-final.log').read_text();assert 'Ran 584 tests' in py and py.rstrip().endswith('OK');node=Path('/tmp/pokemon-source-escalation-node-tests-final.log').read_text();assert 'pass 12' in node and 'fail 0' in node
(r/'test-results-v1.json').write_text(json.dumps(dict(python_tests=584,node_tests=12,python_passed=True,node_passed=True,python_log_sha256=sha('/tmp/pokemon-source-escalation-tests-final.log'),node_log_sha256=sha('/tmp/pokemon-source-escalation-node-tests-final.log')),indent=2)+'\n')
record=dict(schema='pokemon.source-fact-escalation-delivery.v1',verified_at=datetime.now(timezone.utc).isoformat(),deployment=cloud,traffic_percent=100,private_iam_verified=True,local_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' not in p),cloud_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' in p),transport_retries=sum(len(x['transport_errors']) for x in reports.values()),unauthenticated_denial_checks=sum(sum(c['id'].startswith('unauthenticated:') and c['passed'] for c in x.get('results',[])) for p,x in reports.items() if 'cloud' in p and 'source-facts-escalation' in p),report_bindings={p:dict(sha256=sha(p),checks=x['checks'],transport_errors=x['transport_errors']) for p,x in reports.items()},manifest_sha256=sha(manifest),snapshot_sha256=sha(snapshot),ordered_previous_inputs_preserved=57,new_inputs=4,prior_number_events_preserved=1154,prior_fact_events_preserved=1124,prior_graph_rows_preserved=731,base_tables_preserved=41,new_separate_image_model_subjects=308,new_same_artwork_events=9,new_qualified_difference_events=3,final_logical_failures=0,failed_diagnostics_retained=True,population_or_marketplace_accuracy_established=False,physical_or_commerce_approvals_added=False)
(r/'delivery-validation-v1.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');Path('cloud-deployment-20261003-source-facts-escalation-v1.json').write_text(json.dumps(dict(verified_at=record['verified_at'],**cloud,traffic_percent=100,service_spec=service['spec'],manifest_sha256=record['manifest_sha256'],delivery_report_sha256=sha(r/'delivery-validation-v1.json')),ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['local_checks','cloud_checks','transport_retries','unauthenticated_denial_checks']}))
