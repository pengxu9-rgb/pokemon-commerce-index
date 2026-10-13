"""Deterministic internal collector recommendations; no model, offers or style claims."""
from __future__ import annotations
from collections import defaultdict, deque
from decimal import Decimal
import copy,json,re
from . import collector_discovery as discovery, collector_inventory as inventory, collector_character_affiliation, collector_runtime

SCHEMA = 'pokemon.collector-recommendation.v1'
RANKING = 'explicit_axes_then_liked_axes_then_source_scan_tiebreak_then_coordinate_round_robin.v2'
FIELDS = {'mode', 'preferred_dex_ids', 'excluded_dex_ids', 'preferred_illustrators',
          'preferred_releases', 'subjective_notes'}
NEXT = r'what (?:should|can|do) i collect(?: next)?\b|what to collect next|次に何を集め|次.*集める.*おすすめ|接下来.*(?:收藏|收集)|下一步.*(?:收藏|收集)'
RECOMMEND = r'\brecommend\b|\bsuggest\b|おすすめ|推荐|推薦'
MARKET = r'cheapest|\bcheaper\b|\bprofit\b|\binvestment\b|where.*(?:buy|purchase)|どこ.*買|最便宜|哪里.*买|哪里.*买|利润|投資|買取'
STYLE_TERMS = ('cute', 'nostalgic', 'calm', 'quiet scenes', 'quiet scene', 'cute art', 'peaceful', 'cozy', 'cosy', 'different illustrations',
               'かわいい', '可愛い', '可爱', '懐かしい', '怀旧', '安静')
PROMPT = 'Which character, illustrator or release would you like to explore, or which shown card do you like?'
NEGATED_TASTE = (r"\b(?:not|without|avoid|exclude|excluding|except|dislike|hate|never)\b|"
                 r"\bother\s+than\b|\b(?:anything|everything|anyone)\s+but\b|"
                 r"\b(?:don['’]t|do not|no)\b|嫌い|苦手|以外|除外|含めない|いらない|"
                 r"好きではない|好きじゃない|不喜欢|不喜歡|不要|排除|不想|不包含")
HARD_RELEASE = (r'\b(?:only|exclusively|strictly)\s+from\b|'
                r'\b(?:only|exclusively|strictly)\s+in\s+(?!(?:japanese|english|jp|en)\b)|'
                r'\bfrom\b[^.;。！？]{0,120}\bonly\b')


def bounded_negative_intent(db,text):
    """Two exact collection operations, not a general negation interpreter."""
    t=discovery._norm(text)
    ownership=re.fullmatch(r"(.*\bcards)\s+i (?:don['’]t|do not) already own[.!?\s]*",t)
    if ownership and not re.search(NEGATED_TASTE,ownership[1]):
        return dict(positive_text=ownership[1],owned_inventory=True,excluded_dex_ids=[])
    excluded=re.fullmatch(r'(.*?)(?:\bbut\s+)?\bexclude\s+([^.;!?]+)[.!?\s]*',t)
    if not excluded:return None
    positive=excluded[1].rstrip(' ,');name=excluded[2].strip()
    if re.search(NEGATED_TASTE,positive):return None
    if re.search(r'\bfrom\b',positive) and len(discovery._release_codes(db,positive,discovery._languages(positive)))!=1:
        return None
    mentions=discovery._character_mentions(db,name,maximal=False,current_only=True)
    ids={dex for dex,start,end,_ in mentions if start==0 and end==len(name)}
    if len(ids)!=1:return None
    dex=next(iter(ids))
    # A longer card title containing the same character (e.g. Mew ex) is a
    # title-qualified exclusion, not an unambiguous whole-species instruction.
    if any(value==dex and end-start<len(name) for value,start,end,_ in mentions):return None
    if dex in discovery._character_ids(db,positive):return None
    return dict(positive_text=positive,owned_inventory=False,excluded_dex_ids=[dex])


def positive_query(db,text):
    intent=bounded_negative_intent(db,text)
    return intent['positive_text'] if intent else text


def taste_clarification(db, text):
    """Hold unsupported intent instead of converting exclusions to positive taste."""
    t=discovery._norm(positive_query(db,text))
    if re.search(NEGATED_TASTE,t):
        return 'That negative preference was not applied. Explicitly choose which character, illustrator or release to include or exclude before selecting a target.'
    if re.search(HARD_RELEASE,t) and len(discovery._release_codes(db,t,discovery._languages(t)))!=1:
        return 'Which single release must the cards come from? The only-from release constraint was not applied; supply an exact release code.'
    return None


def clarification_requirements(db, text):
    """Describe which explicit action can resolve a held assertion, not its meaning."""
    t=discovery._norm(positive_query(db,text))
    prompt=taste_clarification(db,text)
    if not prompt:return []
    constraints=[]
    codes=discovery._release_codes(db,t,discovery._languages(t))
    if re.search(NEGATED_TASTE,t):
        groups=[]
        if discovery._character_ids(db,t) or any(alias in t for alias in ['皮卡丘','梦幻','夢幻']):
            groups.append(['preferred_dex_ids','excluded_dex_ids'])
        if discovery._artists(db,t):groups.append(['preferred_illustrators'])
        if codes:groups.append(['preferred_releases'])
        constraints.append(dict(text=text,prompt=prompt,preference_groups=groups))
    # A compound negative preference can also contain a hard release demand.
    # A soft preference patch must never resolve that independent scope hold.
    if re.search(HARD_RELEASE,t):
        constraint=dict(text=text,prompt='Confirm the required release with an exact release-scope choice before selecting a target.',scope_field='set_code')
        if len(codes)==1:constraint['required_scope_value']=next(iter(codes))
        constraints.append(constraint)
    return constraints


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
                    f"SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='illustrator' AND value=? LIMIT 1",(v,)).fetchone() for v in val):
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
    return supported_goal(text) and bool(re.search(NEXT+'|'+RECOMMEND+r'|\b(?:help me )?(?:find|show)(?: me)? some\b.{0,160}\bcards?\b',t)) and not re.search(MARKET,t)


def parse_taste(db, text, *, next_goal=False):
    """Only current unambiguous catalog names; completed collections are not preferences."""
    t=discovery._norm(text)
    if taste_clarification(db,text):return {'subjective_notes':[text[:160]]}
    negative=bounded_negative_intent(db,text)
    if negative:t=negative['positive_text']
    if next_goal or re.search(NEXT,t):
        notes=[term for term in STYLE_TERMS if discovery._mentioned(t,term)]
        patch={'subjective_notes':notes} if notes else {}
        if negative and negative['excluded_dex_ids']:patch['excluded_dex_ids']=negative['excluded_dex_ids']
        return patch
    ids=discovery._character_ids(db,t)
    # Explicit bilingual species aliases, accepted only if current facets contain them.
    for aliases,dex in [(('皮卡丘',),25),(('梦幻','夢幻'),151)]:
        if any(alias in t for alias in aliases) and db.execute(
                f"SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='dex_id' AND value=? LIMIT 1",(str(dex),)).fetchone():
            ids.append(dex)
    ids=sorted(set(ids))
    artists=discovery._artists(db,t)
    if not artists:
        artists=[r[0] for r in collector_runtime.vocabulary(db,'artists',collector_runtime.VOCABULARY_SQL['artists']) if discovery._norm(r[0])==t.strip(' .。!！')]
    patch={'excluded_dex_ids':negative['excluded_dex_ids']} if negative and negative['excluded_dex_ids'] else {}
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


def question_constraints(text, db=None):
    """Supported explicit language/finish filters and budget assertions; no affordability."""
    negative=bounded_negative_intent(db,text) if db is not None else None
    t=discovery._norm(negative['positive_text'] if negative else text);scope={};preferences={}
    langs=discovery._languages(t)
    if len(langs)==1:scope['language']=langs[0]
    if db is not None and (re.search(HARD_RELEASE,t) or (negative and re.search(r'\bfrom\b',t))):
        codes=discovery._release_codes(db,t,langs)
        if len(codes)==1:scope['set_code']=next(iter(codes))
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
    return [dict(r) for r in db.execute(f'SELECT * FROM {collector_runtime.facet_lookup_relation(db)} WHERE card_id=? ORDER BY facet_type,value,provenance',(cid,))]


def _facet_batches(db, card_ids, size=400):
    """Bound SQLite variables and transient facet memory, without per-card queries."""
    for start in range(0,len(card_ids),size):
        collector_runtime.checkpoint()
        ids=card_ids[start:start+size];found={cid:[] for cid in ids}
        for row in db.execute(f'SELECT * FROM {collector_runtime.facet_lookup_relation(db)} WHERE card_id IN ('+
                ','.join('?' for _ in ids)+') ORDER BY card_id,facet_type,value,provenance',ids):
            found[row['card_id']].append(dict(row))
        yield found


def _affiliation_reason(affiliation, role, origin):
    return dict(copy.deepcopy(affiliation['reason']),affiliated_card_id=affiliation['card_id'],
                affiliation_role=role,preference_origin=origin)


def _current_affiliations(db, pool_cache):
    if pool_cache is None:return collector_character_affiliation.affiliations(db)
    # Request-local only. data_version catches writes through other connections;
    # total_changes catches local mutations in diagnostic/direct callers.
    key=(id(db),pool_cache.get('revision'),db.total_changes,db.execute('PRAGMA data_version').fetchone()[0])
    if pool_cache.get('affiliation_key')!=key:
        pool_cache['affiliations']=collector_character_affiliation.affiliations(db)
        pool_cache['affiliation_key']=key
    return pool_cache['affiliations']


def _score(row, facets, desired, liked, releases, affiliations=None, liked_affiliations=None):
    affiliations=affiliations or {};liked_affiliations=liked_affiliations or {}
    explicit=[];examples=[];reasons=[]
    for kind,axis in [('dex_id','character'),('illustrator','illustrator')]:
        for bucket,matched in [(desired,explicit),(liked,examples)]:
            matches=[f for f in facets if f['facet_type']==kind and f['value'] in bucket[kind]]
            if matches:
                matched.append(axis)
                reasons.extend(dict(field=kind,value=int(f['value']) if kind=='dex_id' else f['value'],
                    basis='catalog_facet' if bucket is desired else 'liked_example_catalog_facet',
                    source_ref=f['provenance'],rights_reference=f['rights_reference']) for f in matches)
            affiliation=affiliations.get(row['card_id']) if kind=='dex_id' else None
            derived=affiliation is not None and str(affiliation['dex_id']) in bucket[kind]
            if derived and not matches:
                matched.append(axis)
                reasons.append(_affiliation_reason(affiliation,'candidate',
                    'explicit_preference' if bucket is desired else 'liked_example'))
            if kind=='dex_id' and bucket is liked and (matches or derived):
                matched_dex={int(f['value']) for f in matches}
                if derived:matched_dex.add(affiliation['dex_id'])
                for source in liked_affiliations.values():
                    if source['dex_id'] in matched_dex:
                        reasons.append(_affiliation_reason(source,'liked_example','liked_example'))
    if any(row['language']==r['language'] and row['set_code']==r['set_code'] for r in releases):
        explicit.append('release');reasons.append(dict(field='language_set_coordinate',
            value=dict(language=row['language'],set_code=row['set_code']),basis='catalog_coordinate',source_ref=row['provenance']))
    return dict(card_id=row['card_id'],explicit_match_axes=explicit,liked_example_match_axes=examples,reasons=reasons,
        tradeoffs=['Aesthetic fit, affordability, grade availability and physical printing are not established'])


def validate_feedback(card_id, reaction, shown_ids):
    cid=inventory._text(card_id,'card_id',160)
    if not isinstance(reaction,str) or reaction not in {'like','dismiss','clear'}:
        raise ValueError('unsupported feedback reaction')
    if cid not in shown_ids:raise ValueError('feedback card was not shown in the current recommendation context')
    return cid,reaction


@collector_runtime.catalog_request
def recommend(db, question, profile, feedback, *, scope=None, owned=None, limit=5, offset=0, preferences=None, pool_cache=None, resolved_illustrator=None):
    raw_question=question;question=positive_query(db,question)
    profile=validate_collecting_preferences(db,profile)
    if resolved_illustrator is not None:
        validate_collecting_preferences(db,{'preferred_illustrators':[resolved_illustrator]})
    scope=discovery.validate_scope(scope);preferences=preferences or {}
    if type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or not 0<=offset<inventory.MAX_SCOPE:
        raise ValueError('invalid recommendation pagination')
    languages=[scope['language']] if 'language' in scope else discovery._languages(discovery._norm(question))
    # A separate typed, exact-source derivation layer; never insert or masquerade as
    # a target-source dex facet. Current support/anchor evidence is revalidated.
    # An empty positive profile cannot produce a candidate, even with species
    # exclusions. Defer the source-bound derivation until a real preference or
    # liked example needs it; clarification-only turns need no catalog-wide work.
    has_positive_input=(any(profile.get(field) for field in
        ('preferred_dex_ids','preferred_illustrators','preferred_releases')) or
        any(reaction=='like' for reaction in feedback.values()))
    affiliations=_current_affiliations(db,pool_cache) if has_positive_input else {}
    liked_affiliations={cid:affiliations[cid] for cid,reaction in feedback.items()
                        if reaction=='like' and cid in affiliations}
    liked={'dex_id':set(),'illustrator':set()}
    for cid,reaction in feedback.items():
        if reaction=='like':
            for f in _facets(db,cid):
                if f['facet_type'] in liked:liked[f['facet_type']].add(f['value'])
    liked['dex_id'].update(str(a['dex_id']) for a in liked_affiliations.values())
    desired={'dex_id':set(map(str,profile.get('preferred_dex_ids',[]))),
             'illustrator':set(profile.get('preferred_illustrators',[]))}
    releases=profile.get('preferred_releases',[])
    meta=dict(schema=SCHEMA,ranking_policy=RANKING,preference_evidence='user_assertion_only',
        candidate_pool_complete=False,coverage_basis='current_catalog_facets_and_reviewed_name_affiliations_only',
        global_catalog_completeness_established=False,
        unapplied_preferences=[dict(value=v,reason='no_source_backed_style_labels') for v in profile.get('subjective_notes',[])],
        budget_fit='unknown_no_live_price',grade_availability='unknown_no_copy_offers',items=[],coordinate_groups=[])
    numbers=set(re.findall(r'(?<![a-z0-9/])[a-z0-9]{1,16}/[a-z0-9\-]{1,32}(?![a-z0-9/])',discovery._norm(question)))
    if 'collector_number' not in scope and len(numbers)==1 and re.fullmatch(r'\d{1,3}/[a-z0-9\-]{1,32}',next(iter(numbers))):
        scope.update(discovery.validate_scope({'collector_number':next(iter(numbers))}))
    if 'collector_number' in scope and 'set_code' not in scope:
        codes=discovery._release_codes(db,discovery._norm(question),languages)
        if len(codes)==1:scope['set_code']=next(iter(codes))
    result=dict(schema='pokemon.collector-discovery.v1',question=raw_question,languages=languages,
        task='collector_recommendations',status='clarification_needed',cards=[],next_question=PROMPT,
        market_status='no_live_market_evidence',prices=[],live_offers=[],public_display_allowed=False,
        complete_answer_established=False,unfulfilled_constraints=[],requested_scope=scope,
        coverage=dict(matched_catalog_records=0,returned=0,offset=offset,limit=limit,has_more=False),
        scope='Internal preference matches; physical printing, taste, ownership and market claims remain separate.')
    interpretations=discovery.reviewed_release_interpretations(db,question,languages)
    if interpretations:result['release_name_interpretations']=interpretations
    if (discovery.explicit_artist_clause(question)
            and len(discovery._artists(db,discovery._norm(question)))!=1 and resolved_illustrator is None):
        result.update(status='clarification_needed',
            unfulfilled_constraints=['explicit_illustrator_scope_confirmation'],
            next_question='Which one exact current illustrator credit do you mean? The unknown or multiple-artist requirement was not relaxed.')
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    if resolved_illustrator is not None:
        result.update(illustrator=resolved_illustrator,illustrator_scope_basis='later_explicit_user_choice')
    if numbers and 'collector_number' not in scope:
        result.update(status='clarification_needed',next_question='Clarify one printed number or supply an exact catalog ID; unsupported or multiple number assertions are not applied.',unfulfilled_constraints=['recommendation_number_scope_confirmation'])
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    positive=[];params=[];bounded_positive=set();narrow_positive=True
    for kind in desired:
        values=sorted(desired[kind]|liked[kind])
        if values:
            ids = collector_runtime.snapshot_text_dex_card_ids(db, values) if kind=='dex_id' else None
            if ids is not None:
                bounded_positive.update(ids)
                if ids:
                    positive.append('c.card_id IN ('+','.join('?' for _ in ids)+')')
                    params.extend(ids)
                else:
                    positive.append('0')
            else:
                narrow_positive=False
                positive.append(f"c.card_id IN (SELECT f.card_id FROM {collector_runtime.facet_lookup_relation(db)} f WHERE f.facet_type=? AND f.value IN ("+','.join('?' for _ in values)+'))')
                params.extend([kind,*values])
    derived_ids=sorted(cid for cid,a in affiliations.items()
                       if str(a['dex_id']) in desired['dex_id']|liked['dex_id'])
    if derived_ids:
        bounded_positive.update(derived_ids)
        positive.append('c.card_id IN ('+','.join('?' for _ in derived_ids)+')');params.extend(derived_ids)
    for release in releases:
        narrow_positive=False
        positive.append('(c.language=? AND c.set_code=?)');params.extend([release['language'],release['set_code']])
    if not positive:
        result['task']='collection_preferences_needed'
        if profile.get('subjective_notes'):
            result['next_question']=PROMPT+' The requested visual style remains unverified; an artist or character can provide a source-backed starting point.'
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    narrow_positive = narrow_positive and len(bounded_positive)<=collector_runtime.CatalogReadModel.MAX_DEX_QUERY_IDS
    card_source = collector_runtime.card_scan(db, narrow_ids=narrow_positive)
    where=['('+' OR '.join(positive)+')','c.language IN ('+','.join('?' for _ in languages)+')'];params.extend(languages)
    for key,val in scope.items():
        where.append('c.'+key+'=?');params.append(val)
    suffix=discovery.requested_name_suffix(db,question,languages)
    if suffix:
        where.append('lower(substr(c.name,-?))=?');params.extend([len(suffix),suffix])
        where.append("(c.language='ja' OR substr(c.name,-?,1) IN (' ','-'))");params.append(len(suffix)+1)
        result.update(requested_source_name_suffix=suffix,
            name_suffix_scope='source_catalog_title_only_not_mechanic_or_copy_verification')
    # A textual "only" conjunction is a hard request, distinct from optional
    # profile axes, which retain their documented soft-union semantics.
    hard_text=discovery._norm(question)
    hard_ids=discovery._character_ids(db,discovery._without_release_names(db,hard_text,languages))
    hard_artists=[resolved_illustrator] if resolved_illustrator is not None else discovery._artists(db,hard_text)
    explicit_artist_binding=(len(hard_artists)==1 and bool(re.search(
        r'\bby\s+'+re.escape(discovery._norm(hard_artists[0]))+r'(?![a-z0-9])',hard_text)))
    if resolved_illustrator is not None or re.search(r'\bonly\b',hard_text) or explicit_artist_binding:
        if len(hard_ids)==1 and len(hard_artists)==1:
            species=f"c.card_id IN (SELECT card_id FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='dex_id' AND value=?)";params.append(str(hard_ids[0]))
            derived_hard_ids=sorted(cid for cid,a in affiliations.items() if a['dex_id']==hard_ids[0])
            if derived_hard_ids:
                species+=' OR c.card_id IN ('+','.join('?' for _ in derived_hard_ids)+')';params.extend(derived_hard_ids)
            where.append('('+species+')')
            where.append(f"c.card_id IN (SELECT card_id FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='illustrator' AND value=?)");params.append(hard_artists[0])
        elif resolved_illustrator is not None:
            where.append(f"c.card_id IN (SELECT card_id FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='illustrator' AND value=?)");params.append(resolved_illustrator)
    excluded=profile.get('excluded_dex_ids',[])
    if excluded:
        where.append(f"NOT EXISTS(SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ("+','.join('?' for _ in excluded)+'))');params.extend(excluded)
        excluded_affiliations=sorted(cid for cid,a in affiliations.items() if a['dex_id'] in excluded)
        if excluded_affiliations:
            where.append('c.card_id NOT IN ('+','.join('?' for _ in excluded_affiliations)+')');params.extend(excluded_affiliations)
    dismissed=sorted(cid for cid,r in feedback.items() if r=='dismiss')
    if dismissed:
        where.append('c.card_id NOT IN ('+','.join('?' for _ in dismissed)+')');params.extend(dismissed)
    where=' AND '.join(where)
    unknown_membership_where=None;known_params=[]
    if excluded:
        # An absent species facet is unknown membership, not proof that a
        # Pokemon avoids the user's exclusions. Only current source-bound
        # Trainer/Energy classification can exempt a no-species record.
        known_parts=[f"""EXISTS(SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} known
            WHERE known.card_id=c.card_id AND known.facet_type='dex_id'
            AND ((known.provenance=c.provenance AND known.rights_reference=c.rights_reference)
                 OR EXISTS(SELECT 1 FROM active_card_metadata_evidence metadata
                           WHERE metadata.card_id=c.card_id AND metadata.evidence_id=known.provenance)))""",
            """EXISTS(SELECT 1 FROM card_classification category WHERE category.card_id=c.card_id
                AND category.category IN ('Trainer','Energy')
                AND category.provenance=c.provenance AND category.rights_reference=c.rights_reference)"""]
        if affiliations:
            known_parts.append('c.card_id IN ('+','.join('?' for _ in affiliations)+')')
            known_params.extend(sorted(affiliations))
        known='('+' OR '.join(known_parts)+')'
        unknown_membership_where=where+' AND NOT '+known
        where+=' AND '+known
        params.extend(known_params)
    # This cache belongs to one replay only and retains one pool, never one pool
    # per turn. Unsupported subjective notes do not affect candidate membership
    # or ranking. Their disclosure is rebuilt above on every response; journey
    # authority/target invalidation still uses the complete preferences.
    ranking_profile={key:value for key,value in profile.items() if key!='subjective_notes'}
    ranking_preferences=dict(preferences)
    if isinstance(ranking_preferences.get('collecting'),dict):
        ranking_preferences['collecting']={key:value for key,value in
            ranking_preferences['collecting'].items() if key!='subjective_notes'}
    key=json.dumps([id(db),SCHEMA,RANKING,pool_cache.get('revision') if pool_cache is not None else None,
        pool_cache.get('affiliation_key') if pool_cache is not None else None,
        question,ranking_profile,feedback,scope,owned,ranking_preferences,affiliations,resolved_illustrator],sort_keys=True,ensure_ascii=True)
    cached=pool_cache.get('pool') if pool_cache is not None and pool_cache.get('key')==key else None
    if cached is None and pool_cache is not None:
        pool_cache.pop('pool',None);pool_cache.pop('key',None)
    withheld=(cached.get('unknown_membership_withheld',0) if cached is not None else
              db.execute('SELECT count(*) FROM '+card_source+' WHERE '+unknown_membership_where,params).fetchone()[0]
              if unknown_membership_where is not None else 0)
    count=cached['count'] if cached is not None else db.execute('SELECT count(*) FROM '+card_source+' WHERE '+where,params).fetchone()[0]
    result['coverage']['matched_catalog_records']=count
    if count>inventory.MAX_SCOPE:
        result.update(status='scope_too_broad',next_question='Narrow the language, release or character scope; the pool exceeds 10,000 records.',unfulfilled_constraints=['recommendation_scope_too_broad'])
        return dict(scope=result,inventory=None,cards=[],recommendation=meta)
    if cached is None:
        by_id={r['card_id']:r for r in discovery._rows(db,where,tuple(params),narrow_ids=narrow_positive)}
        inv=None
        if owned is not None:
            inv=inventory.partition_owned(db,owned,list(by_id))
            excluded_ids=inv.pop('excluded_card_ids')
            by_id={cid:r for cid,r in by_id.items() if cid not in excluded_ids}
        from . import catalog_media
        scan_tiebreak=not any(k in scope for k in ('set_code','collector_number','variant')) and not re.search(r'\b(?:ja|en):',question)
        scanned=catalog_media.current_ids(db) if scan_tiebreak else set()
        tiers=defaultdict(lambda:defaultdict(deque))
        for batch in _facet_batches(db,list(by_id)):
            for cid,facets in batch.items():
                row=by_id[cid];score=_score(row,facets,desired,liked,releases,affiliations,liked_affiliations)
                group=(row['language'],row['set_code'],row['collector_number'])
                tiers[(-len(score['explicit_match_axes']),-len(score['liked_example_match_axes']),-int(cid in scanned))][group].append(cid)
        # Diversify equal-score coordinates only. Every source version retains its exact ID.
        ordered=[]
        for tier in sorted(tiers):
            groups=tiers[tier]
            for group in groups:groups[group]=deque(sorted(groups[group]))
            active=sorted(groups,key=lambda g:groups[g][0])
            while active:
                collector_runtime.checkpoint()
                next_round=[]
                for group in active:
                    ordered.append(groups[group].popleft())
                    if groups[group]:next_round.append(group)
                active=next_round
        cached=dict(count=count,by_id=by_id,ordered=ordered,inventory=inv,unknown_membership_withheld=withheld,scan_tiebreak=scan_tiebreak)
        if pool_cache is not None:pool_cache.update(key=key,pool=cached)
    by_id=cached['by_id'];ordered=cached['ordered']
    # The response gains scope/page fields below; keep cached ownership unmodified.
    inv=copy.deepcopy(cached['inventory'])
    page=ordered[offset:offset+limit]
    scores={cid:_score(by_id[cid],facets,desired,liked,releases,affiliations,liked_affiliations)
            for batch in _facet_batches(db,page) for cid,facets in batch.items()}
    if cached['scan_tiebreak']:
        for score in scores.values():score['tradeoffs'].append('Current exact source-scan evidence breaks equal relevance ties only; live fetch and display rights remain unverified')
    cards=[discovery._card_result(db,by_id[cid]) for cid in page]
    meta.update(candidate_pool_complete=True,items=[dict(scores[cid],rank=offset+i+1) for i,cid in enumerate(page)])
    groups=defaultdict(list)
    for card in cards:groups[(card['language'],card['set_code'],card['collector_number'])].append(card['card_id'])
    meta['coordinate_groups']=[dict(language=g[0],set_code=g[1],collector_number=g[2],shown_card_ids=ids,physical_versions_merged=False) for g,ids in sorted(groups.items())]
    result.update(status='catalog_partial' if cards else 'no_match',cards=cards,ordering=RANKING,
        next_question='Like or dismiss a shown card, compare two shown cards, or explicitly choose a catalog record.' if cards else 'No current catalog matches. Explicitly change a preference or relax a hard scope filter.',
        coverage=dict(matched_catalog_records=count,not_in_resolved_inventory=len(ordered),returned=len(cards),offset=offset,limit=limit,has_more=offset+limit<len(ordered),global_printing_completeness_established=False,
            missing_character_facets_excluded=not any(cid in affiliations for cid in by_id),
            reviewed_name_affiliation_candidates=sum(cid in affiliations for cid in by_id),
            exclusion_unknown_membership_withheld=withheld,
            exclusion_scope='current_source_or_reviewed_primary_character_affiliation_not_artwork_depictions'))
    if withheld:
        result['next_question']=(result['next_question']+' '+str(withheld)+
            ' additional catalog records were withheld because current character membership could not be established for the exclusions.')
    if inv is not None:
        inv.update(missing_catalog_records=cards,scope=result,coverage=dict(scoped_catalog_records=count,not_in_resolved_inventory=len(ordered),returned=len(cards),offset=offset,limit=limit,has_more=offset+limit<len(ordered)))
    return dict(scope=result,inventory=inv,cards=cards,recommendation=meta)
