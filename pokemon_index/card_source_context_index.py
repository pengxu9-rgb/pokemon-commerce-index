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

SCHEMA = 'pokemon.complete-card-context-index.v1'
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
    return tuple(ids), union


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

    def to_state(self):
        return dict(schema=SCHEMA, enabled=self.enabled,
            known_card_ids=dict(type='str', values=sorted(self.known_card_ids)),
            context_strings=list(self.context_strings),
            assignments=dict(sorted(self.assignments.items())),
            default_string=self.default_string)

    def lookup(self, cid):
        if not self.enabled or type(cid) is not str or cid not in self.known_card_ids:
            return None
        raw = self.context_strings[self.assignments[cid]] if cid in self.assignments else self.default_string
        # Fresh nested containers: response mutation cannot poison later calls.
        return json.loads(raw)

    def counts(self):
        return dict(source_context_cards=len(self.known_card_ids),
            source_context_templates=len(self.context_strings),
            source_context_assignments=len(self.assignments))


def disabled_index():
    return ContextIndex(frozenset(), (), MappingProxyType({}), None, False)


def restore_index(state):
    """Validate the whole compact codec or reject; no partial/guessed template."""
    fields = {'schema', 'enabled', 'known_card_ids', 'context_strings', 'assignments', 'default_string'}
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
    if not state['enabled']:
        _require(not values and not strings and not assignments and default is None,
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
    return ContextIndex(known, tuple(strings), MappingProxyType(dict(assignments)), default, True)


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
        ids, union = dependency_population(db)
        strings = []; interned = {}; assignments = {}; byte_count = len(DEFAULT_ABSENT_JSON.encode('utf-8'))
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
        outside = next((cid for cid in ids if cid not in union), None)
        if outside is not None:
            # Branch regression sanity check supplements the exhaustive dependency
            # proof; it is not presented as sampled evidence for all absent IDs.
            _require(_context_json(helper(db, outside)) == DEFAULT_ABSENT_JSON,
                     'native absence branch contract changed')
        # The native loop already guarantees exact IDs, first-use dedup/index
        # ordering, fields and bounds. Strict untrusted restore stays separate.
        return ContextIndex(frozenset(ids), tuple(strings),
                            MappingProxyType(dict(assignments)), DEFAULT_ABSENT_JSON, True)
    except ContextIndexUnsupported:
        return disabled_index()


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
