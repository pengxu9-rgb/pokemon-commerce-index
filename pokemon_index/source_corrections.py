"""Source-bound printed fact corrections; raw seeds/history remain immutable."""
from __future__ import annotations
import json,re
from . import core,printing_evidence,supported_catalog,number_graph

FALSE_CLAIMS=printing_evidence.FALSE_CLAIMS
KINDS={'printed_artist','printed_qualifier','reference_boundary'}


def snapshot(db,language,code,number):
    cards=[dict(r) for r in db.execute('SELECT * FROM card WHERE language=? AND set_code=? AND collector_number=? ORDER BY card_id',(language,code,number))]
    refs=[dict(r) for r in db.execute('SELECT * FROM card_reference WHERE set_code=? AND collector_number=? ORDER BY source,native_id',(code,number))]
    facets=[dict(r) for r in db.execute('SELECT f.* FROM card_facet f JOIN card c ON c.card_id=f.card_id WHERE c.language=? AND c.set_code=? AND c.collector_number=? ORDER BY f.card_id,f.facet_type,f.value',(language,code,number))]
    return dict(cards=cards,references=refs,facets=facets)


def event_id(row):return 'source-correction:'+supported_catalog.digest({k:v for k,v in row.items() if k!='event_id'})


def _parent(db,row):
    r=db.execute('SELECT * FROM printing_source_evidence WHERE event_id=?',(row['parent_event_id'],)).fetchone()
    if not r or r['record_json']!=row['parent_record_json'] or supported_catalog.digest(json.loads(r['record_json']))!=row['parent_record_sha256']:
        raise ValueError('correction parent differs from imported source readings')
    parent=json.loads(r['record_json'])
    latest=db.execute('SELECT event_id FROM printing_source_evidence WHERE subject_kind=? AND subject_id=? ORDER BY revision DESC LIMIT 1',(parent['subject_kind'],parent['subject_id'])).fetchone()
    if latest[0]!=parent['event_id'] or parent['subject_kind']!='coordinate' or parent['subject_id']!=':'.join(row[k] for k in ('language','set_code','collector_number')):
        raise ValueError('correction parent is superseded or outside coordinate')
    if supported_catalog.digest(printing_evidence.identity(db,'coordinate',parent['subject_id']))!=parent['identity_sha256']:
        raise ValueError('printing source identity is stale')
    reviewers=parent['reviewers']
    if len(reviewers)<2 or len({x['actor'] for x in reviewers})!=len(reviewers) or any(x['method']!='direct_image_reading' for x in reviewers):
        raise ValueError('printed correction needs two actual distinct image reviewers')
    return parent


def import_evidence(db,rows):
    prepared=[]
    for r in rows:
        expected={'schema','event_id','correction_key','revision','kind','language','set_code','collector_number','snapshot','parent_event_id','parent_record_json','parent_record_sha256','value','reference_exclusion','new_card','new_reference','official_page','recorded_at'}|set(FALSE_CLAIMS)
        if set(r)!=expected or r['schema']!='pokemon.source-correction.v1' or r['kind'] not in KINDS or r['language']!='ja':raise ValueError('invalid source correction schema')
        if any(r[k] is not False for k in FALSE_CLAIMS):raise ValueError('source corrections cannot approve physical or commerce claims')
        if type(r['revision']) is not int or r['revision']<1 or r['event_id']!=event_id(r):raise ValueError('source correction digest/revision invalid')
        if r['correction_key']!=':'.join(r[k] for k in ('kind','language','set_code','collector_number')):raise ValueError('correction key differs from scope')
        if snapshot(db,r['language'],r['set_code'],r['collector_number'])!=r['snapshot'] or not r['snapshot']['cards']:raise ValueError('source correction snapshot is stale')
        created=core.parse_time(r['recorded_at']);parent=_parent(db,r)
        if created<max(core.parse_time(parent['recorded_at']),*(core.parse_time(x['reviewed_at']) for x in parent['reviewers'])):
            raise ValueError('correction cannot predate its source reviews')
        refs={'https://www.pokemon-card.com/card-search/details.php/card/'+x['native_id'] for x in r['snapshot']['references']}
        if r['kind'] in {'printed_artist','printed_qualifier'}:
            readings=[o for o in parent['observations'] if o['claim']==r['kind']]
            if (parent['status']!='source_observed' or not refs or {o['source_url'] for o in readings}!=refs or {o['value'] for o in readings}!={r['value']} or not isinstance(r['value'],str) or not r['value'].strip()):
                raise ValueError('correction value lacks complete exact printed evidence')
            if any(r[k] is not None for k in ('reference_exclusion','new_card','new_reference','official_page')):raise ValueError('printed fact cannot create a card/reference')
        else:
            card=r['new_card'];ref=r['new_reference'];ex=r['reference_exclusion'];page=r['official_page']
            if r['value'] is not None or parent['status']!='evidence_hold' or not isinstance(card,dict) or not isinstance(ref,dict) or not isinstance(ex,dict) or not isinstance(page,dict):raise ValueError('reference boundary needs preserved wrong-source hold and new family evidence')
            if set(card)!={'card_id','language','set_code','collector_number','variant','name','rarity','provenance','rights_reference','display_allowed','match_eligible','attributes_json'} or set(ref)!={'source','native_id','set_code','collector_number','name','rarity','attributes_json','provenance','rights_reference','display_allowed'}:
                raise ValueError('new family fields differ from exact schema')
            old=[x for x in r['snapshot']['references'] if all(x.get(k)==v for k,v in ex.items())]
            if len(old)!=1 or set(ex)!={'source','native_id','set_code','collector_number'}:raise ValueError('wrong reference is outside raw source snapshot')
            coord={k:card[k] for k in ('language','set_code','collector_number')};url='https://www.pokemon-card.com/card-search/details.php/card/'+ex['native_id']
            numbers=[o for o in parent['observations'] if o['claim']=='printed_number' and o['source_url']==url and o['coordinate']==coord and o['value']==card['collector_number']]
            source=[s for s in parent['sources'] if s['url']==url]
            if len(numbers)!=1 or len(source)!=1 or coord['language']!='ja' or coord['set_code']!=r['set_code'] or coord['collector_number']==r['collector_number']:raise ValueError('new family number lacks exact printed correction evidence')
            if page['url']!=url or page['page_sha256']!=source[0]['page_sha256'] or page['name']!=card['name'] or len(page['numbered_entries'])!=1 or any(page['numbered_entries'][0].get(k)!=coord[k] for k in ('set_code','collector_number')):raise ValueError('new family page differs from printed source')
            if {c['name'] for c in r['snapshot']['cards']}!={card['name']} or old[0]['name']!=card['name']:
                raise ValueError('new family title needs explicit printed-name evidence when source titles differ')
            variant='official_coordinate_family_only_'+ex['native_id']
            if card['card_id']!=core.card_id('ja',r['set_code'],card['collector_number'],variant) or card['variant']!=variant or card['match_eligible']!=0 or card['display_allowed']!=0 or card['rarity'] is not None:raise ValueError('new family cannot widen identity, finish or eligibility')
            if ref['source']!='official-printed-coordinate' or ref['native_id']!=ex['native_id'] or ref['set_code']!=card['set_code'] or ref['collector_number']!=card['collector_number'] or ref['name']!=card['name'] or ref['display_allowed']!=0 or ref['rarity'] is not None:raise ValueError('new reference namespace/coordinate invalid')
            provenance='official-printed-coordinate:'+ex['native_id']+':page-sha256:'+source[0]['page_sha256']+':image-sha256:'+source[0]['image_sha256']+':parent:'+parent['event_id']
            if card['provenance']!=provenance or ref['provenance']!=provenance or card['rights_reference']!=url or ref['rights_reference']!=url:raise ValueError('new family source provenance invalid')
            attributes=dict(family_scope_only=True,parent_printing_event=parent['event_id'],source_namespace='official-printed-coordinate',physical_finish_verified=False,listing_copy_verified=False)
            if json.loads(card['attributes_json'])!=attributes or json.loads(ref['attributes_json'])!=attributes:raise ValueError('new family scope must be explicit')
            for table,payload,keys in [('card',card,('card_id',)),('card_reference',ref,('source','native_id'))]:
                stored=db.execute('SELECT * FROM '+table+' WHERE '+' AND '.join(k+'=?' for k in keys),tuple(payload[k] for k in keys)).fetchone()
                if stored and dict(stored)!=payload:raise ValueError('new family conflicts with an existing source identity')
        prepared.append((r,json.dumps(r,ensure_ascii=False,sort_keys=True)))
    with db:
        for r,encoded in prepared:
            prior=db.execute('SELECT * FROM source_correction_evidence WHERE correction_key=? ORDER BY revision DESC LIMIT 1',(r['correction_key'],)).fetchone()
            if prior and prior['event_id']==r['event_id']:
                if prior['record_json']!=encoded:raise ValueError('correction event collision')
                continue
            if r['revision']!=(prior['revision']+1 if prior else 1):raise ValueError('nonconsecutive correction revision')
            db.execute('INSERT INTO source_correction_evidence VALUES (?,?,?,?,?,?,?,?)',(r['event_id'],r['correction_key'],r['revision'],r['kind'],r['language'],r['set_code'],r['collector_number'],encoded))
            if r['kind']=='reference_boundary':
                for table,payload in [('card',r['new_card']),('card_reference',r['new_reference'])]:
                    keys=list(payload);db.execute('INSERT OR IGNORE INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(payload[k] for k in keys))
                number_graph.upsert_number_context(db,r['new_card'])
    return len(prepared)


def available(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='source_correction_evidence'").fetchone())


def context(db,cid):
    if not available(db):return None
    rows=db.execute("SELECT e.*,a.event_id active_id FROM source_correction_evidence e LEFT JOIN active_source_correction_evidence a ON a.event_id=e.event_id WHERE NOT EXISTS(SELECT 1 FROM source_correction_evidence later WHERE later.correction_key=e.correction_key AND later.revision>e.revision) AND (EXISTS(SELECT 1 FROM json_each(e.record_json,'$.snapshot.cards') j WHERE json_extract(j.value,'$.card_id')=?) OR json_extract(e.record_json,'$.new_card.card_id')=?) ORDER BY e.kind",(cid,cid)).fetchall()
    if not rows:return None
    findings=[]
    for e in rows:
        r=json.loads(e['record_json']);findings.append(dict(event_id=e['event_id'],kind=e['kind'],status='source_corrected' if e['active_id'] else 'stale_source_correction',value=r['value'],parent_event_id=r['parent_event_id'],reviewer_actors=[x['actor'] for x in json.loads(r['parent_record_json'])['reviewers']],source_coordinate=dict(language=e['language'],set_code=e['set_code'],collector_number=e['collector_number']),reference_exclusion=r['reference_exclusion'],new_family_card_id=r['new_card']['card_id'] if r['new_card'] else None))
    return dict(schema='pokemon.source-correction-context.v1',findings=findings,copy_evidence_needed=True,raw_sources_preserved=True,blind_accuracy_measured=False,**{k:False for k in FALSE_CLAIMS})


def status(db):
    if not available(db):return dict(source_correction_events=0,active_source_corrections=0,stale_source_corrections=0)
    total=db.execute('SELECT COUNT(*) FROM source_correction_evidence').fetchone()[0];latest=db.execute('SELECT COUNT(*) FROM source_correction_evidence e WHERE NOT EXISTS(SELECT 1 FROM source_correction_evidence x WHERE x.correction_key=e.correction_key AND x.revision>e.revision)').fetchone()[0];active=db.execute('SELECT COUNT(*) FROM active_source_correction_evidence').fetchone()[0]
    return dict(source_correction_events=total,active_source_corrections=active,stale_source_corrections=latest-active)


def printed_artist(db,cid):
    ctx=context(db,cid)
    return _printed_artist_from_source_correction(db,cid,ctx)


def _printed_artist_from_source_correction(db,cid,ctx):
    """Private fixed formatter; ordinary calls still validate native context."""
    if ctx:
        findings=[f for f in ctx['findings'] if f['kind']=='printed_artist']
        if findings:
            finding=findings[0]
            return dict(value=finding['value'],evidence_id=finding['event_id'],parent_event_id=finding['parent_event_id'],basis='publisher printed image; two distinct visual inspections; active source-bound SQL correction',reviewer_actors=finding['reviewer_actors'],independent_blind_accuracy_measurement=False) if finding['status']=='source_corrected' else None
    return printing_evidence.supported_artist(db,cid)


def family_scope_only(db,cid):
    """Historical publisher-family identities cannot be promoted by mutable flags."""
    card=db.execute('SELECT variant,provenance,attributes_json FROM card WHERE card_id=?',(cid,)).fetchone()
    if not card:return False
    try:flag=json.loads(card['attributes_json']).get('family_scope_only') is True
    except (ValueError,TypeError,AttributeError):flag=False
    if flag or card['variant'].startswith('official_coordinate_family_only_') or card['provenance'].startswith('official-printed-coordinate:'):return True
    return bool(available(db) and db.execute("SELECT 1 FROM source_correction_evidence WHERE json_extract(record_json,'$.new_card.card_id')=? LIMIT 1",(cid,)).fetchone())
