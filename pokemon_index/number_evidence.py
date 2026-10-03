"""Exact source-image number readings, independent of catalog coordinates.

Agreement concerns visible stock-image text only. It neither changes identity
nor assigns a stock image to a physical variant, seller copy or price unit.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse
from . import core, supported_catalog

SCHEMA = 'pokemon.number-reading-evidence.v1'
FIELDS = ('card_id', 'language', 'set_code', 'collector_number', 'variant', 'name',
          'rarity', 'provenance', 'match_eligible', 'display_allowed', 'rights_reference')
FALSE_CLAIMS = ('catalog_identity_confirmed', 'physical_printing_verified',
                'price_comparable', 'automatic_offer_join_allowed', 'display_allowed')


def snapshot(db, card_id):
    row = db.execute('SELECT '+','.join(FIELDS)+' FROM card WHERE card_id=?', (card_id,)).fetchone()
    if row is None:
        raise ValueError('unknown number-reading subject')
    return dict(row)


def event_id(row):
    return 'number-reading:'+supported_catalog.digest({k: v for k, v in row.items() if k != 'event_id'})


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid number evidence SHA')


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('invalid number reading text')


def _source(value):
    _text(value)
    url = urlparse(value)
    paths = {
        'assets.tcgdex.net': r'/(?:ja|en)/[A-Za-z0-9./_-]+/high\.webp',
        'www.pokemon-card.com': r'/card-search/details\.php/card/[0-9]+',
        'images.pokemontcg.io': r'/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+_hires\.png',
    }
    if (url.scheme != 'https' or url.netloc not in paths or url.query or url.fragment
            or '..' in url.path.split('/') or not re.fullmatch(paths[url.netloc], url.path)):
        raise ValueError('unsupported number reading source')


def reading_key(text):
    # Formatting comparison only. Never synthesize a denominator or prefix.
    from .number_graph import parse_number
    if text is None:
        return None
    _text(text)
    # Reviewers sometimes include the adjacent printed rarity token. Only
    # separate a known token from an otherwise complete numeric fraction;
    # retain the original reading in the event and never infer missing parts.
    match = re.fullmatch(r'(\d{1,6}\s*/\s*\d{1,6})\s+(?:C|U|R|RR|RRR|PR|AR|SR|SAR|UR|SSR|CHR|CSR|ACE)', text.strip())
    parsed = parse_number(match[1] if match else text)
    if parsed['number_format'] == 'other':
        return None
    return parsed['full_number_key']


def classify(catalog_number, readings, *, expected_name=None, observed_names=None):
    from .number_graph import parse_number
    if expected_name is not None and (not observed_names or any(
            name is None or core._compact_identity_text(name) != core._compact_identity_text(expected_name)
            for name in observed_names)):
        return 'reading_hold'
    keys = {reading_key(text) for text in readings}
    if len(keys) != 1 or None in keys:
        return 'reading_hold'
    key = next(iter(keys))
    catalog = parse_number(catalog_number)
    if key == catalog['full_number_key']:
        return 'catalog_text_observed'
    if '/' not in key and key == catalog['numerator_key']:
        return 'catalog_denominator_not_observed'
    return 'different_text_observed'


def validate(row):
    allowed = {'schema', 'event_id', 'revision', 'card_id', 'endpoint_snapshot',
               'identity_sha256', 'source_ref', 'image_sha256', 'review_groups',
               'status', 'recorded_at'} | set(FALSE_CLAIMS)
    if not isinstance(row, dict) or set(row) != allowed or row['schema'] != SCHEMA:
        raise ValueError('invalid number evidence schema')
    if type(row['revision']) is not int or row['revision'] < 1 or row['event_id'] != event_id(row):
        raise ValueError('invalid number evidence event or revision')
    if any(row[k] is not False for k in FALSE_CLAIMS):
        raise ValueError('number reading cannot approve identity, copy or commerce')
    endpoint = row['endpoint_snapshot']
    if not isinstance(endpoint, dict) or set(endpoint) != set(FIELDS) or endpoint['card_id'] != row['card_id']:
        raise ValueError('number evidence endpoint mismatch')
    _sha(row['identity_sha256']); _sha(row['image_sha256']); _source(row['source_ref'])
    if supported_catalog.digest(endpoint) != row['identity_sha256']:
        raise ValueError('number evidence snapshot hash differs')
    core.parse_time(row['recorded_at'])
    groups = row['review_groups']
    if not isinstance(groups, list) or not groups:
        raise ValueError('number evidence needs bound review groups')
    seen = set(); readings = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {'candidate_id', 'cohort_snapshot_sha256', 'reviews'}:
            raise ValueError('invalid number review group')
        _text(group['candidate_id']); _sha(group['cohort_snapshot_sha256'])
        if group['candidate_id'] in seen:
            raise ValueError('duplicate number review group')
        seen.add(group['candidate_id'])
        if not isinstance(group['reviews'], list) or len(group['reviews']) != 2:
            raise ValueError('two number inspections required')
        actors = set(); families = set()
        for review in group['reviews']:
            if not isinstance(review, dict) or set(review) != {'actor', 'model_family', 'model_version',
                    'reviewed_at', 'review_record_sha256', 'source_ref', 'image_sha256',
                    'observed_number_text', 'observed_name', 'prior_verdicts_visible'}:
                raise ValueError('invalid number reviewer fields')
            for k in ('actor', 'model_family'):
                _text(review[k])
            for k in ('observed_number_text', 'observed_name'):
                if review[k] is not None:
                    _text(review[k])
            _sha(review['review_record_sha256']); core.parse_time(review['reviewed_at'])
            if review['source_ref'] != row['source_ref'] or review['image_sha256'] != row['image_sha256']:
                raise ValueError('number reviewer image differs')
            if review['prior_verdicts_visible'] is not False:
                raise ValueError('number inspections must retain separate verdict provenance')
            if core.parse_time(review['reviewed_at']) > core.parse_time(row['recorded_at']):
                raise ValueError('number evidence predates its review')
            actors.add(review['actor'].casefold()); families.add(review['model_family'].casefold())
            readings.append(review['observed_number_text'])
        if len(actors) != 2 or len(families) != 2:
            raise ValueError('distinct number reviewers and model families required')
    names = [r['observed_name'] for g in groups for r in g['reviews']]
    if row['status'] != classify(endpoint['collector_number'], readings,
                               expected_name=endpoint['name'], observed_names=names):
        raise ValueError('number outcome differs from actual readings')


def import_evidence(db, rows):
    prepared = []
    for row in rows:
        validate(row)
        if snapshot(db, row['card_id']) != row['endpoint_snapshot']:
            raise ValueError('number evidence endpoint is stale')
        prepared.append(row)
    with db:
        for row in prepared:
            existing = db.execute('SELECT record_json FROM card_number_reading_evidence WHERE event_id=?',
                                  (row['event_id'],)).fetchone()
            body = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if existing:
                if existing[0] != body:
                    raise ValueError('number event identity changed')
                continue
            latest = db.execute('SELECT max(revision) FROM card_number_reading_evidence WHERE card_id=?',
                                (row['card_id'],)).fetchone()[0] or 0
            if row['revision'] != latest + 1:
                raise ValueError('number revisions must be consecutive')
            db.execute('INSERT INTO card_number_reading_evidence VALUES (?,?,?,?)',
                       (row['event_id'], row['card_id'], row['revision'], body))
    return len(prepared)


def context(db, card_id):
    latest = db.execute('SELECT record_json FROM card_number_reading_evidence WHERE card_id=? '
                        'ORDER BY revision DESC LIMIT 1', (card_id,)).fetchone()
    if latest is None:
        return None
    row = json.loads(latest[0]); validate(row)
    try:
        current = snapshot(db, card_id) == row['endpoint_snapshot']
    except ValueError:
        current = False
    readings = sorted({r['observed_number_text'] for g in row['review_groups'] for r in g['reviews']
                       if r['observed_number_text'] is not None})
    usable = current and row['status'] != 'reading_hold'
    return dict(schema='pokemon.number-reading-context.v1', event_id=row['event_id'],
                current_endpoint=current, status=row['status'] if current else 'stale_endpoint',
                catalog_number=row['endpoint_snapshot']['collector_number'],
                observed_number_texts=readings if usable else [],
                review_groups=row['review_groups'], source_ref=row['source_ref'], image_sha256=row['image_sha256'],
                visible_text_agreement=usable, printed_denominator_observed=usable and '/' in readings[0],
                scope='Exact source stock-image text only; no assignment to sibling labels or seller copies.',
                independent_accuracy_established=False, **{k: False for k in FALSE_CLAIMS})


def status(db):
    heads = db.execute('SELECT card_id FROM card_number_reading_evidence GROUP BY card_id').fetchall()
    contexts = [context(db, row[0]) for row in heads]
    return dict(number_reading_events=db.execute('SELECT count(*) FROM card_number_reading_evidence').fetchone()[0],
                number_reading_subjects=len(heads),
                current_agreed_number_readings=sum(c['visible_text_agreement'] for c in contexts),
                number_reading_holds=sum(c['status'] == 'reading_hold' for c in contexts),
                stale_number_readings=sum(not c['current_endpoint'] for c in contexts),
                catalog_denominator_not_observed=sum(c['status'] == 'catalog_denominator_not_observed' for c in contexts))
