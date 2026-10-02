"""Combine source visibility, release retrieval and artwork guards for staging.

This is development regression evidence, not held-out collector accuracy.
"""
import argparse,json,hashlib
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_discovery,discovery_graph
from scripts.rehearse_coordinate_families import run as family_run
from scripts.rehearse_printing_source_tasks import run as printing_run


def run(db_path,root,output):
    if output.exists():raise FileExistsError(output)
    family=output.with_name(output.stem+'-families.json')
    printing=output.with_name(output.stem+'-printing.json')
    family_run(db_path,family)
    printing_run(db_path,root/'catalog/printing-source-pilot-v1',printing)
    report=json.loads(family.read_text());facts=json.loads(printing.read_text())
    report['schema']='pokemon.next-priorities-development-rehearsal.v1'
    report['priority_source_checks']=[dict(id=r['id'],question=r['question'],limit=10,result=r['result']) for r in facts['results']]
    alias_checks=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        releases=[json.loads(l) for l in (root/'catalog/release-metadata-next-v1/metadata-v1.jsonl').read_text().splitlines()]
        for release in releases:
            question='Japanese cards from '+release['name']
            actual=collector_discovery.execute(db,question,limit=5)
            passed=bool(actual['cards']) and all(c['set_code']==release['set_code'] and
                c['set_name']==release['name'] and c['release_date']==release['release_date'] for c in actual['cards'])
            item=dict(id='release-alias-'+release['set_code'],question=question,limit=5,result=actual)
            report['priority_source_checks'].append(item)
            alias_checks.append(dict(id=item['id'],passed=passed,expected_set_code=release['set_code']))
        verified=[json.loads(l) for l in (root/'catalog/relationship-independent-priority-v1/verified-artwork-events.jsonl').read_text().splitlines()]
        for edge in verified:
            actual=discovery_graph.card_neighborhood(db,edge['left_card_id'])
            matching=[r for r in actual['relationships'] if r['assertion_id']==edge['assertion_id']]
            assert len(matching)==1 and not matching[0]['price_comparable'] and not matching[0]['endpoint_identity_review_required']
            report['graph_checks'].append(actual)
        held=[json.loads(l) for l in (root/'catalog/relationship-independent-priority-v1/cohort.jsonl').read_text().splitlines()]
        for item in [r for r in held if r['status']=='identity_hold'][:3]:
            cid=next(e['card_id'] for e in item['endpoints'] if e['identity_blockers'])
            actual=discovery_graph.card_neighborhood(db,cid)
            assert not actual['relationships']
            assert any(e['endpoint_identity_review_required'] for e in actual['ai_artwork_candidates'])
            report['graph_checks'].append(actual)
    report['failed']+=facts['failed']+sum(not x['passed'] for x in alias_checks)
    report['release_alias_checks']=alias_checks
    report['printing_source_cases']=facts['cases']
    report['source_fact_visibility_cases_passed']=facts['source_fact_cases_supported']
    report['component_report_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (family,printing)}
    report['interpretation']='Source-led authored diagnostics and local/cloud regression. No real listing, physical printing, population accuracy or complete answers established.'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return dict(failed=report['failed'],family_questions=report['cases'],printing_questions=facts['cases'],
        release_alias_questions=len(alias_checks),graph_checks=len(report['graph_checks']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','output']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path('.'))
    a=p.parse_args();print(json.dumps(run(a.db,a.root,a.output)))
