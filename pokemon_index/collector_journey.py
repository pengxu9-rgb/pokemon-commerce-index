"""Replay a bounded collector conversation on the read-only catalog.

The caller owns the transcript. Actions are assertions/choices, not authority,
physical-copy evidence or market data. Derived cards/approvals are never accepted.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from . import core,collector_discovery,collector_inventory,collector_recommendation,card_comparison,discovery_graph,collector_runtime

MAX_TURNS=20
POLICY='pokemon.collector-journey.v1'


def catalog_revision(db):
    """Portable evidence and runtime binding; excludes conversations/market state."""
    h=hashlib.sha256(POLICY.encode())
    for name in ['collector_journey.py','collector_runtime.py','collector_discovery.py','collector_inventory.py','collector_recommendation.py',
                 'collector_character_affiliation.py','collector-character-affiliations-v1.json',
                 'collector_release_alias.py','collector-release-name-aliases-v1.json',
                 'collector_evidence.py','supported_catalog.py','card_metadata.py','metadata_views.sql',
                 'discovery_graph.py','number_graph.py','number_evidence.py','source_image_facts.py','source_mechanic.py','card_comparison.py','offer_comparison.py','card_rarity.py','coordinate_family.py','printing_evidence.py','source_corrections.py','core.py','cli.py']:
        h.update(name.encode());h.update((Path(__file__).parent/name).read_bytes())
    for name in ('active_card_metadata_evidence','discovery_card_facet','base_discovery_card_facet','active_source_correction_evidence','effective_card_reference'):
        definition=db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?",(name,)).fetchone()
        h.update(json.dumps([name,definition[0] if definition else None]).encode())
    tables=['card','card_facet','card_classification','catalog_set_localized','catalog_vocabulary',
            'character_family','character_family_member','catalog_collector_evidence',
            'supported_card','card_reference','card_rarity_correction','catalog_release_evidence','card_metadata_evidence','coordinate_family_evidence',
            'card_relationship_assertion','printing_source_evidence','source_correction_evidence','card_number_reading_evidence','source_image_fact_evidence','source_mechanic_binding']
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
    exact.update(r['set_code'] for r in collector_discovery.collector_release_alias.aliases(db,languages)
                 if collector_discovery._norm(r['alias'])==t)
    if len(exact)==1:return {'set_code':next(iter(exact))}
    return None


def _preferences(value,db=None):
    fields={'grade_company','grade_value','budget_minor','currency','destination','collecting'}
    if not isinstance(value,dict) or set(value)-fields:raise ValueError('unsupported preference fields')
    result={}
    for k,v in value.items():
        if v is None:result[k]=None;continue
        if k=='collecting':
            v=collector_recommendation.validate_collecting_preferences(db,v)
        elif k=='budget_minor':
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


@collector_runtime.catalog_request
def replay(db,request,*,revision=None):
    if not isinstance(request,dict) or set(request)-{'turns','limit','expected_revision'}:raise ValueError('unsupported journey request')
    turns=request.get('turns');limit=request.get('limit',5)
    if not isinstance(turns,list) or not 1<=len(turns)<=MAX_TURNS:raise ValueError('journey needs 1–20 turns')
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('invalid journey limit')
    revision=revision or catalog_revision(db)
    if 'expected_revision' in request and request['expected_revision']!=revision:
        raise ValueError('catalog or journey policy changed; replay without the old revision and reconfirm the target')
    question=None;filters={};owned=None;preferences={};target=None;offset=0;trace=[];cache={};unparsed=None
    reset_reason=None;pending_clarifications=[]
    recommendation_mode=False;feedback={};shown_ids=set();recommendation_shown=set()
    recommendation_pool_cache={'revision':revision};recommendation_baseline_cache={}
    active_comparison=None;focus_id=None;resolved_illustrator=None;ownership_required=False
    def reset_context():
        nonlocal active_comparison,focus_id
        active_comparison=None;focus_id=None;shown_ids.clear();recommendation_shown.clear()
    def patch_preferences(patch):
        nonlocal preferences,offset
        newer=dict(preferences)
        for k,v in patch.items():
            if v is None:newer.pop(k,None)
            elif k=='collecting':newer[k]=collector_recommendation.merge_profile(db,newer.get(k,{}),v)
            else:newer[k]=v
        if newer!=preferences and ('collecting' in patch or recommendation_mode or active_comparison is not None or focus_id is not None):
            clear('collection_preferences_changed');offset=0;reset_context()
        preferences=newer
    def natural_taste(text,taste):
        nonlocal ownership_required,offset
        intent=collector_recommendation.bounded_negative_intent(db,text)
        if not intent:return taste
        if intent['owned_inventory']:ownership_required=True
        excluded=intent['excluded_dex_ids']
        if excluded:
            profile=preferences.get('collecting',{})
            taste=dict(taste,excluded_dex_ids=sorted(set(profile.get('excluded_dex_ids',[]))|set(excluded)),
                preferred_dex_ids=[value for value in taste.get('preferred_dex_ids',profile.get('preferred_dex_ids',[])) if value not in excluded])
        clear('explicit_collection_constraint_changed');offset=0;reset_context()
        return taste
    def hold_clarification(text):
        nonlocal offset
        for constraint in collector_recommendation.clarification_requirements(db,text):
            if (constraint.get('required_scope_value') is not None
                    and filters.get(constraint.get('scope_field'))==constraint['required_scope_value']):
                continue
            if constraint not in pending_clarifications:pending_clarifications.append(constraint)
        clear('unresolved_collection_preference');offset=0;reset_context()
    def resolve_preference_clarifications(patch):
        nonlocal pending_clarifications
        collecting=patch.get('collecting')
        if not isinstance(collecting,dict):return
        # Only an explicit replacement on the named axis resolves its held
        # assertion. Mode, money, unrelated taste and empty objects cannot.
        fields={k for k,v in collecting.items() if isinstance(v,list)}
        remaining=[]
        for constraint in pending_clarifications:
            groups=constraint.get('preference_groups')
            if not groups:
                remaining.append(constraint);continue
            unresolved=[g for g in groups if not fields.intersection(g)]
            if unresolved:remaining.append(dict(constraint,preference_groups=unresolved))
        pending_clarifications=remaining
    def resolve_artist_requirement(patch,reply=None):
        nonlocal resolved_illustrator,offset
        # A carried profile or the original ambiguous question cannot answer a
        # new clarification. Only a later explicit single credit can; remember
        # that answer separately from optional preference axes.
        if not (recommendation_mode and collector_discovery.explicit_artist_clause(question)
                and len(collector_discovery._artists(db,collector_discovery._norm(question)))!=1):return
        collecting=patch.get('collecting',{})
        if collecting is not None and (not isinstance(collecting,dict) or 'preferred_illustrators' not in collecting):return
        artists=collecting.get('preferred_illustrators') if isinstance(collecting,dict) else None
        artist=artists[0] if isinstance(artists,list) and len(artists)==1 else None
        if reply is not None and (artist is None or collector_discovery._norm(reply).strip(' .。!！')!=collector_discovery._norm(artist)):
            return
        # This is a fresh answer even when it repeats a stored preference.
        # Reset comparison/focus/selection authority before showing new cards.
        resolved_illustrator=artist
        clear('illustrator_requirement_confirmed');offset=0;reset_context()
    def identity_blockers(card):
        cid=card['card_id']
        blocks=discovery_graph.endpoint_identity_blockers(db,cid)
        if blocks:blocks.append('catalog_identity_review_needed')
        if card.get('official_coordinate_family',{}).get('copy_evidence_needed'):
            blocks.append('coordinate_family_copy_evidence')
        if card.get('official_metadata',{}).get('official',{}).get('page_kind')=='numbered_parts':
            blocks.append('numbered_part_copy_evidence')
        from . import source_corrections,source_image_facts,number_evidence
        if source_corrections.family_scope_only(db,cid):blocks.append('source_family_copy_evidence')
        reading=number_evidence.context(db,cid)
        if reading and (not reading['current_endpoint'] or reading['status']=='reading_hold'):
            blocks.append('catalog_identity_review_needed')
        facts=source_image_facts.context(db,cid)
        if facts and facts['warnings']:blocks.append('source_image_metadata_resolution')
        return sorted(set(blocks))
    def view():
        key=json.dumps([question,filters,owned,preferences,feedback,active_comparison,focus_id,recommendation_mode,pending_clarifications,resolved_illustrator,ownership_required,offset,limit],ensure_ascii=False,sort_keys=True)
        if key in cache:return cache[key]
        recommendation=None
        if active_comparison is not None:
            scope=dict(schema='pokemon.collector-discovery.v1',question=question,
                task='two_card_comparison',status=active_comparison['status'],
                languages=collector_discovery._languages(collector_discovery._norm(question)),cards=[],
                comparison=active_comparison,next_question=active_comparison['next_question'],
                unfulfilled_constraints=[],required_evidence=active_comparison['required_evidence'])
            inventory=None;cards=[]
        elif focus_id is not None:
            rows=collector_discovery._rows(db,'c.card_id=?',(focus_id,))
            if not rows:raise ValueError('focused catalog record no longer exists')
            scope=collector_discovery._finish_result(db,dict(schema='pokemon.collector-discovery.v1',
                question=focus_id,languages=[rows[0]['language']],task='exact_coordinates',status='target_candidate',
                next_question=None,unfulfilled_constraints=[],prices=[],live_offers=[],public_display_allowed=False,
                complete_answer_established=False),rows,1,0)
            cards=scope['cards'];inventory=None
            if owned is not None:
                inventory=collector_inventory.partition_owned(db,owned,[focus_id])
                excluded=inventory.pop('excluded_card_ids')
                cards=[c for c in cards if c['card_id'] not in excluded]
                inventory.update(scope=scope,missing_catalog_records=cards)
        elif recommendation_mode:
            out=collector_recommendation.recommend(db,question,preferences.get('collecting',{}),feedback,
                scope=filters,owned=owned,limit=limit,offset=offset,preferences=preferences,
                pool_cache=recommendation_pool_cache,resolved_illustrator=resolved_illustrator)
            scope=out['scope'];inventory=out['inventory'];cards=out['cards'];recommendation=out['recommendation']
            baseline_query=collector_recommendation.positive_query(db,question)
            baseline_key=json.dumps([baseline_query,filters],sort_keys=True)
            if recommendation_baseline_cache.get('key')!=baseline_key:
                recommendation_baseline_cache.clear()
                recommendation_baseline_cache.update(key=baseline_key,
                    result=collector_discovery.execute(db,baseline_query,scope=filters,limit=1))
            baseline=recommendation_baseline_cache['result']
            scope['unfulfilled_constraints']=sorted(set(scope['unfulfilled_constraints']+baseline['unfulfilled_constraints']))
        elif owned is None:
            scope=collector_discovery.execute(db,question,scope=filters,limit=limit,offset=offset)
            inventory=None;cards=scope['cards']
        else:
            inventory=collector_inventory.compare(db,dict(question=question,scope=filters,owned_items=owned,limit=limit,offset=offset))
            scope=inventory['scope'];cards=inventory['missing_catalog_records']
        if scope['task']=='two_card_comparison' and active_comparison is None:
            scope['next_question']='The comparison context changed. Start the comparison again before choosing a side.'
        if ownership_required:
            scope['unfulfilled_constraints']=sorted(set(scope['unfulfilled_constraints']+['owned_inventory']))
            if owned is None:
                scope['next_question']='Share your owned-card list first. Results can exclude only those supplied records; they cannot establish what you own globally.'
            elif cards and active_comparison is None and focus_id is None:
                scope['next_question']='These candidates are not in your supplied inventory records. Choose a shown record or refine the scope; possession and a complete collection are not verified.'
        blockers=[]
        if pending_clarifications:
            blockers.append('unresolved_collection_preference')
            scope['next_question']=pending_clarifications[0]['prompt']
        if (recommendation_mode and re.search(collector_recommendation.HARD_RELEASE,collector_discovery._norm(question))
                and 'set_code' not in filters):
            blockers.append('recommendation_release_scope_confirmation')
        if scope['task'] not in collector_inventory.SCOPED_TASKS|{'collector_recommendations'} or not scope.get('coverage',{}).get('matched_catalog_records'):
            blockers.append('supported_catalog_scope_needed')
        partial_only={'artwork_coverage_completeness','physical_variant_completeness','printing_variant_completeness','owned_inventory'}
        blockers.extend(sorted(set(scope['unfulfilled_constraints'])-partial_only))
        text=collector_discovery._norm(collector_recommendation.positive_query(db,question) if recommendation_mode else question)
        if (re.search(r'except|exclud|(?:does not|not|doesn.t) (?:yet )?include|omit|除外|未収録',text)
                and collector_discovery._release_codes(db,text,scope['languages'])):
            blockers.append('release_exclusions_need_explicit_scope')
        if owned is None and 'owned_inventory' in scope['unfulfilled_constraints']:blockers.append('owned_inventory_not_supplied')
        if inventory and inventory['unresolved_items']:blockers.append('owned_inventory_resolution')
        if inventory and inventory['status']=='scope_clarification_needed':blockers.append('inventory_scope_needed')
        card_blockers={c['card_id']:identity_blockers(c) for c in cards}
        if cards and all(card_blockers.values()):
            blockers.extend(sorted({b for bs in card_blockers.values() for b in bs}))
        out=dict(scope=scope,inventory=inventory,cards=cards,recommendation=recommendation,
                 card_selection_blockers=card_blockers,selection_blockers=sorted(set(blockers)))
        cache[key]=out;return out
    def clear(reason):
        nonlocal target,reset_reason
        if target is not None:reset_reason=reason
        target=None
    def refine(patch):
        nonlocal filters,offset,pending_clarifications
        if not isinstance(patch,dict):raise ValueError('scope patch must be an object')
        checked=collector_discovery.validate_scope({k:v for k,v in patch.items() if v is not None})
        if set(patch)-{'language','set_code','collector_number','variant'}:raise ValueError('unsupported scope patch')
        newer=dict(filters)
        for k,v in patch.items():
            if v is None:newer.pop(k,None)
        newer.update(checked)
        pending_clarifications=[c for c in pending_clarifications if c.get('scope_field') not in checked]
        if newer!=filters:clear('collection_scope_changed');offset=0;reset_context()
        filters=newer
    def select(cid,previous):
        nonlocal target
        if pending_clarifications or unparsed:
            raise ValueError('resolve the pending collection clarification before selecting a target')
        cid=_text(cid,'card_id',160)
        shown={c['card_id']:c for c in previous['cards']}
        if cid in shown:
            card=shown[cid]
            if card.get('official_coordinate_family',{}).get('copy_evidence_needed'):
                raise ValueError('coordinate family needs qualified-title and physical-copy evidence before selecting a target')
            if card.get('official_metadata',{}).get('official',{}).get('page_kind')=='numbered_parts':
                raise ValueError('numbered part needs physical-copy evidence before selecting a target')
            from . import source_corrections
            if source_corrections.family_scope_only(db,cid):
                raise ValueError('source-only family needs qualified physical-copy evidence before selecting a target')
            if previous['card_selection_blockers'].get(cid):
                raise ValueError('catalog identity or copy evidence review needed before selecting this record')
        if previous['selection_blockers']:raise ValueError('resolve scope or inventory blockers before selecting a target')
        if cid not in shown:raise ValueError('selected card was not shown in the preceding candidate page')
        target=shown[cid]
    for pos,turn in enumerate(turns):
        if not isinstance(turn,dict):raise ValueError('journey turn must be an object')
        kind=turn.get('type');fields={
            'ask':{'type','question'},'refine':{'type','scope'},'reply':{'type','text'},
            'inventory':{'type','owned_items'},'resolve_owned':{'type','item_id','card_id'},
            'preferences':{'type','preferences'},'select':{'type','card_id'},
            'clear_target':{'type'},'page':{'type','offset'},
            'feedback':{'type','card_id','reaction'},'compare':{'type','left_card_id','right_card_id'},
            'choose_comparison':{'type','side','card_id'}}
        if not isinstance(kind,str) or kind not in fields or set(turn)!=fields[kind]:raise ValueError('invalid journey action fields')
        if pos==0 and kind!='ask':raise ValueError('first journey turn must set a question')
        previous=view() if question else None
        if kind=='ask':
            question=_text(turn['question'],'question');filters={};offset=0;clear('collection_goal_changed');unparsed=None
            reset_context();feedback={};pending_clarifications=[];resolved_illustrator=None;ownership_required=False
            baseline_query=collector_recommendation.positive_query(db,question) if collector_recommendation.is_goal(question) else question
            baseline=collector_discovery.execute(db,baseline_query,limit=1)
            if baseline['task']=='two_card_comparison':
                active_comparison=baseline['comparison']
            recommendation_mode=(collector_recommendation.is_goal(question) and baseline['task'] in {
                'collection_preferences_needed','character_cards','artist_cards','set_cards',
                'need_character_or_coordinates','exact_coordinates'})
            if recommendation_mode:
                scope_patch,money=collector_recommendation.question_constraints(question,db)
                filters.update(scope_patch)
                taste=natural_taste(question,collector_recommendation.parse_taste(db,question))
                if taste:money['collecting']=taste
                if money:patch_preferences(money)
                unparsed=collector_recommendation.taste_clarification(db,question)
                if unparsed:hold_clarification(question)
        elif kind=='refine':refine(turn['scope']);unparsed=None
        elif kind=='reply':
            text=_text(turn['text'],'reply',200)
            patch=_reply_scope(db,text,previous['scope']['languages'])
            if patch is not None:
                refine(patch);unparsed=None
                if recommendation_mode and previous['scope']['task']=='collection_preferences_needed' and 'set_code' in patch:
                    languages=[filters['language']] if 'language' in filters else previous['scope']['languages']
                    releases=[dict(language=r[0],set_code=r[1]) for r in db.execute('SELECT DISTINCT language,set_code FROM card WHERE set_code=? ORDER BY language',(patch['set_code'],)) if r[0] in languages]
                    patch_preferences({'collecting':{'preferred_releases':releases}})
            elif collector_discovery._norm(text).strip(' .。!！') in {'yes','confirm','yes, that one','はい','确认','是'}:
                if len(previous['cards'])==1 and not previous['selection_blockers']:
                    select(previous['cards'][0]['card_id'],previous);unparsed=None
                else:unparsed='Which exact shown card do you mean? A yes reply cannot select multiple or evidence-blocked candidates.'
            elif recommendation_mode:
                taste=collector_recommendation.parse_taste(db,text)
                clarification=collector_recommendation.taste_clarification(db,text)
                if clarification:
                    notes=preferences.get('collecting',{}).get('subjective_notes',[])
                    patch_preferences({'collecting':{'subjective_notes':list(dict.fromkeys(notes+[text[:160]]))[-10:]}})
                    hold_clarification(text)
                    unparsed=clarification
                elif (any(taste.get(k) for k in ['preferred_dex_ids','preferred_illustrators','preferred_releases','excluded_dex_ids'])
                        or collector_recommendation.bounded_negative_intent(db,text)):
                    scope_patch,_=collector_recommendation.question_constraints(text,db)
                    if scope_patch:refine(scope_patch)
                    taste=natural_taste(text,taste)
                    patch_preferences({'collecting':taste})
                    resolve_artist_requirement({'collecting':taste},reply=text)
                    resolve_preference_clarifications({'collecting':taste});unparsed=None
                else:
                    notes=preferences.get('collecting',{}).get('subjective_notes',[])
                    patch_preferences({'collecting':{'subjective_notes':list(dict.fromkeys(notes+[text]))[-10:]}})
                    unparsed=collector_recommendation.PROMPT
            else:unparsed='Clarify the language, printed release code, number or source-declared finish, or start a new collection question.'
        elif kind=='inventory':
            owned=turn['owned_items']
            if not isinstance(owned,list) or len(owned)>collector_inventory.MAX_ITEMS:raise ValueError('inventory must contain at most 1000 items')
            entries=[collector_inventory._entry(db,r) for r in owned]
            if len({r['item_id'] for r in entries})!=len(entries):raise ValueError('duplicate item_id')
            clear('owned_inventory_changed');offset=0;reset_context()
        elif kind=='resolve_owned':
            item_id=_text(turn['item_id'],'item_id',64);cid=_text(turn['card_id'],'card_id',160)
            old=[r for r in (owned or []) if r['item_id']==item_id]
            if len(old)!=1:raise ValueError('unknown owned item')
            entry=collector_inventory._entry(db,old[0])
            if entry['status']=='asserted_exact_record':raise ValueError('owned item is already resolved; submit a corrected inventory explicitly')
            if not db.execute('SELECT 1 FROM card WHERE card_id=?',(cid,)).fetchone():raise ValueError('unknown resolution card')
            if entry['candidate_card_ids'] and cid not in entry['candidate_card_ids']:raise ValueError('owned resolution conflicts with declared coordinates')
            owned=[dict(item_id=item_id,card_id=cid,quantity=entry['quantity']) if r['item_id']==item_id else r for r in owned]
            clear('owned_inventory_resolved');offset=0;reset_context()
        elif kind=='preferences':
            patch=_preferences(turn['preferences'],db)
            patch_preferences(patch)
            resolve_artist_requirement(patch)
            resolve_preference_clarifications(patch)
            if 'collecting' in patch and collector_recommendation.supported_goal(question) and previous['scope']['task'] in collector_inventory.SCOPED_TASKS|{'collection_preferences_needed','collector_recommendations'}:
                recommendation_mode=True
                unparsed=None
        elif kind=='feedback':
            if previous['recommendation'] is None or active_comparison is not None or focus_id is not None:
                raise ValueError('feedback requires the current recommendation context')
            # Clearing an existing reaction must remain possible after a hard
            # scope, preference or inventory change hides that card. This does
            # not authorize a new reaction to an unseen or previous-goal ID.
            allowed=recommendation_shown | (set(feedback) if turn['reaction']=='clear' else set())
            cid,reaction=collector_recommendation.validate_feedback(turn['card_id'],turn['reaction'],allowed)
            old=feedback.get(cid)
            if reaction=='clear':feedback.pop(cid,None)
            else:feedback[cid]=reaction
            if old!=feedback.get(cid):clear('recommendation_feedback_changed');offset=0
            active_comparison=None;focus_id=None;unparsed=None
        elif kind=='compare':
            left=_text(turn['left_card_id'],'left_card_id',160);right=_text(turn['right_card_id'],'right_card_id',160)
            if active_comparison is not None or focus_id is not None or left==right or not {left,right}<=shown_ids:
                raise ValueError('comparison needs two distinct shown IDs from the current candidate context')
            active_comparison=card_comparison.compare(db,{'left':{'card_id':left},'right':{'card_id':right}})
            clear('comparison_started');offset=0;unparsed=None
        elif kind=='choose_comparison':
            # Raw comparison questions enter active_comparison on ask, just
            # like compare actions. Re-parsing an old question after a context
            # reset must not resurrect its former choice authority.
            comparison=active_comparison
            side=turn['side'];cid=_text(turn['card_id'],'card_id',160)
            if not isinstance(side,str) or side not in {'left','right'} or not comparison:
                raise ValueError('choose requires an active comparison side')
            endpoint=comparison[side]
            if endpoint['records_truncated'] or endpoint['status'] not in {'exact_record','coordinate_variants'}:
                raise ValueError('comparison side must be resolved and non-truncated')
            if cid not in {r['card_id'] for r in endpoint['records']}:
                raise ValueError('focus ID does not belong to the chosen comparison side')
            clear('comparison_side_chosen');active_comparison=None;focus_id=cid;offset=0;unparsed=None
        elif kind=='select':select(turn['card_id'],previous);unparsed=None
        elif kind=='clear_target':clear('user_cleared_target')
        elif kind=='page':
            if turn['offset']!=offset:clear('candidate_page_changed')
            offset=turn['offset']
            if type(offset) is not int or not 0<=offset<collector_inventory.MAX_SCOPE:raise ValueError('invalid journey offset')
        current=view()
        if current['scope']['task']!='two_card_comparison':
            shown_ids.update(c['card_id'] for c in current['cards'])
        if current['recommendation'] is not None:
            recommendation_shown.update(c['card_id'] for c in current['cards'])
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
            prompt='Catalog target saved in this replay. Continue catalog exploration, or later verify copy condition and an authorized fresh offer when a feed is available.')
    elif current['cards'] and current['recommendation'] is not None:
        next_step=dict(field='recommendation_feedback_or_choice',prompt=current['scope']['next_question'])
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
        selection_allowed=bool(any(not current['card_selection_blockers'][c['card_id']] for c in current['cards']) and not current['selection_blockers'] and not unparsed),
        card_selection_blockers=current['card_selection_blockers'],recommendation=current['recommendation'],
        selection_blockers=current['selection_blockers'],selected_catalog_target=target,
        target_reset_reason=reset_reason,preferences=preferences,preferences_applied_to_market=False,
        next_step=next_step,target_intent=intent,trace=trace,
        resume=dict(caller_resubmits_turns=True,expected_revision=revision,max_turns=MAX_TURNS),
        conversation_persisted=False,inventory_persisted=False,ownership_assertions_verified=False,
        physical_copy_verified=False,ready_for_offer_tracking=False,purchase_ready=False,
        complete_collection_established=False,public_display_allowed=False,prices=[],live_offers=[],
        interpretation='Caller-owned bounded action replay; catalog selection and user inventory assertions only. AI leads, copy evidence, market preferences and transaction approval remain separate.')
