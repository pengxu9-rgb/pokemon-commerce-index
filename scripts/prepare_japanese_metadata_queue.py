"""Select untouched exact Japanese coordinates with one pinned reference.

Selection is engineering coverage, not marketplace demand. Existing official
metadata and the original supported cohort remain separate and are excluded.
"""
import argparse
import hashlib
import json
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from pokemon_index import core


def prepare(baseline,sets,manifest,output):
    if output.exists():raise FileExistsError(output)
    if len(set(sets))!=len(sets):raise ValueError('duplicate requested release')
    baseline_sha=hashlib.sha256(baseline.read_bytes()).hexdigest()
    queued=[];excluded=Counter();held=[]
    with closing(core.connect(baseline,readonly=True)) as db:
        groups=defaultdict(list)
        for card in db.execute("SELECT * FROM card WHERE language='ja' ORDER BY set_code,collector_number,variant"):
            if card['set_code'] in sets:groups[(card['set_code'],card['collector_number'])].append(card)
        for key,cards in sorted(groups.items(),key=lambda x:(sets.index(x[0][0]),x[0][1])):
            if any(db.execute('SELECT 1 FROM card_metadata_evidence WHERE card_id=?',(c['card_id'],)).fetchone() for c in cards):
                excluded['already_official_metadata']+=1;continue
            if any(db.execute('SELECT 1 FROM supported_card WHERE card_id=?',(c['card_id'],)).fetchone() for c in cards):
                excluded['original_supported_cohort']+=1;continue
            refs=db.execute('SELECT * FROM card_reference WHERE set_code=? AND collector_number=?',key).fetchall()
            def hold(reason):
                excluded[reason]+=1
                held.append(dict(set_code=key[0],collector_number=key[1],reason=reason,
                    catalog_records=[{k:c[k] for k in ('card_id','variant','name','rarity','provenance')} for c in cards],
                    references=[{k:r[k] for k in ('source','native_id','name','rarity','provenance')} for r in refs],
                    review_status='evidence_required',automatic_offer_join_allowed=False))
            if len(cards)!=1:
                hold('multiple_source_versions');continue
            if len(refs)!=1:
                hold('missing_or_multiple_references');continue
            c,r=cards[0],refs[0]
            if (not str(r['native_id']).isdigit() or r['source']!='ptcg-database'
                or core._compact_identity_text(c['name'])!=core._compact_identity_text(r['name'])):
                hold('reference_identity_conflict');continue
            queued.append(dict(schema='pokemon.japanese-metadata-review-queue.v1',language='ja',
                set_code=c['set_code'],collector_number=c['collector_number'],name=c['name'],
                catalog_records=[{k:c[k] for k in ('card_id','variant','name','rarity','provenance')}],
                reference={k:r[k] for k in ('source','native_id','name','rarity','provenance')},
                candidate_official_url='https://www.pokemon-card.com/card-search/details.php/card/'+r['native_id'],
                review_status='pending_fetch_and_verification',physical_finish_verified=False,
                automatic_offer_join_allowed=False,
                selection_reason='engineering coverage of remaining single-reference coordinates in explicit release cohort'))
    if not queued:raise ValueError('no untouched exact coordinates')
    if baseline_sha!=hashlib.sha256(baseline.read_bytes()).hexdigest():
        raise ValueError('baseline changed during read-only queue preparation')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in queued))
    output.with_suffix('.holds.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in held))
    report=dict(schema='pokemon.japanese-metadata-review-queue-audit.v1',requested_sets=sets,
        queued_set_number_groups=len(queued),queued_catalog_records=len(queued),
        set_distribution=dict(Counter(r['set_code'] for r in queued)),exclusions=dict(excluded),
        queue_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),baseline_manifest=str(manifest),
        baseline_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        baseline_snapshot_sha256=baseline_sha,
        selection_uses_market_volume=False,official_pages_fetched=0,approved_records=0,
        scope='review queue only; no physical equivalence or commerce approval')
    output.with_suffix('.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','manifest','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--sets',nargs='+',required=True)
    a=p.parse_args();print(json.dumps(prepare(a.baseline,a.sets,a.manifest,a.output),ensure_ascii=False,indent=2))
