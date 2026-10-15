"""Bounded immutable-image bootstrap data, independently qualified at image build.

A generated seal is not a signature. Custom/offline loading requires the original
external seal pin. The private fixed-image entrypoint trusts the independently
checked immutable image; its full native-state gate remains the trust anchor.
"""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import MappingProxyType
import unicodedata

from . import collector_runtime as runtime

FORMAT = 'pokemon.catalog-read-model-artifact.v1'
STATE_FORMAT = 'pokemon.catalog-read-model-state.v4'
FILES = ('metadata.json', 'facet-image.sqlite3', 'seal.json')
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_SEAL_BYTES = 64 * 1024
MAX_DECODED_BYTES = 192 * 1024 * 1024
MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_JSON_MEMBERS = 1000000
MAX_JSON_DEPTH = 32
_PACKAGED_DIR = Path('/app/catalog-read-model')
_PACKAGED_MANIFEST = Path('/app/catalog-build-manifest.json')
HEX = re.compile(r'[0-9a-f]{64}\Z')
_JSON_STRINGS = re.compile(rb'"(?:[^"\\]++|\\.)*+"')
_NON_JSON_TOKENS = bytes(value for value in range(256) if value not in b'{}[],')
_IMAGE_SQL = (
    ('index', 'card_lookup', 'facets', 'CREATE INDEX card_lookup ON facets(card_id,facet_type,value)'),
    ('index', 'facet_lookup', 'facets', 'CREATE INDEX facet_lookup ON facets(facet_type,value,card_id)'),
    ('table', 'facets', 'facets', 'CREATE TABLE facets (card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)'),
)


class ArtifactInvalid(ValueError):
    """A present artifact is unusable; never silently publish partial facts."""


def _require(condition, message):
    if not condition:
        raise ArtifactInvalid(message)


def _exact(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), label + ' fields')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def _json(raw, limit):
    _require(len(raw) <= limit, 'JSON byte bound')
    # Strip exactly the same escaped JSON string tokens before counting raw
    # punctuation. The decoder below still rejects malformed syntax and names.
    # C-level byte operations avoid a Python regex Match for every scalar.
    tokens = _JSON_STRINGS.sub(b'', raw).translate(None, _NON_JSON_TOKENS)
    _require(len(tokens) <= MAX_JSON_MEMBERS, 'JSON member bound')
    depth = 0
    for index, token in enumerate(tokens):
        if index % 1024 == 0: runtime.checkpoint()
        if token == 44: continue  # comma still counts toward the member bound
        depth += 1 if token in (123, 91) else -1
        _require(0 <= depth <= MAX_JSON_DEPTH, 'JSON nesting bound')
    _require(depth == 0, 'JSON nesting')
    try:
        result = json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ArtifactInvalid('JSON nonfinite value')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ArtifactInvalid('invalid JSON') from exc
    runtime.checkpoint()
    return result


def _file_identity(path):
    st = os.lstat(path)
    _require(not stat.S_ISLNK(st.st_mode), 'symlink artifact or input')
    _require(stat.S_ISREG(st.st_mode), 'nonregular artifact or input')
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _read(path, limit):
    path = Path(path)
    before = _file_identity(path)
    _require(before[2] <= limit, 'file byte bound')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        st = os.fstat(fd)
        _require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) == before, 'file changed before read')
        chunks = []; size = 0
        while True:
            runtime.checkpoint()
            part = os.read(fd, 1024 * 1024)
            if not part: break
            size += len(part); _require(size <= limit, 'file byte bound'); chunks.append(part)
        raw = b''.join(chunks)
    finally:
        os.close(fd)
    _require(_file_identity(path) == before, 'file changed during read')
    return raw, before


def _database_hash(path):
    before = _file_identity(path)
    _require(before[2] <= MAX_DATABASE_BYTES, 'database byte bound')
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as file:
        st = os.fstat(file.fileno())
        _require((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns) == before,
                 'database changed before hash')
        while True:
            runtime.checkpoint(); part = file.read(1024 * 1024)
            if not part: break
            h.update(part)
    _require(_file_identity(path) == before, 'database changed during hash')
    return h.hexdigest(), before[2]


def _no_wal(path):
    wal = Path(str(path) + '-wal')
    _require(not wal.is_symlink(), 'symlink WAL')
    _require(not wal.exists() or wal.stat().st_size == 0, 'nonempty WAL')


def _encode(value):
    if value is None: return ['n']
    if type(value) is str: return ['s', value]
    if type(value) is bytes: return ['b', base64.b64encode(value).decode('ascii')]
    if type(value) is int:
        _require(-(2**63) <= value < 2**63, 'SQLite integer range')
        return ['i', value]
    if type(value) is float: return ['r', value.hex()]
    if type(value) is bool: return ['t', value]
    raise ArtifactInvalid('unsupported SQLite/control type')


def _decode(value):
    _require(type(value) is list and value, 'typed scalar')
    tag = value[0]
    if tag == 'n': _require(len(value) == 1, 'NULL scalar'); return None
    _require(len(value) == 2, 'typed scalar fields')
    data = value[1]
    if tag == 's': _require(type(data) is str, 'TEXT scalar'); return data
    if tag == 'i':
        _require(type(data) is int and -(2**63) <= data < 2**63, 'INTEGER scalar'); return data
    if tag == 't': _require(type(data) is bool, 'boolean scalar'); return data
    if tag == 'b':
        _require(type(data) is str, 'BLOB scalar')
        try: decoded = base64.b64decode(data, validate=True)
        except (ValueError, UnicodeError) as exc: raise ArtifactInvalid('BLOB encoding') from exc
        _require(base64.b64encode(decoded).decode('ascii') == data, 'BLOB canonical encoding'); return decoded
    if tag == 'r':
        _require(type(data) is str, 'REAL scalar')
        try: decoded = float.fromhex(data)
        except ValueError as exc: raise ArtifactInvalid('REAL encoding') from exc
        _require(decoded.hex() == data and decoded == decoded, 'REAL canonical encoding'); return decoded
    raise ArtifactInvalid('unknown typed scalar')


def _sort_key(value):
    return _json_bytes(_encode(value))


def _typed_rows(rows):
    return [[_encode(value) for value in row] for row in rows]


def _id_map(value):
    return [[_encode(key), [_encode(cid) for cid in sorted(ids, key=_sort_key)]]
            for key, ids in sorted(value.items(), key=lambda pair: _sort_key(pair[0]))]


def model_state(model):
    """Every immutable model fact, typed and deterministic; no query or result."""
    state = dict(schema=STATE_FORMAT, facet_image_sha256=_sha(model._image),
        vocabularies={key: dict(columns=list(rows[0].keys()) if rows else
            {'artists':['value'], 'release_codes':['set_code'],
             'character_aliases':['name','dex_id','current_evidence']}[key], rows=_typed_rows(rows))
            for key, rows in model._vocabularies.items()},
        affiliations_json=model._affiliations_json,
        media_ids=[_encode(cid) for cid in sorted(model._media_ids, key=_sort_key)],
        cast_dex_card_ids=_id_map(model._cast_dex_card_ids),
        text_dex_card_ids=_id_map(model._text_dex_card_ids),
        character_names={str(current).lower(): _typed_rows(sorted(rows, key=lambda row: _json_bytes(_typed_rows([row]))))
                         for current, rows in model._character_names.items()},
        release_names=_typed_rows(sorted(model._release_names)),
        release_aliases_json=model._release_aliases_json,
        card_source_context_index=model._card_source_context_index.to_state(),
        parser_facts=model._parser_facts.to_state() if model._parser_facts is not None else None)
    return state


def _schema(db):
    return dict(objects=[tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master ORDER BY type,name,tbl_name')],
        encoding=db.execute('PRAGMA main.encoding').fetchone()[0],
        application_id=db.execute('PRAGMA main.application_id').fetchone()[0],
        user_version=db.execute('PRAGMA main.user_version').fetchone()[0])


def _engine_profile(db):
    return dict(sqlite_version=sqlite3.sqlite_version,
                compile_options=sorted(row[0] for row in db.execute('PRAGMA compile_options')),
                unicode_version=unicodedata.unidata_version)


def _counts(model):
    counts = dict(vocabulary_rows={key:len(rows) for key,rows in model._vocabularies.items()},
        media_ids=len(model._media_ids), affiliations=len(_json(model._affiliations_json.encode(), 1024*1024)),
        cast_dex_keys=len(model._cast_dex_card_ids), cast_dex_bindings=sum(map(len,model._cast_dex_card_ids.values())),
        text_dex_keys=len(model._text_dex_card_ids), text_dex_bindings=sum(map(len,model._text_dex_card_ids.values())),
        character_name_rows={str(key).lower():len(rows) for key,rows in model._character_names.items()},
        release_name_rows=len(model._release_names), release_aliases=len(_json(model._release_aliases_json.encode(), 1024*1024)))

    facts=model._parser_facts
    counts.update(parser_plan_enabled=facts is not None,
        parser_vocabulary_rows=len(facts.vocabulary) if facts is not None else 0,
        parser_qualifier_heads=len(facts.qualifiers) if facts is not None else 0,
        parser_known_qualifiers=len(facts.known_qualifiers) if facts is not None else 0)
    counts.update(model._card_source_context_index.counts())
    return counts


def _source_identities():
    from . import collector_journey
    package = Path(__file__).parent
    return tuple((package / name, _file_identity(package / name)) for name in collector_journey.RUNTIME_SOURCES)


def _unchanged(identities):
    for path, identity in identities:
        runtime.checkpoint()
        _require(_file_identity(path) == identity, 'artifact or source policy changed')


def _guard(model):
    _unchanged(model._artifact_identities)


def _request_guard(model):
    try:
        _guard(model)
    except (OSError, ArtifactInvalid) as exc:
        raise runtime.CatalogSnapshotChanged() from exc


def _safe_directory(path):
    _require(not path.is_symlink() and path.is_dir(), 'artifact directory')
    _require(set(p.name for p in path.iterdir()) == set(FILES), 'partial or extra artifact members')


def write(db, manifest_path, output_dir):
    """Export the fully native model after this build's actual DB is finalized."""
    from . import collector_journey
    output_dir = Path(output_dir)
    _require(not output_dir.exists() and not output_dir.is_symlink(), 'artifact output already exists')
    sources = _source_identities(); roster = collector_journey.runtime_source_hashes()
    main = next(row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main')
    path = Path(main); _no_wal(path)
    database_sha256, database_bytes = _database_hash(path)
    manifest, manifest_identity = _read(Path(manifest_path), MAX_SEAL_BYTES)
    revision = collector_journey.catalog_revision(db)
    model = runtime.CatalogReadModel(db)
    metadata = _json_bytes(model_state(model))
    _require(len(metadata) <= MAX_METADATA_BYTES, 'metadata byte bound')
    seal = dict(schema=FORMAT, database_sha256=database_sha256, database_bytes=database_bytes,
        manifest_sha256=_sha(manifest), canonical_revision=revision, runtime_source_sha256=roster,
        engine_profile=_engine_profile(db),
        schema_sha256=_sha(_json_bytes(_schema(db))),
        metadata_sha256=_sha(metadata), metadata_bytes=len(metadata),
        facet_image_sha256=_sha(model._image), facet_image_bytes=len(model._image),
        model_state_sha256=_sha(metadata), fact_counts=_counts(model))
    seal_raw = _json_bytes(seal); _require(len(seal_raw) <= MAX_SEAL_BYTES, 'seal byte bound')
    model._check_snapshot(db); _no_wal(path); _unchanged(sources)
    _require(_file_identity(Path(manifest_path)) == manifest_identity, 'manifest changed')
    # The directory is exclusively claimed. Each file is atomically published;
    # seal.json is the final commit marker. A partial directory always rejects.
    output_dir.mkdir()
    try:
        for name, raw in [('metadata.json', metadata), ('facet-image.sqlite3', model._image), ('seal.json', seal_raw)]:
            temporary = output_dir / ('.' + name + '.tmp')
            with temporary.open('xb') as file:
                file.write(raw); file.flush(); os.fsync(file.fileno())
            os.rename(temporary, output_dir / name)
    except BaseException:
        # Preserve the exclusive diagnostic directory. No partial model can load.
        raise
    model._check_snapshot(db); _no_wal(path); _unchanged(sources)
    _require(_file_identity(Path(manifest_path)) == manifest_identity, 'manifest changed during publication')
    return dict(seal, seal_sha256=_sha(seal_raw))


def _restore_map(encoded, key_type, cls):
    _require(type(encoded) is list and len(encoded) <= cls.MAX_DEX_KEYS, 'Dex key bound')
    result = {}; total = 0; size = 0
    for entry in encoded:
        runtime.checkpoint()
        _require(type(entry) is list and len(entry) == 2 and type(entry[1]) is list, 'Dex map record')
        key = _decode(entry[0]); _require(type(key) is key_type and key not in result, 'Dex key type or duplicate')
        ids = [_decode(value) for value in entry[1]]
        _require(all(type(cid) in (str, bytes) for cid in ids) and len(ids) == len(set(ids)), 'Dex ID type or duplicate')
        total += len(ids); size += sum(len(cid.encode('utf-8') if type(cid) is str else cid) for cid in ids)
        _require(total <= cls.MAX_DEX_BINDINGS and size <= cls.MAX_DEX_ID_BYTES, 'Dex binding bound')
        result[key] = frozenset(ids)
    return MappingProxyType(result)


def _proof_json(raw, *, release=False):
    _require(type(raw) is str, 'proof JSON type')
    value = _json(raw.encode('utf-8'), 1024*1024)
    if release:
        _require(type(value) is list and len(value) <= 100000, 'release proof bound')
        keys = {'alias','language','set_code','derivation','source_published_alias','source_title','source_ref','source_page_sha256','rights_reference'}
        for row in value:
            _exact(row, keys, 'release proof')
            _require(row['source_published_alias'] is False and
                     all(type(item) is str for key,item in row.items()
                         if key != 'source_published_alias'), 'release authority or type')
    else:
        from . import collector_character_affiliation
        _require(type(value) is dict and len(value) <= collector_character_affiliation.MAX_BINDINGS, 'affiliation proof bound')
        reason_keys = {'field','value','basis','source_ref','target_name','base_name_ja','mechanic','source_asserted_dex_id','anchor_evidence','anchor_count','anchor_evidence_sha256','derivation'}
        for cid, row in value.items():
            _exact(row, {'card_id','dex_id','reason'}, 'affiliation proof')
            _require(type(cid) is str and row['card_id'] == cid and
                     type(row['dex_id']) is int and 1 <= row['dex_id'] <= 1025,
                     'affiliation identity or type')
            _exact(row['reason'], reason_keys, 'affiliation reason')
            reason = row['reason']
            _require(reason['source_asserted_dex_id'] is False and
                     type(reason['value']) is int and reason['value'] == row['dex_id'] and
                     type(reason['anchor_count']) is int and reason['anchor_count'] >= 1 and
                     type(reason['anchor_evidence']) is list and len(reason['anchor_evidence']) == 1 and
                     all(type(reason[key]) is str for key in reason_keys -
                         {'value','source_asserted_dex_id','anchor_count','anchor_evidence'}),
                     'affiliation authority or type')
            for anchor in row['reason']['anchor_evidence']:
                _exact(anchor, {'card_id','name','dex_id','provenance','rights_reference'}, 'affiliation anchor')
                _require(type(anchor['dex_id']) is int and anchor['dex_id'] == row['dex_id'] and
                         all(type(item) is str for key,item in anchor.items() if key != 'dex_id'),
                         'affiliation anchor type')
    return raw


def _restore(state, image):
    cls = runtime.CatalogReadModel
    keys = {'schema','facet_image_sha256','vocabularies','affiliations_json','media_ids','cast_dex_card_ids','text_dex_card_ids','character_names','release_names','release_aliases_json','card_source_context_index','parser_facts'}
    _exact(state, keys, 'model state'); _require(state['schema'] == STATE_FORMAT and state['facet_image_sha256'] == _sha(image), 'model format or image hash')
    model = object.__new__(cls)
    _exact(state['vocabularies'], runtime.VOCABULARY_SQL, 'vocabulary')
    expected_columns = {'artists':['value'], 'release_codes':['set_code'], 'character_aliases':['name','dex_id','current_evidence']}
    vocabularies = {}
    with closing(sqlite3.connect(':memory:')) as rows_db:
        for key, value in state['vocabularies'].items():
            _exact(value, {'columns','rows'}, 'vocabulary record')
            _require(value['columns'] == expected_columns[key] and type(value['rows']) is list and len(value['rows']) <= 100000, 'vocabulary columns or bound')
            cursor = rows_db.execute('SELECT ' + ','.join('NULL AS '+column for column in expected_columns[key]))
            rows = []
            for row in value['rows']:
                runtime.checkpoint(); _require(type(row) is list and len(row) == len(expected_columns[key]), 'vocabulary row shape')
                rows.append(sqlite3.Row(cursor, tuple(_decode(item) for item in row)))
            _require(len(rows) == len(set(tuple(row) for row in rows)), 'duplicate vocabulary row')
            vocabularies[key] = tuple(rows)
    model._vocabularies = MappingProxyType(vocabularies)
    model._affiliations_json = _proof_json(state['affiliations_json'])
    _require(type(state['media_ids']) is list and len(state['media_ids']) <= cls.MAX_MEDIA_IDS, 'media membership bound')
    ids = [_decode(value) for value in state['media_ids']]
    _require(all(type(cid) is str for cid in ids) and len(ids) == len(set(ids)) and sum(len(cid.encode('utf-8')) for cid in ids) <= cls.MAX_MEDIA_ID_BYTES, 'media ID type, duplicate or bound')
    model._media_ids = frozenset(ids)
    model._cast_dex_card_ids = _restore_map(state['cast_dex_card_ids'], int, cls)
    model._text_dex_card_ids = _restore_map(state['text_dex_card_ids'], str, cls)
    _exact(state['character_names'], {'true','false'}, 'character names')
    names = {}
    for flag, rows in state['character_names'].items():
        _require(type(rows) is list and len(rows) <= cls.MAX_CHARACTER_NAME_ROWS, 'character name row bound')
        decoded = []
        for row in rows:
            _require(type(row) is list and len(row) == 3, 'character name row')
            name, dex, current = tuple(_decode(item) for item in row)
            _require(type(name) is str and (dex is None or type(dex) is int) and type(current) is bool, 'character name types')
            decoded.append((name,dex,current))
        _require(len(decoded) == len(set((name,dex) for name,dex,current in decoded)) and sum(len(name.encode('utf-8')) for name,dex,current in decoded) <= cls.MAX_CHARACTER_NAME_BYTES, 'character name duplicate or bound')
        names[flag == 'true'] = tuple(decoded)
    model._character_names = MappingProxyType(names)
    _require(type(state['release_names']) is list and len(state['release_names']) <= cls.MAX_RELEASE_NAME_ROWS, 'release name row bound')
    releases = []
    for row in state['release_names']:
        _require(type(row) is list and len(row) == 3, 'release name row')
        decoded = tuple(_decode(item) for item in row)
        _require(all(type(value) is str for value in decoded), 'release name types'); releases.append(decoded)
    _require(sum(sum(len(value.encode('utf-8')) for value in row) for row in releases) <= cls.MAX_RELEASE_NAME_BYTES, 'release name byte bound')
    # Normalization can create duplicate source terms. Preserve that native
    # tuple multiplicity; query-time membership uses its original set semantics.
    model._release_names = tuple(releases)
    model._release_aliases_json = _proof_json(state['release_aliases_json'], release=True)
    from . import card_source_context_index
    model._card_source_context_index = card_source_context_index.restore_index(state['card_source_context_index'])
    from . import collector_discovery
    model._parser_facts=collector_discovery._restore_parser_facts(state['parser_facts'],model)
    model._image = image
    return model


def _validate_image(image):
    _require(len(image) <= runtime.CatalogReadModel.MAX_IMAGE_BYTES, 'facet image byte bound')
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(image)
        db.execute('PRAGMA query_only=ON')
        actual = tuple(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name'))
        _require(actual == _IMAGE_SQL, 'facet image schema')
        _require(db.execute('PRAGMA encoding').fetchone()[0] == 'UTF-8' and db.execute('PRAGMA application_id').fetchone()[0] == 0 and db.execute('PRAGMA user_version').fetchone()[0] == 0, 'facet image versions')
        _require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'facet image integrity')


def _deep_size(value, seen=None):
    if seen is None: seen = set()
    pending = [value]; size = 0
    getsizeof = sys.getsizeof; visited = seen.add
    extend = pending.extend; pop = pending.pop
    mappings = (dict, MappingProxyType)
    sequences = (tuple, list, set, frozenset, sqlite3.Row)
    while pending:
        item = pop(); identity = id(item)
        if identity in seen: continue
        visited(identity); size += getsizeof(item)
        if isinstance(item, mappings):
            extend(item.keys()); extend(item.values())
        elif isinstance(item, sequences):
            extend(item)
    return size


def _read_bootstrap_files(path, artifact_dir, seal):
    """Overlap bounded file reads with one checksum task before restoration.

    The worker inherits the original cooperative deadline and only hashes the
    source database. SQLite, JSON decoding and model restoration stay on the
    caller and wait for accepted checksum/byte evidence. The context manager
    joins on every exit, including read failure and interruption.
    """
    def hash_task():
        started = time.monotonic()
        result = _database_hash(path)
        return result, time.monotonic() - started

    context = copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='catalog-bootstrap-hash') as executor:
        task = executor.submit(context.run, hash_task)
        started = time.monotonic()
        read_error = None
        try:
            metadata, metadata_identity = _read(artifact_dir/'metadata.json', MAX_METADATA_BYTES)
            image, image_identity = _read(artifact_dir/'facet-image.sqlite3', runtime.CatalogReadModel.MAX_IMAGE_BYTES)
        except Exception as exc:
            read_error = exc
        read_seconds = time.monotonic() - started
        (database_sha256, database_bytes), hash_seconds = task.result()
        _require((database_sha256, database_bytes) ==
                 (seal['database_sha256'], seal['database_bytes']), 'database byte mismatch')
        if read_error is not None:
            raise read_error
        started = time.monotonic()
        metadata_sha256 = _sha(metadata)
        _require((len(metadata), metadata_sha256) ==
                 (seal['metadata_bytes'], seal['metadata_sha256']) and
                 metadata_sha256 == seal['model_state_sha256'], 'metadata hash mismatch')
        _require((len(image), _sha(image)) ==
                 (seal['facet_image_bytes'], seal['facet_image_sha256']), 'image hash mismatch')
        read_seconds += time.monotonic() - started
    return metadata, metadata_identity, image, image_identity, hash_seconds, read_seconds


def _load(db, artifact_dir, manifest_path, expected_seal_sha256, bootstrap_timings=None):
    _require(bootstrap_timings is None or type(bootstrap_timings) is dict,
             'bootstrap diagnostics must be a plain dictionary')
    phases = {}
    phase_started = time.monotonic()
    def measured(name):
        nonlocal phase_started
        current = time.monotonic()
        phases[name] = current - phase_started
        phase_started = current
    from . import collector_journey, collector_release_alias
    cls = runtime.CatalogReadModel
    artifact_dir = Path(artifact_dir); manifest_path = Path(manifest_path)
    _safe_directory(artifact_dir)
    main = next(row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main')
    _file_identity(Path(main))
    path, identity = cls._validate_database(db); _no_wal(path)
    sources = _source_identities(); roster = collector_journey.runtime_source_hashes()
    seal_raw, seal_identity = _read(artifact_dir/'seal.json', MAX_SEAL_BYTES)
    if expected_seal_sha256 is not None:
        _require(type(expected_seal_sha256) is str and HEX.fullmatch(expected_seal_sha256) and _sha(seal_raw) == expected_seal_sha256, 'external seal pin mismatch')
    seal = _json(seal_raw, MAX_SEAL_BYTES)
    keys = {'schema','database_sha256','database_bytes','manifest_sha256','canonical_revision','runtime_source_sha256','engine_profile','schema_sha256','metadata_sha256','metadata_bytes','facet_image_sha256','facet_image_bytes','model_state_sha256','fact_counts'}
    _exact(seal, keys, 'seal'); _require(seal['schema'] == FORMAT, 'artifact format')
    _require(seal['engine_profile'] == _engine_profile(db), 'SQLite or Unicode engine profile mismatch')
    for name in ('database_sha256','manifest_sha256','canonical_revision','schema_sha256','metadata_sha256','facet_image_sha256','model_state_sha256'):
        _require(type(seal[name]) is str and HEX.fullmatch(seal[name]), 'seal hash field')
    for name,limit in [('database_bytes', 2**63-1),('metadata_bytes',MAX_METADATA_BYTES),('facet_image_bytes',cls.MAX_IMAGE_BYTES)]:
        _require(type(seal[name]) is int and 0 <= seal[name] <= limit, 'seal byte field')
    _require(seal['runtime_source_sha256'] == roster and seal['schema_sha256'] == _sha(_json_bytes(_schema(db))), 'source roster or schema mismatch')
    manifest, manifest_identity = _read(manifest_path, MAX_SEAL_BYTES)
    _require(seal['manifest_sha256'] == _sha(manifest), 'manifest mismatch')
    measured('source_schema_and_seal_validation')
    metadata, metadata_identity, image, image_identity, hash_seconds, read_seconds = _read_bootstrap_files(path, artifact_dir, seal)
    # These operation timers overlap; they are not sequential phase totals.
    phases['database_hash'] = hash_seconds
    phases['artifact_read_and_hash'] = read_seconds
    phase_started = time.monotonic()
    _validate_image(image)
    measured('facet_integrity')
    state = _json(metadata, MAX_METADATA_BYTES)
    from . import card_source_context_index
    card_source_context_index.validate_aggregate_json_members(state, metadata)
    measured('bounded_json_decode')
    model = _restore(state, image)
    measured('typed_state_restore')
    decoded_bytes = _deep_size(state) + _deep_size(model.__dict__) + len(metadata) + len(image)
    _require(decoded_bytes <= MAX_DECODED_BYTES, 'decoded-state allocation bound')
    _require(_json_bytes(_counts(model)) == _json_bytes(seal['fact_counts']), 'fact counts mismatch')
    measured('allocation_and_count_validation')
    model._path = path; model._identity = identity
    model._release_alias_path = collector_release_alias.BINDINGS_PATH.resolve(strict=True)
    model._release_alias_identity = runtime.snapshot_identity(model._release_alias_path)
    model._artifact_identities = sources + ((artifact_dir/'seal.json',seal_identity),
        (artifact_dir/'metadata.json',metadata_identity),(artifact_dir/'facet-image.sqlite3',image_identity),(manifest_path,manifest_identity))
    model._artifact_guard = lambda: _request_guard(model)
    model._check_snapshot(db); _guard(model); _no_wal(path)
    _require(runtime.snapshot_identity(path) == identity, 'database changed during load')
    runtime.checkpoint()
    measured('final_identity_guards')
    if bootstrap_timings is not None:
        bootstrap_timings.update(phases)
    return model, seal['canonical_revision'], dict(seal, seal_sha256=_sha(seal_raw),
        decoded_state_bytes=decoded_bytes)


def load(db, artifact_dir, manifest_path, *, expected_seal_sha256, bootstrap_timings=None):
    """Custom paths require a separately trusted original seal digest."""
    _require(type(expected_seal_sha256) is str and HEX.fullmatch(expected_seal_sha256), 'external seal pin required')
    return _load(db, artifact_dir, manifest_path, expected_seal_sha256, bootstrap_timings)


def load_packaged(db, required=False, *, bootstrap_timings=None):
    """Private image bootstrap: literal packaged paths, never HTTP selections."""
    _require(type(required) is bool, 'required flag type')
    if not _PACKAGED_DIR.exists() and not _PACKAGED_DIR.is_symlink():
        if required: raise ArtifactInvalid('required packaged read model is absent')
        return None
    return _load(db, _PACKAGED_DIR, _PACKAGED_MANIFEST, None, bootstrap_timings)


def main():
    import argparse
    from . import core
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with closing(core.connect(args.db, readonly=True)) as db:
        receipt = write(db, args.manifest, args.output)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
