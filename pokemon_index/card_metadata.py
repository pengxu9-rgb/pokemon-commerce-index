"""Official coordinate metadata, separate from physical-printing approvals."""
from __future__ import annotations

import hashlib
import json
import re
from . import core
from .card_rarity import OFFICIAL_ICON_RARITIES

FALSE_CLAIMS = ('physical_finish_verified', 'listing_copy_verified', 'price_comparable',
                'automatic_offer_join_allowed', 'display_allowed')


def event_id(row):
    body = {k: v for k, v in row.items() if k != 'evidence_id'}
    return 'official-metadata:' + hashlib.sha256(json.dumps(body, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='active_card_metadata_evidence'").fetchone())


def import_evidence(db, rows):
    from .supported_catalog import identity_snapshot
    count = 0
    with db:
        for row in rows:
            if row.get('schema') != 'pokemon.official-card-metadata.v1' or row.get('status') != 'source_supported':
                raise ValueError('unsupported official metadata record')
            if any(row.get(k) is not False for k in FALSE_CLAIMS):
                raise ValueError('coordinate metadata cannot authorize physical or commerce claims')
            if type(row.get('revision')) is not int or row['revision'] < 1 or row.get('evidence_id') != event_id(row):
                raise ValueError('metadata revision or digest is invalid')
            card = db.execute('SELECT * FROM card WHERE card_id=?', (row.get('card_id'),)).fetchone()
            if not card or card['language'] != 'ja' or identity_snapshot(card) != row.get('identity'):
                raise ValueError('metadata identity is stale')
            refs = db.execute('SELECT * FROM card_reference WHERE set_code=? AND collector_number=?',
                              (card['set_code'], card['collector_number'])).fetchall()
            if len(refs) != 1 or row.get('reference') != {k: refs[0][k] for k in ('source','native_id','name','provenance')}:
                raise ValueError('metadata needs one exact source reference')
            official = row.get('official', {})
            if (official.get('url') != 'https://www.pokemon-card.com/card-search/details.php/card/' + refs[0]['native_id']
                or not re.fullmatch('[0-9a-f]{64}', official.get('page_sha256', ''))
                or core._compact_identity_text(official.get('name', '')) != core._compact_identity_text(card['name'])
                or core._compact_identity_text(refs[0]['name']) != core._compact_identity_text(card['name'])):
                raise ValueError('official page does not bind the target identity')
            core.parse_time(official.get('fetched_at', ''))
            entries = official.get('numbered_entries')
            if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
                raise ValueError('official numbered entries missing')
            coordinates = [(e.get('set_code'), e.get('collector_number')) for e in entries]
            if len(set(coordinates)) != len(entries) or coordinates.count((card['set_code'],card['collector_number'])) != 1:
                raise ValueError('official numbered entries are ambiguous')
            for entry in entries:
                icons = entry.get('rarity_icons')
                if not isinstance(icons, list) or len(set(icons)) != len(icons) or len(icons) > 1:
                    raise ValueError('official rarity icons ambiguous')
                rarity = OFFICIAL_ICON_RARITIES.get(icons[0]) if icons else None
                expected_status = 'recognized_icon' if rarity else 'unrecognized_icon' if icons else 'no_rarity_icon'
                if entry.get('rarity') != rarity or entry.get('rarity_status') != expected_status:
                    raise ValueError('metadata invents a rarity')
                if entry.get('part_role') not in {None,'上','下','左','右'}:
                    raise ValueError('unknown numbered part role')
            selected = next(e for e in entries if (e['set_code'],e['collector_number']) == (card['set_code'],card['collector_number']))
            if any(official.get(k) != v for k,v in selected.items()):
                raise ValueError('selected official number differs from page entries')
            kind = 'single_number' if len(entries) == 1 else 'numbered_parts'
            if official.get('page_kind') != kind:
                raise ValueError('official page scope is invalid')
            artists = official.get('illustrators')
            if not isinstance(artists, list) or len(artists) > 8 or any(not isinstance(x,str) or not x.strip() or len(x)>160 for x in artists):
                raise ValueError('invalid official illustrator credits')
            dex = official.get('dex_id')
            if dex is not None and (type(dex) is not int or not 1 <= dex <= 9999):
                raise ValueError('invalid official character ID')
            previous = db.execute('SELECT * FROM card_metadata_evidence WHERE card_id=? ORDER BY revision DESC LIMIT 1', (card['card_id'],)).fetchone()
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if previous and previous['evidence_id'] == row['evidence_id']:
                if previous['record_json'] != encoded:
                    raise ValueError('metadata digest collision')
            elif row['revision'] != (previous['revision'] + 1 if previous else 1):
                raise ValueError('metadata revisions must be consecutive')
            else:
                db.execute('INSERT INTO card_metadata_evidence VALUES (?,?,?,?)',
                           (row['evidence_id'], row['card_id'], row['revision'], encoded))
            count += 1
    return count


def context(db, cid):
    if not available(db):
        return None
    row = db.execute('SELECT record_json FROM active_card_metadata_evidence WHERE card_id=?', (cid,)).fetchone()
    if not row:
        saved = db.execute('SELECT 1 FROM card_metadata_evidence WHERE card_id=?', (cid,)).fetchone()
        return {'status': 'stale_official_metadata', 'automatic_offer_join_allowed': False} if saved else None
    evidence = json.loads(row[0])
    facet_status={}
    for kind,values in [('illustrator',evidence['official']['illustrators']),
                        ('dex_id',[str(evidence['official']['dex_id'])] if evidence['official']['dex_id'] else [])]:
        source={r[0] for r in db.execute('SELECT value FROM card_facet WHERE card_id=? AND facet_type=?',(cid,kind))}
        facet_status[kind]=('page_level_only' if evidence['official']['page_kind']=='numbered_parts'
            else 'not_declared' if not values else 'source_conflict' if source-set(values) else 'source_supported')
    from . import source_corrections
    correction=source_corrections.context(db,cid)
    printed=[f for f in correction['findings'] if f['kind']=='printed_artist' and f['status']=='source_corrected'] if correction else []
    if printed:facet_status['illustrator']='printed_source_corrected_html_or_seed_conflict_preserved'
    return dict(status='official_coordinate_metadata_supported', evidence_id=evidence['evidence_id'],
                facet_status=facet_status,
                printed_source_corrections=printed,
                official=evidence['official'], claims_scope='official page coordinates; physical printing/copy unverified',
                **{k:False for k in FALSE_CLAIMS})


def effective_rarity(db, cid, fallback):
    evidence = context(db, cid)
    return evidence['official']['rarity'] if evidence and evidence['status']=='official_coordinate_metadata_supported' and evidence['official']['rarity'] else fallback


def status(db):
    if not available(db):
        return dict(official_metadata_events=0, current_official_metadata_cards=0,
                    official_metadata_stale_cards=0, official_known_rarity_cards=0, official_numbered_parts_cards=0)
    total = db.execute('SELECT COUNT(*),COUNT(DISTINCT card_id) FROM card_metadata_evidence').fetchone()
    current = db.execute("""SELECT COUNT(*), SUM(json_extract(record_json,'$.official.rarity') IS NOT NULL),
        SUM(json_extract(record_json,'$.official.page_kind')='numbered_parts') FROM active_card_metadata_evidence""").fetchone()
    return dict(official_metadata_events=total[0], current_official_metadata_cards=current[0],
        official_metadata_stale_cards=total[1]-current[0], official_known_rarity_cards=current[1] or 0,
        official_numbered_parts_cards=current[2] or 0)
