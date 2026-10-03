"""Deterministic internal collector recommendations; no model, offers or style claims."""
from __future__ import annotations
from collections import defaultdict, deque
from decimal import Decimal
import re
from . import collector_discovery as discovery, collector_inventory as inventory

SCHEMA = 'pokemon.collector-recommendation.v1'
RANKING = 'explicit_axes_then_liked_axes_then_coordinate_round_robin.v1'
FIELDS = {'mode', 'preferred_dex_ids', 'excluded_dex_ids', 'preferred_illustrators',
          'preferred_releases', 'subjective_notes'}
NEXT = r'what (?:should|can|do) i collect next|what to collect next|次に何を集め|次.*集める.*おすすめ|接下来.*(?:收藏|收集)|下一步.*(?:收藏|收集)'
RECOMMEND = r'\brecommend\b|\bsuggest\b|おすすめ|推荐|推薦'
MARKET = r'cheapest|\bcheaper\b|\bprofit\b|\binvestment\b|where.*(?:buy|purchase)|どこ.*買|最便宜|哪里.*买|哪里.*买|利润|投資|買取'
STYLE_TERMS = ('cute', 'nostalgic', 'calm', 'quiet scenes', 'quiet scene', 'cute art',
               'かわいい', '可愛い', '可爱', '懐かしい', '怀旧', '安静')
PROMPT = 'Which character, illustrator or release would you like to explore, or which shown card do you like?'


def validate_collecting_preferences(db, value):
    """Validate a PATCH. Lists replace; null deletes. Validate merged conflicts separately."""
    if not isinstance(value, dict) or set(value)-FIELDS:
        raise ValueError('unsupported collecting preference fields')
    out = {}
    for key, val in value.items():
        if val is None:
            out[key] = None
            continue
        if key == 'mode':
            if not isinstance(val,str) or val not in {'discover_next', 'explore'}:
                raise ValueError('invalid collecting mode')
        else:
            maximum = 20 if key.endswith('dex_ids') else 10
            if not isinstance(val,list) or len(val)>maximum:
                raise ValueError('invalid collecting preference array')
            if key.endswith('dex_ids'):
                if any(type(v) is not int or not 1<=v<=1025 for v in val):
                    raise ValueError('invalid dex preference')
            elif key == 'preferred_releases':
                cleaned=[]
                for release in val:
                    if not isinstance(release,dict) or set(release)!={'language','set_code'}:
                        raise ValueError('invalid preferred release')
                    scope=discovery.validate_scope(release)
                    if not db.execute('SELECT 1 FROM card WHERE language=? AND set_code=? LIMIT 1',
                                      (scope['language'],scope['set_code'])).fetchone():
                        raise ValueError('unknown preferred release')
                    cleaned.append(scope)
                val=cleaned
            else:
                val=[inventory._text(v,key,160) for v in val]
                if key == 'preferred_illustrators' and any(not db.execute(
                    "SELECT 1 FROM discovery_card_facet WHERE facet_type='illustrator' AND value=? LIMIT 1",(v,)).fetchone() for v in val):
                    raise ValueError('unknown preferred illustrator')
            keys=[tuple(sorted(v.items())) if isinstance(v,dict) else v for v in val]
            if len(set(keys))!=len(keys):raise ValueError('duplicate collecting preference')
        out[key]=val
    if set(out.get('preferred_dex_ids') or []) & set(out.get('excluded_dex_ids') or []):
        raise ValueError('preferred and excluded species conflict')
    return out


def merge_profile(db, old, patch):
    new=dict(old)
    for key,val in validate_collecting_preferences(db,patch).items():
        if val is None:new.pop(key,None)
        else:new[key]=val
    validate_collecting_preferences(db,new)
    return new


def supported_goal(text):
    t=discovery._norm(text)
    return not re.search(r'\bkorean\b|\bfrench\b|\bgerman\b|\bchinese\b|韓国語|韓版|法文|德文|中文版|yugioh|yu-?gi-?oh|magic the gathering|遊戯王|游戏王',t)


def is_goal(text):
    t=discovery._norm(text)
    return supported_goal(text) and bool(re.search(NEXT+'|'+RECOMMEND,t)) and not re.search(MARKET,t)


def parse_taste(db, text, *, next_goal=False):
    """Only current unambiguous catalog names; completed collections are not preferences."""
    t=discovery._norm(text)
    if next_goal or re.search(NEXT,t):return {}
    ids=discovery._character_ids(db,t)
    # Explicit bilingual species aliases, accepted only if current facets contain them.
    for aliases,dex in [(('皮卡丘',),25),(('梦幻','夢幻'),151)]:
        if any(alias in t for alias in aliases) and db.execute(
                "SELECT 1 FROM discovery_card_facet WHERE facet_type='dex_id' AND value=? LIMIT 1",(str(dex),)).fetchone():
            ids.append(dex)
    ids=sorted(set(ids))
    artists=discovery._artists(db,t)
    if not artists:
        artists=[r[0] for r in db.execute("SELECT DISTINCT value FROM discovery_card_facet WHERE facet_type='illustrator'") if discovery._norm(r[0])==t.strip(' .。!！')]
    patch={}
    if len(ids)==1:patch['preferred_dex_ids']=ids
    if len(artists)==1:patch['preferred_illustrators']=artists
    codes=discovery._release_codes(db,t,['ja','en'])
    if len(codes)==1:
        languages=discovery._languages(t)
        patch['preferred_releases']=[dict(language=r[0],set_code=r[1]) for r in db.execute(
            'SELECT DISTINCT language,set_code FROM card WHERE set_code=? ORDER BY language',(next(iter(codes)),)) if r[0] in languages]
    notes=[term for term in STYLE_TERMS if discovery._mentioned(t,term)]
    subjective=re.search(r'(?:i (?:like|prefer)|我喜欢|我喜歡)\s+([^.;。！？]{1,160})',t)
    if subjective and not discovery._character_ids(db,subjective[1]) and not discovery._artists(db,subjective[1]):
        notes.append(subjective[1].strip())
    if notes:patch['subjective_notes']=list(dict.fromkeys(notes))[:10]
    return patch


def question_constraints(text):
    """Supported explicit language/finish filters and budget assertions; no affordability."""
    t=discovery._norm(text);scope={};preferences={}
    langs=discovery._languages(t)
    if len(langs)==1:scope['language']=langs[0]
    for pattern,variant in [(r'non[ -]?holo|ノンホロ','normal'),
                            (r'master\s*ball|マスターボール|大师球','reverse_masterball'),
                            (r'poke\s*ball|poké\s*ball|モンスターボール','reverse_pokeball'),
                            (r'\bholo\b|ホロ','holo')]:
        if re.search(pattern,t):scope['variant']=variant;break
    budget=re.search(r'(?:under|below|up to|budget(?: of)?|预算|預算)\s*(usd\s*|\$|jpy\s*|¥|￥)(\d{1,9}(?:\.\d{1,2})?)',t)
    if budget:
        currency='JPY' if budget[1].strip() in {'jpy','¥','￥'} else 'USD'
        amount=Decimal(budget[2])*(1 if currency=='JPY' else 100)
        if amount==amount.to_integral_value() and amount>0:
            preferences.update(budget_minor=int(amount),currency=currency)
    return scope,preferences


def _facets(db, cid):
    return [dict(r) for r in db.execute('SELECT * FROM discovery_card_facet WHERE card_id=? ORDER BY facet_type,value,provenance',(cid,))]


def validate_feedback(card_id, reaction, shown_ids):
    cid=inventory._text(card_id,'card_id',160)
    if not isinstance(reaction,str) or reaction not in {'like','dismiss','clear'}:
        raise ValueError('unsupported feedback reaction')
    if cid not in shown_ids:raise ValueError('feedback card was not shown in the current recommendation context')
    return cid,reaction


def recommend(db, question, profile, feedback, *, scope=None, owned=None, limit=5, offset=0, preferences=None):
    profile=validate_collecting_preferences(db,profile)
    scope=discovery.validate_scope(scope);preferences=preferences or {}
    if type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or not 0<=offset<inventory.MAX_SCOPE:
        raise ValueError('invalid recommendation pagination')
    languages=[scope['language']] if 'language' in scope else discovery._languages(discovery._norm(question))
    liked={'dex_id':set(),'illustrator':set()}
    for cid,reaction in feedback.items():
        if reaction=='like':
            for f in _facets(db,cid):
                if f['facet_type'] in liked:liked[f['facet_type']].add(f['value'])
    desired={'dex_id':set(map(str,profile.get('preferred_dex_ids',[]))),
             'illustrator':set(profile.get('preferred_illustrators',[]))}
    releases=profile.get('preferred_releases',[])
    meta=dict(schema=SCHEMA,ranking_policy=RANKING,preference_evidence='user_assertion_only',
        candidate_pool_complete=False,coverage_basis='current_source_declared_catalog_and_facets_only',
        global_catalog_completeness_established=False,
        unapplied_preferences=[dict(value=v,reason='no_source_backed_style_labels') for v in profile.get('subjective_notes',[])],
        budget_fit='unknown_no_live_price',grade_availability='unknown_no_copy_offers',items=[],coordinate_groups=[])
    numbers=set(re.findall(r'(?<![a-z0-9/])[a-z0-9]{1,16}/[a-z0-9\-]{1,32}(?![a-z0-9/])',discovery._norm(question)))
    if 'collector_number' not in scope and len(numbers)==1 and re.fullmatch(r'\d{1,3}/[a-z0-9\-]{1,32}',next(iter(numbers))):
        scope.update(discovery.validate_scope({'collector_number':next(iter(numbers))}))
    if 'collector_number' in scope and 'set_code' not in scope:
        codes=discovery._release_codes(db,discovery._norm(question),languages)
        if len(codes)==1:scope['set_code']=next(iter(codes))
    result=dict(schema='pokemon.collector-discovery.v1',question=question,languages=languages,
        task='collector_recommendations',status='clarification_needed',cards=[],next_question=PROMPT,
        market_status='no_live_market_evidence',prices=[],live_offers=[],public_display_allowed=False,
        complete_answer_established=False,unfulfilled_constraints=[],requested_scope=scope,
        coverage=dict(matched_catalog_records=0,returned=0,offset=offset,limit=limit,has_more=False),
        scope='Internal preference matches; physical printing, taste, ownership and market claims remain separate.')
    if numbers and 'collector_number' not in scope:
        result.update(status='clarification_needed',next_question='Clarify one printed number or supply an exact catalog ID; unsupported or multiple number assertions are not applied.',unfulfilled_constraints=['recommendation_number_scope_confirmation'])
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    positive=[];params=[]
    for kind in desired:
        values=sorted(desired[kind]|liked[kind])
        if values:
            positive.append("EXISTS(SELECT 1 FROM discovery_card_facet f WHERE f.card_id=c.card_id AND f.facet_type=? AND f.value IN ("+','.join('?' for _ in values)+'))')
            params.extend([kind,*values])
    for release in releases:
        positive.append('(c.language=? AND c.set_code=?)');params.extend([release['language'],release['set_code']])
    if not positive:
        result['task']='collection_preferences_needed'
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    where=['('+' OR '.join(positive)+')','c.language IN ('+','.join('?' for _ in languages)+')'];params.extend(languages)
    for key,val in scope.items():
        where.append('c.'+key+'=?');params.append(val)
    excluded=profile.get('excluded_dex_ids',[])
    if excluded:
        where.append("NOT EXISTS(SELECT 1 FROM discovery_card_facet f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ("+','.join('?' for _ in excluded)+'))');params.extend(excluded)
    dismissed=sorted(cid for cid,r in feedback.items() if r=='dismiss')
    if dismissed:
        where.append('c.card_id NOT IN ('+','.join('?' for _ in dismissed)+')');params.extend(dismissed)
    where=' AND '.join(where)
    count=db.execute('SELECT count(*) FROM card c WHERE '+where,params).fetchone()[0]
    result['coverage']['matched_catalog_records']=count
    if count>inventory.MAX_SCOPE:
        result.update(status='scope_too_broad',next_question='Narrow the language, release or character scope; the pool exceeds 10,000 records.',unfulfilled_constraints=['recommendation_scope_too_broad'])
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    rows=discovery._rows(db,where,tuple(params));by_id={r['card_id']:r for r in rows}
    inv=None
    if owned is not None:
        inv=inventory.partition_owned(db,owned,list(by_id))
        excluded_ids=inv.pop('excluded_card_ids')
        by_id={cid:r for cid,r in by_id.items() if cid not in excluded_ids}
    scores={};tiers=defaultdict(lambda:defaultdict(deque))
    for cid,row in by_id.items():
        facets=_facets(db,cid);explicit=[];examples=[];reasons=[]
        for kind,axis in [('dex_id','character'),('illustrator','illustrator')]:
            for bucket,matched in [(desired,explicit),(liked,examples)]:
                matches=[f for f in facets if f['facet_type']==kind and f['value'] in bucket[kind]]
                if matches:
                    matched.append(axis)
                    reasons.extend(dict(field=kind,value=int(f['value']) if kind=='dex_id' else f['value'],
                        basis='catalog_facet' if bucket is desired else 'liked_example_catalog_facet',
                        source_ref=f['provenance'],rights_reference=f['rights_reference']) for f in matches)
        if any(row['language']==r['language'] and row['set_code']==r['set_code'] for r in releases):
            explicit.append('release');reasons.append(dict(field='language_set_coordinate',
                value=dict(language=row['language'],set_code=row['set_code']),basis='catalog_coordinate',source_ref=row['provenance']))
        scores[cid]=dict(card_id=cid,explicit_match_axes=explicit,liked_example_match_axes=examples,reasons=reasons,
            tradeoffs=['Aesthetic fit, affordability, grade availability and physical printing are not established'])
        group=(row['language'],row['set_code'],row['collector_number'])
        tiers[(-len(explicit),-len(examples))][group].append(cid)
    # Diversify equal-score coordinates only. Every source version retains its exact ID.
    ordered=[]
    for tier in sorted(tiers):
        groups=tiers[tier]
        for group in groups:groups[group]=deque(sorted(groups[group]))
        active=sorted(groups,key=lambda g:groups[g][0])
        while active:
            next_round=[]
            for group in active:
                ordered.append(groups[group].popleft())
                if groups[group]:next_round.append(group)
            active=next_round
    page=ordered[offset:offset+limit]
    cards=[discovery._card_result(db,by_id[cid]) for cid in page]
    meta.update(candidate_pool_complete=True,items=[dict(scores[cid],rank=offset+i+1) for i,cid in enumerate(page)])
    groups=defaultdict(list)
    for card in cards:groups[(card['language'],card['set_code'],card['collector_number'])].append(card['card_id'])
    meta['coordinate_groups']=[dict(language=g[0],set_code=g[1],collector_number=g[2],shown_card_ids=ids,physical_versions_merged=False) for g,ids in sorted(groups.items())]
    result.update(status='catalog_partial' if cards else 'no_match',cards=cards,ordering=RANKING,
        next_question='Like or dismiss a shown card, compare two shown cards, or explicitly choose a catalog record.' if cards else 'No current catalog matches. Explicitly change a preference or relax a hard scope filter.',
        coverage=dict(matched_catalog_records=count,not_in_resolved_inventory=len(ordered),returned=len(cards),offset=offset,limit=limit,has_more=offset+limit<len(ordered),global_printing_completeness_established=False,missing_character_facets_excluded=True))
    if inv is not None:
        inv.update(missing_catalog_records=cards,scope=result,coverage=dict(scoped_catalog_records=count,not_in_resolved_inventory=len(ordered),returned=len(cards),offset=offset,limit=limit,has_more=offset+limit<len(ordered)))
    return dict(scope=result,inventory=inv,cards=cards,recommendation=meta)
