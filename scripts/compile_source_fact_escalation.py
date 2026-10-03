"""Append separate image-model inspections against frozen evidence heads.

The original OCR observations remain immutable. A second reading does not
inherit its predecessor's verdict or grant identity, copy or commerce approval.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3, tarfile
from collections import Counter
from pathlib import Path
from pokemon_index import core, number_evidence as numbers, source_image_facts as facts
from scripts.compile_source_image_facts import keyed
from scripts.freeze_relationship_identity_review import digest, source_bytes, SOURCE


def head(db, table, card_id):
    found = db.execute('SELECT record_json FROM '+table+' WHERE card_id=? ORDER BY revision DESC LIMIT 1', (card_id,)).fetchone()
    return json.loads(found[0]) if found else None


def freeze_heads(db, cohort):
    if len({c['endpoint_snapshot']['card_id'] for c in cohort.values()})!=len(cohort):
        raise ValueError('unique evidence subjects required')
    result = []
    for tid, original in sorted(cohort.items()):
        if digest({k:v for k,v in original.items() if k!='snapshot_sha256'}) != original['snapshot_sha256']:
            raise ValueError('image cohort changed')
        row = dict(original)
        row['prior_image_cohort_snapshot_sha256'] = row.pop('snapshot_sha256')
        cid = row['endpoint_snapshot']['card_id']
        for table, prefix, validate in [('card_number_reading_evidence','number',numbers.validate), ('source_image_fact_evidence','source_fact',facts.validate)]:
            prior = head(db, table, cid)
            if prior is None: raise ValueError('existing evidence head required')
            validate(prior)
            if any(prior[k] != row[k] for k in ['source_ref','image_sha256','endpoint_snapshot','identity_sha256']):
                raise ValueError('existing head has another source image')
            if prefix=='number' and prior['event_id']!=row['prior_number_event_id']:
                raise ValueError('number head changed before freeze')
            row['prior_'+prefix+'_event_id'] = prior['event_id']
            row['prior_'+prefix+'_revision'] = prior['revision']
        row['snapshot_sha256'] = digest(row)
        result.append(row)
    return result


def compile_reviews(db, archive, cohort, first, second):
    if not cohort or set(cohort)!=set(first) or set(cohort)!=set(second):
        raise ValueError('complete frozen review membership required')
    if len({c['endpoint_snapshot']['card_id'] for c in cohort.values()})!=len(cohort):
        raise ValueError('unique evidence subjects required')
    number_rows, fact_rows, outcomes = [], [], []
    for tid, c in sorted(cohort.items()):
        if digest({k:v for k,v in c.items() if k!='snapshot_sha256'})!=c['snapshot_sha256']:
            raise ValueError('escalation cohort changed')
        snap=c['endpoint_snapshot']; cid=snap['card_id']
        if numbers.snapshot(db,cid)!=snap or digest(snap)!=c['identity_sha256']:
            raise ValueError('endpoint drift')
        for table,prefix,validator in [('card_number_reading_evidence','number',numbers.validate),('source_image_fact_evidence','source_fact',facts.validate)]:
            prior=head(db,table,cid)
            if prior is None or prior['event_id']!=c['prior_'+prefix+'_event_id'] or prior['revision']!=c['prior_'+prefix+'_revision']:
                raise ValueError('stale '+prefix+' head')
            validator(prior)
            if any(prior[k]!=c[k] for k in ['source_ref','image_sha256','endpoint_snapshot','identity_sha256']):
                raise ValueError('prior exact source image changed')
        audit=source_bytes(snap['provenance'],archive)
        if audit!=c['source_audit']:raise ValueError('source bytes changed')
        m=SOURCE.fullmatch(snap['provenance'])
        body=archive.extractfile('cards-database-'+m[1]+'/'+m[2]).read().decode()
        hp=re.findall(r'^\s*hp:\s*(\d+)\s*,?\s*$',body,re.M)
        if len(hp)>1 or (int(hp[0]) if hp else None)!=c['pinned_source_hp']:
            raise ValueError('pinned HP changed')
        if hashlib.sha256(Path(c['image_path']).read_bytes()).hexdigest()!=c['image_sha256']:
            raise ValueError('image bytes changed')
        raw=[first[tid],second[tid]]
        if any(r['status']!='reviewed' for r in raw):
            outcomes.append(dict(target_id=tid,card_id=cid,status='review_incomplete',number_event_id=None,source_fact_event_id=None,previous_heads_preserved=True));continue
        if {r['model_family'].casefold() for r in raw}!={'openai','google'}:
            raise ValueError('two image-model families required; OCR is not an upgrade')
        bound=[]; fact_reviews=[]
        for r in raw:
            if r['target_id']!=tid or r['source_ref']!=c['source_ref'] or r['image_sha256']!=c['image_sha256']:
                raise ValueError('inspection image substituted')
            if r['prior_verdicts_visible'] is not False or r['expected_catalog_context_visible'] is not False:
                raise ValueError('blind inspection context required')
            facts.validate_reading(r['reading'])
            fact_reviews.append({k:r[k] for k in facts.REVIEW_FIELDS if k!='review_record_sha256'}|dict(review_record_sha256=digest(r)))
            bound.append({k:r[k] for k in ['actor','model_family','model_version','reviewed_at','source_ref','image_sha256','prior_verdicts_visible']}|
                dict(observed_number_text=r['reading']['observed_number_text'],observed_name=facts.title_interpretation(r['reading'])['canonical_candidate'],review_record_sha256=digest(r)))
        status=numbers.classify(snap['collector_number'],[r['observed_number_text'] for r in bound],expected_name=snap['name'],observed_names=[r['observed_name'] for r in bound])
        when=max((r['reviewed_at'] for r in bound),key=core.parse_time)
        nr=dict(schema=numbers.SCHEMA,revision=c['prior_number_revision']+1,card_id=cid,endpoint_snapshot=snap,identity_sha256=c['identity_sha256'],source_ref=c['source_ref'],image_sha256=c['image_sha256'],review_groups=[dict(candidate_id=tid,cohort_snapshot_sha256=c['snapshot_sha256'],reviews=bound)],status=status,recorded_at=when,**{k:False for k in numbers.FALSE_CLAIMS})
        nr['event_id']=numbers.event_id(nr);numbers.validate(nr);number_rows.append(nr)
        fr=dict(schema=facts.SCHEMA,revision=c['prior_source_fact_revision']+1,card_id=cid,endpoint_snapshot=snap,identity_sha256=c['identity_sha256'],source_ref=c['source_ref'],image_sha256=c['image_sha256'],source_file_sha256=audit['sha256'],pinned_source_hp=c['pinned_source_hp'],cohort_snapshot_sha256=c['snapshot_sha256'],reviews=fact_reviews,recorded_at=when,**{k:False for k in facts.FALSE_CLAIMS})
        fr['event_id']=facts.event_id(fr);facts.validate(fr);fact_rows.append(fr)
        outcomes.append(dict(target_id=tid,card_id=cid,status=status,number_event_id=nr['event_id'],source_fact_event_id=fr['event_id'],prior_number_event_id=c['prior_number_event_id'],prior_source_fact_event_id=c['prior_source_fact_event_id'],catalog_number=snap['collector_number'],observed_number_texts=[r['observed_number_text'] for r in bound],observed_names=[r['observed_name'] for r in bound],source_fact_outcome=facts.outcomes(fr)))
    return number_rows,fact_rows,outcomes


def write(path,rows):
    if path.exists():raise FileExistsError('use fresh immutable output')
    path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--cohort',type=Path,required=True)
    p.add_argument('--freeze-output',type=Path)
    for k in ['archive','first','second','number-output','fact-output','summary']:p.add_argument('--'+k,type=Path)
    a=p.parse_args()
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if a.freeze_output:write(a.freeze_output,freeze_heads(db,keyed(a.cohort)))
        else:
            if any(getattr(a,k.replace('-','_')) is None for k in ['archive','first','second','number-output','fact-output','summary']):p.error('complete compilation paths required')
            if any(f.exists() for f in [a.number_output,a.fact_output,a.summary]):raise FileExistsError('fresh outputs required')
            with tarfile.open(a.archive) as archive:
                nr,fr,outcomes=compile_reviews(db,archive,keyed(a.cohort),keyed(a.first),keyed(a.second))
            write(a.number_output,nr);write(a.fact_output,fr)
            report=dict(schema='pokemon.source-fact-escalation-compilation.v1',subjects=len(outcomes),number_events=len(nr),fact_events=len(fr),statuses=dict(Counter(r['status'] for r in outcomes)),outcomes=outcomes,input_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.cohort,a.first,a.second]},source_and_image_bytes_verified=True,prior_heads_guarded=True,physical_or_commerce_approvals_added=False,independent_accuracy_established=False)
            a.summary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:report[k] for k in ['subjects','number_events','fact_events','statuses']}))
