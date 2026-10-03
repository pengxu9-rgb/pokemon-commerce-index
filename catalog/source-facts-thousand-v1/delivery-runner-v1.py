from pathlib import Path
import json,hashlib,subprocess,datetime
p=Path('catalog/source-facts-thousand-v1');root=Path.cwd()
def sha(f):return hashlib.sha256(Path(f).read_bytes()).hexdigest()
reports={name:json.load(open(p/name)) for name in ['local-replay-v2.json','prior-facts-local-v1.json','private-cloud-replay-v3.json','prior-facts-cloud-v1.json']}
for name,r in reports.items():
 assert r['completed'] and r['checks']==r['planned_checks']==r['passed'],name
 assert r['catalog_bytes_unchanged'] and r['catalog_sha256']==sha('/tmp/pokemon-source-facts-thousand-v1.sqlite3')
 assert all(sha(root/'pokemon_index'/f)==v for f,v in r['runtime_sha256'].items())
 assert r['evidence_sha256']==sha('catalog/source-facts-thousand-v1/evidence-v1.jsonl' if name in ['local-replay-v2.json','private-cloud-replay-v3.json'] else 'catalog/source-image-facts-v1/evidence-v1.jsonl')
 assert not r['physical_or_market_approvals_added'] and not r['independent_real_user_or_marketplace_accuracy_established']
new=json.load(open('catalog-build-manifest-source-facts-thousand-v1.json'));old=json.load(open('catalog-build-manifest-cross-release-source-facts-v1.json'));assert len(new['steps'])==57 and new['steps'][:55]==old['steps']
assert all(sha(s['path'])==s['sha256'] for s in new['steps'])
build=json.load(open(p/'build-result-v1.json'));assert build['manifest_sha256']==sha('catalog-build-manifest-source-facts-thousand-v1.json')
assert all(build[k]==v for k,v in new['expected'].items())
cloud=reports['private-cloud-replay-v3.json']['deployment'];assert reports['prior-facts-cloud-v1.json']['deployment']==cloud
service=json.loads(subprocess.check_output(['gcloud','run','services','describe','pokemon-commerce-index','--region=us-west1','--project=pivota-staging','--format=json'],text=True));iam=json.loads(subprocess.check_output(['gcloud','run','services','get-iam-policy','pokemon-commerce-index','--region=us-west1','--project=pivota-staging','--format=json'],text=True))
assert service['status']['latestReadyRevisionName']==cloud['revision'];assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==cloud['revision'])==100
assert not any(m in ['allUsers','allAuthenticatedUsers'] for b in iam.get('bindings',[]) for m in b['members'])
revision=json.loads(subprocess.check_output(['gcloud','run','revisions','describe',cloud['revision'],'--region=us-west1','--project=pivota-staging','--format=json'],text=True));assert revision['status']['imageDigest']==cloud['image']
combined=dict(local_checks=sum(r['checks'] for name,r in reports.items() if 'cloud' not in name),cloud_checks=sum(r['checks'] for name,r in reports.items() if 'cloud' in name),final_transport_retries=sum(len(r['transport_errors']) for r in reports.values()),unauthenticated_denial_checks=sum(sum(c['id'].startswith('unauthenticated:') and c['passed'] for c in r['results']) for name,r in reports.items() if 'cloud' in name))
coverage=json.load(open(p/'coverage-v1.json'));assert coverage['coordinates']==45438 and coverage['new_catalog_identities_added']==0 and coverage['new_graph_decisions_added']==0
records={name:dict(sha256=sha(p/name),checks=r['checks'],transport_errors=r['transport_errors']) for name,r in reports.items()}
record=dict(schema='pokemon.source-facts-thousand-delivery.v1',verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),deployment=cloud,traffic_percent=100,private_iam_verified=True,report_bindings=records,**combined,manifest_sha256=sha('catalog-build-manifest-source-facts-thousand-v1.json'),snapshot_sha256=sha('/tmp/pokemon-source-facts-thousand-v1.sqlite3'),catalog_revision=coverage['catalog_revision'],runtime_sha256=reports['private-cloud-replay-v3.json']['runtime_sha256'],ordered_previous_inputs_preserved=55,new_compiled_inputs=2,prior_number_events_preserved=178,prior_fact_events_preserved=148,base_tables_preserved=42,ocr_initial_screening_subjects=976,two_image_model_subjects_added=0,previous_failed_cloud_replay_retained=True,final_logical_failures=0,independent_ground_truth_or_marketplace_accuracy_established=False,physical_or_commerce_approvals_added=False)
(p/'delivery-validation-v1.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');Path('cloud-deployment-20261003-source-facts-thousand-v1.json').write_text(json.dumps(dict(verified_at=record['verified_at'],**cloud,traffic_percent=100,service_spec=service['spec'],manifest_sha256=record['manifest_sha256'],delivery_report_sha256=sha(p/'delivery-validation-v1.json')),ensure_ascii=False,indent=2)+'\n');print(json.dumps(combined))
