"""Freeze match-disabled artwork proposals and three distinct artwork controls.

Checks pinned source bytes and current endpoint identities, never upgrades an
artwork or printing relationship. The read-only artifact binds current pair
heads so review compilers can reject drift before importing any new decision.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tarfile

from pokemon_index import discovery_graph

CONTROLS = ('89fd46d34e24f96d0be7', 'c3472df9b3b2688079dc', '05ff3153fd9b732453e3')
FIELDS = ('card_id','language','set_code','collector_number','variant','name','rarity',
          'provenance','match_eligible','display_allowed','rights_reference')
SOURCE = re.compile(r'tcgdex:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def source_bytes(provenance, archive):
    match = SOURCE.fullmatch(provenance)
    if not match:
        raise ValueError('endpoint lacks pinned source')
    revision, path, expected = match.groups()
    if path.startswith('/') or '..' in Path(path).parts:
        raise ValueError('unsafe source path')
    member = archive.getmember('cards-database-' + revision + '/' + path)
    if not member.isfile():
        raise ValueError('source is not a regular file')
    body = archive.extractfile(member).read()
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError('pinned endpoint source hash differs')
    return {'revision': revision, 'path': path, 'sha256': expected,
            'bytes': len(body), 'status': 'source_bytes_verified'}


def freeze(db, archive):
    selected = []
    counts = Counter()
    for row in db.execute('''SELECT a.* FROM card_relationship_assertion a
        WHERE a.review_status='proposed' AND a.relation_type='same_artwork'
        AND NOT EXISTS(SELECT 1 FROM card_relationship_assertion newer
           WHERE newer.left_card_id=a.left_card_id AND newer.right_card_id=a.right_card_id
           AND newer.relation_type=a.relation_type AND newer.rowid>a.rowid)
        ORDER BY a.assertion_id'''):
        evidence = json.loads(row['evidence_ref'])
        candidate_id = evidence.get('candidate_id')
        cards = [dict(db.execute('SELECT * FROM card WHERE card_id=?', (cid,)).fetchone())
                 for cid in (row['left_card_id'], row['right_card_id'])]
        disabled = any(not card['match_eligible'] for card in cards)
        if not disabled and candidate_id not in CONTROLS:
            continue
        endpoints = []
        for card in cards:
            frozen = {field: card[field] for field in FIELDS}
            frozen['source_audit'] = source_bytes(card['provenance'], archive)
            frozen['identity_blockers'] = discovery_graph.endpoint_identity_blockers(db, card['card_id'])
            prefix = 'ja' if card['language'] == 'ja' else 'en'
            frozen['image_ref'] = evidence[prefix+'_image_ref']
            frozen['image_sha256'] = evidence[prefix+'_image_sha256']
            frozen['image_scope'] = 'coordinate artwork stock image; physical variant assignment unverified'
            endpoints.append(frozen)
        record = dict(schema='pokemon.relationship-identity-cohort.v1',
                      candidate_id=candidate_id, expected_pair_head=row['assertion_id'],
                      source_evidence_sha256=hashlib.sha256(row['evidence_ref'].encode()).hexdigest(),
                      original_source_snapshot_sha256=evidence['source_snapshot_sha256'],
                      selection_reason='match_disabled_endpoint' if disabled else 'distinct_coordinate_control',
                      status='identity_hold' if disabled else 'awaiting_independent_artwork_reviews',
                      endpoints=endpoints, relation_type='same_artwork',
                      price_comparable=False, physical_printing_verified=False,
                      automatic_offer_join_allowed=False, display_allowed=False)
        record['cohort_snapshot_sha256'] = digest(record)
        selected.append(record)
        counts[record['status']] += 1
    if sum(row['selection_reason']=='distinct_coordinate_control' for row in selected) != len(CONTROLS):
        raise ValueError('expected control artwork pairs are unavailable')
    summary = dict(schema='pokemon.relationship-identity-cohort-summary.v1',
                   pairs=len(selected), statuses=dict(counts),
                   endpoint_records=sum(len(row['endpoints']) for row in selected),
                   unique_source_files=len({card['provenance'] for row in selected for card in row['endpoints']}),
                   source_byte_checks=sum(len(row['endpoints']) for row in selected),
                   verified_relationships_created=0, rejected_relationships_created=0,
                   scope='Identity quarantine and pinned source bytes only; no visual review or accuracy score.')
    return selected, summary


def check_current(db, row):
    """Prevent review of an old frozen identity/pair head after any source drift."""
    body = {key:value for key,value in row.items() if key!='cohort_snapshot_sha256'}
    if digest(body) != row['cohort_snapshot_sha256']:
        raise ValueError('cohort snapshot hash differs')
    for endpoint in row['endpoints']:
        current = db.execute('SELECT * FROM card WHERE card_id=?', (endpoint['card_id'],)).fetchone()
        if current is None or {field:current[field] for field in FIELDS} != {field:endpoint[field] for field in FIELDS}:
            raise ValueError('frozen endpoint identity drifted')
        if discovery_graph.endpoint_identity_blockers(db, endpoint['card_id']) != endpoint['identity_blockers']:
            raise ValueError('frozen endpoint blockers drifted')
    left,right = sorted(endpoint['card_id'] for endpoint in row['endpoints'])
    head = db.execute('''SELECT assertion_id,evidence_ref FROM card_relationship_assertion
        WHERE left_card_id=? AND right_card_id=? AND relation_type=? ORDER BY rowid DESC LIMIT 1''',
        (left,right,row['relation_type'])).fetchone()
    if row.get('pair_scope') == 'new_source_qualified_control':
        if row['expected_pair_head'] is not None or row['source_evidence_sha256'] is not None or head is not None:
            raise ValueError('frozen new control pair head drifted')
        return
    if (head is None or head['assertion_id'] != row['expected_pair_head'] or
        hashlib.sha256(head['evidence_ref'].encode()).hexdigest()!=row['source_evidence_sha256']):
        raise ValueError('frozen relationship pair head drifted')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--source-archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--summary', type=Path, required=True)
    args=p.parse_args()
    if args.output.exists() or args.summary.exists():raise FileExistsError('outputs must be new')
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro',uri=True) as db, tarfile.open(args.source_archive) as archive:
        db.row_factory=sqlite3.Row
        rows,summary=freeze(db,archive)
        for row in rows:check_current(db,row)
    args.output.write_text(''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows))
    summary['cohort_file_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.summary.write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':main()
