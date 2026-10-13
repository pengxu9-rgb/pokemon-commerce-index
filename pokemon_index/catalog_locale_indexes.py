"""Explicit bulk-snapshot lookup indexes; legacy build schemas stay unchanged."""
SPECIFICATIONS = (
    ('catalog_locale_evidence_card', 'catalog_locale_evidence'),
    ('catalog_source_mapping_card', 'catalog_source_mapping'),
)
SQL = {name: f'CREATE INDEX {name} ON {table}(card_id)' for name, table in SPECIFICATIONS}
RECORD = dict(schema='pokemon.catalog-locale-lookup-indexes.v1', indexes=[
    dict(name=name, table=table, columns=['card_id'], unique=False) for name, table in SPECIFICATIONS])


def import_manifest_evidence(db, rows):
    records = list(rows)
    if len(records) != 1 or records[0] != RECORD:
        raise ValueError('only the two exact nonunique locale lookup indexes are supported')
    added = 0
    with db:
        for name, table in SPECIFICATIONS:
            found = db.execute('SELECT type,tbl_name,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if found:
                if tuple(found) != ('index', table, SQL[name]):
                    raise ValueError('locale lookup index definition differs')
            else:
                db.execute(SQL[name]); added += 1
    return added


def without_optional_indexes(schema):
    """Return the full base schema only when both extra indexes match exactly."""
    extras = [row for row in schema if row[1] in SQL]
    expected = {('index', name, table, SQL[name]) for name, table in SPECIFICATIONS}
    if extras and set(extras) != expected:
        raise ValueError('partial or altered locale lookup index schema')
    return tuple(row for row in schema if row[1] not in SQL)
