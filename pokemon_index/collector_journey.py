"""Replay a bounded collector conversation on the read-only catalog.

The caller owns the transcript. Actions are assertions/choices, not authority,
physical-copy evidence or market data. Derived cards/approvals are never accepted.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from . import core,collector_discovery,collector_inventory

MAX_TURNS=20
POLICY='pokemon.collector-journey.v1'


def catalog_revision(db):
    """Portable evidence and runtime binding; excludes conversations/market state."""
    h=hashlib.sha256(POLICY.encode())
    for name in ['collector_journey.py','collector_discovery.py','collector_inventory.py',
                 'collector_evidence.py','supported_catalog.py','card_metadata.py','metadata_views.sql',
                 'discovery_graph.py','number_graph.py','number_evidence.py','source_image_facts.py','card_comparison.py','offer_comparison.py','card_rarity.py','coordinate_family.py','printing_evidence.py','source_corrections.py','core.py','cli.py']:
        h.update(name.encode());h.update((Path(__file__).parent/name).read_bytes())
    for name in ('active_card_metadata_evidence','discovery_card_facet','base_discovery_card_facet','active_source_correction_evidence','effective_card_reference'):
        definition=db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?",(name,)).fetchone()
        h.update(json.dumps([name,definition[0] if definition else None]).encode())
    tables=['card','card_facet','catalog_set_localized','catalog_vocabulary',
            'character_family','character_family_member','catalog_collector_evidence',
            'supported_card','card_reference','card_rarity_correction','catalog_release_evidence','card_metadata_evidence','coordinate_family_evidence',
            'card_relationship_assertion','printing_source_evidence','source_correction_evidence','card_number_reading_evidence','source_image_fact_evidence']
    for table in tables:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():continue
        columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
        # Build-time bookkeeping differs between equivalent snapshots. Bind the
        # correction evidence, not the time a local/container builder applied it.
        if table=='card_rarity_correction':columns.remove('applied_at')
        h.update(json.dumps([table,columns]).encode())
        for row in db.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+','.join(columns)):
            values=list(row)
            if table=='card_relationship_assertion' and row['asserted_by']=='ai-artwork-review-v1' and row['review_status']=='proposed':
                # Only the application time of frozen imported AI proposals is
                # bookkeeping. Review times inside evidence and all other
                # assertion timestamps remain part of the conversation proof.
                core.parse_time(row['asserted_at'])
                values[columns.index('asserted_at')]=None
            h.update(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n')
    return h.hexdigest()


def _text(value,field,maximum=2000):
    return collector_inventory._text(value,field,maximum)


def _reply_scope(db,text,languages):
    t=collector_discovery._norm(text).strip(' .。!！')
    language_replies={'japanese':'ja','japanese only':'ja','only japanese':'ja','in japanese':'ja',
        '日本語':'ja','日本語だけ':'ja','日文':'ja','日版':'ja',
        'english':'en','english only':'en','only english':'en','in english':'en','英語':'en','英文':'en','英版':'en'}
    if t in language_replies:return {'language':language_replies[t]}
    variants={'normal':'normal','non-holo':'normal','non holo':'normal','ノンホロ':'normal',
        'holo':'holo','holographic':'holo','ホロ':'holo',
        'master ball':'reverse_masterball','master ball reverse':'reverse_masterball',
        'マスターボール':'reverse_masterball','大师球':'reverse_masterball',
        'poke ball':'reverse_pokeball','poké ball':'reverse_pokeball','poke ball reverse':'reverse_pokeball',
        'モンスターボール':'reverse_pokeball','精灵球':'reverse_pokeball'}
    if t in variants:return {'variant':variants[t]}
    if re.fullmatch(r'\d{1,3}/[a-z0-9\-]{1,32}',t):
        return collector_discovery.validate_scope({'collector_number':t})
    # Full release code only; arbitrary prose cannot silently alter a goal.
    if db.execute('SELECT 1 FROM card WHERE set_code=? LIMIT 1',(t.upper(),)).fetchone():return {'set_code':t.upper()}
    exact={r['set_code'] for r in db.execute('SELECT language,set_code,name FROM catalog_set_localized WHERE name IS NOT NULL')
           if r['language'] in languages and collector_discovery._norm(r['name'])==t}
    exact.update(r['set_code'] for r in db.execute('SELECT language,set_code,alias FROM catalog_vocabulary')
                 if r['language'] in languages and collector_discovery._norm(r['alias'])==t)
    if len(exact)==1:return {'set_code':next(iter(exact))}
    return None


def _preferences(value):
    fields={'grade_company','grade_value','budget_minor','currency','destination'}
    if not isinstance(value,dict) or set(value)-fields:raise ValueError('unsupported preference fields')
    result={}
    for k,v in value.items():
        if v is None:result[k]=None;continue
        if k=='budget_minor':
            if type(v) is not int or not 1<=v<=10**12:raise ValueError('invalid budget in minor units')
        else:
            v=_text(v,k,32)
            if k=='grade_value':
                if not re.fullmatch(r'\d{1,2}(?:\.\d)?',v) or not 0<=float(v)<=10:raise ValueError('invalid grade preference')
            else:
                v=v.upper()
                if k=='grade_company' and v not in {'PSA','BGS','CGC','ARS','PGC'}:raise ValueError('unsupported grading scale')
                if k=='currency' and not re.fullmatch('[A-Z]{3}',v):raise ValueError('invalid currency preference')
                if k=='destination' and not re.fullmatch('[A-Z]{2}',v):raise ValueError('invalid destination preference')
        result[k]=v
    return result


def replay(db,request,*,revision=None):
    if not isinstance(request,dict) or set(request)-{'turns','limit','expected_revision'}:raise ValueError('unsupported journey request')
    turns=request.get('turns');limit=request.get('limit',20)
    if not isinstance(turns,list) or not 1<=len(turns)<=MAX_TURNS:raise ValueError('journey needs 1–20 turns')
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('invalid journey limit')
    revision=revision or catalog_revision(db)
    if 'expected_revision' in request and request['expected_revision']!=revision:
        raise ValueError('catalog or journey policy changed; replay without the old revision and reconfirm the target')
    question=None;filters={};owned=None;preferences={};target=None;offset=0;trace=[];cache={};unparsed=None
    reset_reason=None
    def view():
        key=json.dumps([question,filters,owned,offset,limit],ensure_ascii=False,sort_keys=True)
        if key in cache:return cache[key]
        if owned is None:
            scope=collector_discovery.execute(db,question,scope=filters,limit=limit,offset=offset)
            inventory=None;cards=scope['cards']
        else:
            inventory=collector_inventory.compare(db,dict(question=question,scope=filters,owned_items=owned,limit=limit,offset=offset))
            scope=inventory['scope'];cards=inventory['missing_catalog_records']
        blockers=[]
        if scope['task'] not in collector_inventory.SCOPED_TASKS or not scope.get('coverage',{}).get('matched_catalog_records'):
            blockers.append('supported_catalog_scope_needed')
        partial_only={'artwork_coverage_completeness','physical_variant_completeness','printing_variant_completeness','owned_inventory'}
        blockers.extend(sorted(set(scope['unfulfilled_constraints'])-partial_only))
        text=collector_discovery._norm(question)
        if (re.search(r'except|exclud|(?:does not|not|doesn.t) (?:yet )?include|omit|除外|未収録',text)
                and collector_discovery._release_codes(db,text,scope['languages'])):
            blockers.append('release_exclusions_need_explicit_scope')
        if owned is None and 'owned_inventory' in scope['unfulfilled_constraints']:blockers.append('owned_inventory_not_supplied')
        if inventory and inventory['unresolved_items']:blockers.append('owned_inventory_resolution')
        if inventory and inventory['status']=='scope_clarification_needed':blockers.append('inventory_scope_needed')
        out=dict(scope=scope,inventory=inventory,cards=cards,selection_blockers=sorted(set(blockers)))
        cache[key]=out;return out
    def clear(reason):
        nonlocal target,reset_reason
        if target is not None:reset_reason=reason
        target=None
    def refine(patch):
        nonlocal filters,offset
        if not isinstance(patch,dict):raise ValueError('scope patch must be an object')
        checked=collector_discovery.validate_scope({k:v for k,v in patch.items() if v is not None})
        if set(patch)-{'language','set_code','collector_number','variant'}:raise ValueError('unsupported scope patch')
        newer=dict(filters)
        for k,v in patch.items():
            if v is None:newer.pop(k,None)
        newer.update(checked)
        if newer!=filters:clear('collection_scope_changed');offset=0
        filters=newer
    def select(cid,previous):
        nonlocal target
        cid=_text(cid,'card_id',160)
        if previous['selection_blockers']:raise ValueError('resolve scope or inventory blockers before selecting a target')
        shown={c['card_id']:c for c in previous['cards']}
        if cid not in shown:raise ValueError('selected card was not shown in the preceding candidate page')
        if shown[cid].get('official_coordinate_family',{}).get('copy_evidence_needed'):
            raise ValueError('coordinate family needs qualified-title and physical-copy evidence before selecting a target')
        if shown[cid].get('official_metadata',{}).get('official',{}).get('page_kind')=='numbered_parts':
            raise ValueError('numbered part needs physical-copy evidence before selecting a target')
        from . import source_corrections
        if source_corrections.family_scope_only(db,cid):
            raise ValueError('source-only family needs qualified physical-copy evidence before selecting a target')
        target=shown[cid]
    for pos,turn in enumerate(turns):
        if not isinstance(turn,dict):raise ValueError('journey turn must be an object')
        kind=turn.get('type');fields={
            'ask':{'type','question'},'refine':{'type','scope'},'reply':{'type','text'},
            'inventory':{'type','owned_items'},'resolve_owned':{'type','item_id','card_id'},
            'preferences':{'type','preferences'},'select':{'type','card_id'},
            'clear_target':{'type'},'page':{'type','offset'}}
        if not isinstance(kind,str) or kind not in fields or set(turn)!=fields[kind]:raise ValueError('invalid journey action fields')
        if pos==0 and kind!='ask':raise ValueError('first journey turn must set a question')
        previous=view() if question else None
        if kind=='ask':
            question=_text(turn['question'],'question');filters={};offset=0;clear('collection_goal_changed');unparsed=None
        elif kind=='refine':refine(turn['scope']);unparsed=None
        elif kind=='reply':
            text=_text(turn['text'],'reply',200)
            patch=_reply_scope(db,text,previous['scope']['languages'])
            if patch is not None:refine(patch);unparsed=None
            elif collector_discovery._norm(text).strip(' .。!！') in {'yes','confirm','yes, that one','はい','确认','是'}:
                if len(previous['cards'])==1 and not previous['selection_blockers']:
                    select(previous['cards'][0]['card_id'],previous);unparsed=None
                else:unparsed='Which exact shown card do you mean? A yes reply cannot select multiple or evidence-blocked candidates.'
            else:unparsed='Clarify the language, printed release code, number or source-declared finish, or start a new collection question.'
        elif kind=='inventory':
            owned=turn['owned_items']
            if not isinstance(owned,list) or len(owned)>collector_inventory.MAX_ITEMS:raise ValueError('inventory must contain at most 1000 items')
            entries=[collector_inventory._entry(db,r) for r in owned]
            if len({r['item_id'] for r in entries})!=len(entries):raise ValueError('duplicate item_id')
            clear('owned_inventory_changed');offset=0
        elif kind=='resolve_owned':
            item_id=_text(turn['item_id'],'item_id',64);cid=_text(turn['card_id'],'card_id',160)
            old=[r for r in (owned or []) if r['item_id']==item_id]
            if len(old)!=1:raise ValueError('unknown owned item')
            entry=collector_inventory._entry(db,old[0])
            if entry['status']=='asserted_exact_record':raise ValueError('owned item is already resolved; submit a corrected inventory explicitly')
            if not db.execute('SELECT 1 FROM card WHERE card_id=?',(cid,)).fetchone():raise ValueError('unknown resolution card')
            if entry['candidate_card_ids'] and cid not in entry['candidate_card_ids']:raise ValueError('owned resolution conflicts with declared coordinates')
            owned=[dict(item_id=item_id,card_id=cid,quantity=entry['quantity']) if r['item_id']==item_id else r for r in owned]
            clear('owned_inventory_resolved');offset=0
        elif kind=='preferences':
            patch=_preferences(turn['preferences'])
            for k,v in patch.items():
                if v is None:preferences.pop(k,None)
                else:preferences[k]=v
        elif kind=='select':select(turn['card_id'],previous);unparsed=None
        elif kind=='clear_target':clear('user_cleared_target')
        elif kind=='page':
            offset=turn['offset']
            if type(offset) is not int or not 0<=offset<collector_inventory.MAX_SCOPE:raise ValueError('invalid journey offset')
        current=view()
        trace.append(dict(turn=pos+1,action=kind,task=current['scope']['task'],
                          displayed_card_ids=[c['card_id'] for c in current['cards']],
                          selection_blockers=current['selection_blockers'],
                          selected_card_id=target['card_id'] if target else None,
                          clarification_needed=unparsed is not None))
    status='candidate_clarification_needed';next_step=None
    if unparsed:status='followup_clarification_needed';next_step=dict(field='scope_or_new_question',prompt=unparsed)
    elif current['selection_blockers']:
        if 'owned_inventory_resolution' in current['selection_blockers']:
            status='inventory_review_needed';next_step=dict(field='owned_item_resolution',prompt=current['inventory']['next_question'],
                items=current['inventory']['unresolved_items'])
        else:
            status='evidence_or_scope_needed';next_step=dict(field='collection_evidence',prompt=current['scope']['next_question'] or 'Clarify the requested exclusions, referenced checklist or unresolved collection scope before choosing a target.',
                required_evidence=current['scope'].get('required_evidence',[]),blockers=current['selection_blockers'])
    elif target:
        status='catalog_target_selected';next_step=dict(field='offer_and_copy_evidence',
            prompt='This selects a catalog record. Verify the physical printing/copy and obtain an authorized fresh offer before comparison or purchase.')
    elif current['cards']:
        field='card_id'
        if len(current['cards'])>1:
            for k in ['language','set_code','collector_number','variant']:
                if len({c[k] for c in current['cards']})>1:field=k;break
        next_step=dict(field=field,prompt='Choose a shown catalog record or narrow the collection scope; source-declared finish does not verify a physical copy.')
    elif current['inventory'] and current['inventory'].get('coverage',{}).get('scoped_catalog_records'):
        status='submitted_scope_covered';next_step=dict(field='collection_scope',prompt='The submitted resolved inventory covers this partial catalog scope. Which scope should we explore next?')
    else:
        status='no_candidates';next_step=dict(field='collection_scope',prompt='No records match this scope. Check the printed release, number, language and source-declared finish.')
    intent=None
    if target and status=='catalog_target_selected':
        intent=dict(contract='pokemon.collector-target-intent.v1',card_id=target['card_id'],
            language=target['language'],set_code=target['set_code'],collector_number=target['collector_number'],
            source_declared_variant=target['variant'],catalog_provenance=target['provenance'],
            preferences=dict(preferences),preferences_evidence='user_assertion_only',
            priceable_unit_id=None,product_url=None,quote=None,transaction_ready=False,
            automatic_offer_join_allowed=False,physical_printing_verified=False,public_display_allowed=False,
            required_evidence=['physical_printing_and_copy_condition','grade_evidence_if_requested',
                'authorized_fresh_offer','permitted_catalog_display','destination_landed_quote','confirmed_checkout_lifecycle'])
    return dict(schema=POLICY,catalog_revision=revision,turn_count=len(turns),status=status,
        goal_question=question,scope_filters=filters,candidate_cards=current['cards'],
        discovery=current['scope'],inventory=current['inventory'],
        artwork_review_leads=current['scope'].get('artwork_review_leads',[]),
        selection_allowed=bool(current['cards'] and not current['selection_blockers'] and not unparsed),
        selection_blockers=current['selection_blockers'],selected_catalog_target=target,
        target_reset_reason=reset_reason,preferences=preferences,preferences_applied_to_market=False,
        next_step=next_step,target_intent=intent,trace=trace,
        resume=dict(caller_resubmits_turns=True,expected_revision=revision,max_turns=MAX_TURNS),
        conversation_persisted=False,inventory_persisted=False,ownership_assertions_verified=False,
        physical_copy_verified=False,ready_for_offer_tracking=False,purchase_ready=False,
        complete_collection_established=False,public_display_allowed=False,prices=[],live_offers=[],
        interpretation='Caller-owned bounded action replay; catalog selection and user inventory assertions only. AI leads, copy evidence, market preferences and transaction approval remain separate.')
