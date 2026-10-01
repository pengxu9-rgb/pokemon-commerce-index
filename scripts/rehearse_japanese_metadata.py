"""Exercise source metadata, graph retrieval and split-card guards read-only."""
from __future__ import annotations
import argparse
import hashlib
import json
from contextlib import closing
from pathlib import Path
from pokemon_index import core,card_metadata,collector_discovery,collector_journey,discovery_graph

QUESTIONS=['Japanese M6A 136/103','Japanese M6 110/076','Japanese M-P 135/M-P',
 'Japanese SV11W 094/086','Japanese SV11B 174/086','Japanese SV10 112/098',
 'Japanese SV9A 080/063','Japanese SV9 114/100','Japanese SV8A 224/187',
 'Japanese M6A 151/103','Japanese M6 071/076','Japanese M6 073/076','Japanese M6 075/076',
 'Japanese M-P 131/M-P','Japanese M-P 046/M-P','Japanese SV4A 347/190 holo',
 'Japanese Yuka Morii cards','Japanese Pikachu cards',
 'English counterpart of Japanese M-P 135/M-P','Cheapest Japanese Pikachu card']


def run(path, baseline, output, queue=None, metadata_count=1000):
    if output.exists():raise FileExistsError(output)
    before=hashlib.sha256(path.read_bytes()).hexdigest();results=[];journeys=[];graphs=[]
    questions=QUESTIONS
    queued=[]
    if queue is not None:
        queued=[json.loads(l) for l in queue.read_text().splitlines()]
        by_set={}
        for row in queued:by_set.setdefault(row['set_code'],[]).append(row)
        # Constructed source-coordinate regression cases, not a blind sample.
        questions=['Japanese '+s+' '+max(rows,key=lambda r:int(r['collector_number'].split('/')[0]))['collector_number']
                   for s,rows in by_set.items()]
        questions+=QUESTIONS[9:13]+['Japanese Yuka Morii cards',
            'English counterpart of Japanese SV8 132/106','Cheapest Japanese Pikachu card']
    with closing(core.connect(path,readonly=True)) as db,closing(core.connect(baseline,readonly=True)) as old:
        revision=collector_journey.catalog_revision(db)
        for i,q in enumerate(questions):
            ids=[];offset=0;first=None
            while True:
                r=collector_discovery.execute(db,q,limit=100,offset=offset)
                if first is None:first=r
                ids.extend(c['card_id'] for c in r['cards'])
                assert all(not c['automatic_offer_join_allowed'] and not c['price_comparable'] for c in r['cards'])
                if not r.get('coverage',{}).get('has_more'):break
                offset+=100
            earlier=collector_discovery.execute(old,q,limit=100)
            results.append(dict(id=f'jp-metadata-{i+1:02d}',question=q,returned_card_ids=ids,first_page=first,
                baseline_matched_catalog_records=earlier.get('coverage',{}).get('matched_catalog_records',0)))
        for q in QUESTIONS[9:13]:
            r=collector_journey.replay(db,dict(turns=[dict(type='ask',question=q)]),revision=revision)
            assert not r['selection_allowed'] and not r['target_intent'] and 'numbered_part_copy_evidence' in r['selection_blockers']
            journeys.append(dict(question=q,result=r))
        for cid in ('ja:SV10:112/098:holo','ja:M-P:046/M-P:normal'):
            r=discovery_graph.card_neighborhood(db,cid)
            assert all(n.get('price_comparable') is False for n in r['metadata_neighbors'].values() if n.get('total'))
            assert r['relationships']==[]
            graphs.append(r)
        batch_filter=(' AND e.card_id IN ('+','.join('?' for _ in queued)+')') if queued else ''
        candidates=db.execute("""SELECT e.card_id FROM active_card_metadata_evidence e
          WHERE json_extract(record_json,'$.official.page_kind')='single_number'
          AND json_array_length(record_json,'$.official.illustrators')>0
          AND NOT EXISTS(SELECT 1 FROM card_facet f WHERE f.card_id=e.card_id AND facet_type='illustrator')
          """+batch_filter+" ORDER BY e.card_id LIMIT 5",[r['catalog_records'][0]['card_id'] for r in queued]).fetchall()
        for row in candidates:
            r=discovery_graph.card_neighborhood(db,row['card_id']);assert r['metadata_neighbors']['same_illustrator']['total']>0
            graphs.append(r)
        assert card_metadata.status(db)['current_official_metadata_cards']==metadata_count
        assert db.execute('SELECT COUNT(*) FROM observation').fetchone()[0]==0
        summary=core.catalog_status(db);summary.pop('set_coverage')
    assert before==hashlib.sha256(path.read_bytes()).hexdigest()
    report=dict(schema='pokemon.japanese-metadata-development-rehearsal.v1',constructed_questions=True,
        independent_accuracy_measurement=False,cases=len(results),failed=0,catalog_sha256=before,
        catalog_revision=revision,results=results,numbered_part_journey_checks=journeys,
        graph_checks=graphs,catalog_summary=summary)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return dict(cases=len(results),numbered_part_checks=len(journeys),graph_checks=len(graphs),catalog_summary=summary)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--queue',type=Path)
    p.add_argument('--metadata-count',type=int,default=1000)
    a=p.parse_args();print(json.dumps(run(a.db,a.baseline,a.output,a.queue,a.metadata_count),ensure_ascii=False))
