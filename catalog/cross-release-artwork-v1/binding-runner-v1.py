import json,hashlib,shutil,sqlite3
from pathlib import Path
from collections import Counter
from pokemon_index import core,number_evidence,discovery_graph
from scripts.compile_source_image_facts import keyed
from scripts.freeze_relationship_identity_review import digest,check_current
from scripts.adjudicate_relationship_expansion import adjudicate
from scripts.adjudicate_artwork_controls import adjudicate as differences
r=Path('catalog/cross-release-artwork-v1');cache=Path('/tmp/pokemon-blind-cross-artwork-v1');cohort={x['candidate_id']:x for x in map(json.loads,(r/'cohort-v1.jsonl').read_text().splitlines())};source=keyed(Path('catalog/cross-release-source-facts-v1/next-artwork-pair-targets-v1.jsonl'));blind=keyed(cache/'pairs-v2.jsonl');astra=keyed(cache/'astra-readings.jsonl');man=json.loads((cache/'astra-inspection-manifest.json').read_text());sheets={x['target_id']:x for x in man}
for x in man:assert x['inspected'] and hashlib.sha256(Path(x['sheet_path']).read_bytes()).hexdigest()==x['sheet_sha256']
assert set(astra)==set(cohort)==set(blind)==set(sheets)
for name in ['pairs-v2.jsonl','astra-readings.jsonl','astra-inspection-manifest.json']:shutil.copyfile(cache/name,r/name)
g={x['candidate_id']:x for x in map(json.loads,(r/'gemini-review-v1.jsonl').read_text().splitlines()) if x['status']=='reviewed'};controls=keyed(r/'gemini-controls-review-v1.jsonl');retry=keyed(r/'gemini-controls-review-v2.jsonl');assert set(retry)=={'cross-artwork-014'} and controls['cross-artwork-014']['status']=='review_failed';controls.update(retry)
assets=[];first={};second={}
def bind(tid,raw,is_control=False,is_astra=False):
 f=cohort[tid];old=source[tid];reads=raw['readings'] if is_astra or is_control else raw['coordinate_readings'];images=[];checks=[];readings=[]
 for side in ['left','right']:
  x=old[side];ep=x['endpoint_snapshot'];label=side if is_astra or is_control else ep['language'];rd=next(v for v in reads if v['side']==label);im=next(v for v in blind[tid]['images'] if v['side']==side)
  assert hashlib.sha256(Path(im['image_path']).read_bytes()).hexdigest()==x['image_sha256']==im['image_sha256']
  if is_astra:assert rd['image_sha256']==x['image_sha256']
  images.append(dict(side=side,card_id=ep['card_id'],source_ref=x['source_ref'],image_sha256=x['image_sha256']))
  checks.append(core._compact_identity_text(rd['name'])==core._compact_identity_text(ep['name']) and core.normalize_collector_number(rd['collector_number']).upper()==ep['collector_number'].upper())
  readings.append(dict(side=side,card_id=ep['card_id'],name=rd['name'],collector_number=rd['collector_number']))
 # Prism icon is not a catalog name-concept confirmation. Preserve that hold.
 identity=all(checks) and not any('◇' in rd['name'] or '☆' in rd['name'] for rd in reads)
 decision=raw['artwork_decision'] if is_astra or is_control else raw['artwork']['outcome'];rationale=raw['rationale'] if is_astra or is_control else raw['artwork']['note']
 row=dict(schema='pokemon.relationship-artwork-inspection.v1',candidate_id=tid,cohort_snapshot_sha256=f['cohort_snapshot_sha256'],reviewer=raw['actor'] if is_astra or is_control else raw['reviewer'],model_family=raw['model_family'],model_version=raw['model_version'],reviewed_at=raw['reviewed_at'],first_review_verdicts_visible=False,expected_catalog_context_visible=False if is_astra or is_control else True,decision={'same':'same_artwork','different':'different_artwork','uncertain':'uncertain'}[decision] if identity else 'uncertain',endpoint_coordinate_identity_checked=identity,image_evidence=images,coordinate_readings=readings,artwork=dict(outcome=decision if identity else 'uncertain',note=rationale),finish=dict(outcome='not_comparable',note='Source stock images do not establish physical printing, foil, seller copy, condition, or price equivalence.'),physical_printing_verified=False,price_comparable=False,automatic_offer_join_allowed=False,display_allowed=False,status='reviewed',raw_review_record_sha256=digest(raw))
 if is_astra:row['inspection_sheet_sha256']=sheets[tid]['sheet_sha256'];assert raw['prior_verdicts_visible'] is False and raw['expected_catalog_context_visible'] is False
 else:
  for key in ['protocol_sha256','prompt_sha256','response_sha256']:
   if key in raw:row[key]=raw[key]
 return row
for tid in sorted(cohort):
 for x in blind[tid]['images']:
  old=source[tid][x['side']];assets.append(dict(candidate_id=tid,side=x['side'],card_id=old['endpoint_snapshot']['card_id'],status='source_hash_verified',source_ref=old['source_ref'],image_sha256=old['image_sha256'],path=x['image_path']))
 first[tid]=bind(tid,astra[tid],is_astra=True)
 second[tid]=bind(tid,controls[tid],is_control=True) if tid in controls else bind(tid,g[tid])
def write(name,rows):
 with (r/name).open('x') as f:f.write(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rows))
write('astra-bound-v1.jsonl',first.values());write('gemini-bound-v1.jsonl',second.values());(r/'assets-v2.json').write_text(json.dumps(assets,ensure_ascii=False,indent=2)+'\n')
with core.connect('/tmp/pokemon-source-facts-thousand-v1.sqlite3',readonly=True) as db:
 positive,holds=adjudicate(db,cohort,first,second,assets)
 negative_ids={tid for tid in cohort if first[tid]['decision']==second[tid]['decision']=='different_artwork'}
 negative,results=differences(db,{k:v for k,v in cohort.items() if k in negative_ids},{k:v for k,v in first.items() if k in negative_ids},{k:v for k,v in second.items() if k in negative_ids},assets)
write('verified-artwork-events-v1.jsonl',positive);write('qualified-difference-events-v1.jsonl',negative);write('positive-lane-holds-v1.jsonl',holds)
summary=dict(pairs=len(cohort),raw_astra_decisions=dict(Counter(x['artwork_decision'] for x in astra.values())),qualified_same_artwork_events=len(positive),qualified_artwork_difference_events=len(negative),final_holds=[dict(candidate_id=k,reason='printed_symbol_identity_unconfirmed') for k in cohort if first[k]['decision']=='uncertain' or second[k]['decision']=='uncertain'],difference_results=results,all_28_source_hashes_verified=True,separate_verdicts=True,ground_truth_accuracy_established=False,physical_or_price_permissions_added=False,method='Astra blind images. Gemini expected coordinates visible for 11 cross-language pairs, blind images for 3 same-language controls. Original invalid language-side binding run retained; corrected exact-record bindings. One malformed control response retried with history retained.')
(r/'adjudication-v1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
