"""Extract observed text from existing separate inspections, without re-review.

Artwork/identity holds do not erase a legible reading. This compiler checks the
original pinned source bytes, local image bytes, snapshots and complete review
memberships. It imports number observations only, never artwork decisions.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
from pokemon_index import core, number_evidence
from scripts.freeze_relationship_identity_review import source_bytes, digest
from scripts.compile_relationship_identity_reviews import keyed


def compile_readings(db, cohort, first, second, assets, archive):
    if set(cohort) != set(first) or set(first) != set(second):
        raise ValueError('complete number review membership required')
    if len(assets) != 2 * len(cohort):
        raise ValueError('complete source assets required')
    asset_map = {(a['candidate_id'], a['side']): a for a in assets}
    if len(asset_map) != len(assets):
        raise ValueError('duplicate number source asset')
    grouped = {}
    for cid, frozen in sorted(cohort.items()):
        if digest({k: v for k, v in frozen.items() if k != 'cohort_snapshot_sha256'}) != frozen['cohort_snapshot_sha256']:
            raise ValueError('frozen number cohort hash differs')
        for endpoint in frozen['endpoints']:
            card_id = endpoint['card_id']; side = endpoint['language']
            snap = {k: endpoint[k] for k in number_evidence.FIELDS}
            if number_evidence.snapshot(db, card_id) != snap:
                raise ValueError('number source endpoint drifted')
            if source_bytes(endpoint['provenance'], archive) != endpoint['source_audit']:
                raise ValueError('number source audit differs')
            asset = asset_map[(cid, side)]
            image_bytes = Path(asset['path']).read_bytes()
            if (asset['status'] != 'source_hash_verified' or asset['source_ref'] != endpoint['image_ref']
                    or asset['image_sha256'] != endpoint['image_sha256']
                    or hashlib.sha256(image_bytes).hexdigest() != endpoint['image_sha256']):
                raise ValueError('number source image substituted or unavailable')
            reviews = []
            for review in (first[cid], second[cid]):
                if review['status'] != 'reviewed' or review['cohort_snapshot_sha256'] != frozen['cohort_snapshot_sha256']:
                    raise ValueError('incomplete or stale number review')
                if any(review.get(k) is not False for k in ('physical_printing_verified', 'price_comparable', 'automatic_offer_join_allowed', 'display_allowed')):
                    raise ValueError('number review permission overclaim')
                if {r['side'] for r in review['coordinate_readings']} != {'ja', 'en'} or len(review['coordinate_readings']) != 2:
                    raise ValueError('number review readings incomplete')
                if {r['side'] for r in review['image_evidence']} != {'ja', 'en'} or len(review['image_evidence']) != 2:
                    raise ValueError('number review image bindings incomplete')
                image = next(r for r in review['image_evidence'] if r['side'] == side)
                if image['source_ref'] != endpoint['image_ref'] or image['image_sha256'] != endpoint['image_sha256']:
                    raise ValueError('number review image differs')
                reading = next(r for r in review['coordinate_readings'] if r['side'] == side)
                reviews.append(dict(actor=review['reviewer'], model_family=review['model_family'],
                    model_version=review['model_version'], reviewed_at=review['reviewed_at'],
                    review_record_sha256=digest(review), source_ref=image['source_ref'], image_sha256=image['image_sha256'],
                    observed_number_text=reading['collector_number'], observed_name=reading['name'],
                    prior_verdicts_visible=review['first_review_verdicts_visible']))
            base = dict(endpoint_snapshot=snap, identity_sha256=digest(snap), source_ref=endpoint['image_ref'],
                        image_sha256=endpoint['image_sha256'])
            if card_id in grouped and any(grouped[card_id][k] != v for k, v in base.items()):
                raise ValueError('one catalog endpoint has conflicting source snapshots')
            row = grouped.setdefault(card_id, dict(base, review_groups=[]))
            row['review_groups'].append(dict(candidate_id=cid, cohort_snapshot_sha256=frozen['cohort_snapshot_sha256'], reviews=reviews))
    rows = []
    for card_id, values in sorted(grouped.items()):
        reviews = [r for g in values['review_groups'] for r in g['reviews']]
        row = dict(schema=number_evidence.SCHEMA, card_id=card_id, revision=1, **values,
                   status=number_evidence.classify(values['endpoint_snapshot']['collector_number'],
                       [r['observed_number_text'] for r in reviews],
                       expected_name=values['endpoint_snapshot']['name'],observed_names=[r['observed_name'] for r in reviews]),
                   recorded_at=max((r['reviewed_at'] for r in reviews), key=core.parse_time),
                   **{k: False for k in number_evidence.FALSE_CLAIMS})
        row['event_id'] = number_evidence.event_id(row); number_evidence.validate(row); rows.append(row)
    return rows


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('db', 'archive', 'cohort', 'first', 'second', 'assets', 'output', 'summary'):
        p.add_argument('--'+k, type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.summary.exists():
        raise FileExistsError('use fresh number evidence outputs')
    with sqlite3.connect(f'file:{a.db.resolve()}?mode=ro', uri=True) as db, tarfile.open(a.archive) as archive:
        db.row_factory = sqlite3.Row
        rows = compile_readings(db, keyed(a.cohort), keyed(a.first), keyed(a.second), json.loads(a.assets.read_text()), archive)
    a.output.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in rows))
    summary = dict(schema='pokemon.number-readings-compilation.v1', subjects=len(rows),
        statuses=dict(Counter(r['status'] for r in rows)), source_bytes_and_images_verified=True,
        original_inspections_reused_without_new_model_calls=True, graph_decisions_changed=False,
        review_file_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (a.cohort, a.first, a.second, a.assets)},
        output_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),
        scope='Constructed source-image controls; AI agreement is not measured marketplace precision or physical version approval.')
    a.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n'); print(json.dumps(summary))
