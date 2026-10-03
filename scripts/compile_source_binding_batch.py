"""Compile recovered publisher scans and exact Prism Star source bindings."""
from pathlib import Path
import json,re,hashlib,tarfile,sqlite3,shutil
from collections import Counter
from pokemon_index import core,number_evidence as n,source_image_facts as f,source_mechanic as m,supported_catalog as s
from scripts.freeze_relationship_identity_review import source_bytes,SOURCE
root=Path('catalog/source-binding-v1')
def read(p):return [json.loads(l) for l in p.read_text().splitlines()]
def save(name,rows):(root/name).write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
base=Path('/tmp/pokemon-source-notation-v1.sqlite3');out=Path('/tmp/pokemon-source-binding-working-v1.sqlite3');assert not out.exists();shutil.copy2(base,out)
reviews=[{r['target_id']:r for r in read(root/name)} for name in ['root-image-review-v1.jsonl','gemini-image-review-v1.jsonl']]
cohort=read(root/'image-review-cohort-v1.jsonl');assert len(cohort)==17 and all(set(r)=={c['target_id'] for c in cohort} for r in reviews)
numbers=[];facts=[];binds=[];derived=[]
with core.connect(out) as db,tarfile.open('../../work/tcgdex-complete-a211f11f3ba57d56c65c5ac33be35b77d3280757.tar.gz') as archive:
 core.init_db(db)
 for c in cohort:
  tid=c['target_id'];snap=c['endpoint_snapshot'];assert n.snapshot(db,snap['card_id'])==snap
  audit=source_bytes(snap['provenance'],archive);assert audit==c['source_audit'];assert digest(Path(c['image_path']))==c['image_sha256']
  match=SOURCE.fullmatch(snap['provenance']);body=archive.extractfile('cards-database-'+match[1]+'/'+match[2]).read().decode();hp=re.findall(r'^\s*hp:\s*(\d+)\s*,?\s*$',body,re.M);assert len(hp)<=1
  c=dict(c,pinned_source_hp=int(hp[0]) if hp else None);c['snapshot_sha256']=s.digest({k:v for k,v in c.items() if k!='snapshot_sha256'});derived.append(c)
  bound=[]
  for rows in reviews:
   r=rows[tid];assert r['status']=='reviewed' and r['source_ref']==c['source_ref'] and r['image_sha256']==c['image_sha256']
   f.validate_reading(r['reading']);bound.append({k:r[k] for k in f.REVIEW_FIELDS if k!='review_record_sha256'}|dict(review_record_sha256=s.digest(r)))
  assert not any(r['prior_verdicts_visible'] for r in bound)
  frev=(db.execute('SELECT max(revision) FROM source_image_fact_evidence WHERE card_id=?',(snap['card_id'],)).fetchone()[0] or 0)+1
  nr=(db.execute('SELECT max(revision) FROM card_number_reading_evidence WHERE card_id=?',(snap['card_id'],)).fetchone()[0] or 0)+1
  recorded=core.utcnow()
  fact=dict(schema=f.SCHEMA,revision=frev,card_id=snap['card_id'],endpoint_snapshot=snap,identity_sha256=c['identity_sha256'],
    source_ref=c['source_ref'],image_sha256=c['image_sha256'],source_file_sha256=audit['sha256'],pinned_source_hp=c['pinned_source_hp'],
    cohort_snapshot_sha256=c['snapshot_sha256'],reviews=bound,recorded_at=recorded,**{k:False for k in f.FALSE_CLAIMS})
  fact['event_id']=f.event_id(fact);f.validate(fact);facts.append(fact)
  number_reviews=[{k:r[k] for k in ['actor','model_family','model_version','reviewed_at','review_record_sha256','source_ref','image_sha256','prior_verdicts_visible']}|dict(observed_name=''.join(r['reading']['title_text_parts']),observed_number_text=r['reading']['observed_number_text']) for r in bound]
  status=n.classify(snap['collector_number'],[r['observed_number_text'] for r in number_reviews],expected_name=snap['name'],observed_names=[r['observed_name'] for r in number_reviews]);assert status=='catalog_text_observed'
  number=dict(schema=n.SCHEMA,revision=nr,card_id=snap['card_id'],endpoint_snapshot=snap,identity_sha256=c['identity_sha256'],source_ref=c['source_ref'],image_sha256=c['image_sha256'],
   review_groups=[dict(candidate_id=tid,cohort_snapshot_sha256=c['snapshot_sha256'],reviews=number_reviews)],status=status,recorded_at=recorded,**{k:False for k in n.FALSE_CLAIMS})
  number['event_id']=n.event_id(number);n.validate(number);numbers.append(number)
 n.import_evidence(db,numbers);f.import_evidence(db,facts)
 frozen={x['priority']['card_id']:x for x in read(root/'frozen-cohort-v1.jsonl')}
 for a in read(root/'official-audit-v1.jsonl'):
  if a['reason']!='title_symbol_unconfirmed':continue
  q=frozen[a['card_id']];assert len(a['official_attempts'])==len(q['references'])==1
  ref=q['references'][0];e=a['official_attempts'][0];receipt=e['receipt'];raw=(root/'publisher'/(ref['native_id']+'.html')).read_bytes()
  assert hashlib.sha256(raw).hexdigest()==receipt['page_sha256'];header=re.findall(r'<h1 class="Heading1 mt20">(.*?)</h1>',raw.decode(),re.S)
  assert len(header)==1 and header[0].count('pcg-prismstar')==1 and e['prism_rule_present'] and e['exact_number'] and e['parsed']['page_kind']=='single_number'
  head=m.fact_head(db,a['card_id']);assert head==q['latest_fact'];off=e['parsed'];entry=off['numbered_entries'][0]
  official=dict(**receipt,name=off['name'],set_code=entry['set_code'],collector_number=entry['collector_number'],title_symbol='prism_star',special_rule='prism_star',page_kind=off['page_kind'])
  row=dict(schema=m.SCHEMA,revision=1,card_id=a['card_id'],endpoint_snapshot=q['endpoint_snapshot'],identity_sha256=q['identity_sha256'],
   source_fact_event_id=head['event_id'],source_fact_sha256=s.digest(head),reference={k:ref[k] for k in ['source','native_id','name','provenance']},
   official=official,mechanic='prism_star',recorded_at=core.utcnow(),**{k:False for k in m.FALSE_CLAIMS})
  row['event_id']=m.event_id(row);m.validate(row);binds.append(row)
 assert len(binds)==16;m.import_evidence(db,binds)
 status=core.catalog_status(db)
save('compiled-cohort-v1.jsonl',derived);save('number-evidence-v1.jsonl',numbers);save('source-facts-v1.jsonl',facts);save('mechanic-bindings-v1.jsonl',binds)
done={r['card_id'] for r in numbers+binds};remaining=[q['priority'] for q in frozen.values() if q['priority']['card_id'] not in done];assert len(remaining)==18;save('next-source-targets-v1.jsonl',remaining)
manifest=json.loads(Path('catalog-build-manifest-source-notation-v1.json').read_text());assert len(manifest['steps'])==62
for op,name in [('import-number-reading-evidence','number-evidence-v1.jsonl'),('import-source-image-facts','source-facts-v1.jsonl'),('import-source-mechanic-bindings','mechanic-bindings-v1.jsonl')]:
 p=root/name;manifest['steps'].append(dict(operation=op,path=str(p),sha256=digest(p)))
manifest['expected'].update(status['number_reading_evidence']);manifest['expected'].update(status['source_image_facts']);manifest['expected'].update(status['source_mechanic_bindings'])
manifest['description']='Preserve all 62 prior inputs. Add17 recovered exact publisher stock-image readings from OpenAI root/context visible and image-only Vertex Gemini, and16 exact official Prism Star mechanic bindings. Original catalog identities and facts preserved; no physical or commerce approvals.'
Path('catalog-build-manifest-source-binding-v1.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
report=dict(recovered_image_subjects=17,source_mechanic_bindings=16,remaining_priority_subjects=18,remaining_reasons=dict(Counter(x['reason'] for x in remaining)),
 numbers=status['number_reading_evidence'],facts=status['source_image_facts'],mechanics=status['source_mechanic_bindings'],
 graph_events_added=0,catalog_identities_added=0,root_catalog_context_visible=True,gemini_catalog_context_visible=False,prior_verdicts_supplied=False,
 image_and_pinned_source_bytes_verified=True,input_sha256={name:digest(root/name) for name in ['image-review-cohort-v1.jsonl','root-image-review-v1.jsonl','gemini-image-review-v1.jsonl','official-audit-v1.jsonl','frozen-cohort-v1.jsonl']})
(root/'compilation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report))

