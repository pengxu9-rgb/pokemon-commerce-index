"""Acquire every frozen target; unavailable images remain explicit outcomes."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, tarfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pokemon_index import number_evidence
from scripts.freeze_promo_number_reviews import fetch
from scripts.freeze_relationship_identity_review import digest, source_bytes

def acquire(db, archive, queue, output, cache, expected_targets=100):
    if output.exists(): raise FileExistsError('use a fresh asset outcome file')
    rows=[json.loads(line) for line in queue.read_text().splitlines()]
    if expected_targets<1 or len(rows)!=expected_targets or len({r['target_id'] for r in rows})!=expected_targets or len({r['endpoint_snapshot']['card_id'] for r in rows})!=expected_targets:
        raise ValueError('complete frozen unique endpoint cohort required')
    for row in rows:
        if digest({k:v for k,v in row.items() if k!='snapshot_sha256'})!=row['snapshot_sha256']:
            raise ValueError('frozen target changed')
        endpoint=row['endpoint_snapshot']
        if number_evidence.snapshot(db, endpoint['card_id'])!=endpoint or digest(endpoint)!=row['identity_sha256']:
            raise ValueError('frozen endpoint drift')
        if source_bytes(endpoint['provenance'],archive)!=row['source_audit']:
            raise ValueError('pinned source bytes changed')
    cache.mkdir(parents=True,exist_ok=True)
    def one(row):
        try: result=fetch(row,cache)
        except Exception as error:
            result=dict(target_id=row['target_id'],status='asset_hold',error_type=type(error).__name__,attempts=[])
        return result|dict(target_snapshot_sha256=row['snapshot_sha256'],queue_sha256=hashlib.sha256(queue.read_bytes()).hexdigest())
    with ThreadPoolExecutor(max_workers=4) as pool: outcomes=list(pool.map(one,rows))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(outcomes,ensure_ascii=False,indent=2)+'\n')
    return dict(targets=len(rows),statuses=dict(Counter(o['status'] for o in outcomes)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['db','archive','queue','output','cache']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--expected-targets',type=int,default=100)
    a=p.parse_args()
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True) as db,tarfile.open(a.archive) as archive:
        db.row_factory=sqlite3.Row
        print(json.dumps(acquire(db,archive,a.queue,a.output,a.cache,a.expected_targets)))
