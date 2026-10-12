"""Append-only held coverage candidates; never an identity admission path.

Provider product text is a lead, not a verified product link. Qualification is
scoped to the exact existing coordinate, source and localized-release snapshot.
It does not add search aliases, source mappings, cards, rights or commerce flags.
"""
import json
import re

from . import catalog_locale, core

FLAGS = catalog_locale.FALSE_CLAIMS
SCHEMA = 'pokemon.catalog-coverage-candidate.v1'
FIELDS = {'schema', 'candidate_id', 'identity', 'coordinate_snapshot', 'coordinate_references',
          'release_snapshot', 'numbering_scope', 'status', 'test_only', 'source', 'confidence',
          'source_product_declarations', 'cached_official_page', 'hold_reasons'} | set(FLAGS)


def coordinate_snapshot(db, identity):
    return [catalog_locale.snapshot(db, r[0]) for r in db.execute(
        'SELECT card_id FROM card WHERE language=? AND set_code=? AND collector_number=? ORDER BY card_id',
        tuple(identity[k] for k in ('language', 'set_code', 'collector_number')))]


def references_snapshot(db, identity):
    return [dict(r) for r in db.execute(
        'SELECT * FROM card_reference WHERE set_code=? AND collector_number=? ORDER BY source,native_id',
        (identity['set_code'], identity['collector_number']))]


def release_snapshot(db, identity):
    row = db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                     (identity['language'], identity['set_code'])).fetchone()
    return dict(row) if row else None


def hold_reasons(row):
    # Even a later supplied link needs the separate release-metadata importer.
    # This record type can register evidence work only; it cannot approve it.
    reasons = ['release_metadata_not_qualified']
    page = row['cached_official_page']
    if page is None:
        reasons.append('official_card_page_not_in_cached_evidence')
    elif not page['product_links']:
        reasons.append('official_card_page_has_no_product_link')
    else:
        reasons.append('product_link_requires_separate_release_review')
    if row['source_product_declarations']:
        reasons.append('provider_product_text_is_not_verified_release_binding')
    if row['identity']['variant'].startswith('unverified'):
        reasons.append('physical_printing_family_unresolved')
    if len(row['coordinate_snapshot']) != 1:
        reasons.append('coordinate_has_multiple_source_variant_records')
    return reasons


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + ' must be nonempty text')


def _hash(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(field + ' needs SHA-256')


def validate(db, row):
    if not isinstance(row, dict) or row.get('schema') != SCHEMA:
        raise ValueError('unknown coverage candidate schema')
    if set(row) != FIELDS:
        raise ValueError('coverage candidate fields missing or unsupported')
    if row.get('status') != 'held' or row.get('test_only') is not False or any(row.get(k) is not False for k in FLAGS):
        raise ValueError('coverage candidates cannot grant identity, display or commerce approval')
    body = {k: v for k, v in row.items() if k != 'candidate_id'}
    if row.get('candidate_id') != 'coverage-candidate:' + catalog_locale.digest(body):
        raise ValueError('coverage candidate hash mismatch')
    identity = row.get('identity')
    if not isinstance(identity, dict) or identity != catalog_locale.snapshot(db, identity.get('card_id')):
        raise ValueError('coverage identity snapshot differs')
    attributes = json.loads(db.execute('SELECT attributes_json FROM card WHERE card_id=?', (identity['card_id'],)).fetchone()[0])
    if not isinstance(attributes, dict) or attributes.get('test_only', False) is not False:
        raise ValueError('test-only baseline records cannot enter real coverage qualification')
    if row.get('coordinate_snapshot') != coordinate_snapshot(db, identity):
        raise ValueError('coverage coordinate/sibling snapshot differs')
    if row.get('coordinate_references') != references_snapshot(db, identity):
        raise ValueError('coverage reference snapshot differs')
    if row.get('release_snapshot') != release_snapshot(db, identity):
        raise ValueError('coverage localized release snapshot differs')
    if row.get('numbering_scope') != 'provisional:' + identity['language'] + ':' + identity['set_code']:
        raise ValueError('coverage scope must remain provisional language/set')
    src = row.get('source')
    if not isinstance(src, dict):
        raise ValueError('coverage source must be an object')
    for k in ('provider', 'native_id', 'revision', 'sha256', 'rights_reference', 'language', 'region'):
        _text(src.get(k), k)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,60}', src['provider']) or not re.fullmatch(r'[0-9a-f]{40}', src['revision']):
        raise ValueError('invalid coverage provider/revision')
    _hash(src['sha256'], 'source hash')
    _hash(src.get('license_sha256'), 'license hash')
    if (src['language'] != identity['language'] or src['region'] != 'ZZ'
            or src['rights_reference'] != identity['rights_reference']
            or src.get('rights_status') != 'metadata_internal_reviewed'):
        raise ValueError('coverage source language/rights or unknown physical region differs')
    if identity['provenance'] != f"{src['provider']}:{src['revision']}:{src['native_id']}:sha256:{src['sha256']}":
        raise ValueError('coverage provider source differs from baseline')
    _text(src.get('inspected_at'), 'source inspection time')
    core.parse_time(src['inspected_at'])
    if src.get('retrieved_at') is not None or src.get('retrieval_status') != 'historical_snapshot_time_not_recorded':
        raise ValueError('historical source retrieval time must remain unknown')
    confidence = row.get('confidence')
    if (not isinstance(confidence, dict) or type(confidence.get('source_bytes')) not in (int, float)
            or confidence != {'source_bytes': 1.0, 'product_binding': None, 'physical_printing': None}):
        raise ValueError('coverage confidence must distinguish checked bytes from unknown identity')
    declarations = row.get('source_product_declarations')
    if not isinstance(declarations, list) or len(declarations) > 20:
        raise ValueError('coverage product declarations must be a bounded list')
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != {'name', 'product_url'}:
            raise ValueError('invalid coverage product declaration')
        _text(declaration['name'], 'declared product name')
        if declaration['product_url'] is not None:
            _text(declaration['product_url'], 'declared product URL')
    page = row.get('cached_official_page')
    if page is not None:
        if not isinstance(page, dict):
            raise ValueError('cached official page must be an object')
        _text(page.get('native_id'), 'official native ID')
        if not page['native_id'].isdigit() or page.get('url') != 'https://www.pokemon-card.com/card-search/details.php/card/' + page['native_id']:
            raise ValueError('cached page URL differs from exact official reference')
        _hash(page.get('sha256'), 'cached page hash')
        _text(page.get('retrieved_at'), 'cached page retrieval time')
        core.parse_time(page['retrieved_at'])
        if page.get('rights_status') != 'cached_evidence_only_no_display_grant':
            raise ValueError('official cache rights must remain unapproved for display')
        if not any(r['source'] == 'ptcg-database' and r['native_id'] == page['native_id'] for r in row['coordinate_references']):
            raise ValueError('cached page is not bound to this provider coordinate')
        if page.get('name') != identity['name'] or page.get('coordinate') != {'set_code': identity['set_code'], 'collector_number': identity['collector_number']}:
            raise ValueError('cached page text/coordinate differs from this record')
        links = page.get('product_links')
        if not isinstance(links, list) or len(links) > 20:
            raise ValueError('cached page product links must be a bounded list')
        for link in links:
            if not isinstance(link, dict) or set(link) != {'name', 'url'}:
                raise ValueError('invalid official product link')
            _text(link['name'], 'product link name')
            if not isinstance(link['url'], str) or not re.fullmatch(r'https://www\.pokemon-card\.com/(?:ex/[a-z0-9]+/(?:index\.html)?|products/[a-z0-9]+/[a-z0-9]+\.html)', link['url']):
                raise ValueError('product link must be official')
    if row.get('hold_reasons') != hold_reasons(row):
        raise ValueError('coverage hold reasons differ')
    return identity['card_id']


def import_candidates(db, rows):
    counts = dict(inserted=0, unchanged=0, rejected=0)
    with db:
        for row in rows:
            try:
                cid = validate(db, row)
                encoded = catalog_locale.encoded(row)
                previous = db.execute('SELECT record_json FROM catalog_coverage_candidate WHERE candidate_id=?',
                                      (row['candidate_id'],)).fetchone()
                if previous:
                    if previous[0] != encoded:
                        raise ValueError('immutable coverage candidate changed')
                    counts['unchanged'] += 1
                else:
                    db.execute('INSERT INTO catalog_coverage_candidate VALUES (?,?,?)', (row['candidate_id'], cid, encoded))
                    counts['inserted'] += 1
                reason = '; '.join(row['hold_reasons'])
            except (ValueError, KeyError, TypeError) as exc:
                reason = str(exc)
                counts['rejected'] += 1
            # Valid ambiguous families and malformed records remain held. Neither
            # branch creates a card, source mapping or positive release overlay.
            db.execute('INSERT OR IGNORE INTO catalog_identity_quarantine VALUES (?,?,?)',
                       ('catalog-quarantine:' + catalog_locale.digest(row), reason, catalog_locale.encoded(row)))
    return counts


def import_manifest_candidates(db, rows):
    result = import_candidates(db, rows)
    if result['rejected']:
        raise ValueError('invalid coverage candidate; offline build aborted')
    return result['inserted'] + result['unchanged']


def current(db, row):
    try:
        validate(db, row)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def _present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_coverage_candidate'").fetchone()


def context(db, cid):
    if not _present(db):
        return []
    return [dict(candidate_id=row['candidate_id'], status='held' if current(db, row) else 'stale',
                 hold_reasons=row['hold_reasons'], numbering_scope=row['numbering_scope'],
                 source=row['source'], confidence=row['confidence'],
                 scope='evidence qualification only; no identity, alias, release date or offer approval',
                 **{k: False for k in FLAGS})
            for record in db.execute('SELECT record_json FROM catalog_coverage_candidate WHERE card_id=? ORDER BY candidate_id', (cid,))
            for row in [json.loads(record[0])]]


def status(db):
    rows = [json.loads(r[0]) for r in db.execute('SELECT record_json FROM catalog_coverage_candidate')] if _present(db) else []
    held = sum(current(db, row) for row in rows)
    return dict(coverage_candidate_events=len(rows), coverage_candidate_subjects=len({r['identity']['card_id'] for r in rows}), coverage_current_held=held,
                coverage_stale_candidates=len(rows)-held, coverage_admitted_identities=0)
