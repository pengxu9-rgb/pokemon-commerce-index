from pathlib import Path
import json,hashlib,subprocess
from datetime import datetime,timezone
r=Path('catalog/source-binding-v1');a=Path('catalog/cross-release-artwork-v1');root=Path.cwd()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['local-replay-v2.json','prior-facts-local-v2.json','cloud-replay-v1.json','prior-facts-cloud-v1.json','artwork-local-v2.json','artwork-cloud-v1.json']
paths=[r/n for n in names];reports={str(p):json.loads(p.read_text()) for p in paths};snapshot=Path('/tmp/pokemon-source-binding-v1.sqlite3')
for path,x in reports.items():
 assert x['completed'] and x['checks']==x['planned_checks']==x['passed'],path
 assert x['catalog_bytes_unchanged'] and x['catalog_sha256']==sha(snapshot)
 for n,h in x.get('runtime_sha256',{}).items():assert sha(root/'pokemon_index'/n)==h
 assert sha(root/'scripts'/('rehearse_cross_release_artwork.py' if '/artwork-' in path else 'rehearse_source_image_facts.py'))==x['rehearsal_script_sha256']
 if 'evidence_sha256' in x:
  prior='prior-facts' in path
  p=Path('catalog/source-image-facts-v1/evidence-v1.jsonl') if prior else r/'replay-facts-v1.jsonl'
  q=Path('catalog/source-image-facts-v1/questions-v1.jsonl') if prior else r/'questions-v1.jsonl'
  assert sha(p)==x['evidence_sha256'] and sha(q)==x['questions_sha256']
  if not prior:assert sha(r/'replay-outcomes-v1.json')==x['outcomes_sha256']
 if 'input_sha256' in x:
  for name,h in x['input_sha256'].items():assert sha(a/name)==h
 assert not x['physical_or_market_approvals_added'] if 'physical_or_market_approvals_added' in x else not x['physical_or_commerce_approvals_added']
manifest=Path('catalog-build-manifest-source-binding-v1.json');new=json.loads(manifest.read_text());old=json.loads(Path('catalog-build-manifest-source-notation-v1.json').read_text())
assert len(new['steps'])==65 and new['steps'][:62]==old['steps'];assert all(sha(s['path'])==s['sha256'] for s in new['steps'])
build=json.loads((r/'build-result-v1.json').read_text());assert build['manifest_sha256']==sha(manifest) and all(build[k]==v for k,v in new['expected'].items())
preservation=json.loads((r/'preservation-v1.json').read_text())
assert preservation['base_tables_preserved']==42 and preservation['prior_number_events_preserved']==1469 and preservation['prior_source_fact_events_preserved']==1432 and preservation['prior_graph_history_preserved']==743
compilation=json.loads((r/'compilation-v1.json').read_text())
assert compilation['recovered_image_subjects']==17 and compilation['source_mechanic_bindings']==16 and compilation['remaining_priority_subjects']==18 and not compilation['graph_events_added']
for name,h in compilation['input_sha256'].items():assert sha(r/name)==h
outcomes=[json.loads(l) for l in (r/'batch-outcomes-v1.jsonl').read_text().splitlines()]
assert len(outcomes)==51 and len({x['card_id'] for x in outcomes})==51
assert sum(x['outcome']=='evidence_hold' for x in outcomes)==18
cloud=reports[str(r/'cloud-replay-v1.json')]['deployment']
for path,x in reports.items():
 if 'cloud' in path:assert all(x['deployment'][k]==cloud[k] for k in ['revision','url','image','private_iam_verified'])
def gc(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
service=gc('run','services','describe','pokemon-commerce-index','--region=us-west1');iam=gc('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
assert service['status']['latestReadyRevisionName']==cloud['revision']
assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==cloud['revision'])==100
assert not any(m in ['allUsers','allAuthenticatedUsers'] for b in iam.get('bindings',[]) for m in b['members'])
revision=gc('run','revisions','describe',cloud['revision'],'--region=us-west1');assert revision['status']['imageDigest']==cloud['image']
py=Path('/tmp/pokemon-source-binding-tests-final-v2.log').read_text();assert 'Ran 601 tests' in py and py.rstrip().endswith('OK')
node=Path('/tmp/pokemon-source-binding-node-tests-final.log').read_text();assert 'pass 12' in node and 'fail 0' in node
(r/'test-results-v1.json').write_text(json.dumps(dict(python_tests=601,node_tests=12,python_passed=True,node_passed=True,python_log_sha256=sha('/tmp/pokemon-source-binding-tests-final-v2.log'),node_log_sha256=sha('/tmp/pokemon-source-binding-node-tests-final.log')),indent=2)+'\n')
record=dict(schema='pokemon.source-binding-delivery.v1',verified_at=datetime.now(timezone.utc).isoformat(),deployment=cloud,traffic_percent=100,private_iam_verified=True,
 local_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' not in p),cloud_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' in p),
 transport_retries=sum(len(x['transport_errors']) for x in reports.values()),
 unauthenticated_denial_checks=sum(sum(c.get('id','').startswith('unauthenticated:') and c['passed'] for c in x.get('results',[])) for p,x in reports.items() if 'cloud' in p),
 report_bindings={p:dict(sha256=sha(p),checks=x['checks'],transport_errors=x['transport_errors']) for p,x in reports.items()},
 artifact_sha256={str(r/n):sha(r/n) for n in ['number-evidence-v1.jsonl','source-facts-v1.jsonl','mechanic-bindings-v1.jsonl','compilation-v1.json','preservation-v1.json','next-source-targets-v1.jsonl','batch-outcomes-v1.jsonl','grounded-research-audit-v1.json','engineering-diagnostics-v1.json']},
 manifest_sha256=sha(manifest),snapshot_sha256=sha(snapshot),ordered_previous_inputs_preserved=62,new_inputs=3,
 prior_number_events_preserved=1469,prior_fact_events_preserved=1432,prior_graph_rows_preserved=743,base_tables_preserved=42,
 new_source_image_model_subjects=17,new_official_mechanic_bindings=16,new_graph_events=0,new_catalog_identities=0,
 root_catalog_context_visible=True,gemini_catalog_context_visible=False,prior_verdicts_visible=False,
 final_logical_failures=0,population_or_marketplace_accuracy_established=False,physical_or_commerce_approvals_added=False)
assert record['local_checks']==111 and record['cloud_checks']==115 and record['unauthenticated_denial_checks']==4
(r/'delivery-validation-v1.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
Path('cloud-deployment-20261003-source-binding-v1.json').write_text(json.dumps(dict(verified_at=record['verified_at'],**cloud,traffic_percent=100,service_spec=service['spec'],manifest_sha256=record['manifest_sha256'],delivery_report_sha256=sha(r/'delivery-validation-v1.json')),ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:record[k] for k in ['local_checks','cloud_checks','transport_retries','unauthenticated_denial_checks']}))

