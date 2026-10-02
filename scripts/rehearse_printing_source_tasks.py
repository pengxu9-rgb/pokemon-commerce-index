"""Replay frozen source-led printing questions; retain omissions and abstention.

This development diagnostic does not grade semantic accuracy or physical copies.
Initial outputs must be preserved and never replaced by a corrected replay.
"""
import argparse,json,hashlib
from pathlib import Path
from contextlib import closing
from pokemon_index import core,collector_discovery,collector_journey,printing_evidence


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def readings(value):
    found=[]
    if isinstance(value,dict):
        if {'claim','value','source_url','scope'}.issubset(value):found.append(value)
        for item in value.values():found.extend(readings(item))
    elif isinstance(value,list):
        for item in value:found.extend(readings(item))
    return found


def run(db_path,cohort,output):
    if output.exists():raise FileExistsError(output)
    inputs=cohort/'questions-frozen-v1.jsonl';lock=json.loads((cohort/'questions-lock-v1.json').read_text())
    if digest(inputs)!=lock['questions_sha256'] or digest(cohort/'evidence-v1.jsonl')!=lock['evidence_sha256']:raise ValueError('frozen source/expectation changed')
    baseline=digest(db_path);runtime_files=[Path(m.__file__) for m in (core,collector_discovery,collector_journey,printing_evidence)]
    hashes={p.name:digest(p) for p in runtime_files};cases=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        for row in [json.loads(l) for l in inputs.read_text().splitlines()]:
            response=collector_discovery.execute(db,row['question'],limit=10,offset=0)
            observed=readings(response)
            wanted=(row['expected_claim'],row['expected_value'])
            source_fact_found=any((r['claim'],r['value'])==wanted for r in observed) if wanted[0] else None
            unsupported_market=bool(response['prices'] or response['live_offers'])
            blockers=response.get('unfulfilled_constraints',[])
            negative_ok=(not unsupported_market and (bool(blockers) or bool(response.get('next_question')))) if row.get('require_copy_or_market_block') else None
            passed=not unsupported_market and (source_fact_found if wanted[0] else negative_ok)
            cases.append(dict(id=row['id'],question=row['question'],passed=passed,source_fact_found=source_fact_found,
                unsupported_market=unsupported_market,returned_card_ids=[c['card_id'] for c in response['cards']],
                expected_source_claim=row['expected_claim'],expected_source_value=row['expected_value'],result=response))
    if digest(db_path)!=baseline:raise ValueError('read-only replay changed catalog')
    if hashes!={p.name:digest(p) for p in runtime_files}:raise ValueError('runtime changed during initial replay')
    report=dict(schema='pokemon.printing-source-development-rehearsal.v1',cases=len(cases),passed=sum(r['passed'] for r in cases),
        source_fact_cases=sum(r['expected_source_claim'] is not None for r in cases),source_fact_cases_supported=sum(r['source_fact_found'] is True for r in cases),
        unsupported_market_cases=sum(r['unsupported_market'] for r in cases),failed=sum(not r['passed'] for r in cases),
        questions_sha256=lock['questions_sha256'],evidence_sha256=lock['evidence_sha256'],catalog_sha256=baseline,catalog_revision=revision,runtime_sha256=hashes,
        independent_held_out_accuracy_measurement=False,results=cases,
        interpretation='Twenty source-led authored diagnostics; first-page source-fact visibility and explicit abstention only. No claim of useful complete answers, global coverage, blind image accuracy or marketplace precision.')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ['cases','passed','failed','source_fact_cases_supported','unsupported_market_cases']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','cohort','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.db,a.cohort,a.output)))
