"""Versioned source-independent catalog evidence identity for benchmark fixtures.

This is the evidence-only portion of the reviewed collector journey revision:
twenty evidence tables and five view definitions retain their reviewed data
encoding. Version2 additionally binds the complete stored main schema (including
column types, collations, indexes, triggers and intermediate views), encoding,
application ID and user version. Explicit version3 additionally binds locale,
provider mappings, concept revisions/reviews and identity quarantine rows. The
version2 default is retained for historical fixtures. It deliberately does not read runtime
source files, mutable conversation state, or market state. The two documented
build-time timestamp normalizations are the only excluded evidence fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json


SCHEMA = 'pokemon.collector-catalog-evidence.v2'
LOCALIZED_SCHEMA = 'pokemon.collector-catalog-evidence.v3'
VIEW_NAMES = (
    'active_card_metadata_evidence', 'discovery_card_facet',
    'base_discovery_card_facet', 'active_source_correction_evidence',
    'effective_card_reference',
)
TABLE_NAMES = (
    'card', 'card_facet', 'card_classification', 'catalog_set_localized',
    'catalog_vocabulary', 'character_family', 'character_family_member',
    'catalog_collector_evidence', 'supported_card', 'card_reference',
    'card_rarity_correction', 'catalog_release_evidence', 'card_metadata_evidence',
    'coordinate_family_evidence', 'card_relationship_assertion',
    'printing_source_evidence', 'source_correction_evidence',
    'card_number_reading_evidence', 'source_image_fact_evidence',
    'source_mechanic_binding',
)


def _validate_timestamp(value):
    """Mirror the reviewed core.parse_time without importing production source."""
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include a UTC offset')
    parsed.astimezone(timezone.utc)


def catalog_schema_record(db):
    """Bind query-relevant stored schema, not just table column names/row values.

    Page layout, freelist and SQLite's schema-change counter are not evidence.
    No stored schema object is silently omitted, including implicit indexes.
    """
    return {
        'encoding': db.execute('PRAGMA main.encoding').fetchone()[0],
        'application_id': db.execute('PRAGMA main.application_id').fetchone()[0],
        'user_version': db.execute('PRAGMA main.user_version').fetchone()[0],
        'objects': [list(row) for row in db.execute(
            'SELECT type,name,tbl_name,sql FROM main.sqlite_master '
            'ORDER BY type COLLATE BINARY,name COLLATE BINARY,tbl_name COLLATE BINARY')],
    }


def encoded_schema_record(db):
    return json.dumps(['main_schema', catalog_schema_record(db)],
        ensure_ascii=False, separators=(',', ':')).encode() + b'\n'


def catalog_evidence_digest(db, *, schema=SCHEMA):
    """Return evidence identity without writes, source reads, or row-factory edits.

    ``db`` is an existing SQLite connection, ideally opened read-only. Callers
    must still record and independently check the physical database byte hash
    before and after their measurement. This digest permits only the original
    review's narrow bookkeeping differences between equivalent database builds.
    """
    if schema not in (SCHEMA,LOCALIZED_SCHEMA):raise ValueError('unsupported catalog evidence schema')
    tables=TABLE_NAMES if schema==SCHEMA else TABLE_NAMES+('catalog_identity_quarantine','catalog_locale_evidence','catalog_source_mapping','bilingual_concept_revision','concept_review_event')
    digest = hashlib.sha256(schema.encode())
    digest.update(encoded_schema_record(db))
    for name in VIEW_NAMES:
        definition = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
        ).fetchone()
        digest.update(json.dumps([name, definition[0] if definition else None]).encode())
    for table in tables:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
            continue
        columns = [row[1] for row in db.execute('PRAGMA table_info(' + table + ')')]
        if table == 'card_rarity_correction':
            columns.remove('applied_at')
        digest.update(json.dumps([table, columns]).encode())
        query = 'SELECT ' + ','.join(columns) + ' FROM ' + table + ' ORDER BY ' + ','.join(columns)
        for row in db.execute(query):
            values = list(row)
            if (table == 'card_relationship_assertion'
                    and values[columns.index('asserted_by')] == 'ai-artwork-review-v1'
                    and values[columns.index('review_status')] == 'proposed'):
                index = columns.index('asserted_at')
                _validate_timestamp(values[index])
                values[index] = None
            digest.update(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode())
            digest.update(b'\n')
    return digest.hexdigest()
