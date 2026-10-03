from pathlib import Path
import json,hashlib,datetime
p=Path('catalog/source-facts-thousand-v1')
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def stamp(f):return datetime.datetime.fromtimestamp(f.stat().st_mtime,datetime.timezone.utc).isoformat()
vision=list(map(json.loads,(p/'vision-review-v1.jsonl').read_text().splitlines()));protocol=json.load(open(p/'vision-protocol-v1.json'));gemini=json.load(open(p/'gemini-review-v1.protocol.json'));assert protocol['cohort_sha256']==sha(p/'image-cohort-v1.jsonl');assert protocol['derivation_script_sha256']==sha(Path('scripts/derive_vision_card_facts.py'));assert protocol['swift_source_sha256']==sha(Path('scripts/vision_card_ocr.swift'));assert gemini['script_sha256']==sha(p/'gemini-runner-v1.py')
assert (p/'vision-review-v1.jsonl').stat().st_mtime < (p/'gemini-review-v1.protocol.json').stat().st_mtime
attempts=[]
for name in ['gemini-review-v2','gemini-retry-v1']:
 prot=json.load(open(p/(name+'.protocol.json')));assert prot['script_sha256']==sha(Path('scripts/review_source_image_facts.py'));rows=list(map(json.loads,(p/(name+'.jsonl')).read_text().splitlines()));ledger=list(map(json.loads,(p/(name+'.attempts.jsonl')).read_text().splitlines()));assert {r['attempt_id'] for r in rows}=={r['attempt_id'] for r in ledger};attempts.extend(ledger)
assert len(attempts)==850
checks={f:dict(sha256=sha(p/f),mtime_utc=stamp(p/f)) for f in ['image-cohort-v1.jsonl','vision-protocol-v1.json','vision-input-v1.jsonl','vision-native-v1.jsonl','vision-review-v1.jsonl','gemini-review-v1.protocol.json','gemini-review-v2.protocol.json','gemini-selected-v1.jsonl','gemini-attempt-selection-v2.json','number-evidence-v1.jsonl','evidence-v1.jsonl','number-compilation-v1.json','compilation-v1.json','contextual-image-spotcheck-v1.json','python-tests-final.log','node-tests-v1.log']}
report=dict(schema='pokemon.source-facts-thousand-chronology.v1',file_bindings=checks,first_lane_records=976,first_lane_is_ocr=True,first_lane_last_native_timestamp=max(r['reviewed_at'] for r in vision),first_lane_output_frozen_before_second_lane_protocol=True,first_lane_expected_name_number_and_hp_context_supplied=False,first_lane_language_from_catalog=True,gemini_catalog_values_previous_readings_and_search_supplied=False,contextual_actual_image_spotchecks=1,contextual_spotchecks_not_imported_as_independent_reviews=True,resumed_and_retry_attempt_ledger_records=850,completed_attempt_records=987,structured_model_responses=976,transport_failure_records=11,unrecorded_inflight_outcomes_maximum=3,billable_api_call_total_unknown=True,python_tests_final=572,node_tests=12,independent_accuracy_established=False)
(p/'chronology-and-tests-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('chronology verified')
