import json,sqlite3,tarfile,shutil,hashlib
from pathlib import Path
from collections import Counter
from pokemon_index import core,number_evidence,source_image_facts as facts
from scripts.compile_cross_release_numbers import compile_reviews
from scripts.compile_source_image_facts import keyed,compile_reviews as compile_facts
from scripts.freeze_relationship_identity_review import digest
root=Path('catalog/source-facts-thousand-v1');baseline=Path('/tmp/pokemon-cross-release-source-facts-v1.sqlite3');out=Path('/tmp/pokemon-source-facts-thousand-working-v1.sqlite3');archive=Path('../../work/tcgdex-complete-a211f11f3ba57d56c65c5ac33be35b77d3280757.tar.gz')
def write(name,rows):
 with (root/name).open('x') as f:
  for r in rows:f.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n')
assets_list=json.loads((root/'assets-v4.json').read_text());assets={r['target_id']:r for r in assets_list};targets=keyed(root/'bound-targets-v1.jsonl');cohort=keyed(root/'image-cohort-v1.jsonl');first=keyed(root/'vision-review-v1.jsonl');second=keyed(root/'gemini-selected-v1.jsonl')
with core.connect(baseline,readonly=True) as db,tarfile.open(archive) as ar:
 events,outcomes,fc=compile_reviews(db,ar,targets,assets,cohort,first,second,1000)
write('number-evidence-v1.jsonl',events);write('fact-cohort-v1.jsonl',fc)
s=dict(schema='pokemon.cross-release-number-compilation.v1',targets=1000,number_evidence_events=len(events),statuses=dict(Counter(r['status'] for r in outcomes)),outcomes=outcomes,scope='OCR plus Gemini initial screening of source image title/number. Not two image models, independent ground truth, or physical identity.',decoded_images=len(cohort),source_bytes_verified_subjects=1000,image_bytes_verified_subjects=len(cohort),physical_or_commerce_approvals_added=False,independence_or_marketplace_accuracy_established=False)
(root/'number-compilation-v1.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
if out.exists():raise FileExistsError(out)
shutil.copy2(baseline,out)
with core.connect(out) as db,tarfile.open(archive) as ar:
 number_evidence.import_evidence(db,events)
 ids={r['target_id'] for r in fc};fact_events=compile_facts(db,ar,{r['target_id']:r for r in fc},{k:v for k,v in first.items() if k in ids},{k:v for k,v in second.items() if k in ids})
 facts.import_evidence(db,fact_events)
 status=core.catalog_status(db)
write('evidence-v1.jsonl',fact_events)
(root/'compilation-v1.json').write_text(json.dumps(dict(schema='pokemon.source-image-fact-compilation.v1',subjects=len(fact_events),inspection_tier='ocr_and_image_model_screening',outcomes=[dict(card_id=r['card_id'],**facts.outcomes(r)) for r in fact_events],name_statuses=dict(Counter(facts.outcomes(r)['name_status'] for r in fact_events)),hp_statuses=dict(Counter(facts.outcomes(r)['hp_status'] for r in fact_events)),image_and_source_bytes_verified=True,independent_review_agreement_established=False,number_reading_qualification_changed=False),ensure_ascii=False,indent=2)+'\n')
manifest=json.loads(Path('catalog-build-manifest-cross-release-source-facts-v1.json').read_text())
assert len(manifest['steps'])==55
for operation,name in [('import-number-reading-evidence','number-evidence-v1.jsonl'),('import-source-image-facts','evidence-v1.jsonl')]:
 p=root/name;manifest['steps'].append(dict(operation=operation,path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
manifest['expected'].update(status['number_reading_evidence']);manifest['expected'].update(status['source_image_facts']);manifest['description']='Preserve all 55 prior ordered inputs and graph decisions. Append source-scoped OCR plus Gemini image-only initial screenings from a frozen thousand; method tiers disclosed separately. Missing images and unreadable fields remain held; no physical, graph or commerce approval.'
Path('catalog-build-manifest-source-facts-thousand-v1.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(root/'coverage-working-v1.json').write_text(json.dumps(dict(catalog_status=status,number_statuses=s['statuses'],batch_subjects=len(fact_events),scope='Initial screening, not new catalog SKUs or relationship edges.'),ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(number=s['statuses'],fact_subjects=len(fact_events),title_advisories=sum(facts.outcomes(r)['name_status']!='unconfirmed' for r in fact_events),hp=Counter(facts.outcomes(r)['hp_status'] for r in fact_events)),ensure_ascii=False))
