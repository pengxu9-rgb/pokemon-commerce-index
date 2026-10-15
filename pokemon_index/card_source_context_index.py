"""Complete native source contexts for a guarded immutable catalog snapshot.

Raw card fields and current source rarity remain outside this index. Native
contexts cover all historical card/release/coordinate dependencies; known IDs
outside that complete union retain the existing missing-evidence result. Unknown
or differently typed IDs use native resolution. No query, ranking or session is
retained, and a source context grants no image, physical or trading permission.

The caller must freshly validate its snapshot before every hit and fallback.
Changes to the native helper's source dependencies require review of this union
and complete native parity; sampled absence cannot justify a new default.
"""
from __future__ import annotations

import json
import math
from types import MappingProxyType
from . import collector_runtime as runtime
from . import collector_discovery as discovery
from . import catalog_read_model_artifact as artifact

SCHEMA = 'pokemon.complete-card-context-index.v2'
STATE_KEY = 'card_source_context_index'
MAX_CARD_IDS = 100000
MAX_HISTORY_ROWS = 100000
MAX_CID_BYTES = 8 * 1024 * 1024
REQUIRED_KEYS = frozenset({'support_status', 'media_availability'})
CONTEXT_KEYS = REQUIRED_KEYS | frozenset({'collector_evidence', 'official_metadata',
    'source_corrections', 'official_coordinate_family', 'printing_source_evidence',
    'printed_artist_credit', 'variant_dimension_hold'})
BASIC_ROW_KEYS_NOT_CACHED = frozenset({'card_id', 'language', 'set_code',
    'collector_number', 'variant', 'name', 'rarity', 'provenance', 'set_name',
    'release_date', 'release_provenance', 'structural_match_eligible', 'source_rarity'})
DIRECT_DEPENDENCIES = ('supported_card', 'card_metadata_evidence',
    'source_image_fact_evidence', 'card_number_reading_evidence')
SUBJECT_DEPENDENCIES = ('catalog_collector_evidence', 'printing_source_evidence')
DEFAULT_ABSENT = {
    'support_status': 'research_candidate',
    'media_availability': {
        'schema': 'pokemon.catalog-media-availability.v1',
        'status': 'missing_source_scan_evidence', 'evidence_basis': None,
        'reason': 'no exact imported source scan evidence',
        'with_source_scans_eligible': False, 'source_scan_event_id': None,
        'warnings': [], 'inspection_tier': None, 'current_endpoint': False,
        'source_ref': None, 'image_sha256': None, 'live_fetch_verified': False,
        'display_allowed': False, 'physical_printing_verified': False,
    },
}
DEFAULT_ABSENT_JSON = artifact._json_bytes(DEFAULT_ABSENT).decode('utf-8')


class ContextIndexUnsupported(artifact.ArtifactInvalid):
    """Disable the WHOLE index and retain native behavior; never partial reuse."""


def _require(condition, reason):
    if not condition:
        raise artifact.ArtifactInvalid(reason)


def _unsupported(condition, reason):
    if not condition:
        raise ContextIndexUnsupported(reason)


def _utf8(value):
    try:
        return value.encode('utf-8')
    except UnicodeError as exc:
        raise artifact.ArtifactInvalid('context UTF-8') from exc


def _rows(db, sql):
    for count, row in enumerate(db.execute(sql), 1):
        runtime.checkpoint()
        _unsupported(count <= MAX_HISTORY_ROWS, 'context history row bound')
        yield row


def _validate_context_object(context):
    _require(type(context) is dict and REQUIRED_KEYS <= set(context) <= CONTEXT_KEYS,
             'native context fields changed; dependency contract needs review')
    _require(not set(context) & BASIC_ROW_KEYS_NOT_CACHED, 'basic card values in context')
    _require(type(context['support_status']) is str and context['support_status'] in {'research_candidate',
             'supported_for_internal_review', 'stale_support_evidence'},
             'native context support status')
    media = context['media_availability']
    _require(type(media) is dict and set(media) == set(DEFAULT_ABSENT['media_availability']) and
             media['schema'] == 'pokemon.catalog-media-availability.v1' and
             type(media['status']) is str and media['status'] in {'identity_hold', 'missing_source_scan_evidence',
                 'stale_source_scan_evidence', 'held_source_scan_evidence', 'current_source_scan_evidence'} and
             type(media['with_source_scans_eligible']) is bool and type(media['current_endpoint']) is bool and
             type(media['warnings']) is list and all(type(value) is str for value in media['warnings']) and
             type(media['reason']) is str and
             context['media_availability'].get('live_fetch_verified') is False and
             context['media_availability'].get('display_allowed') is False and
             context['media_availability'].get('physical_printing_verified') is False,
             'native context cannot widen media permissions')
    _require(media['with_source_scans_eligible'] == (media['status'] == 'current_source_scan_evidence')
             and all(value is None or type(value) is str for value in
                 (media['evidence_basis'], media['source_scan_event_id'], media['inspection_tier'],
                  media['source_ref'], media['image_sha256'])), 'native media context types or status')
    _require(all(type(value) is dict for key, value in context.items()
                 if key not in REQUIRED_KEYS), 'optional native context shape')
    _validate_native_json(context)


def _validate_native_json(value):
    """No JSON coercion of tuples, bytes, subclasses or non-string dict keys."""
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        kind = type(current)
        if kind is dict:
            _require(depth < artifact.MAX_JSON_DEPTH, 'native context JSON depth')
            _unsupported(all(type(key) is str for key in current), 'non-string native JSON key')
            for key, item in current.items():
                _require(key not in AUTHORITY_FALSE_KEYS or item is False,
                         'context authority must remain false')
                pending.append((item, depth + 1))
        elif kind is list:
            _require(depth < artifact.MAX_JSON_DEPTH, 'native context JSON depth')
            pending.extend((item, depth + 1) for item in current)
        elif kind is float:
            _require(math.isfinite(current), 'nonfinite native context JSON')
        elif current is None or kind in (str, bool, int):
            continue
        else:
            raise ContextIndexUnsupported('unsupported native JSON container/scalar')


def _context_json(context):
    _validate_context_object(context)
    try:
        raw = artifact._json_bytes(context)
    except UnicodeError as exc:
        raise artifact.ArtifactInvalid('native context UTF-8') from exc
    _unsupported(len(raw) <= MAX_CONTEXT_BYTES, 'native context byte bound')
    _unsupported(_member_count(raw) <= artifact.MAX_JSON_MEMBERS, 'native context member bound')
    return raw.decode('utf-8')


def _history_json(value):
    _require(type(value) is str, 'non-TEXT context history')
    result = artifact._json(value.encode('utf-8'), artifact.MAX_METADATA_BYTES)
    _require(type(result) is dict, 'context history object')
    return result


def _typed_id(value):
    # EXACT type, no str()/normalization or bool/int/Python-equality coercion.
    _unsupported(type(value) is str, 'non-TEXT context ID')
    return ['s', value]


def dependency_population(db):
    """Conservative historical union; membership is never inferred from names."""
    ids,union,_,_ = _dependency_population(db)
    return ids,union


def _dependency_population(db, *, include_advisories=False):
    needed = {'card', *DIRECT_DEPENDENCIES, *SUBJECT_DEPENDENCIES,
              'coordinate_family_evidence', 'source_correction_evidence',
              'catalog_identity_quarantine'}
    present = {row[0] for row in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    _unsupported(needed <= present, 'partial context dependency tables')
    ids = []; release = {}; coordinate = {}; cid_bytes = 0
    for row in _rows(db, 'SELECT card_id,typeof(card_id),language,set_code,collector_number FROM main.card ORDER BY card_id'):
        cid, storage, language, code, number = row
        _unsupported(storage == 'text' and type(cid) is str, 'non-TEXT card ID storage')
        _unsupported(all(type(value) is str for value in (language, code, number)),
                 'unsupported release/coordinate key')
        ids.append(cid); cid_bytes += len(_utf8(cid))
        _unsupported(len(ids) <= MAX_CARD_IDS and cid_bytes <= MAX_CID_BYTES, 'card universe bound')
        release.setdefault(language + ':' + code, set()).add(cid)
        coordinate.setdefault(language + ':' + code + ':' + number, set()).add(cid)
    _require(len(ids) == len(set(ids)), 'duplicate exact card ID')
    known = frozenset(ids); populations = {}
    for table in DIRECT_DEPENDENCIES:
        populations[table] = {_typed_id(row[0])[1] for row in _rows(db,
            'SELECT DISTINCT card_id FROM main.' + table)}
    for table in SUBJECT_DEPENDENCIES:
        found = set()
        for kind, subject in _rows(db, 'SELECT DISTINCT subject_kind,subject_id FROM main.' + table):
            _typed_id(subject)
            if kind == 'card': found.add(subject)
            elif kind == 'release': found.update(release.get(subject, ()))
            elif kind == 'coordinate': found.update(coordinate.get(subject, ()))
            else: raise ContextIndexUnsupported('unknown context subject kind')
        populations[table] = found
    found = set()
    for language, code, number in _rows(db,
            'SELECT DISTINCT language,set_code,collector_number FROM main.coordinate_family_evidence'):
        _unsupported(all(type(value) is str for value in (language, code, number)),
                 'non-TEXT family coordinate')
        found.update(coordinate.get(':'.join((language, code, number)), ()))
    populations['coordinate_family_evidence'] = found
    found = set()
    for row in _rows(db, 'SELECT record_json FROM main.source_correction_evidence'):
        record = _history_json(row[0]); snapshot = record.get('snapshot')
        _require(type(snapshot) is dict and type(snapshot.get('cards')) is list,
                 'correction dependency snapshot')
        for card in snapshot['cards']:
            runtime.checkpoint()
            _require(type(card) is dict and 'card_id' in card, 'correction dependency card')
            found.add(_typed_id(card['card_id'])[1])
        new = record.get('new_card')
        if new is not None:
            _require(type(new) is dict and 'card_id' in new, 'correction new-card dependency')
            found.add(_typed_id(new['card_id'])[1])
    populations['source_correction_evidence'] = found
    found = set()
    for row in _rows(db, "SELECT record_json FROM main.catalog_identity_quarantine WHERE quarantine_id GLOB 'variant-dimension-hold:*'"):
        record = _history_json(row[0])
        if record.get('schema') != 'pokemon.variant-dimension-hold.v1': continue
        identity = record.get('identity')
        _require(type(identity) is dict and 'card_id' in identity, 'hold dependency identity')
        found.add(_typed_id(identity['card_id'])[1])
    populations['variant_dimension_hold'] = found
    union = frozenset().union(*populations.values()) & known
    result=(tuple(ids), union, frozenset(populations['source_correction_evidence']), frozenset(found))
    if not include_advisories:return result
    # Native readers select image/number by the TABLE card_id, not the JSON
    # endpoint identity. Family contexts select all variants at the exact
    # historical coordinate; correction fallback may name any historical new
    # card. These complete populations prove only historical advisory absence.
    advisory=(populations['source_image_fact_evidence'] | populations['card_number_reading_evidence'] |
              populations['coordinate_family_evidence'] | populations['source_correction_evidence']) & known
    _unsupported(advisory <= union and len(advisory) <= MAX_CARD_IDS and
                 sum(len(_utf8(cid)) for cid in advisory) <= MAX_CID_BYTES,
                 'identity advisory dependency bound')
    return (*result,frozenset(advisory))


from typing import NamedTuple

MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_TEMPLATES = 10000
AUTHORITY_FALSE_KEYS = frozenset({'price_comparable', 'automatic_offer_join_allowed',
    'physical_finish_verified', 'physical_printing_verified', 'physical_copy_verified',
    'copy_condition_verified', 'card_pair_relationship_verified', 'display_allowed',
    'public_display_allowed', 'image_display_allowed', 'purchase_allowed',
    'live_fetch_verified', 'purchase_ready', 'ready_for_offer_tracking'})


def _validate_context_string(value):
    _require(type(value) is str, 'context string type')
    raw = _utf8(value)
    decoded = artifact._json(raw, MAX_CONTEXT_BYTES)
    _validate_context_object(decoded)
    _require(artifact._json_bytes(decoded).decode('utf-8') == value, 'noncanonical context JSON')
    return decoded


class ContextIndex(NamedTuple):
    """Immutable contents are tuples/frozensets/proxies, with no external backing.

    NamedTuple keeps every retained value visible to existing deep-size accounting.
    Runtime must validate the active trusted snapshot before calling lookup, even
    for an unknown ID or disabled index; this class alone is not a trust gate.
    """
    known_card_ids: frozenset
    context_strings: tuple
    assignments: MappingProxyType
    default_string: str | None
    enabled: bool
    identity_flags: MappingProxyType | None

    def to_state(self):
        return dict(schema=SCHEMA, enabled=self.enabled,
            known_card_ids=dict(type='str', values=sorted(self.known_card_ids)),
            context_strings=list(self.context_strings),
            assignments=dict(sorted(self.assignments.items())),
            default_string=self.default_string,
            identity_flags=(None if self.identity_flags is None else
                {cid:list(flags) for cid,flags in sorted(self.identity_flags.items())}))

    def lookup(self, cid):
        if not self.enabled or type(cid) is not str or cid not in self.known_card_ids:
            return None
        raw = self.context_strings[self.assignments[cid]] if cid in self.assignments else self.default_string
        # Fresh nested containers: response mutation cannot poison later calls.
        return json.loads(raw)

    def lookup_identity_flags(self,cid):
        if (not self.enabled or self.identity_flags is None or
                type(cid) is not str or cid not in self.known_card_ids):
            return None
        return self.identity_flags.get(cid,EMPTY_IDENTITY_FLAGS)

    def counts(self):
        return dict(source_context_cards=len(self.known_card_ids),
            source_context_templates=len(self.context_strings),
            source_context_assignments=len(self.assignments),
            identity_advisory_flag_subjects=(0 if self.identity_flags is None else len(self.identity_flags)),
            identity_advisory_available=self.identity_flags is not None)


def disabled_index():
    return ContextIndex(frozenset(), (), MappingProxyType({}), None, False, None)


def restore_index(state):
    """Validate the whole compact codec or reject; no partial/guessed template."""
    fields = {'schema', 'enabled', 'known_card_ids', 'context_strings', 'assignments', 'default_string','identity_flags'}
    _require(type(state) is dict and set(state) == fields and state['schema'] == SCHEMA,
             'context index schema')
    _require(type(state['enabled']) is bool, 'context index enabled type')
    ids = state['known_card_ids']
    _require(type(ids) is dict and set(ids) == {'type', 'values'} and ids['type'] == 'str'
             and type(ids['values']) is list, 'typed context universe')
    values = ids['values']
    _require(len(values) <= MAX_CARD_IDS and all(type(cid) is str for cid in values),
             'context universe type/count')
    _require(values == sorted(set(values)), 'context universe duplicate/order')
    _require(sum(len(_utf8(cid)) for cid in values) <= MAX_CID_BYTES,
             'context universe byte bound')
    strings = state['context_strings']; assignments = state['assignments']; default = state['default_string']
    _require(type(strings) is list and len(strings) <= MAX_TEMPLATES and
             all(type(value) is str for value in strings), 'context template type/count')
    _require(type(assignments) is dict and len(assignments) <= len(values), 'context assignment shape')
    known = frozenset(values)
    _require(all(type(cid) is str and cid in known and type(index) is int and
                 0 <= index < len(strings) for cid, index in assignments.items()),
             'context assignment key/type/range')
    flags=_restore_identity_flags(state['identity_flags'],known,assignments)
    if not state['enabled']:
        _require(not values and not strings and not assignments and flags is None and default is None,
                 'disabled index cannot retain partial facts')
        return disabled_index()
    _require(type(default) is str and default == DEFAULT_ABSENT_JSON,
             'default absence context changed')
    _require(sum(len(_utf8(value)) for value in strings) + len(_utf8(default))
             <= MAX_CONTEXT_BYTES, 'aggregate context string byte bound')
    _require(len(strings) == len(set(strings)), 'duplicate context template')
    _require(set(assignments.values()) == set(range(len(strings))), 'unused or missing context template')
    # Native compile visits sorted CIDs: first-use indexes must be deterministic.
    first_use = list(dict.fromkeys(assignments[cid] for cid in sorted(assignments)))
    _require(first_use == list(range(len(strings))), 'noncanonical template assignment order')
    for value in strings:
        runtime.checkpoint(); _validate_context_string(value)
    _validate_context_string(default)
    return ContextIndex(known, tuple(strings), MappingProxyType(dict(assignments)), default, True, flags)


def compile_index(db):
    """Native fixed helper only, all historical dependencies or entirely disabled.

    The complete union proves absence without65k expensive context queries. The
    native helper is fixed code owned by discovery, never a user callback. An
    unexpected helper field/dependency, non-TEXT key, or codec bound disables all
    acceleration. The caller's existing deadline/checkpoints remain unchanged.
    """
    try:
        _unsupported(runtime._snapshot_scope.get() is None and runtime._catalog_scope.get() is None
                 and not db.in_transaction, 'context compile needs unscoped committed native DB')
        helper = getattr(discovery, '_card_context', None)
        _unsupported(callable(helper), 'native card context helper not integrated')
        ids,union,_,_,advisory_ids = _dependency_population(db,include_advisories=True)
        strings = []; interned = {}; assignments = {}; flags = {}; byte_count = len(DEFAULT_ABSENT_JSON.encode('utf-8'))
        for cid in ids:
            runtime.checkpoint()
            if cid not in union: continue
            raw = _context_json(helper(db, cid))
            if raw not in interned:
                _unsupported(len(strings) < MAX_TEMPLATES, 'context template bound')
                byte_count += len(_utf8(raw))
                _unsupported(byte_count <= MAX_CONTEXT_BYTES, 'context string byte bound')
                interned[raw] = len(strings); strings.append(raw)
            assignments[cid] = interned[raw]
            if flags is not None and cid in advisory_ids:
                advisory=_native_identity_flags(db,cid)
                if advisory is None:
                    # A valid native primary makes corrupt secondary number data
                    # invisible to the original constructor. Defer the unchanged
                    # native endpoint error; never publish guessed empty bits.
                    _check_constructor_guard(db)
                    flags.clear();flags=None
                elif advisory!=EMPTY_IDENTITY_FLAGS:flags[cid]=advisory
        outside = next((cid for cid in ids if cid not in union), None)
        if outside is not None:
            # Branch regression sanity check supplements the exhaustive dependency
            # proof; it is not presented as sampled evidence for all absent IDs.
            _require(_context_json(helper(db, outside)) == DEFAULT_ABSENT_JSON,
                     'native absence branch contract changed')
        # The native loop already guarantees exact IDs, first-use dedup/index
        # ordering, fields and bounds. Strict untrusted restore stays separate.
        return ContextIndex(frozenset(ids), tuple(strings),
                            MappingProxyType(dict(assignments)), DEFAULT_ABSENT_JSON, True, None if flags is None else MappingProxyType(dict(flags)))
    except ContextIndexUnsupported:
        return disabled_index()


def _constructor_stamp(db):
    """Same opened database and source policies across the whole transient phase."""
    _unsupported(runtime._snapshot_scope.get() is None and runtime._catalog_scope.get() is None
        and not db.in_transaction, 'constructor source facts need an unscoped committed DB')
    _unsupported(db.execute('PRAGMA query_only').fetchone()[0] == 1,
                 'constructor source facts need query-only mode')
    try:
        path,identity=runtime.CatalogReadModel._validate_database(db)
    except runtime.CatalogReadModelUnsupported:
        raise ContextIndexUnsupported('unsupported constructor schema') from None
    _unsupported(identity[1] is None, 'constructor source facts do not reuse a WAL')
    version=runtime._static_snapshot_version(db)
    _unsupported(version is not None, 'constructor source namespace changed')
    return (id(db),str(path),identity,version,artifact._source_identities())


def _check_constructor_guard(db):
    active=runtime._constructor_scope.get()
    if active is not None:
        if active[0] is not db:raise runtime.CatalogSnapshotChanged()
        db._catalog_check_clone_guard(active[1])
        _assert_constructor_stamp(db,active[2])


def _assert_constructor_stamp(db,before):
    try:
        current=_constructor_stamp(db)
    except (ContextIndexUnsupported,OSError):
        # Initial unsupported inputs can fall back. An unsupported namespace
        # AFTER reuse began must never publish native membership as a fallback.
        raise runtime.CatalogSnapshotChanged() from None
    if current != before:raise runtime.CatalogSnapshotChanged()


def compile_constructor_facts(db):
    """Fixed constructor entry point; transient media/hold facts never escape.

    All historical source subjects and holds are read once with the ordinary
    native validators. Correction absence follows the complete historical
    snapshot/new-card union, including superseded records. Standalone imports
    and compile_index keep their original native validation. No supplied map,
    callback, request/query result or authority is accepted.
    """
    from . import catalog_media,variant_dimension_hold,source_corrections
    media_strings={};hold_strings={};before=None
    try:
        before=_constructor_stamp(db)
        ids,union,correction_ids,hold_ids,advisory_ids=_dependency_population(db,include_advisories=True)
        known=frozenset(ids)
        subjects=catalog_media.subjects(db)
        _unsupported(all(type(cid) is str for cid in subjects), 'non-TEXT media subject')
        complete=subjects | hold_ids
        _unsupported(len(complete) <= MAX_HISTORY_ROWS, 'constructor media subject bound')
        bytes_used=0
        for cid in sorted(hold_ids):
            runtime.checkpoint()
            hold=variant_dimension_hold.context(db,cid)
            _validate_native_json(hold)
            raw=artifact._json_bytes(hold).decode('utf-8')
            hold_strings[cid]=raw;bytes_used+=len(_utf8(raw))
            _unsupported(bytes_used <= artifact.MAX_METADATA_BYTES, 'constructor transient byte bound')
            del hold,raw
        current_ids=set()
        for cid in sorted(complete):
            runtime.checkpoint()
            hold=json.loads(hold_strings[cid]) if cid in hold_strings else None
            basis,evidence=catalog_media.evidence(db,cid)
            media=catalog_media._availability_from_evidence(basis,evidence,hold)
            _validate_native_json(media)
            raw=artifact._json_bytes(media).decode('utf-8')
            media_strings[cid]=raw;bytes_used+=len(_utf8(raw))
            _unsupported(bytes_used <= artifact.MAX_METADATA_BYTES, 'constructor transient byte bound')
            if cid in subjects and media['with_source_scans_eligible']:current_ids.add(cid)
            del basis,evidence,media,hold,raw
        transient=(media_strings,hold_strings,known,ids,union,correction_ids,
                   hold_ids,subjects,complete,current_ids,advisory_ids)
        _unsupported(artifact._deep_size(transient) <= artifact.MAX_METADATA_BYTES,
                     'constructor transient decoded bound')
        _assert_constructor_stamp(db,before)
        strings=[];interned={};assignments={};flags={};byte_count=len(_utf8(DEFAULT_ABSENT_JSON))
        for cid in ids:
            runtime.checkpoint()
            if cid not in union:continue
            correction=source_corrections.context(db,cid) if cid in correction_ids else None
            context=discovery._constructor_card_context(db,cid,correction)
            context['media_availability']=(json.loads(media_strings[cid]) if cid in media_strings
                else json.loads(DEFAULT_ABSENT_JSON)['media_availability'])
            hold=json.loads(hold_strings[cid]) if cid in hold_strings else None
            if hold:context['variant_dimension_hold']=hold
            raw=_context_json(context)
            if raw not in interned:
                _unsupported(len(strings) < MAX_TEMPLATES, 'context template bound')
                byte_count+=len(_utf8(raw))
                _unsupported(byte_count <= MAX_CONTEXT_BYTES, 'context string byte bound')
                interned[raw]=len(strings);strings.append(raw)
            assignments[cid]=interned[raw]
            if flags is not None and cid in advisory_ids:
                advisory=_native_identity_flags(db,cid)
                if advisory is None:
                    # A valid native primary makes corrupt secondary number data
                    # invisible to the original constructor. Defer the unchanged
                    # native endpoint error; never publish guessed empty bits.
                    _check_constructor_guard(db)
                    flags.clear();flags=None
                elif advisory!=EMPTY_IDENTITY_FLAGS:flags[cid]=advisory
        outside=next((cid for cid in ids if cid not in union),None)
        if outside is not None:
            _require(_context_json(discovery._card_context(db,outside)) == DEFAULT_ABSENT_JSON,
                     'native absence branch contract changed')
        # Shared objects are counted once across all live fact sets, native
        # contexts, templates, assignment/interner maps and the CID universe.
        # Nothing from the transient facts remains during model serialization.
        _unsupported(artifact._deep_size((transient,strings,interned,assignments,flags,
            context if assignments else None,correction if assignments else None,
            raw if assignments else None)) <= artifact.MAX_DECODED_BYTES,
            'constructor aggregate decoded bound')
        _assert_constructor_stamp(db,before)
        return (ContextIndex(known,tuple(strings),MappingProxyType(dict(assignments)),
                             DEFAULT_ABSENT_JSON,True,None if flags is None else MappingProxyType(dict(flags))),frozenset(current_ids))
    except ContextIndexUnsupported:
        # No partially compiled index or membership escapes an unsupported case.
        if before is not None:_assert_constructor_stamp(db,before)
        current_ids=frozenset(catalog_media.current_ids(db))
        if before is not None:_assert_constructor_stamp(db,before)
        return disabled_index(),current_ids
    finally:
        media_strings.clear();hold_strings.clear()


def _member_count(raw):
    # Exact same lexical member accounting as the existing artifact decoder.
    stripped = artifact._JSON_STRINGS.sub(b'', raw)
    return len(stripped.translate(None, artifact._NON_JSON_TOKENS))


def validate_aggregate_json_members(state, outer_raw):
    """One unchanged1M cap across outer metadata + ALL UNIQUE nested proof roots.

    Existing affiliation/alias JSON strings are included along with every new
    context template and its default. Outer and inner byte/depth/grammar checks
    remain mandatory in their existing decoder/restore paths.
    """
    _require(type(state) is dict and type(outer_raw) is bytes, 'aggregate metadata type')
    _require(len(outer_raw) <= artifact.MAX_METADATA_BYTES, 'outer metadata byte bound')
    total = _member_count(outer_raw); _require(total <= artifact.MAX_JSON_MEMBERS, 'outer JSON member bound')
    roots = set()
    for key in ('affiliations_json', 'release_aliases_json'):
        _require(type(state.get(key)) is str, 'existing nested proof string')
        roots.add(state[key])
    index = state.get(STATE_KEY)
    _require(type(index) is dict and type(index.get('context_strings')) is list,
             'nested context index shape')
    _require(all(type(value) is str for value in index['context_strings']), 'nested context string type')
    roots.update(index['context_strings'])
    default = index.get('default_string')
    _require(default is None or type(default) is str, 'nested absence string type')
    if default is not None: roots.add(default)
    for value in sorted(roots):
        runtime.checkpoint(); raw = _utf8(value)
        total += _member_count(raw)
        _require(total <= artifact.MAX_JSON_MEMBERS, 'aggregate nested JSON member bound')


EMPTY_IDENTITY_FLAGS=(None,False,False,False,False)
IDENTITY_FAMILY_STATUSES=frozenset({'coordinate_family_evidence_hold','stale_coordinate_family_evidence'})


def _validate_identity_flags(flags):
    _require(type(flags) in (list,tuple) and len(flags)==5,
             'identity advisory flag shape')
    _require((flags[0] is None or type(flags[0]) is str and flags[0] in IDENTITY_FAMILY_STATUSES)
             and all(type(value) is bool for value in flags[1:]),
             'identity advisory flag types/status')
    return tuple(flags)


def _restore_identity_flags(state,known,assignments):
    if state is None:return None
    _require(type(state) is dict and len(state)<=len(assignments),
             'identity advisory sparse shape/count')
    restored={}
    for cid,value in state.items():
        runtime.checkpoint()
        _require(type(cid) is str and cid in known and cid in assignments,
                 'identity advisory key outside complete dependency union')
        _require(type(value) is list,'identity advisory JSON array')
        flags=_validate_identity_flags(value)
        _require(flags!=EMPTY_IDENTITY_FLAGS,'identity advisory empty sparse entry')
        restored[cid]=flags
    return MappingProxyType(restored)


def _native_identity_flags(db,cid):
    """Original native validators over the whole historical context union.

    The fifth bit is only the native historical fallback when the native raw
    shortcut is false. Raw attributes/variant/provenance are freshly evaluated
    again for every request, including known IDs outside the historical union.
    This function accepts no caller-supplied row, callback or cached context.
    """
    from . import coordinate_family,number_evidence,source_image_facts,source_corrections
    raw=db.execute('SELECT variant,provenance,attributes_json FROM card WHERE card_id=?',(cid,)).fetchone()
    _require(raw is not None,'identity advisory native endpoint missing')
    _unsupported(type(raw['variant']) is str and type(raw['provenance']) is str,
        'unsupported native raw family fields')
    family=coordinate_family.context(db,cid)
    try:
        reading=number_evidence.context(db,cid)
    except ValueError:
        from . import catalog_media
        # Only this independent secondary validator is optional after a native
        # primary has already validated. With no valid primary, evidence() runs
        # its original secondary validator and preserves that constructor error.
        basis,evidence=catalog_media.evidence(db,cid)
        if basis != 'source_image_facts' or evidence is None:raise
        _check_constructor_guard(db)
        return None
    facts=source_image_facts.context(db,cid)  # includes source_mechanic validation
    family_scope=source_corrections.family_scope_only(db,cid)
    raw_family=_raw_family_scope_only(raw)
    if family is not None:
        _unsupported(type(family) is dict and type(family.get('status')) is str
            and family['status'] in IDENTITY_FAMILY_STATUSES|{'official_coordinate_family_supported'},
            'unsupported native family advisory')
    if reading is not None:
        _unsupported(type(reading) is dict and type(reading.get('source_coordinate_conflict')) is bool
            and type(reading.get('current_endpoint')) is bool and type(reading.get('status')) is str,
            'unsupported native number advisory')
    if facts is not None:
        _unsupported(type(facts) is dict and type(facts.get('warnings')) is list
            and all(type(value) is str for value in facts['warnings']),
            'unsupported native image advisory')
    _unsupported(type(family_scope) is bool and type(raw_family) is bool,'unsupported native family shortcut')
    flags=(family['status'] if family and family['status'] in IDENTITY_FAMILY_STATUSES else None,
        bool(reading and reading['source_coordinate_conflict']),
        bool(reading and (not reading['current_endpoint'] or reading['status']=='reading_hold')),
        bool(facts and facts['warnings']),family_scope and not raw_family)
    return _validate_identity_flags(flags)


def _raw_family_scope_only(card):
    """Exact original native raw short circuit; never read historical evidence.

    This predicate is evaluated again on the fresh SQL row for every request.
    Its JSON exceptions, short-circuit order and .startswith errors mirror the
    unchanged source_corrections.family_scope_only reader.
    """
    try:flag=json.loads(card['attributes_json']).get('family_scope_only') is True
    except (ValueError,TypeError,AttributeError):flag=False
    return (flag or card['variant'].startswith('official_coordinate_family_only_')
            or card['provenance'].startswith('official-printed-coordinate:'))
