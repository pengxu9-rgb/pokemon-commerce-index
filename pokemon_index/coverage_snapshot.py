"""Read hash-bound offline image decisions without importing a separate runtime.

An export is supplied evidence, not proof of reader correctness, rights, image
delivery or physical authenticity. The operator must obtain it from the reviewed
catalog reader and pin its digest independently. This module never fetches data.
"""
import hashlib
import json
from pathlib import Path
import re

IDENTITY_FIELDS = ('language', 'set_code', 'collector_number', 'variant', 'name')
SCHEMA = 'pokemon.catalog-primary-decisions.v1'
MAX_BYTES = 128 * 1024 * 1024


def strict_json(body):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite JSON value')
    return json.loads(body, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def is_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def load_snapshot(path, expected_sha256, database_sha256):
    path = Path(path)
    with path.open('rb') as stream:
        body = stream.read(MAX_BYTES + 1)
    if not is_sha(expected_sha256) or len(body) > MAX_BYTES or hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError('primary-decision snapshot checksum or size mismatch')
    data = strict_json(body)
    if (data.get('schema') != SCHEMA or data.get('database_sha256') != database_sha256
            or not isinstance(data.get('producer'), dict)
            or not isinstance(data['producer'].get('name'), str) or not data['producer']['name']
            or not is_sha(data['producer'].get('reader_code_sha256'))
            or type(data.get('catalog_records')) is not int or not 0 <= data['catalog_records'] <= 100000
            or not isinstance(data.get('rows'), list) or len(data['rows']) != data['catalog_records']):
        raise ValueError('invalid or mismatched primary-decision snapshot')
    rows = {}
    for row in data['rows']:
        if (not isinstance(row, dict) or set(row) != {'card_id', 'identity', 'catalog_provenance_sha256', 'primary_image', 'source_scan'}
                or not isinstance(row['card_id'], str) or not row['card_id'] or row['card_id'] in rows
                or not isinstance(row['identity'], dict) or set(row['identity']) != set(IDENTITY_FIELDS)
                or any(not isinstance(row['identity'][key], str) or not row['identity'][key] for key in IDENTITY_FIELDS)
                or not is_sha(row['catalog_provenance_sha256'])):
            raise ValueError('invalid or duplicate primary-decision subject')
        image, scan = row['primary_image'], row['source_scan']
        if (not isinstance(image, dict) or set(image) - {'status', 'basis', 'event_id', 'image_sha256', 'current_endpoint', 'source_ref', 'reason'}
                or image.get('status') not in {'missing', 'current', 'held', 'stale'}
                or image.get('basis') not in {None, 'catalog_source_reference', 'source_image_facts', 'number_reading'}
                or type(image.get('current_endpoint')) is not bool
                or image.get('image_sha256') is not None and not is_sha(image['image_sha256'])
                or image['status'] == 'current' and (not image['current_endpoint'] or not is_sha(image.get('image_sha256'))
                    or image.get('basis') is None or not isinstance(image.get('event_id'), str)
                    or not re.fullmatch(r'(?:catalog-source-image|source-image-fact|number-reading):[a-f0-9]{64}', image['event_id']))
                or not isinstance(scan, dict) or set(scan) - {'status', 'evidence_basis', 'source_scan_event_id', 'image_sha256', 'current_endpoint', 'inspection_tier'}
                or scan.get('status') not in {'missing_source_scan_evidence', 'current_source_scan_evidence', 'held_source_scan_evidence', 'stale_source_scan_evidence', 'identity_hold'}
                or type(scan.get('current_endpoint')) is not bool
                or scan.get('status') == 'current_source_scan_evidence' and (scan['current_endpoint'] is not True
                    or not is_sha(scan.get('image_sha256')) or scan.get('evidence_basis') not in {'source_image_facts', 'number_reading'}
                    or not isinstance(scan.get('source_scan_event_id'), str)
                    or not re.fullmatch(r'(?:source-image-fact|number-reading):[a-f0-9]{64}', scan['source_scan_event_id']))):
            raise ValueError('invalid primary or source-scan decision')
        rows[row['card_id']] = row
    return data, rows


def match_card(row, card):
    if (row['card_id'] != card['card_id'] or row['identity'] != {key: card[key] for key in IDENTITY_FIELDS}
            or row['catalog_provenance_sha256'] != hashlib.sha256(card['provenance'].encode()).hexdigest()):
        raise ValueError('snapshot card identity or provenance differs from database')


def validate_catalog(db, data, rows):
    cards = list(db.execute('SELECT card_id,language,set_code,collector_number,variant,name,provenance FROM card ORDER BY card_id'))
    if len(cards) != data['catalog_records'] or {row['card_id'] for row in cards} != set(rows):
        raise ValueError('snapshot population differs from database')
    for card in cards:
        match_card(rows[card['card_id']], card)
