"""Execute a bounded set of internal collector tasks from a plain question.

This conservative interpreter asks for clarification outside its supported
patterns. It does not generate prices, infer a physical finish or call a model.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from . import core, discovery_graph, supported_catalog


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _mentioned(text: str, term: str) -> bool:
    term = _norm(term)
    if re.fullmatch(r"[a-z0-9 '\-\.]+", term):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def _languages(text: str) -> list[str]:
    ja = bool(re.search(r"japanese|\bjp\b|日本語|日文|日版|日英", text))
    en = bool(re.search(r"english|\ben\b|英語|英文|英版|日英", text))
    return ["ja", "en"] if ja == en else ["ja"] if ja else ["en"]


def _card_result(db, row) -> dict:
    card = {k:row[k] for k in ("card_id", "language", "set_code", "collector_number",
                               "variant", "name", "rarity", "provenance")}
    card.update(set_name=row["set_name"], release_date=row["release_date"],
                release_provenance=row["release_provenance"],
                structural_match_eligible=bool(row["match_eligible"]),
                support_status=supported_catalog.support_for_card(db, row["card_id"])["status"],
                price_comparable=False, automatic_offer_join_allowed=False)
    return card


def _rows(db, where: str, params: tuple) -> list:
    return db.execute(f"""SELECT c.*,s.name AS set_name,s.release_date,
              s.provenance AS release_provenance FROM card c
        LEFT JOIN catalog_set_localized s ON c.language=s.language AND c.set_code=s.set_code
        WHERE {where} ORDER BY s.release_date IS NULL OR s.release_date='',
        s.release_date,c.language,c.set_code,c.collector_number,c.variant""", params).fetchall()


def _finish_result(db, result: dict, rows: list, limit: int, offset: int) -> dict:
    text = _norm(result['question'])
    finish = None
    if re.search(r'master\s*ball|マスターボール|大师球', text):
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
    result.update(cards=[_card_result(db, r) for r in rows[offset:offset+limit]],
                  coverage={"matched_catalog_records":len(rows),
                            "returned":len(rows[offset:offset+limit]), "offset":offset,
                            "limit":limit, "has_more":offset+limit<len(rows),
                            "undated_records":sum(not r["release_date"] for r in rows),
                            "release_metadata_missing":sum(not r["set_name"] for r in rows),
                            "global_printing_completeness_established":False,
                            "missing_character_facets_excluded":True,
                            "artwork_cameos_supported":False},
                  ordering="release date ascending; unknown dates last; stable printing coordinates")
    return result


def _character_ids(db, text: str) -> list[int]:
    # One character facet only: a team card name cannot name a single species.
    aliases = db.execute("""SELECT c.name,CAST(MIN(f.value) AS INTEGER) AS dex_id
        FROM card c JOIN card_facet f ON f.card_id=c.card_id AND f.facet_type='dex_id'
        GROUP BY c.card_id HAVING COUNT(DISTINCT f.value)=1""").fetchall()
    ids = set()
    for row in aliases:
        if len(row["name"]) >= 3 and _mentioned(text, row["name"]):
            ids.add(row["dex_id"])
    for row in db.execute("SELECT * FROM character_family_member"):
        if _mentioned(text, row["name_en"]) or _mentioned(text, row["name_ja"]):
            ids.add(row["dex_id"])
    return sorted(ids)


def execute(db: sqlite3.Connection, question: str, *, limit: int = 50,
            offset: int = 0) -> dict:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError("question must contain 1–2000 characters")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("invalid collector pagination")
    text = _norm(question); languages = _languages(text)
    result = {"schema":"pokemon.collector-discovery.v1", "question":question,
              "languages":languages, "task":None, "status":"clarification_needed",
              "cards":[], "next_question":None,
              "market_status":"no_live_market_evidence", "live_offers":[],
              "prices":[], "public_display_allowed":False,
              "scope":"Internal catalog results; printing/character membership is not physical-copy, availability or price evidence"}
    if re.search(r'\bkorean\b|\bfrench\b|\bgerman\b|\bchinese\b|韓国語|韓版|法文|德文|中文版', text):
        return dict(result, task='unsupported_language', status='unsupported_scope',
                    next_question='This executor currently searches Japanese and English catalog records. Which of those should we inspect?')
    if re.search(r"yugioh|yu-?gi-?oh|magic the gathering|遊戯王|游戏王", text):
        return dict(result, task="unsupported_game", status="unsupported_scope",
                    next_question="Would you like to search physical Pokémon TCG cards?")
    if re.search(r"\bprice\b|cheapest|\bcheaper\b|\bmerchant\b|\bprofit\b|\bpopular\b|\bworth\b|価格|相場|いくら|買取|价格|价差|到手价", text):
        return dict(result, task="market_evidence_needed", status="blocked",
                    required_evidence=["exact_printing_target", "authorized_fresh_offers_or_relevant_market_evidence"],
                    next_question="Which exact printing should we track when an authorized feed is available?")
    if re.search(r"\bdeck\b|デッキ|卡组构筑", text):
        return dict(result, task="gameplay_evidence_needed", status="blocked",
                    next_question="Which game format and deck goal should be checked against a rules/card-text source?")
    if re.search(r'first[ -]edition|\b1st\b|unlimited|初版|\b(?:psa|bgs|cgc|ars|pgc)\b|graded|鑑定|评级', text):
        return dict(result, task='copy_evidence_needed', status='blocked',
                    next_question='This catalog cannot verify edition or a graded copy. Which base printing should we explore before reviewing copy evidence?')

    cid = re.search(r"\b(ja|en):([a-z0-9.\-]+):([^\s:]+):([a-z0-9_\-]+)", text)
    if cid:
        card_id = core.card_id(cid[1], cid[2], cid[3].upper(), cid[4])
        card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
        if card is None:
            return dict(result, task="exact_coordinates", status="no_match", next_question="Please check the printed language, set, number and version.")
        neighborhood = discovery_graph.card_neighborhood(db, card_id)
        if re.search(r"same artwork|same art|同画|同插画|同じイラスト", text):
            task, kinds = "same_artwork", {"same_artwork", "localization_counterpart"}
        elif re.search(r"counterpart|对应|対応", text):
            task, kinds = "counterpart", {"localization_counterpart"}
        else:
            ids = [card_id] + [r["card_id"] for r in neighborhood["variants_at_number"]]
            rows = _rows(db, "c.card_id IN (" + ",".join("?" for _ in ids) + ") AND c.language IN (" + ",".join("?" for _ in languages) + ")", (*ids,*languages))
            return _finish_result(db, dict(result, task="printing_variants", status="results" if rows else "no_match",
                   claim_basis="same language, set and number; physical finish remains source-declared"), rows, limit, offset)
        verified = [r for r in neighborhood["relationships"] if r["relation_type"] in kinds
                    and r["other_language"] in languages and r["other_language"] != card["language"]]
        proposed = [r for r in neighborhood["ai_artwork_candidates"]
                    if r["other_language"] in languages and r["other_language"] != card["language"]]
        return dict(result, task=task, status="verified_links_available" if verified else "relationship_review_needed",
                    verified_links=verified, proposed_artwork_leads=proposed,
                    price_comparable=False, next_question=None if verified else
                    "Would you like to inspect the source-bound, unverified artwork leads?")

    numbers = set(re.findall(r"\b\d{1,3}/[a-z0-9\-]+\b", text))
    if numbers:
        if len(numbers) != 1:
            return dict(result, task="need_release_scope", next_question="Which one printed card number should we inspect first?")
        number = core.normalize_collector_number(next(iter(numbers))).upper()
        sets = {r[0] for r in db.execute("SELECT DISTINCT set_code FROM card") if _mentioned(text, r[0])}
        for row in db.execute("SELECT * FROM catalog_vocabulary"):
            if _mentioned(text, row["alias"]):
                sets.add(row["set_code"])
        if len(sets) != 1:
            return dict(result, task="need_release_scope", next_question="Which printed set code or release name accompanies that number?")
        code = next(iter(sets)); marks = ",".join("?" for _ in languages)
        rows = _rows(db, f"c.set_code=? AND c.collector_number=? AND c.language IN ({marks})",
                     (code, number, *languages))
        # An explicit card name is an additional identity constraint, never ignored.
        named_ids = _character_ids(db, text)
        if named_ids:
            rows = [r for r in rows if _mentioned(text,r["name"]) or db.execute("SELECT 1 FROM card_facet WHERE card_id=? AND facet_type='dex_id' AND CAST(value AS INTEGER) IN (" +
                        ",".join("?" for _ in named_ids) + ")", (r["card_id"], *named_ids)).fetchone()]
        status = "target_candidate" if len(rows) == 1 else "printing_clarification_needed" if rows else "no_match"
        return _finish_result(db, dict(result, task="exact_coordinates", status=status,
                  next_question="Confirm this catalog printing before evaluating a marketplace copy." if len(rows)==1 else
                  "Which language and physical finish do you mean?"), rows, limit, offset)

    if re.search(r"\bartist\b|illustrat|画師|绘师|插画师", text):
        artists = [r[0] for r in db.execute("SELECT DISTINCT value FROM card_facet WHERE facet_type='illustrator'")
                   if _mentioned(text, r[0])]
        if len(artists) != 1:
            return dict(result, task="artist_cards", next_question="Which illustrator's credited name do you mean?")
        marks = ",".join("?" for _ in languages)
        rows = _rows(db, f"c.language IN ({marks}) AND EXISTS(SELECT 1 FROM card_facet f WHERE f.card_id=c.card_id AND f.facet_type='illustrator' AND f.value=?)",
                     (*languages, artists[0]))
        return _finish_result(db, dict(result, task="artist_cards", status="results", illustrator=artists[0],
                        claim_basis="pinned source illustrator credits"), rows, limit, offset)

    ids = _character_ids(db, text)
    family_task = bool(re.search(r"family|evolution|checklist|chronolog|release order|進化|一覧|チェックリスト|进化|家族|时间顺序", text))
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
        return dict(result, task="need_character_or_coordinates", next_question="Which character, illustrator or printed set/number should I search?")
    marks, lmarks = ",".join("?" for _ in ids), ",".join("?" for _ in languages)
    rows = _rows(db, f"c.language IN ({lmarks}) AND EXISTS(SELECT 1 FROM card_facet f WHERE f.card_id=c.card_id AND f.facet_type='dex_id' AND CAST(f.value AS INTEGER) IN ({marks}))",
                 (*languages, *ids))
    return _finish_result(db, result, rows, limit, offset)
