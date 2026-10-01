"""Freeze supported families and explicit holds, retaining every source snapshot."""
import argparse,hashlib,json
from collections import Counter
from contextlib import closing
from pathlib import Path
from pokemon_index import core,coordinate_family


def build(queue,audit,baseline,output):
    if output.exists():raise FileExistsError(output)
    queued=[json.loads(l) for l in queue.read_text().splitlines()]
    reviewed=[json.loads(l) for l in audit.read_text().splitlines()]
    if len(queued)!=len(reviewed) or any(q!=r['group'] for q,r in zip(queued,reviewed)):raise ValueError('family audit differs from queue')
    result=[]
    with closing(core.connect(baseline,readonly=True)) as db:
        for q,review in zip(queued,reviewed):
            snapshot=coordinate_family.snapshot(db,'ja',q['set_code'],q['collector_number'])
            seed={c['card_id']:c for c in snapshot['cards']}
            if set(seed)!={c['card_id'] for c in q['catalog_records']} or any(any(seed[c['card_id']][k]!=v for k,v in c.items()) for c in q['catalog_records']):raise ValueError('family seed changed')
            refs=[{k:r[k] for k in ('source','native_id','name','provenance')} for r in q['references']]
            if sorted(refs,key=lambda r:(r['source'],r['native_id']))!=snapshot['references']:raise ValueError('family references changed')
            supported=review['decision'] in {'coordinate_family_supported','coordinate_supported_name_qualifier'}
            r=dict(schema='pokemon.coordinate-family-evidence.v1',revision=1,language='ja',set_code=q['set_code'],
                collector_number=q['collector_number'],snapshot=snapshot,pages=review['pages'],
                status='source_supported' if supported else 'evidence_hold',
                name_status=coordinate_family.name_status([c['name'] for c in snapshot['cards']],review['pages']) if supported else 'unresolved',
                hold_reason=None if supported else review.get('error') or review['decision'],
                queue_sha256=hashlib.sha256(queue.read_bytes()).hexdigest(),audit_sha256=hashlib.sha256(audit.read_bytes()).hexdigest(),
                **{k:False for k in coordinate_family.FALSE_CLAIMS})
            r['evidence_id']=coordinate_family.event_id(r);result.append(r)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in result))
    report=dict(events=len(result),states=dict(Counter(r['status'] for r in result)),
        source_records=sum(len(r['snapshot']['cards']) for r in result if r['status']=='source_supported'),
        held_source_records=sum(len(r['snapshot']['cards']) for r in result if r['status']=='evidence_hold'),
        evidence_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),physical_printing_approvals=0)
    output.with_suffix('.summary.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['queue','audit','baseline','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.queue,a.audit,a.baseline,a.output)))
