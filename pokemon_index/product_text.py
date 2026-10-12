"""Exact publisher product captions for existing coordinate families.

These captions can support internal text retrieval. They never identify an
entire set, physical variant, regional release, copy, price or purchase target.
"""
import json
import re

from . import catalog_locale, core, coverage_qualification as qualification

FLAGS = catalog_locale.FALSE_CLAIMS + ('release_binding_verified',)
SCHEMA = 'pokemon.catalog-product-text.v1'
FIELDS = {'schema', 'evidence_id', 'candidate_id', 'card_id', 'publisher', 'products',
          'confidence', 'scope', 'inspected_at', 'test_only'} | set(FLAGS)
SCOPE = 'publisher_product_caption_for_exact_coordinate_family'


def link_kind(url):
    if url is None:
        return 'unlinked_text'
    if not isinstance(url, str):
        raise ValueError('product link must be text or explicitly absent')
    if re.fullmatch(r'https://www\.pokemon-card\.com/(?:ex/[a-z0-9]+/(?:index\.html)?|products/[a-z0-9]+/[a-z0-9]+\.html)', url):
        return 'official_product_page'
    if re.fullmatch(r'https://www\.pokemon-card\.com/info/[0-9]{4}/[0-9]{8}_[0-9]+\.html(?:#[A-Za-z0-9_-]+)?', url):
        return 'official_news_article'
    raise ValueError('product caption URL is outside the publisher evidence namespace')


def declared_products(candidate):
    # The source also contains purchase-button text, sometimes with a malformed
    # marketplace URL. Preserve that in the old held lead, never use it here.
    products = [dict(name=d['name'], publisher_link=d['product_url'], link_kind=link_kind(d['product_url']))
                for d in candidate['source_product_declarations'] if d['name'].startswith('ポケモンカードゲーム')]
    if not 1 <= len(products) <= 10 or len({p['name'] for p in products}) != len(products):
        raise ValueError('product captions missing, duplicate or ambiguous')
    return products


def candidate(db, candidate_id):
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError('product text needs an exact held candidate ID')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_coverage_candidate'").fetchone():
        raise ValueError('product text lacks installed qualification evidence')
    record = db.execute('SELECT record_json FROM catalog_coverage_candidate WHERE candidate_id=?', (candidate_id,)).fetchone()
    if not record:
        raise ValueError('product text lacks installed qualification evidence')
    row = json.loads(record[0])
    qualification.validate(db, row)
    return row


def validate(db, row):
    if not isinstance(row, dict) or row.get('schema') != SCHEMA or set(row) != FIELDS:
        raise ValueError('product text schema/fields differ')
    if row['scope'] != SCOPE or row['test_only'] is not False or any(row[k] is not False for k in FLAGS):
        raise ValueError('product text cannot grant release, physical, display or commerce approval')
    if row['evidence_id'] != 'product-text:' + catalog_locale.digest({k:v for k,v in row.items() if k != 'evidence_id'}):
        raise ValueError('product text evidence hash differs')
    held = candidate(db, row['candidate_id'])
    identity, page = held['identity'], held['cached_official_page']
    if row['card_id'] != identity['card_id'] or identity['language'] != 'ja' or page is None:
        raise ValueError('product text requires exact Japanese cached coordinate evidence')
    if len(held['coordinate_snapshot']) != 1:
        raise ValueError('product caption cannot select a physical variant from siblings')
    expected = dict(provider='pokemon-card-publisher', native_id=page['native_id'], language='ja',
        url=page['url'], sha256=page['sha256'], revision='sha256:' + page['sha256'], retrieved_at=page['retrieved_at'],
        rights_status='existing_cached_factual_text_internal_only', metadata_license_grant=None,
        physical_distribution_region=None)
    if row['publisher'] != expected:
        raise ValueError('publisher snapshot differs from exact cached page')
    if row['products'] != declared_products(held):
        raise ValueError('publisher captions differ from pinned coordinate source declarations')
    confidence = row['confidence']
    if (not isinstance(confidence, dict) or type(confidence.get('source_text_correspondence')) not in (int, float)
            or confidence != dict(source_text_correspondence=1.0, product_release_identity=None, physical_variant=None)):
        raise ValueError('caption confidence cannot imply release or physical identity')
    if not isinstance(row['inspected_at'], str):
        raise ValueError('caption inspection time must be recorded')
    core.parse_time(row['inspected_at'])
    return row['card_id']


def import_evidence(db, rows):
    result = dict(inserted=0, unchanged=0, quarantined=0)
    with db:
        for row in rows:
            try:
                cid = validate(db, row)
                encoded = catalog_locale.encoded(row)
                previous = db.execute('SELECT record_json FROM catalog_product_text WHERE evidence_id=?', (row['evidence_id'],)).fetchone()
                if previous:
                    if previous[0] != encoded:
                        raise ValueError('immutable publisher text changed')
                    result['unchanged'] += 1
                else:
                    db.execute('INSERT INTO catalog_product_text VALUES (?,?,?)', (row['evidence_id'], cid, encoded))
                    result['inserted'] += 1
            except (ValueError, KeyError, TypeError) as exc:
                db.execute('INSERT OR IGNORE INTO catalog_identity_quarantine VALUES (?,?,?)',
                    ('catalog-quarantine:' + catalog_locale.digest(row), str(exc), catalog_locale.encoded(row)))
                result['quarantined'] += 1
    return result


def import_manifest_evidence(db, rows):
    result = import_evidence(db, rows)
    if result['quarantined']:
        raise ValueError('publisher text quarantined; offline build aborted')
    return result['inserted'] + result['unchanged']


def current(db, row):
    try:
        validate(db, row)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def records(db, cid=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_product_text'").fetchone():
        return []
    return [json.loads(r[0]) for r in db.execute('SELECT record_json FROM catalog_product_text WHERE (? IS NULL OR card_id=?) ORDER BY evidence_id', (cid, cid))]


def search_aliases(db):
    aliases = {}
    for row in records(db):
        if current(db, row):
            aliases.setdefault(row['card_id'], []).extend(p['name'] for p in row['products'])
    return aliases


def context(db, cid):
    return [dict(evidence_id=row['evidence_id'], status='current' if current(db, row) else 'stale',
                 products=row['products'], publisher=row['publisher'], scope=SCOPE,
                 confidence=row['confidence'], **{k: False for k in FLAGS}) for row in records(db, cid)]


def status(db):
    rows = records(db)
    active = sum(current(db, row) for row in rows)
    return dict(product_text_events=len(rows), product_text_subjects=len({r['card_id'] for r in rows}),
                current_product_text_events=active, stale_product_text_events=len(rows)-active)
