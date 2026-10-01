"""Stateless comparison of a user-asserted inventory to scoped catalog records.

Coordinates without a declared version remain unresolved. Neither ownership nor
physical printing completeness is verified by this comparison.
"""
from __future__ import annotations
from collections import defaultdict
from . import core,collector_discovery

MAX_ITEMS=1000
MAX_SCOPE=10000
SCOPED_TASKS={'artist_cards','character_cards','family_checklist','set_cards','exact_coordinates','printing_variants','artwork_evidence_needed'}


def _text(value, field, maximum=100):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:
        raise ValueError(f'{field} must contain 1–{maximum} characters')
    return value.strip()


def _entry(db, value):
    if not isinstance(value,dict):raise ValueError('owned item must be an object')
    allowed={'item_id','card_id','language','set_code','collector_number','variant','quantity'}
    if set(value)-allowed:raise ValueError('owned item has unsupported fields')
    item_id=_text(value.get('item_id'),'item_id',64)
    quantity=value.get('quantity',1)
    if type(quantity) is not int or not 1<=quantity<=10000:
        raise ValueError('quantity must be an integer from 1 to 10000')
    row=dict(item_id=item_id,quantity=quantity,ownership_evidence='user_assertion_only',candidate_card_ids=[])
    if 'card_id' in value:
        if set(value)&{'language','set_code','collector_number','variant'}:
            raise ValueError('choose card_id or printing coordinates, not both')
        cid=_text(value['card_id'],'card_id',160)
        found=db.execute('SELECT card_id FROM card WHERE card_id=?',(cid,)).fetchone()
        return dict(row,status='asserted_exact_record' if found else 'unknown_record',card_id=cid)
    language=_text(value.get('language'),'language',8).lower()
    code=_text(value.get('set_code'),'set_code',32).upper()
    number=core.normalize_collector_number(_text(value.get('collector_number'),'collector_number',64)).upper()
    variant=_text(value['variant'],'variant',64) if 'variant' in value else None
    if language not in {'ja','en'}:
        return dict(row,status='unsupported_language',language=language)
    candidates=[r[0] for r in db.execute('SELECT card_id FROM card WHERE language=? AND set_code=? AND collector_number=? ORDER BY card_id',(language,code,number))]
    if variant is None:
        return dict(row,status='version_evidence_needed' if candidates else 'unknown_coordinates',
                    language=language,set_code=code,collector_number=number,candidate_card_ids=candidates)
    cid=core.card_id(language,code,number,variant)
    return dict(row,status='asserted_exact_record' if cid in candidates else 'unknown_record',
                card_id=cid,candidate_card_ids=candidates if cid not in candidates else [])


def compare(db, request: dict) -> dict:
    if not isinstance(request,dict) or set(request)-{'question','owned_items','limit','offset'}:
        raise ValueError('inventory request has unsupported fields')
    question=_text(request.get('question'),'question',2000)
    owned=request.get('owned_items')
    if not isinstance(owned,list) or len(owned)>MAX_ITEMS:
        raise ValueError(f'owned_items must be an array of at most {MAX_ITEMS} entries')
    limit=request.get('limit',50);offset=request.get('offset',0)
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
        raise ValueError('invalid inventory pagination')
    entries=[_entry(db,row) for row in owned]
    if len({r['item_id'] for r in entries})!=len(entries):raise ValueError('duplicate item_id')
    scope=collector_discovery.execute(db,question,limit=100)
    result=dict(schema='pokemon.collector-inventory.v1',question=question,scope=scope,
                status='scope_clarification_needed',inventory_entries=entries,
                owned_in_scope=[],possible_owned=[],missing_catalog_records=[],
                duplicates=[],outside_scope=[],unresolved_items=[r for r in entries if r['status']!='asserted_exact_record'],
                ownership_assertions_verified=False,physical_copy_verification=False,
                comparison_complete_for_submitted_catalog_scope=False,
                complete_missing_list_established=False,public_display_allowed=False,
                prices=[],live_offers=[],inventory_persisted=False,
                interpretation='Not found in the submitted resolved inventory relative to this catalog query. Unresolved items may cover additional records; no exhaustive physical-printing checklist or verified ownership is established.')
    if scope['task'] not in SCOPED_TASKS or not scope.get('coverage',{}).get('matched_catalog_records'):
        result['next_question']=scope['next_question'] or 'Specify a character, artist or release with matching catalog records.'
        return result
    count=scope['coverage']['matched_catalog_records']
    if count>MAX_SCOPE:
        result['next_question']='Narrow the character, artist, language or release scope before comparing inventory.'
        return result
    cards=list(scope['cards']);page=scope
    while page['coverage']['has_more']:
        page=collector_discovery.execute(db,question,limit=100,offset=len(cards))
        cards.extend(page['cards'])
    ids={c['card_id'] for c in cards}
    if len(cards)!=count or len(ids)!=count:raise ValueError('catalog scope changed during pagination')
    groups=defaultdict(list)
    for row in entries:
        if row['status']=='asserted_exact_record':groups[row['card_id']].append(row)
    resolved=set(groups); exact=ids&resolved
    possible={cid for row in result['unresolved_items'] for cid in row['candidate_card_ids']} & ids - exact
    missing=[c for c in cards if c['card_id'] not in exact|possible]
    result['owned_in_scope']=[dict(card_id=cid,quantity=sum(r['quantity'] for r in groups[cid]),
                                   item_ids=[r['item_id'] for r in groups[cid]]) for cid in sorted(exact)]
    result['possible_owned']=[dict(card_id=cid,item_ids=[r['item_id'] for r in result['unresolved_items'] if cid in r['candidate_card_ids']]) for cid in sorted(possible)]
    result['outside_scope']=[dict(card_id=cid,item_ids=[r['item_id'] for r in groups[cid]]) for cid in sorted(resolved-ids)]
    result['duplicates']=[dict(card_id=cid,entry_count=len(rows),quantity=sum(r['quantity'] for r in rows))
                          for cid,rows in sorted(groups.items()) if len(rows)>1]
    result['missing_catalog_records']=missing[offset:offset+limit]
    result['coverage']=dict(scoped_catalog_records=count,asserted_owned_records=len(exact),
                            possible_owned_records=len(possible),not_in_resolved_inventory=len(missing),
                            unresolved_inventory_entries=len(result['unresolved_items']),
                            unknown_inventory_may_cover_missing_records=bool(result['unresolved_items']),
                            returned=len(missing[offset:offset+limit]),offset=offset,limit=limit,
                            has_more=offset+limit<len(missing))
    result['status']='inventory_review_needed' if result['unresolved_items'] else 'comparison_ready'
    result['comparison_complete_for_submitted_catalog_scope']=not result['unresolved_items']
    result['next_question']=('Resolve the unknown or version-uncertain inventory entries before treating these catalog gaps as purchase targets.'
                             if result['unresolved_items'] else 'Inspect the remaining catalog candidates within this scope before selecting a physical copy.')
    result['unfulfilled_constraints']=[g for g in scope['unfulfilled_constraints'] if g!='owned_inventory']
    if result['unresolved_items']:result['unfulfilled_constraints'].append('owned_inventory_resolution')
    return result
