"""Execute a bounded set of internal collector tasks from a plain question.

This conservative interpreter asks for clarification outside its supported
patterns. It does not generate prices, infer a physical finish or call a model.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import deque
from . import core, discovery_graph, supported_catalog, collector_evidence, card_metadata, collector_runtime, collector_release_alias


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def validate_scope(value: dict | None) -> dict:
    """Explicit follow-up choices override language/release/number/finish text.

    These are catalog filters, never evidence of a physical printing.
    """
    if value is None:return {}
    if not isinstance(value,dict) or set(value)-{'language','set_code','collector_number','variant'}:
        raise ValueError('unsupported collector scope')
    result={}
    for key,item in value.items():
        if not isinstance(item,str) or not item.strip():raise ValueError('invalid collector scope value')
        item=unicodedata.normalize('NFKC',item).strip()
        if key=='language':
            item=item.lower()
            if item not in {'ja','en'}:raise ValueError('unsupported collector language')
        elif key=='set_code':
            item=item.upper()
            if not re.fullmatch(r'[A-Z0-9.\-]{1,32}',item):raise ValueError('invalid release code')
        elif key=='collector_number':
            item=core.normalize_collector_number(item).upper()
            if not re.fullmatch(r'\d{1,3}/[A-Z0-9\-]{1,32}',item):raise ValueError('invalid collector number')
        else:
            item=item.lower()
            if not re.fullmatch(r'[a-z0-9_\-]{1,64}',item):raise ValueError('invalid source-declared variant')
        result[key]=item
    return result


def _mentioned(text: str, term: str) -> bool:
    term = _norm(term)
    # The boundary-aware pattern below contains only this escaped literal.
    # Reject impossible matches before compiling one regex per catalog name.
    if term not in text:
        return False
    if re.fullmatch(r"[a-z0-9 '\-\.]+", term):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def _languages(text: str) -> list[str]:
    ja = bool(re.search(r"japanese|\bjp\b|日本語|日文|日版|日英", text))
    en = bool(re.search(r"english|\ben\b|英語|英文|英版|日英", text))
    # A user's Japanese example in a general checklist request is not an
    # instruction to discard every English record.
    if (ja and not en and re.search(r'\b(?:my|have|own)\s+(?:a\s+)?japanese\b',text)
            and re.search(r'\b(?:list|checklist|all|every)\b',text)
            and not re.search(r'\b(?:all|only|every)\s+japanese\b|\bin japanese\b',text)):
        ja=False
    return ["ja", "en"] if ja == en else ["ja"] if ja else ["en"]


def _card_result(db, row) -> dict:
    card = {k:row[k] for k in ("card_id", "language", "set_code", "collector_number",
                               "variant", "name", "rarity", "provenance")}
    card.update(set_name=row["set_name"], release_date=row["release_date"],
                release_provenance=row["release_provenance"],
                structural_match_eligible=bool(row["match_eligible"]),
                support_status=supported_catalog.support_for_card(db, row["card_id"])["status"],
                price_comparable=False, automatic_offer_join_allowed=False)
    context=collector_evidence.card_context(db,row['card_id'])
    if context['findings'] or context['stale_findings']:card['collector_evidence']=context
    metadata = card_metadata.context(db, row['card_id'])
    if metadata:
        card['official_metadata'] = metadata
        if metadata['status'] == 'official_coordinate_metadata_supported' and metadata['official']['rarity']:
            card['source_rarity'] = card['rarity']
            card['rarity'] = metadata['official']['rarity']
    from . import coordinate_family,printing_evidence,source_corrections
    corrected=source_corrections.context(db,row['card_id'])
    if corrected:card['source_corrections']=corrected
    family=coordinate_family.context(db,row['card_id'])
    if family:card['official_coordinate_family']=family
    printing=printing_evidence.context(db,row['card_id'])
    if printing:card['printing_source_evidence']=printing
    artist=source_corrections.printed_artist(db,row['card_id'])
    if artist:card['printed_artist_credit']=artist
    return card


def _rows(db, where: str, params: tuple) -> list:
    return db.execute(f"""SELECT c.*,s.name AS set_name,s.release_date,
              s.provenance AS release_provenance FROM card c
        LEFT JOIN catalog_set_localized s ON c.language=s.language AND c.set_code=s.set_code
        WHERE {where} ORDER BY s.release_date IS NULL OR s.release_date='',
        s.release_date,c.language,c.set_code,c.collector_number,c.variant""", params).fetchall()


def _set_browse_order(rows: list) -> list:
    """Show one source version per coordinate before revisiting coordinates.

    Input order determines both coordinate order and variant order. This only
    interleaves exact source records; it never merges versions or establishes
    physical equivalence. Apply to the complete filtered pool before paging.
    """
    groups = {}
    for row in rows:
        coordinate = (row['language'], row['set_code'], row['collector_number'])
        groups.setdefault(coordinate, deque()).append(row)
    active = list(groups.values())
    ordered = []
    while active:
        next_round = []
        for variants in active:
            ordered.append(variants.popleft())
            if variants:
                next_round.append(variants)
        active = next_round
    return ordered


def _finish_result(db, result: dict, rows: list, limit: int, offset: int, *, _row_capture=None) -> dict:
    text = _norm(result['question'])
    explicit=result.get('requested_scope',{})
    rows=[r for r in rows if all(r[k]==v for k,v in explicit.items())]
    suffix=requested_name_suffix(db,result['question'],result['languages'])
    if suffix:
        rows=[r for r in rows if name_has_suffix(r['name'],r['language'],suffix)]
        result.update(requested_source_name_suffix=suffix,
            name_suffix_scope='source_catalog_title_only_not_mechanic_or_copy_verification')
        if not rows:
            result.update(status='no_match',
                next_question='No current catalog title in this scope has the requested '+suffix+' suffix. Explicitly relax the title or coordinate constraint to broaden the search.')
    requested_artists=_artists(db,text)
    artist_inquiry=bool(re.search(r'who (?:is|was) (?:credited as )?(?:the )?(?:illustrator|artist)|who (?:illustrated|drew)|which (?:artist|illustrator) (?:is|was)|イラストレーターは誰|誰.*(?:描|イラスト)',text))
    if (requested_artists or (not artist_inquiry and re.search(r'\bartist\b|illustrat|イラストレーター|画師|绘师|插画师|\bby\s+(?!\d|set\b|number\b|date\b)',text))):
        artist_ids={r[0] for r in db.execute(f"SELECT card_id FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='illustrator' AND value=?",(requested_artists[0],))} if len(requested_artists)==1 else set()
        rows=[r for r in rows if r['card_id'] in artist_ids]
        if not rows:
            result.update(status='no_match',next_question=(
                'No current catalog record satisfies the requested character and illustrator together. Explicitly relax either constraint or start a new collection question.'
                if result['task']=='artist_cards' else
                'That exact coordinate does not have the requested current source-backed illustrator credit.'))
    qualifiers=_qualifier_findings(db,text,result['languages'])
    unsupported_professors=_unsupported_professors(db,text)
    if qualifiers or unsupported_professors:
        allowed={cid for f in qualifiers if f['active'] for cid in f['card_ids']} if len(qualifiers)==1 and not unsupported_professors else set()
        rows=[r for r in rows if r['card_id'] in allowed]
        result['requested_printed_qualifiers']=sorted({f['value'] for f in qualifiers})
        result['unfulfilled_constraints'].append('publisher_qualifier_not_seller_copy_verified')
        if not rows:result.update(status='no_match',next_question='The scoped printing does not satisfy the current source-backed professor subtitle; inspect the exact printed number and copy photos.')
    codes={explicit['set_code']} if 'set_code' in explicit else _release_codes(db,text,result['languages'])
    # Incidental/omitted releases in an external checklist are not affirmative
    # release filters. Explicit follow-up scope remains authoritative.
    exclusions=re.search(r'except|exclud|(?:does not|not|doesn.t) (?:yet )?include|omit|除外|未収録',text)
    if 'set_code' in explicit or (len(codes)==1 and not exclusions):
        rows=[r for r in rows if r['set_code'] in codes]
    finish = None
    # A set-variant comparison needs all declared variants, not one ball filter.
    if result['task']=='artist_cards' and re.search(r'base.*reverse|all.*(?:variants|versions|prints)|unique.*prints',text):
        result['unfulfilled_constraints'].append('printing_variant_completeness')
        result['physical_finish_verification']='not_established_by_catalog'
    elif result['task'] == 'set_cards':
        result['variant_summary'] = [dict(variant=v, records=sum(r['variant']==v for r in rows))
                                     for v in sorted({r['variant'] for r in rows})]
        rarities = [card_metadata.effective_rarity(db, r['card_id'], r['rarity']) for r in rows]
        result['rarity_summary'] = [dict(rarity=v, records=rarities.count(v))
                                    for v in sorted(set(rarities), key=lambda v:v or '')]
        result['physical_finish_verification'] = 'not_established_by_catalog'
        result['unfulfilled_constraints'].append('physical_variant_completeness')
    elif 'variant' in explicit:
        finish={explicit['variant']}
    elif re.search(r'master\s*ball|マスターボール|大师球', text):
        finish = {'reverse_masterball'}
    elif re.search(r'poke\s*ball|poké\s*ball|モンスターボール|精灵球', text):
        finish = {'reverse_pokeball'}
    elif re.search(r'non[ -]?holo|non[ -]?foil|ノンホロ', text):
        finish = {'normal'}
    elif re.search(r'\breverse\b|ミラー', text):
        finish = {r['variant'] for r in rows if r['variant'].startswith('reverse')}
    elif re.search(r'\bholo(?:graphic)?\b|\bfoil\b', text):
        finish = {'holo'}
    if finish is not None:
        rows = [r for r in rows if r['variant'] in finish]
        result['requested_source_variants'] = sorted(finish)
        result['physical_finish_verification'] = 'not_established_by_catalog'
        if not rows:
            result.update(status='no_match', next_question='No catalog record satisfies that source-declared finish; inspect the printed version evidence.')
        elif result['task']=='exact_coordinates':
            result['status'] = 'target_candidate' if len(rows)==1 else 'printing_clarification_needed'
    if result['task'] == 'set_cards':
        rows = _set_browse_order(rows)
    # Private inventory projection: retain only a bounded, fully filtered pool.
    # The public response remains paginated and contains no internal row objects.
    if _row_capture is not None and len(rows)<=_row_capture[0]:
        _row_capture[1].extend(rows)
    result.update(cards=[_card_result(db, r) for r in rows[offset:offset+limit]],
                  coverage={"matched_catalog_records":len(rows),
                            "returned":len(rows[offset:offset+limit]), "offset":offset,
                            "limit":limit, "has_more":offset+limit<len(rows),
                            "undated_records":sum(not r["release_date"] for r in rows),
                            "release_metadata_missing":sum(not r["set_name"] for r in rows),
                            "global_printing_completeness_established":False,
                            "missing_character_facets_excluded":True,
                            "artwork_cameos_supported":False},
                  ordering=("stable coordinate round-robin; every exact source version retained; no physical versions merged"
                            if result['task'] == 'set_cards' else
                            "release date ascending; unknown dates last; stable printing coordinates"))
    parts = [c for c in result['cards'] if c.get('official_metadata',{}).get('official',{}).get('page_kind')=='numbered_parts']
    if parts and result['task']=='exact_coordinates':
        result['unfulfilled_constraints'].append('numbered_part_copy_evidence')
        result['next_question']='The official page lists multiple numbered parts. Confirm the requested part and inspect the listing photos before selecting a physical copy.'
    from . import source_corrections
    source_families=[c for c in result['cards'] if source_corrections.family_scope_only(db,c['card_id'])]
    if source_families and result['task']=='exact_coordinates':
        result['unfulfilled_constraints'].append('source_family_copy_evidence')
        result['next_question']='This publisher-source record supports a number family only. Confirm the physical edition, finish and seller-copy photos before selecting a purchase target.'
    families=[c for c in result['cards'] if c.get('official_coordinate_family',{}).get('copy_evidence_needed')]
    if families and result['task']=='exact_coordinates':
        result['unfulfilled_constraints'].append('coordinate_family_copy_evidence')
        result['next_question']='Official evidence supports this number family. Confirm the qualified card title and printed finish/edition from copy photos; official pages are not yet mapped to source variants.'
    return result


def _release_name_mentions(db, text: str, languages: list[str]) -> list[tuple]:
    """Prefer full release titles over nested titles or code-shaped words."""
    names={(r['set_code'],r['alias']) for r in db.execute("SELECT * FROM catalog_vocabulary WHERE alias_kind='set_name'") if r['language'] in languages}
    names.update((r['set_code'],r['name']) for r in db.execute('SELECT language,set_code,name FROM catalog_set_localized') if r['language'] in languages and r['name'])
    names.update((r['set_code'],r['alias']) for r in collector_release_alias.aliases(db,languages))
    candidates=[]
    for code,name in names:
        collector_runtime.checkpoint()
        term=_norm(name)
        if len(term)<3 or not _mentioned(text,term):continue
        if term.isdigit() and not re.search(r'\bset\b|\bcards?\b|拡張|カード',text):continue
        pattern=(r'(?<![a-z0-9/])'+re.escape(term)+r'(?![a-z0-9/])') if term.isdigit() else ((r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])') if re.fullmatch(r"[a-z0-9 '\-\.]+",term) else re.escape(term))
        for match in re.finditer(pattern,text):candidates.append((code,match.start(),match.end(),term))
    return sorted({m for m in candidates if not any(n[1]<=m[1] and n[2]>=m[2] and n[2]-n[1]>m[2]-m[1] for n in candidates)})


def reviewed_release_interpretations(db, text, languages):
    return [row for row in collector_release_alias.aliases(db,languages) if _mentioned(_norm(text),row['alias'])]


def requested_name_suffix(db, question, languages):
    """Recognize a species-title ex qualifier without reclassifying card mechanics."""
    text=_without_release_names(db,_norm(question),languages)
    if re.search(r'(?<![a-z0-9])ex(?![a-z0-9])',text) and len(_character_ids(db,text))==1:
        return 'ex'
    return None


def name_has_suffix(name,language,suffix):
    text=_norm(name)
    if language=='en':return text.endswith(' '+suffix) or text.endswith('-'+suffix)
    return text.endswith(suffix)


def _without_release_names(db, text: str, languages: list[str]) -> str:
    chars=list(text)
    for _,start,end,_ in _release_name_mentions(db,text,languages):chars[start:end]=' '*(end-start)
    return ''.join(chars)


def _release_codes(db, text: str, languages: list[str]) -> set[str]:
    names=_release_name_mentions(db,text,languages)
    residual=list(text)
    for _,start,end,_ in names:residual[start:end]=' '*(end-start)
    residual=''.join(residual)
    codes={code for code,_,_,_ in names}
    codes.update(r[0] for r in collector_runtime.vocabulary(db,'release_codes',collector_runtime.VOCABULARY_SQL['release_codes']) if _mentioned(residual,r[0]))
    for row in db.execute('SELECT * FROM catalog_vocabulary'):
        if row['language'] in languages and row['alias_kind']=='printed_code' and _mentioned(residual,row['alias']):codes.add(row['set_code'])
        # Numeric product titles are shorthand only in explicit release context.
        short=re.fullmatch(r'ポケモンカード(\d+)',row['alias'])
        if (short and row['language'] in languages and
                re.search(r'(?<![a-z0-9/])'+re.escape(short[1])+r'(?![a-z0-9/])',text)
                and re.search(r'japanese|日本語|日版|ポケモンカード',text)):
            codes.add(row['set_code'])
    return codes


def _artists(db, text: str) -> list[str]:
    intent=bool(re.search(r'\bartist\b|illustrat|イラストレーター|画師|绘师|插画师|\bby\b',text))
    return [r[0] for r in collector_runtime.vocabulary(db,'artists',collector_runtime.VOCABULARY_SQL['artists'])
            if (intent or len(r[0].split())>=2) and _mentioned(text,r[0])]


def explicit_artist_clause(text):
    return bool(re.search(r'\bby\s+(?!\d|set\b|number\b|date\b)',_norm(text)))


def _qualifier_findings(db,text,languages):
    from . import source_corrections
    if not source_corrections.available(db):return []
    result=[]
    for row in db.execute("SELECT e.*,a.event_id active_id FROM source_correction_evidence e LEFT JOIN active_source_correction_evidence a ON a.event_id=e.event_id WHERE e.kind='printed_qualifier' AND NOT EXISTS(SELECT 1 FROM source_correction_evidence later WHERE later.correction_key=e.correction_key AND later.revision>e.revision)"):
        record=json.loads(row['record_json'])
        if _mentioned(text,record['value']):result.append(dict(value=record['value'],active=bool(row['active_id']) and row['language'] in languages,card_ids=[c['card_id'] for c in record['snapshot']['cards']],evidence_id=row['event_id']))
    return result


def _unsupported_professors(db,text):
    from . import source_corrections
    names=re.findall(r'[一-龯ぁ-んァ-ヶー・]{2,30}博士',text.replace('博士の研究',' '))
    english=re.findall(r'\bprofessor\s+([a-z][a-z\-\']{1,40})',text)
    # These predicates ask who is shown; they do not supply a person's name.
    inquiry_words={'research','is','was','are','were','appears','appear','printed',
                   'shown','depicted','does','do','has','have','on','in'}
    english=[name for name in english if name not in inquiry_words]
    known={r[0] for r in db.execute("SELECT DISTINCT json_extract(record_json,'$.value') FROM source_correction_evidence WHERE kind='printed_qualifier'")} if source_corrections.available(db) else set()
    return [name for name in names if not any(name.endswith(_norm(value)) for value in known)]+['professor '+name for name in english]


def _character_mentions(db, text: str, *, maximal=True, current_only=False) -> list[tuple]:
    # User text and matches stay in this replay, never in the shared catalog image.
    return list(collector_runtime.request_mentions(db,(text,maximal,current_only),
        lambda:tuple(_compute_character_mentions(db,text,maximal=maximal,current_only=current_only))))


def _compute_character_mentions(db, text: str, *, maximal=True, current_only=False) -> list[tuple]:
    # One character facet only: a team card name cannot name a single species.
    aliases = collector_runtime.vocabulary(db, 'character_aliases', collector_runtime.VOCABULARY_SQL['character_aliases'])
    names={}
    for index,row in enumerate(aliases):
        if index%128==0:collector_runtime.checkpoint()
        if len(row['name'])>=3 and (not current_only or row['current_evidence']):
            key=(_norm(row['name']),row['dex_id'])
            names[key]=names.get(key,False) or bool(row['current_evidence'])
    if not current_only:
        for row in db.execute("SELECT * FROM character_family_member"):
            for key in ['name_en','name_ja']:names.setdefault((_norm(row[key]),row['dex_id']),False)
    matches=set();current_matches=set()
    for index,((name,dex),current) in enumerate(names.items()):
        if index%128==0:collector_runtime.checkpoint()
        if not name or name not in text:continue
        pattern=(r'(?<![a-z0-9])'+re.escape(name)+r'(?![a-z0-9])'
                 if re.fullmatch(r"[a-z0-9 '\-\.]+",name) else re.escape(name))
        found={(dex,m.start(),m.end(),name) for m in re.finditer(pattern,text)}
        matches.update(found)
        if current:current_matches.update(found)
    # Containment is occurrence-local: ミュウ alone still counts when another
    # occurrence is inside ミュウツー. A stale longer match cannot suppress a
    # shorter one to create new certainty. Equal-span conflicts stay ambiguous.
    return sorted(m for m in matches if not maximal or not any(
        other[1]<=m[1] and other[2]>=m[2] and other[2]-other[1]>m[2]-m[1] for other in current_matches))


def _character_ids(db, text: str) -> list[int]:
    return sorted({match[0] for match in _character_mentions(db,text)})


@collector_runtime.catalog_request
def execute(db: sqlite3.Connection, question: str, *, limit: int = 50,
            offset: int = 0, scope: dict | None = None, _row_capture=None) -> dict:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError("question must contain 1–2000 characters")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("invalid collector pagination")
    explicit=validate_scope(scope)
    text = _norm(question)
    language_text=re.sub(r'\b(?:ja|en):[a-z0-9.\-]+:[^\s:]+:[a-z0-9_\-]+',' ',text)
    languages = [explicit['language']] if 'language' in explicit else _languages(language_text)
    release_codes=lambda: {explicit['set_code']} if 'set_code' in explicit else _release_codes(db,text,languages)
    release_context=bool(re.search(r'\bcards?\s+from\b|\b(?:set|release|checklist)\b|拡張パック|収録|のカード|カード一覧|カードリスト',text))
    identity_text=_without_release_names(db,text,languages) if release_context else text
    result = {"schema":"pokemon.collector-discovery.v1", "question":question,
              "languages":languages, "task":None, "status":"clarification_needed",
              "cards":[], "next_question":None,
              "market_status":"no_live_market_evidence", "live_offers":[],
              "prices":[], "public_display_allowed":False,
              "unfulfilled_constraints":[], "complete_answer_established":False,
              "scope":"Internal catalog results; printing/character membership is not physical-copy, availability or price evidence"}
    interpretations=reviewed_release_interpretations(db,question,languages)
    if interpretations:result['release_name_interpretations']=interpretations
    if explicit:result['requested_scope']=explicit
    non_card_text=re.sub(r'(?:anything|everything)?\s*(?:other than|except|excluding)\s+(?:pokemon\s+)?cards?', '', text)
    accessory_request=(re.search(r'\b(?:sleeves?|playmats?|deck boxes?)\b|スリーブ|プレイマット|デッキケース',non_card_text)
                       and not re.search(r'\bcards?\b|\btcg\b|カード',non_card_text))
    if re.search(r'\bfigures?\b(?!\s+out\b)|フィギュア',text) or accessory_request:
        return dict(result,task='other_product_evidence_needed',status='blocked',
                    required_evidence=['official_non_card_product_identity_and_authenticity_source'],
                    next_question='Which exact figure or other product should be checked against its official release source? Card identities cannot verify merchandise.')
    if re.search(r'what (?:should|can|do) i collect next|what to collect next|次に何を集め|次.*集める.*おすすめ',text):
        return dict(result,task='collection_preferences_needed',status='clarification_needed',
                    required_evidence=['next_collection_character_artist_or_release_preferences'],
                    next_question='Would you like a new character, illustrator or release collection? Your completed collection is context, not an instruction to search it again.')
    if re.search(r'\bkorean\b|\bfrench\b|\bgerman\b|\bchinese\b|韓国語|韓版|法文|德文|中文版', text):
        return dict(result, task='unsupported_language', status='unsupported_scope',
                    required_evidence=['catalog_and_release_evidence_for_requested_languages'],
                    next_question='This executor currently searches Japanese and English catalog records. Which of those should we inspect?')
    if re.search(r"yugioh|yu-?gi-?oh|magic the gathering|遊戯王|游戏王", text):
        return dict(result, task="unsupported_game", status="unsupported_scope",
                    next_question="Would you like to search physical Pokémon TCG cards?")
    if not explicit:
        from . import card_comparison
        comparison = card_comparison.from_question(db, question)
        if comparison is not None:
            return dict(result, task='two_card_comparison', status=comparison['status'],
                        comparison=comparison, next_question=comparison['next_question'],
                        unfulfilled_constraints=comparison.get('unfulfilled_constraints', []),
                        required_evidence=comparison['required_evidence'])
    market_text=re.sub(r"price (?:does not|doesn't|doesn’t) matter|(?:it )?(?:does not|doesn't|doesn’t) matter (?:the )?price|価格(?:は)?関係ない",'',text)
    if re.search(r"\bprices?\b|cheapest|\bcheaper\b|\bmerchant\b|\bprofit\b|\bpopular\b|\bworth\b|sources? of raw cards|where can i (?:find|buy).*raw cards|\bwhere\b.{0,80}\b(?:buy|purchase)\b|売って|価格|相場|いくら|買取|価値|价格|价差|到手价", market_text):
        return dict(result, task="market_evidence_needed", status="blocked",
                    required_evidence=["exact_printing_target", "authorized_fresh_offers_or_relevant_market_evidence"],
                    next_question="Which exact printing should we track when an authorized feed is available?")
    # Product context precedes species names or incidental illustrator words.
    if re.search(r'\bvideo\b|動画',text) and re.search(r'list|checklist|リスト',text):
        return dict(result,task='collection_scope_needed',status='clarification_needed',
                    required_evidence=['referenced_checklist_text_and_release_scope'],
                    next_question='Share the checklist text or printed release name from the video so we can compare actual records.')
    if re.search(r'裏面.*(?:違|模様)|card backs?.*(?:different|differ)',text):
        return dict(result,task='release_history_evidence_needed',status='blocked',
                    required_evidence=['official_historical_design_and_regional_release_source'],
                    next_question='Which release era and region should we check? Catalog metadata does not establish the historical reason for a design difference.')
    if re.search(r'公式.*(?:カードリスト|カード検索).*(?:検索|機能)',text):
        return dict(result,task='official_search_evidence_needed',status='blocked',
                    required_evidence=['official_search_interface_or_help_evidence'],
                    next_question='Which official search page or filter should we inspect? Our catalog cannot confirm another website’s current controls.')
    if re.search(r'psa.*(?:アイテム|入力|submission|submit)|grading.*submission',text):
        return dict(result,task='grading_policy_evidence_needed',status='blocked',
                    required_evidence=['official_grader_submission_search_instructions','exact_printing_coordinates'],
                    next_question='Confirm the printed release and number, then check the grader’s own submission instructions; catalog matching cannot validate its form selections.')
    if re.search(r'同じタイトル.*同じカード|同じ物.*内容|sealed.*contents|starter.*(?:contents|same cards)',text):
        return dict(result,task='sealed_contents_evidence_needed',status='blocked',
                    required_evidence=['exact_sealed_product_release','official_contents_or_randomization_source'],
                    next_question='Which exact starter product should we check? Individual card rows do not establish a sealed box’s fixed or random contents.')
    if re.search(r'ex.*(?:全部|全種類)|(?:全部|全種類).*ex',text):
        return dict(result,task='card_type_scope_needed',status='clarification_needed',
                    required_evidence=['card_type_era_and_collection_scope','single_cards_vs_sealed_contents_plan'],
                    next_question='Do you mean modern ex cards or another era, and which releases? Starter boxes and booster packs are not proof of a complete card-type checklist.')
    if re.search(r'\bshiny\b|色違い',text) and re.search(r'all|dex|list|全部|一覧|図鑑',text):
        return dict(result,task='classification_evidence_needed',status='blocked',
                    required_evidence=['source_bound_shiny_depiction_and_card_type_annotations'],
                    next_question='Should we scope the shiny depiction checklist to a release? Shiny Pokémon, shiny paper, Radiant and Shining card types need distinct evidence.')
    if re.search(r'black star.*white|黒.*星.*白|白.*星.*黒',text):
        return dict(result,task='release_variant_evidence_needed',status='blocked',
                    required_evidence=['printed_release_code_and_number','source_bound_variant_table_or_copy_photos'],
                    next_question='Share the printed set code and number for the two copies. Star color alone cannot determine every version in a release.')
    if (re.search(r"\bdeck\b|デッキ|卡组构筑", identity_text)
            or re.search(r"how (?:do|can|should) (?:i|we) (?:play|build|use)|how to (?:play|build)|\bcompetitive\b|\bgameplay\b|\bstrategy\b|\brules?\b|デッキ構築|使い方|遊び方|対戦|環境で|大会",text)):
        return dict(result, task="gameplay_evidence_needed", status="blocked",
                    next_question="Which game format and deck goal should be checked against a rules/card-text source?")
    artists=_artists(db,text)
    inventory=bool(re.search(r"check off|ones i (?:have|still)|what i (?:have|own)|my inventory|collected.*still need|missing (?:any|cards|some)|missing from|check my.*list|check.*linked|my current.*checklist|不足|持って|\bi (?:don['’]t|do not) already own\b",text))
    if inventory:
        result['unfulfilled_constraints'].append('owned_inventory')
        result['next_question']='Share your owned-card list and language/version scope so we can compare it with these catalog records.'
    for constraint,pattern in [
            ('external_checklist',r'linked.*(?:list|checklist)|my.*(?:checklist|catalog)|my.*missing anything'),
            ('future_language_scope',r'\bkr\b.*future|korean.*future'),
            ('sealed_opening_strategy',r'open (?:a )?sets?|pull.*then buy|until.*pull'),
            ('binder_organization_preferences',r'organiz.*binder|sort.*(?:date|language)|how.*organize'),
            ('all_language_coverage',r'(?:all|every)\s+languages?|全言語'),
            ('stamp_variants',r'stamp.*vari|stamped|スタッフ|staff'),
            ('non_card_product_request',r'(?:buy|purchase).*binder|binder.*msrp'),
            ('external_catalog_comparison',r'bulbapedia.*serebii|serebii.*bulbapedia'),
            ('jumbo_exclusion_and_specific_release_omissions',r'excludes?.*jumbo|does not include.*jumbo'),
            ('art_style_description',r'art style|イラストレーター.*特徴')]:
        if re.search(pattern,text) and not (constraint=='all_language_coverage' and 'language' in explicit):
            result['unfulfilled_constraints'].append(constraint)
    if re.search(r'\bcustoms?\b|\bcarddass\b|\btopps\b|カスタム',text):
        return dict(result,task='collection_scope_needed',status='clarification_needed',
                    required_evidence=['physical_TCG_vs_custom_or_other_product_scope','owned_inventory_if_omissions_requested'],
                    next_question='Should we first list official physical Pokémon TCG cards? Custom and other product lines need their own sources; share your inventory to check omissions.')
    edition=bool(re.search(r'first[ -]edition|\b1st\b|unlimited|初版',text))
    graded=bool(re.search(r'\b(?:psa|bgs|cgc|ars|pgc)\b|graded|grading|鑑定|评级',text))
    if graded or (edition and len(artists)!=1):
        return dict(result, task='copy_evidence_needed', status='blocked',
                    required_evidence=['exact_base_printing','edition_or_grading_copy_evidence'],
                    next_question='This catalog cannot verify edition or a graded copy. Which base printing should we explore before reviewing copy evidence?')
    if edition:result['unfulfilled_constraints'].append('edition_variants')
    exclusive=bool(re.search(r'exclusiv|only released in japan|only printed in english|only.*language.*printed|never made it to america|日本限定|海外未発売',text))
    if exclusive and len(artists)!=1:
        return dict(result,task='regional_evidence_needed',status='blocked',
                    required_evidence=['verified_regional_release_and_artwork_coverage'],
                    next_question='Which exact artwork or release should we compare? Missing catalog matches do not establish regional exclusivity.')
    if exclusive:result['unfulfilled_constraints'].append('regional_exclusivity')
    explicit_family=bool(re.search(r'family|evolution|進化|进化|家族',text))
    cameo=bool(re.search(r'cameo|in (?:the )?(?:card )?art\b|appears in|appearances|カメオ|客串|映って|写って|写りこん|写り込',text))
    if cameo and not explicit_family:
        focus=re.search(r'カード名に(.+?)(?:と書|という|が)',text)
        target_ids=_character_ids(db,focus[1] if focus else identity_text)
        if len(target_ids)==1:
            ids,leads=collector_evidence.artwork_candidates(db,target_ids,languages)
            # Depictions do not transfer across releases, numbers or finishes.
            pool=sorted(set(ids)|{r['subject_id'] for r in leads})
            if pool:
                candidate_rows=_rows(db,'c.card_id IN ('+','.join('?' for _ in pool)+')',tuple(pool))
                codes=release_codes()
                numbers={explicit['collector_number']} if 'collector_number' in explicit else {core.normalize_collector_number(n).upper() for n in re.findall(r'\b\d{1,3}/[a-z0-9\-]+\b',text)}
                exact=re.search(r'\b(ja|en):([a-z0-9.\-]+):([^\s:]+):([a-z0-9_\-]+)',text)
                exact_id=core.card_id(exact[1],exact[2],exact[3].upper(),exact[4]) if exact else None
                allowed=set()
                for row in candidate_rows:
                    if codes and row['set_code'] not in codes:continue
                    if numbers and row['collector_number'] not in numbers:continue
                    if exact_id and row['card_id']!=exact_id:continue
                    filtered=_finish_result(db,dict(result,task='artwork_evidence_needed'),[row],1,0)
                    if filtered['cards']:allowed.add(row['card_id'])
                ids=[cid for cid in ids if cid in allowed]
                leads=[r for r in leads if r['subject_id'] in allowed]
            if ids:
                rows=_rows(db,'c.card_id IN ('+','.join('?' for _ in ids)+')',tuple(ids))
                partial=_finish_result(db,dict(result,task='artwork_evidence_needed',status='scoped_artwork_partial',
                    required_evidence=['expanded_source_bound_artwork_coverage'],
                    next_question='These official descriptions support a partial cameo list. Which release should we inspect next?',
                    artwork_review_leads=leads,requested_depicted_dex_ids=target_ids),rows,limit,offset,_row_capture=_row_capture)
                partial['coverage']['artwork_cameos_supported']=True
                partial['unfulfilled_constraints'].append('artwork_coverage_completeness')
                return partial
            if leads:
                return dict(result,task='artwork_evidence_needed',status='artwork_review_needed',
                    artwork_review_leads=leads,requested_depicted_dex_ids=target_ids,
                    required_evidence=['independent_depiction_review','expanded_source_bound_artwork_coverage'],
                    next_question='Inspect these source-bound AI artwork leads before adding them to a confirmed collection checklist.')
        return dict(result,task='artwork_evidence_needed',status='blocked',
                    required_evidence=['verified_depicted_character_artwork_annotations'],
                    next_question='Which depicted character should we inspect first? Subject-card metadata cannot verify cameo appearances; those need source-bound artwork evidence.')

    cid = re.search(r"\b(ja|en):([a-z0-9.\-]+):([^\s:]+):([a-z0-9_\-]+)", text)
    if cid:
        card_id = core.card_id(cid[1], cid[2], cid[3].upper(), cid[4])
        card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
        if card is None:
            return dict(result, task="exact_coordinates", status="no_match", next_question="Please check the printed language, set, number and version.")
        neighborhood = discovery_graph.card_neighborhood(db, card_id)
        if re.search(r"same artwork|same art|同画|同插画|同じイラスト", text):
            task, kinds = "same_artwork", {"same_artwork", "localization_counterpart"}
        elif re.search(r"counterpart|对应|対応|(?:english|japanese) (?:version|equivalent)\b", text):
            task, kinds = "counterpart", {"localization_counterpart"}
        else:
            ids = [card_id] + [r["card_id"] for r in neighborhood["variants_at_number"]]
            rows = _rows(db, "c.card_id IN (" + ",".join("?" for _ in ids) + ") AND c.language IN (" + ",".join("?" for _ in languages) + ")", (*ids,*languages))
            return _finish_result(db, dict(result, task="printing_variants", status="results" if rows else "no_match",
                   claim_basis="same language, set and number; physical finish remains source-declared"), rows, limit, offset,_row_capture=_row_capture)
        verified = [r for r in neighborhood["relationships"] if r["relation_type"] in kinds
                    and r["other_language"] in languages and r["other_language"] != card["language"]]
        proposed = [r for r in neighborhood["ai_artwork_candidates"]
                    if r["other_language"] in languages and r["other_language"] != card["language"]]
        return dict(result, task=task, status="verified_links_available" if verified else "relationship_review_needed",
                    verified_links=verified, proposed_artwork_leads=proposed,
                    price_comparable=False, next_question=None if verified else
                    "Would you like to inspect the source-bound, unverified artwork leads?")

    # A counterpart question does not become a base-card purchase request just
    # because the user adds coordinates or narrows the browsing language.
    if re.search(r'counterpart|(?:english|japanese) (?:version|equivalent)\b|英語版.*(?:ある|存在)|対応する.*(?:英語|日本語)',text):
        return dict(result,task='cross_language_relation',status='blocked',price_comparable=False,
                    required_evidence=['exact_base_printing_coordinates','verified_card_level_localization_relationship'],
                    next_question='Confirm the original card’s printed language, release, number and version. A translated name or shared number cannot establish an English/Japanese counterpart; verified card-level relationship evidence is needed.')
    numbers = {explicit['collector_number']} if 'collector_number' in explicit else set(re.findall(r"\b\d{1,3}/[a-z0-9\-]+\b", text))
    if numbers:
        if len(numbers) != 1:
            return dict(result, task="need_release_scope", next_question="Which one printed card number should we inspect first?")
        number = core.normalize_collector_number(next(iter(numbers))).upper()
        sets = release_codes()
        if len(sets) != 1:
            return dict(result, task="need_release_scope", next_question="Which printed set code or release name accompanies that number?")
        code = next(iter(sets)); marks = ",".join("?" for _ in languages)
        rows = _rows(db, f"c.set_code=? AND c.collector_number=? AND c.language IN ({marks})",
                     (code, number, *languages))
        # An explicit card name is an additional identity constraint, never ignored.
        named_ids = _character_ids(db, identity_text)
        if named_ids:
            rows = [r for r in rows if _mentioned(text,r["name"]) or db.execute(f"SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} WHERE card_id=? AND facet_type='dex_id' AND CAST(value AS INTEGER) IN (" +
                        ",".join("?" for _ in named_ids) + ")", (r["card_id"], *named_ids)).fetchone()]
        status = "target_candidate" if len(rows) == 1 else "printing_clarification_needed" if rows else "no_match"
        return _finish_result(db, dict(result, task="exact_coordinates", status=status,
                  next_question="Confirm this catalog printing before evaluating a marketplace copy." if len(rows)==1 else
                  "Which language and physical finish do you mean?"), rows, limit, offset,_row_capture=_row_capture)

    if artists or re.search(r"\bartist\b|illustrat|イラストレーター|画師|绘师|插画师", text):
        if len(artists) != 1:
            return dict(result, task="artist_cards", next_question="Which illustrator's credited name do you mean?")
        marks = ",".join("?" for _ in languages)
        where=f"c.language IN ({marks}) AND EXISTS(SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} f WHERE f.card_id=c.card_id AND f.facet_type='illustrator' AND f.value=?)"
        params=[*languages,artists[0]]
        named_ids=_character_ids(db,identity_text)
        if named_ids and re.search(r"\b(?:not|except|without|excluding)\b|以外|除外|不要|不是",text):
            return dict(result,task='collection_scope_needed',status='clarification_needed',
                unfulfilled_constraints=['negative_collection_scope_confirmation'],
                next_question='Clarify which character and illustrator to include or exclude; the negative conjunction was not applied.')
        if named_ids:
            from . import collector_character_affiliation
            affiliations=collector_character_affiliation.affiliations(db)
            derived_ids=sorted(cid for cid,a in affiliations.items() if a['dex_id'] in named_ids)
            species=f"c.card_id IN (SELECT card_id FROM {collector_runtime.facet_lookup_relation(db)} WHERE facet_type='dex_id' AND value IN ("+','.join('?' for _ in named_ids)+'))'
            params.extend(map(str,named_ids))
            if derived_ids:
                species+=' OR c.card_id IN ('+','.join('?' for _ in derived_ids)+')';params.extend(derived_ids)
            where+=' AND ('+species+')'
        rows = _rows(db,where,tuple(params))
        if named_ids:
            result['character_name_affiliations']=[affiliations[r['card_id']] for r in rows if r['card_id'] in affiliations]
        return _finish_result(db, dict(result, task="artist_cards", status="results", illustrator=artists[0],
                        claim_basis="pinned source illustrator credits" if not named_ids else 'source character and illustrator intersection',
                        next_question=result.get('next_question') if rows else 'No current catalog record satisfies the requested character and illustrator together. Explicitly relax either constraint to broaden the search.'), rows, limit, offset,_row_capture=_row_capture)

    qualifiers=_qualifier_findings(db,text,languages)
    if _unsupported_professors(db,text):
        return dict(result,task='printed_qualifier_evidence_needed',status='blocked',required_evidence=['source_bound_requested_professor_subtitle'],next_question='That named professor subtitle is not supported in the requested scope. Confirm the printed release and number before selecting a target.')
    if qualifiers:
        if len(qualifiers)!=1 or not qualifiers[0]['active']:
            return dict(result,task='printed_qualifier_evidence_needed',status='blocked',required_evidence=['current_source_bound_qualified_title'],next_question='Choose one printed professor subtitle and confirm its language/set/number; stale or multiple source readings cannot select a target.')
        ids=qualifiers[0]['card_ids'];rows=_rows(db,'c.card_id IN ('+','.join('?' for _ in ids)+')',tuple(ids))
        return _finish_result(db,dict(result,task='qualified_title_cards',status='results',claim_basis='exact publisher printed subtitle; source seed/main HTML title retained',qualified_title_evidence=qualifiers[0]),rows,limit,offset,_row_capture=_row_capture)

    if _mentioned(text,'博士の研究'):
        return dict(result,task='printed_qualifier_scope_needed',status='clarification_needed',required_evidence=['printed_professor_subtitle_and_language_set_number'],next_question='Which printed professor subtitle and release number do you mean? The generic main title does not identify one professor or printing.')

    ids = _character_ids(db, identity_text)
    sets=release_codes()
    if (sets and ids and not explicit_family and not release_context
            and not re.search(r'\bcharacter\b|\bspecies\b',text)
            and not _character_ids(db,_without_release_names(db,text,languages))):
        return dict(result,task='need_release_scope',next_question='Do you mean that release title or a character? State the printed release code or ask for cards from the named set.')
    if sets and not ids and not explicit_family:
        if len(sets)!=1:
            return dict(result,task='need_release_scope',next_question='Which one language-specific release should we inspect first?')
        code=next(iter(sets));marks=','.join('?' for _ in languages)
        rows=_rows(db,f'c.set_code=? AND c.language IN ({marks})',(code,*languages))
        return _finish_result(db,dict(result,task='set_cards',status='results' if rows else 'no_match',
                              claim_basis='pinned language-specific release records and source-declared variants'),rows,limit,offset,_row_capture=_row_capture)
    family_task = explicit_family
    if family_task:
        families = {r[0] for i in ids for r in db.execute("SELECT family_id FROM character_family_member WHERE dex_id=?", (i,))}
        if len(families) != 1:
            return dict(result, task="family_evidence_needed", next_question="Which family should be checked? Currently sourced families are Ralts, Eevee and Pikachu.")
        family_id = next(iter(families))
        record = json.loads(db.execute("SELECT record_json FROM character_family WHERE family_id=?", (family_id,)).fetchone()[0])
        ids = [m["dex_id"] for m in record["members"]]
        result.update(task="family_checklist", status="results", family_id=family_id,
                      family=record, claim_basis="official species family joined to pinned card character IDs",
                      unsupported_requested_dimensions=[label for label,pattern in
                         [("artwork_cameos",r"cameo|カメオ|客串"),("paradox_relationships",r"iron valiant|テツノブジン|铁武者"),
                          ("exhaustive_promos",r"all promo|全.*プロモ|全部.*promo")]
                         if re.search(pattern,text)])
    elif len(ids) == 1:
        result.update(task="character_cards", status="results", dex_ids=ids,
                      claim_basis="source character ID; not shared artwork or cross-region counterpart")
    else:
        return dict(result, task="need_character_or_coordinates",required_evidence=['explicit_character_artist_or_release_scope'],
                    next_question="Which character, illustrator or printed set/number should I search? Multiple characters or an unnamed checklist need a clear collection scope.")
    marks, lmarks = ",".join("?" for _ in ids), ",".join("?" for _ in languages)
    rows = _rows(db, f"c.language IN ({lmarks}) AND EXISTS(SELECT 1 FROM {collector_runtime.facet_lookup_relation(db)} f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ({marks}))",
                 (*languages, *ids))
    return _finish_result(db, result, rows, limit, offset,_row_capture=_row_capture)
