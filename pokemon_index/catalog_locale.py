"""Offline, append-only source bindings and reviewed name retrieval.

Bindings enrich existing records. An unrepresented or ambiguous physical
printing is quarantined; it must pass a separate identity expansion review.
"""
import hashlib
import json
import re

from . import core
from .languages import normalize_language

FALSE_CLAIMS = ('display_allowed', 'image_display_allowed', 'purchase_allowed',
                'automatic_offer_join_allowed', 'physical_printing_verified', 'price_comparable')
IDENTITY_FIELDS = ('card_id', 'language', 'set_code', 'collector_number', 'variant',
                   'name', 'rarity', 'provenance', 'rights_reference')
SOURCE_FIELDS = ('provider', 'language', 'region', 'release_id', 'native_id', 'source_variant')


def encoded(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(row):
    return hashlib.sha256(encoded(row).encode()).hexdigest()


def snapshot(db, cid):
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError('card_id must be a nonempty string')
    card = db.execute('SELECT * FROM card WHERE card_id=?', (cid,)).fetchone()
    if not card:
        raise ValueError('printing not represented in baseline; identity review required')
    return {k: card[k] for k in IDENTITY_FIELDS}


def approved_alias(db, alias):
    fields = {'concept_id', 'revision', 'name_ja', 'name_en', 'category', 'review_event_id'}
    if not isinstance(alias, dict) or set(alias) != fields or type(alias['revision']) is not int or alias['revision'] < 1 or any(not isinstance(alias[k], str) or not alias[k].strip() for k in ('concept_id', 'name_ja', 'name_en', 'category')) or (alias['review_event_id'] is not None and not isinstance(alias['review_event_id'], str)):
        raise ValueError('invalid reviewed name alias fields')
    row = db.execute('''SELECT * FROM bilingual_concept_revision
        WHERE concept_id=? ORDER BY revision DESC LIMIT 1''', (alias['concept_id'],)).fetchone()
    expected = {k: row[k] for k in ('concept_id', 'revision', 'name_ja', 'name_en',
                                    'category', 'review_event_id')} if row else None
    if not row or row['status'] != 'approved' or alias != expected:
        raise ValueError('reviewed name alias missing, withdrawn or stale')
    return row


def validate(db, row):
    if not isinstance(row, dict) or row.get('schema') != 'pokemon.catalog-locale.v1':
        raise ValueError('unknown localization schema')
    if any(row.get(k) is not False for k in FALSE_CLAIMS):
        raise ValueError('localization cannot grant display, copy, price or commerce permissions')
    body = {k: v for k, v in row.items() if k != 'evidence_id'}
    if row.get('evidence_id') != 'catalog-locale:' + digest(body):
        raise ValueError('localization evidence hash mismatch')
    if not isinstance(row.get('identity'), dict):
        raise ValueError('identity snapshot must be an object')
    actual = snapshot(db, row['identity']['card_id'])
    if row['identity'] != actual:
        raise ValueError('identity snapshot differs')
    if actual['variant'].startswith('unverified') or not db.execute(
            'SELECT match_eligible FROM card WHERE card_id=?', (actual['card_id'],)).fetchone()[0]:
        raise ValueError('unresolved printing family')
    if type(row.get('confidence')) not in (int, float) or not 0 <= row['confidence'] <= 1:
        raise ValueError('invalid metadata confidence')
    if row.get('unresolved_conflicts') != [] or row.get('test_only') is not False:
        raise ValueError('conflicted or test-only metadata cannot enrich real catalog')
    src = row['source']
    if not isinstance(src, dict):
        raise ValueError('source must be an object')
    if any(not isinstance(src.get(k), str) or not src[k].strip() for k in SOURCE_FIELDS):
        raise ValueError('source requires explicit provider, language, region, release and variant')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,60}', src['provider']):
        raise ValueError('invalid provider namespace')
    if normalize_language(src['language']) != actual['language'] or src['source_variant'] != actual['variant']:
        raise ValueError('source language or variant differs from printing')
    if not re.fullmatch(r'[A-Z]{2}', src['region']):
        raise ValueError('explicit region must be an ISO country label')
    if not isinstance(src.get('revision'), str) or not isinstance(src.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{40}', src['revision']) or not re.fullmatch(r'[0-9a-f]{64}', src['sha256']):
        raise ValueError('source revision/hash missing')
    expected_provenance = f"{src['provider']}:{src['revision']}:{src['native_id']}:sha256:{src['sha256']}"
    if expected_provenance != actual['provenance']:
        raise ValueError('source is not bound to baseline provenance')
    if src.get('rights_status') != 'metadata_internal_reviewed' or src.get('rights_reference') != actual['rights_reference']:
        raise ValueError('internal metadata rights not reviewed')
    if not isinstance(src.get('inspected_at'), str):
        raise ValueError('inspection time must be recorded')
    core.parse_time(src['inspected_at'])
    if src.get('retrieved_at') is None:
        if src.get('retrieval_status') != 'historical_snapshot_time_not_recorded':
            raise ValueError('missing retrieval time must remain explicitly unknown')
    else:
        if not isinstance(src['retrieved_at'], str):
            raise ValueError('retrieval time must be a timestamp or explicitly unknown')
        core.parse_time(src['retrieved_at'])
        if src.get('retrieval_status') != 'recorded':
            raise ValueError('retrieval status differs')
    release = db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                         (actual['language'], actual['set_code'])).fetchone()
    if not release or row['release_snapshot'] != dict(release):
        raise ValueError('localized release snapshot differs')
    # Every translation must be an exact current reviewed concept, with category
    # evidence on this printing. Shared names/art are not counterpart assertions.
    aliases = row.get('name_aliases')
    if not isinstance(aliases, list):
        raise ValueError('name aliases must be a list')
    for alias in aliases:
        if not isinstance(alias, dict):
            raise ValueError('name alias must be an object')
        concept = approved_alias(db, alias)
        own_name = concept['name_ja' if actual['language'] == 'ja' else 'name_en'] if actual['language'] in {'en', 'ja'} else None
        category = db.execute('SELECT category FROM card_classification WHERE card_id=?',
                              (actual['card_id'],)).fetchone()
        if actual['name'] != own_name or not category or category[0] != concept['category']:
            raise ValueError('reviewed alias is not scoped to this name/category')
    mapping = tuple(src[k] for k in SOURCE_FIELDS)
    previous = db.execute('''SELECT card_id FROM catalog_source_mapping WHERE
        provider=? AND language=? AND region=? AND release_id=? AND native_id=? AND source_variant=?''', mapping).fetchone()
    if previous and previous[0] != actual['card_id']:
        raise ValueError('provider source collision')
    scopes = db.execute('SELECT language,region,release_id FROM catalog_source_mapping WHERE card_id=?',
                        (actual['card_id'],)).fetchall()
    if any(tuple(r) != (src['language'], src['region'], src['release_id']) for r in scopes):
        raise ValueError('legacy printing reused across distinct regional releases; quarantine')
    return mapping, actual['card_id']


def import_evidence(db, rows):
    counts = {'inserted': 0, 'unchanged': 0, 'quarantined': 0}
    with db:
        for row in rows:
            try:
                mapping, cid = validate(db, row)
                previous = db.execute('SELECT record_json FROM catalog_locale_evidence WHERE evidence_id=?',
                                      (row['evidence_id'],)).fetchone()
                if previous:
                    if previous[0] != encoded(row):
                        raise ValueError('immutable evidence changed')
                    counts['unchanged'] += 1
                    continue
                db.execute('INSERT OR IGNORE INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)', (*mapping, cid))
                db.execute('INSERT INTO catalog_locale_evidence VALUES (?,?,?)', (row['evidence_id'], cid, encoded(row)))
                counts['inserted'] += 1
            except (ValueError, KeyError, TypeError) as exc:
                db.execute('INSERT OR IGNORE INTO catalog_identity_quarantine VALUES (?,?,?)',
                           ('catalog-quarantine:' + digest(row), str(exc), encoded(row)))
                counts['quarantined'] += 1
    return counts


def current(db, row):
    try:
        validate(db, row)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def search_aliases(db, *, set_code=None):
    # Old read-only snapshots predate this additive schema; preserve their API.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_locale_evidence'").fetchone():
        return {}
    aliases = {}
    for record in db.execute('''SELECT e.record_json FROM catalog_locale_evidence e JOIN card c USING(card_id)
            WHERE (? IS NULL OR c.set_code=?)''', (set_code.upper() if set_code else None, set_code.upper() if set_code else None)):
        row = json.loads(record[0])
        if current(db, row):
            aliases.setdefault(row['identity']['card_id'], []).extend(
                a['name_en' if row['identity']['language'] == 'ja' else 'name_ja'] for a in row['name_aliases'])
    return aliases


def has_current_alias(db, cid, aliases):
    """Require a source-bound record for name concepts that opt into this guard."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_locale_evidence'").fetchone():
        return False
    wanted={(a['concept_id'],a['revision']) for a in aliases}
    for record in db.execute('SELECT record_json FROM catalog_locale_evidence WHERE card_id=?',(cid,)):
        row=json.loads(record[0])
        if row['identity']['card_id']==cid and current(db,row) and any(
                (a['concept_id'],a['revision']) in wanted for a in row['name_aliases']):
            return True
    return False


def context(db, cid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_locale_evidence'").fetchone():
        return []
    return [{'evidence_id': r['evidence_id'], 'source': r['source'],
             'current': current(db, r), 'name_aliases': r['name_aliases'],
             'scope': 'internal metadata retrieval; no counterpart, copy or price equivalence',
             **{k: False for k in FALSE_CLAIMS}}
            for record in db.execute('SELECT record_json FROM catalog_locale_evidence WHERE card_id=?', (cid,))
            for r in [json.loads(record[0])]]


def import_manifest_evidence(db, rows):
    result = import_evidence(db, rows)
    if result['quarantined']:
        raise ValueError('manifest localization evidence quarantined; rebuild aborted')
    return result['inserted'] + result['unchanged']
