"""Read-only comparison of two scoped catalog coordinates or exact record IDs.

Reviewed stock-image edges cover only their recorded endpoints. Sibling variants,
counterparts, physical copies and price units never inherit that approval.
"""
from __future__ import annotations

import json
import re
import unicodedata
from . import core, discovery_graph, number_graph, number_evidence,source_image_facts

SCHEMA = 'pokemon.card-comparison.v1'
MAX_CANDIDATES = 32
FIELDS = ('card_id', 'language', 'set_code', 'collector_number', 'variant', 'name',
          'provenance', 'match_eligible')


def _norm(text):
    return unicodedata.normalize('NFKC', text).casefold()


def _descriptor(value, *, partial=False):
    from .collector_discovery import validate_scope
    if not isinstance(value, dict):
        raise ValueError('comparison endpoint must be an object')
    if set(value) == {'card_id'}:
        if not isinstance(value['card_id'], str) or not 1 <= len(value['card_id']) <= 160:
            raise ValueError('invalid comparison card_id')
        return dict(value)
    result = validate_scope(value)
    required = {'language', 'collector_number'} if partial else {'language', 'set_code', 'collector_number'}
    if not required <= set(result):
            raise ValueError('comparison needs language, release and catalog number on each side')
    return result


def _side(db, descriptor):
    where = ' AND '.join(k+'=?' for k in descriptor)
    args = list(descriptor.values())
    count = db.execute('SELECT count(*) FROM card WHERE '+where, args).fetchone()[0]
    rows = [dict(r) for r in db.execute('SELECT '+','.join(FIELDS)+' FROM card WHERE '+where+
                                      ' ORDER BY card_id LIMIT ?', args+[MAX_CANDIDATES])]
    coordinates = {(r['language'], r['set_code'], r['collector_number']) for r in rows}
    status = ('not_found' if not count else 'refinement_needed' if count > MAX_CANDIDATES else
              'release_confirmation_needed' if 'set_code' not in descriptor and 'card_id' not in descriptor else
              'exact_record' if 'card_id' in descriptor or 'variant' in descriptor else 'coordinate_variants')
    context = None
    if len(coordinates) == 1 and count <= MAX_CANDIDATES:
        language, release, number = next(iter(coordinates))
        # Derive from current raw coordinates, not a possibly stale materialized number table.
        context = dict(number_graph.parse_number(number), printed_number=number, catalog_number=number,
                       number_basis='catalog_coordinate_only',
                       printed_number_semantics='legacy_catalog_coordinate_not_visual_evidence',
                       number_scope_id=language+':'+release, language=language, set_code=release)
    observed = [dict(card_id=r['card_id'], evidence=evidence) for r in rows
                if (evidence := number_evidence.context(db, r['card_id'])) is not None]
    facts = [dict(card_id=r['card_id'], evidence=evidence) for r in rows
             if (evidence := source_image_facts.context(db,r['card_id'])) is not None]
    return dict(requested=descriptor, status=status, matched_records=count, records=rows,
                records_truncated=count > MAX_CANDIDATES, number_context=context,
                observed_printed_numbers=observed,
                source_image_facts=facts,
                physical_variant_verified=False)


def _edges(db, left, right):
    if left['records_truncated'] or right['records_truncated']:
        return []
    a = [r['card_id'] for r in left['records']]
    b = [r['card_id'] for r in right['records']]
    if not a or not b:
        return []
    marks = lambda ids: ','.join('?' for _ in ids)
    # Newest event per exact endpoint pair/type wins, including rejection.
    query = '''SELECT e.* FROM card_relationship_assertion e WHERE
      ((e.left_card_id IN (A) AND e.right_card_id IN (B)) OR
       (e.right_card_id IN (A) AND e.left_card_id IN (B))) AND
      NOT EXISTS (SELECT 1 FROM card_relationship_assertion newer WHERE
        newer.left_card_id=e.left_card_id AND newer.right_card_id=e.right_card_id AND
        newer.relation_type=e.relation_type AND newer.rowid>e.rowid) ORDER BY e.assertion_id'''
    query = query.replace('(A)', '('+marks(a)+')').replace('(B)', '('+marks(b)+')')
    rows = []
    for row in db.execute(query, a+b+a+b):
        edge = dict(row)
        edge['endpoint_identity_blockers'] = discovery_graph.relationship_identity_blockers(db, edge)
        edge['evidence'] = json.loads(edge.pop('evidence_ref'))
        edge['usable_artwork_evidence'] = (edge['relation_type'] == 'same_artwork' and
            edge['review_status'] == 'verified' and not edge['endpoint_identity_blockers'])
        edge['usable_artwork_difference_evidence'] = discovery_graph.reviewed_artwork_difference_usable(db,row)
        edge['price_comparable'] = False
        rows.append(edge)
    return rows


def _compare(db, left_descriptor, right_descriptor):
    if left_descriptor == right_descriptor:
        raise ValueError('choose two distinct card scopes')
    left, right = _side(db, left_descriptor), _side(db, right_descriptor)
    if left['matched_records'] == right['matched_records'] == 1 and (
            left['records'][0]['card_id'] == right['records'][0]['card_id']):
        raise ValueError('choose two distinct cards')
    links = _edges(db, left, right)
    reviewed = [e for e in links if e['usable_artwork_evidence']]
    different = [e for e in links if e['usable_artwork_difference_evidence']]
    unresolved = [name for name, side in [('left', left), ('right', right)]
                  if side['status'] in {'not_found', 'refinement_needed', 'release_confirmation_needed'}]
    numbers = None
    if left['number_context'] and right['number_context'] and not unresolved:
        numbers = dict(number_graph.number_alignment(left['number_context'], right['number_context']),
            left=left['number_context'], right=right['number_context'],
            explanation='This alignment compares catalog coordinates in language/release namespaces. Actual visible stock-image readings are separate exact-record evidence. Equal or different catalog numbers establish neither matching artwork nor regional printing equivalence.',
            print_run_explanation='A catalog denominator can be a source inventory convention; it is not verified printed text or a quantity of printed copies. These coordinates establish neither scarcity nor a price trend.',
            print_run_quantity_established=False, scarcity_established=False,
            explanation_of_release_number_assignment_established=False)
    covered = {cid for e in reviewed+different for cid in (e['left_card_id'], e['right_card_id'])}
    candidate_ids = {r['card_id'] for side in (left, right) for r in side['records']}
    source_warnings=[dict(card_id=f['card_id'],warnings=f['evidence']['warnings'])
        for side in (left,right) for f in side['source_image_facts'] if f['evidence']['warnings']]
    return dict(schema=SCHEMA, status='scope_confirmation_needed' if unresolved else 'catalog_partial',
        left=left, right=right, unresolved_sides=unresolved, numbering=numbers,
        artwork=dict(status='reviewed_endpoint_sources_only' if reviewed else
            'reviewed_endpoint_differences_only' if different else 'unestablished',
            reviewed_links=reviewed, reviewed_difference_links=different,
            other_pair_states=[e for e in links if not e['usable_artwork_evidence'] and not e['usable_artwork_difference_evidence']],
            uncovered_record_ids=sorted(candidate_ids-covered),
            scope='Only the exact reviewed stock-image endpoints; no approval transfers to sibling source labels or physical copies.',
            difference_scope='A reviewed difference rules out same artwork only for its exact source endpoints; an absent/rejected link alone is not difference evidence.',
            all_coordinate_variants_verified=False),
        source_metadata_warnings=source_warnings,
        required_evidence=(['source_image_metadata_resolution'] if source_warnings else [])+
            ['physical_finish_edition_and_copy_condition', 'authorized_fresh_offers'],
        next_question='Confirm the release on '+', '.join(unresolved)+' before choosing an exact catalog version.' if unresolved else
            'Choose exact catalog versions and supply physical-copy evidence before offer comparison.',
        same_physical_printing_established=False, physical_finish_verified=False,
        copy_condition_verified=False, price_comparable=False, price_series_merge_allowed=False,
        numeric_price_gap_available=False, prices=[], live_offers=[], product_url=None,
        automatic_offer_join_allowed=False, purchase_ready=False, public_display_allowed=False,
        complete_answer_established=False)


def compare(db, payload):
    if not isinstance(payload, dict) or set(payload) != {'left', 'right'}:
        raise ValueError('comparison request must contain only left and right')
    return _compare(db, _descriptor(payload['left']), _descriptor(payload['right']))


def from_question(db, question):
    """Conservative two-fraction interpreter; absent release stays unconfirmed.

    Does not select a counterpart from an artwork edge. Explicit canonical IDs
    bypass parsing. No LLM, network, hidden caller evidence or price inference.
    """
    text = _norm(question)
    if not re.search(r'compar|same|different|artwork|picture|both|cheaper|イラスト|番号|比較|比较|対比|对比|比对|同じ|同一|相同', text):
        return None
    ids = re.findall(r'\b(?:ja|en):[a-z0-9.\-]+:[a-z0-9]{1,16}/[a-z0-9\-]{1,32}:[a-z0-9_\-]+', text)
    if ids:
        if len(ids) != 2 or len(re.findall(r'(?<![a-z0-9/])[a-z0-9]{1,16}/[a-z0-9\-]{1,32}(?![a-z0-9/])', text)) != 2:
            return None
        lookup = {r['card_id'].casefold(): r['card_id'] for r in db.execute(
            'SELECT card_id FROM card WHERE lower(card_id) IN (?,?)', ids)}
        result = compare(db, dict(left=dict(card_id=lookup.get(ids[0], ids[0])),
                                  right=dict(card_id=lookup.get(ids[1], ids[1]))))
    else:
        fractions = list(re.finditer(r'(?<![a-z0-9/])\d{1,3}/(?:\d{1,3}|[a-z][a-z0-9\-]{0,31})(?![a-z0-9/])', text))
        if len(fractions) != 2:
            return None
        releases = list(db.execute('SELECT language,set_code,name FROM catalog_set_localized'))
        descriptors = []
        start = 0
        for match in fractions:
            segment = text[start:match.start()]
            start = match.end()
            languages = list(re.finditer(r'japanese|english|日本語|英語|日文|英文|日版|英版|\bjp\b|\ben\b', segment))
            if not languages:
                return None
            language = 'ja' if languages[-1].group() in {'japanese','日本語','日文','日版','jp'} else 'en'
            # Only inspect text after that side's language mention. This avoids
            # borrowing the first release for the second card.
            release_text = segment[languages[-1].end():]
            found = set()
            for row in releases:
                if row['language'] != language:
                    continue
                for term in [row['set_code'], row['name']]:
                    boundary='a-z0-9.-' if term==row['set_code'] else 'a-z0-9'
                    if term and re.search(r'(?<!['+boundary+r'])'+re.escape(_norm(term))+r'(?!['+boundary+r'])', release_text):
                        found.add(row['set_code'])
            # An explicit unsupported code is preserved, never replaced with
            # another release inferred from the number or a graph neighbor.
            code_tokens = re.findall(r'\b(?:(?:sv|sm|swsh|xy|bw|me)\d|s\d|m\d)[a-z0-9.\-]*\b', release_text)
            if code_tokens:
                found.update(token.upper() for token in code_tokens)
            if len(found) > 1:
                return None
            descriptor = dict(language=language, collector_number=match.group())
            if found:
                descriptor['set_code'] = next(iter(found))
            descriptors.append(_descriptor(descriptor, partial=True))
        result = _compare(db, *descriptors)
    result['interpretation'] = 'Explicit IDs or nearest preceding language/release/number tokens only; named character, illustrator, grade and finish assertions are not independently resolved.'
    result['question'] = question
    result['unfulfilled_constraints'] = ['named_identity_and_physical_version_claims', 'physical_copy_evidence', 'live_market_evidence']
    return result
