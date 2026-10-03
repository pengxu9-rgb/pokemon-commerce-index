from pathlib import Path
import json,hashlib,subprocess
from datetime import datetime,timezone
r=Path('catalog/source-notation-v1');a=Path('catalog/cross-release-artwork-v1');root=Path.cwd()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['local-replay-v1.json','prior-facts-local-v1.json','cloud-replay-v1.json','prior-facts-cloud-v1.json','artwork-local-v1.json','artwork-cloud-v1.json']
paths=[r/n for n in names];reports={str(p):json.loads(p.read_text()) for p in paths};snapshot=Path('/tmp/pokemon-source-notation-v1.sqlite3')
for path,x in reports.items():
 assert x['completed'] and x['checks']==x['planned_checks']==x['passed'],path
 assert x['catalog_bytes_unchanged'] and x['catalog_sha256']==sha(snapshot)
 for n,h in x.get('runtime_sha256',{}).items():assert sha(root/'pokemon_index'/n)==h
 assert sha(root/'scripts'/('rehearse_cross_release_artwork.py' if '/artwork-' in path else 'rehearse_source_image_facts.py'))==x['rehearsal_script_sha256']
 if 'evidence_sha256' in x:
  prior='prior-facts' in path
  p=Path('catalog/source-image-facts-v1/evidence-v1.jsonl') if prior else r/'reused-fact-fixtures-v1.jsonl'
  q=Path('catalog/source-image-facts-v1/questions-v1.jsonl') if prior else r/'questions-v1.jsonl'
  assert sha(p)==x['evidence_sha256'] and sha(q)==x['questions_sha256']
  if not prior:assert sha(r/'complete-replay-outcomes-v1.json')==x['outcomes_sha256']
 if 'input_sha256' in x:
  for name,h in x['input_sha256'].items():assert sha(a/name)==h
 assert not x['physical_or_market_approvals_added'] if 'physical_or_market_approvals_added' in x else not x['physical_or_commerce_approvals_added']
manifest=Path('catalog-build-manifest-source-notation-v1.json');new=json.loads(manifest.read_text());old=json.loads(Path('catalog-build-manifest-source-facts-escalation-v1.json').read_text())
assert len(new['steps'])==62 and new['steps'][:61]==old['steps']
assert all(sha(s['path'])==s['sha256'] for s in new['steps'])
build=json.loads((r/'build-result-v1.json').read_text())
assert build['manifest_sha256']==sha(manifest) and all(build[k]==v for k,v in new['expected'].items())
preservation=json.loads((r/'preservation-v1.json').read_text())
assert preservation['base_tables_preserved']==43 and preservation['prior_number_events_preserved']==1462 and preservation['prior_source_fact_events_preserved']==1432 and preservation['prior_graph_history_preserved']==743
interpretations=json.loads((r/'reinterpretation-audit-v1.json').read_text())
assert len(interpretations['interpretations'])==7 and interpretations['new_inspections']==0 and interpretations['legacy_rule_unchanged']
assert all(x['source_bytes_verified'] and x['image_bytes_verified'] and x['reviews_unchanged'] and x['fresh_model_inspections']==0 for x in interpretations['interpretations'])
notation=json.loads((r/'notation-audit-v1.json').read_text());assert notation['subjects']==26 and not notation['identity_qualification_changed']
coverage=json.loads((r/'coverage-v1.json').read_text());assert coverage['remaining_priority_subjects']==51 and coverage['fresh_ai_inspections']==0 and coverage['new_graph_events']==0
cloud=reports[str(r/'cloud-replay-v1.json')]['deployment']
for path,x in reports.items():
 if 'cloud' in path:assert all(x['deployment'][k]==cloud[k] for k in ['revision','url','image','private_iam_verified'])
def gc(*args):return json.loads(subprocess.check_output(['gcloud',*args,'--project=pivota-staging','--format=json'],text=True))
service=gc('run','services','describe','pokemon-commerce-index','--region=us-west1')
iam=gc('run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1')
assert service['status']['latestReadyRevisionName']==cloud['revision']
assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==cloud['revision'])==100
assert not any(m in ['allUsers','allAuthenticatedUsers'] for b in iam.get('bindings',[]) for m in b['members'])
revision=gc('run','revisions','describe',cloud['revision'],'--region=us-west1');assert revision['status']['imageDigest']==cloud['image']
py=Path('/tmp/pokemon-notation-tests-final.log').read_text();assert 'Ran 593 tests' in py and py.rstrip().endswith('OK')
node=Path('/tmp/pokemon-notation-node-tests-final.log').read_text();assert 'pass 12' in node and 'fail 0' in node
(r/'test-results-v1.json').write_text(json.dumps(dict(python_tests=593,node_tests=12,python_passed=True,node_passed=True,python_log_sha256=sha('/tmp/pokemon-notation-tests-final.log'),node_log_sha256=sha('/tmp/pokemon-notation-node-tests-final.log')),indent=2)+'\n')
record=dict(schema='pokemon.source-notation-delivery.v1',verified_at=datetime.now(timezone.utc).isoformat(),deployment=cloud,traffic_percent=100,private_iam_verified=True,
 local_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' not in p),cloud_checks=sum(x['checks'] for p,x in reports.items() if 'cloud' in p),
 transport_retries=sum(len(x['transport_errors']) for x in reports.values()),
 unauthenticated_denial_checks=sum(sum(c.get('id','').startswith('unauthenticated:') and c['passed'] for c in x.get('results',[])) for p,x in reports.items() if 'cloud' in p),
 report_bindings={p:dict(sha256=sha(p),checks=x['checks'],transport_errors=x['transport_errors']) for p,x in reports.items()},
 artifact_sha256={str(r/n):sha(r/n) for n in ['number-evidence-v1.jsonl','reinterpretation-audit-v1.json','notation-audit-v1.json','preservation-v1.json','next-source-targets-v1.jsonl','coverage-v1.json','publisher-rule-references-v1.json']},
 manifest_sha256=sha(manifest),snapshot_sha256=sha(snapshot),ordered_previous_inputs_preserved=61,new_inputs=1,
 prior_number_events_preserved=1462,prior_fact_events_preserved=1432,prior_graph_rows_preserved=743,base_tables_preserved=43,
 new_number_interpretations=7,structured_notation_subjects=26,fresh_image_model_inspections=0,new_graph_events=0,
 final_logical_failures=0,population_or_marketplace_accuracy_established=False,physical_or_commerce_approvals_added=False)
assert record['local_checks']==108 and record['cloud_checks']==112 and record['unauthenticated_denial_checks']==4
(r/'delivery-validation-v1.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
Path('cloud-deployment-20261003-source-notation-v1.json').write_text(json.dumps(dict(verified_at=record['verified_at'],**cloud,traffic_percent=100,service_spec=service['spec'],manifest_sha256=record['manifest_sha256'],delivery_report_sha256=sha(r/'delivery-validation-v1.json')),ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:record[k] for k in ['local_checks','cloud_checks','transport_retries','unauthenticated_denial_checks']}))
