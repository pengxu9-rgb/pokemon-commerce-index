"""Read-only family/copy blockers and catalog result regression replay."""
import argparse,json,hashlib
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_discovery,collector_journey,discovery_graph

QUESTIONS=['Japanese SV8A 001/187 master ball','Japanese SV8A 002/187 non-holo',
 'Japanese SV4A 001/190 non-holo','Japanese SV4A 025/190','Japanese SV-P 021/SV-P',
 'Japanese SV-P 022/SV-P','Japanese SV-P 153/SV-P','Japanese SV-P 037/SV-P',
 'Japanese SV-P 044/SV-P','Japanese SV8 138/106','Japanese SV11W 094/086',
 'Japanese M-P 046/M-P','Japanese M6A 151/103','Japanese M6 071/076',
 'Japanese M6 073/076','Japanese M6 075/076','Japanese SV4A 347/190 holo',
 'Japanese Yuka Morii cards','English counterpart of Japanese SV8A 001/187','Cheapest Japanese Pikachu card']


def run(path,output):
    if output.exists():raise FileExistsError(output)
    before=hashlib.sha256(path.read_bytes()).hexdigest();results=[];families=[];parts=[];graphs=[]
    with closing(core.connect(path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        for i,q in enumerate(QUESTIONS):
            ids=[];offset=0;first=None
            while True:
                r=collector_discovery.execute(db,q,limit=100,offset=offset)
                if first is None:first=r
                ids.extend(c['card_id'] for c in r['cards'])
                assert not r['prices'] and not r['live_offers']
                if not r.get('coverage',{}).get('has_more'):break
                offset+=100
            results.append(dict(id=f'coordinate-family-{i+1:02d}',question=q,returned_card_ids=ids,first_page=first))
        for q in QUESTIONS[:9]:
            r=collector_journey.replay(db,dict(turns=[dict(type='ask',question=q)]),revision=revision)
            assert not r['selection_allowed'] and not r['target_intent'] and 'coordinate_family_copy_evidence' in r['selection_blockers'],q
            families.append(dict(question=q,result=r))
        for q in QUESTIONS[12:16]:
            r=collector_journey.replay(db,dict(turns=[dict(type='ask',question=q)]),revision=revision)
            assert not r['selection_allowed'] and 'numbered_part_copy_evidence' in r['selection_blockers']
            parts.append(dict(question=q,result=r))
        for cid in ['ja:SV8A:001/187:normal','ja:SV-P:021/SV-P:normal','ja:SV-P:153/SV-P:normal','ja:SV-P:037/SV-P:normal','ja:M-P:046/M-P:normal']:
            r=discovery_graph.card_neighborhood(db,cid);assert not r['relationships'];graphs.append(r)
    assert before==hashlib.sha256(path.read_bytes()).hexdigest()
    report=dict(schema='pokemon.coordinate-family-development-rehearsal.v1',constructed_questions=True,
        independent_accuracy_measurement=False,cases=len(results),failed=0,catalog_revision=revision,
        results=results,coordinate_family_journey_checks=families,numbered_part_journey_checks=parts,graph_checks=graphs)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return dict(cases=len(results),family_copy_blockers=len(families),numbered_part_checks=len(parts),graph_checks=len(graphs))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.db,a.output)))
