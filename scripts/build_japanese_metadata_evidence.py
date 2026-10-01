"""Freeze official metadata support bound to an unchanged catalog baseline."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from pokemon_index import core, card_metadata, supported_catalog


def build(queue, audit, baseline, output):
    if output.exists():
        raise FileExistsError(output)
    queued = [json.loads(l) for l in queue.read_text().splitlines()]
    reviewed = [json.loads(l) for l in audit.read_text().splitlines()]
    if len(queued) != len(reviewed) or any(r['queue'] != q for q,r in zip(queued,reviewed)):
        raise ValueError('official audit does not bind the frozen queue')
    rows, holds, disagreements = [], [], []
    queue_sha, audit_sha = (hashlib.sha256(p.read_bytes()).hexdigest() for p in (queue,audit))
    db = core.connect(baseline, readonly=True)
    try:
        for review in reviewed:
            if review['decision'] != 'exact_metadata_agreement':
                holds.append(dict(set_code=review['queue']['set_code'],
                    collector_number=review['queue']['collector_number'],
                    decision=review['decision'],official_url=review['queue']['candidate_official_url'],
                    error_type=review.get('error_type')))
                continue
            q, official = review['queue'], review['official']
            for seed in q['catalog_records']:
                card = db.execute('SELECT * FROM card WHERE card_id=?', (seed['card_id'],)).fetchone()
                if not card or any(card[k]!=seed[k] for k in ('card_id','variant','name','rarity','provenance')):
                    raise ValueError('queue catalog identity changed')
                row = dict(schema='pokemon.official-card-metadata.v1', revision=1,
                    status='source_supported', card_id=card['card_id'],
                    identity=supported_catalog.identity_snapshot(card),
                    reference={k:q['reference'][k] for k in ('source','native_id','name','provenance')},
                    official=official, queue_sha256=queue_sha, audit_sha256=audit_sha,
                    **{k:False for k in card_metadata.FALSE_CLAIMS})
                row['evidence_id']=card_metadata.event_id(row)
                rows.append(row)
                for kind, declared in [('illustrator',official['illustrators']),('dex_id',[str(official['dex_id'])] if official['dex_id'] else [])]:
                    old = sorted({r[0] for r in db.execute('SELECT value FROM card_facet WHERE card_id=? AND facet_type=?',(card['card_id'],kind))})
                    if old and declared and old != sorted(set(declared)):
                        disagreements.append(dict(card_id=card['card_id'],facet_type=kind,source_values=old,
                            official_page_values=declared,page_kind=official['page_kind'],official_url=official['url']))
    finally:
        db.close()
    output.write_text(''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows))
    report = dict(queue_sha256=queue_sha,audit_sha256=audit_sha,evidence_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        reviewed_number_groups=len(queued), official_metadata_records=len(rows),
        recognized_rarity=sum(bool(r['official']['rarity']) for r in rows),
        no_rarity_icon=sum(r['official']['rarity_status']=='no_rarity_icon' for r in rows),
        unrecognized_rarity=sum(r['official']['rarity_status']=='unrecognized_icon' for r in rows),
        numbered_parts=sum(r['official']['page_kind']=='numbered_parts' for r in rows),
        set_distribution=dict(Counter(r['identity']['set_code'] for r in rows)),
        held_number_groups=holds, facet_disagreements=disagreements,
        scope='official coordinate metadata; version/physical copy and cross-region price equivalence unverified')
    output.with_suffix('.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('queue','audit','baseline','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.queue,args.audit,args.baseline,args.output),ensure_ascii=False,indent=2))
