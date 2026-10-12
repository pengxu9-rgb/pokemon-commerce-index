"""Advisory source-scan facts; literal text and interpretation stay separate.

These observations expose metadata conflicts and name correspondence. They
never replace independent number qualification or physical identity evidence.
"""
from __future__ import annotations
import json,re,unicodedata
from . import core,number_evidence,supported_catalog

SCHEMA='pokemon.source-image-fact-evidence.v1'
FALSE_CLAIMS=number_evidence.FALSE_CLAIMS+('independent_accuracy_established',
    'independent_review_agreement_established')
READING_FIELDS={'title_text_parts','title_symbols','title_furigana','observed_number_text','hp','hp_status','notes'}
REVIEW_FIELDS={'actor','model_family','model_version','reviewed_at','review_record_sha256',
    'source_ref','image_sha256','prior_verdicts_visible','expected_catalog_context_visible','reading'}
RULE='ja-basic-energy-title-symbol-and-furigana-v1'

def compact(s):return re.sub(r'\s+','',unicodedata.normalize('NFKC',s))

def validate_reading(r):
    if not isinstance(r,dict) or set(r)!=READING_FIELDS:raise ValueError('invalid image fact reading fields')
    if not isinstance(r['title_text_parts'],list) or len(r['title_text_parts'])>10:raise ValueError('invalid title parts')
    for part in r['title_text_parts']:number_evidence._text(part)
    if not isinstance(r['title_symbols'],list) or len(r['title_symbols'])>5:raise ValueError('invalid title symbols')
    positions=[]
    for symbol in r['title_symbols']:
        if not isinstance(symbol,dict) or set(symbol)!={'kind','after_text_part'}:raise ValueError('invalid title symbol')
        if symbol['kind'] not in {'grass','fire','prism_star','unknown'}:raise ValueError('unsupported title symbol')
        at=symbol['after_text_part']
        if type(at)!=int or not 0<=at<len(r['title_text_parts']):raise ValueError('title symbol position outside text')
        positions.append(at)
    if len(set(positions))!=len(positions) or positions!=sorted(positions):raise ValueError('duplicate or unordered title symbols')
    for key in ['title_furigana','observed_number_text']:
        if r[key] is not None:number_evidence._text(r[key])
    if r['hp_status'] not in {'visible','absent','unreadable'}:raise ValueError('invalid HP status')
    if r['hp_status']=='visible':
        if type(r['hp'])!=int or not 1<=r['hp']<=9999:raise ValueError('invalid visible HP')
    elif r['hp'] is not None:raise ValueError('absent or unreadable HP must be null')
    if not isinstance(r['notes'],str) or len(r['notes'])>4000:raise ValueError('invalid image fact notes')

def title_interpretation(r):
    validate_reading(r)
    literal=''.join(r['title_text_parts']) or None
    symbols=r['title_symbols']
    if not symbols:return dict(literal_text=literal,canonical_candidate=literal,normalization_rule=None)
    candidate=None
    if [compact(t) for t in r['title_text_parts']]==['基本','エネルギー'] and len(symbols)==1 and symbols[0]['after_text_part']==0:
        mapping={'grass':('草','きほんくさ'),'fire':('炎','きほんほのお')}
        rule=mapping.get(symbols[0]['kind'])
        if rule and r['title_furigana'] is not None and compact(r['title_furigana'])==rule[1]:
            candidate='基本'+rule[0]+'エネルギー'
    return dict(literal_text=literal,canonical_candidate=candidate,normalization_rule=RULE if candidate else None)

def outcomes(row):
    reviews=row['reviews'];readings=[r['reading'] for r in reviews]
    titles=[title_interpretation(r) for r in readings]
    candidates=[t['canonical_candidate'] for t in titles]
    name_agrees=all(n is not None and core._compact_identity_text(n)==core._compact_identity_text(row['endpoint_snapshot']['name']) for n in candidates)
    # The exact symbolic structure must agree too: a literal expanded word is
    # not interchangeable with an icon merely because both yield the same name.
    structure=[title_structure(r) for r in readings]
    name_agrees=name_agrees and structure[0]==structure[1]
    name_status=('symbol_correspondence_advisory' if any(t['normalization_rule'] for t in titles) else 'literal_correspondence_advisory') if name_agrees else 'unconfirmed'
    states=[r['hp_status'] for r in readings];values=[r['hp'] for r in readings];pinned=row['pinned_source_hp']
    if states==['absent','absent']:hp_status='no_hp_observed' if pinned is None else 'source_hp_without_visible_header'
    elif states==['visible','visible'] and values[0]==values[1]:
        hp_status='source_hp_unknown' if pinned is None else 'source_hp_agrees' if values[0]==pinned else 'source_hp_conflict'
    else:hp_status='hp_unconfirmed'
    warnings=[]
    if name_status=='unconfirmed':warnings.append('source_image_name_unconfirmed')
    if hp_status in {'source_hp_conflict','source_hp_without_visible_header'}:warnings.append(hp_status)
    keys=[number_evidence.reading_key(r['observed_number_text']) for r in readings]
    return dict(name_status=name_status,title_interpretations=titles,
        hp_status=hp_status,observed_hp=values[0] if states==['visible','visible'] and values[0]==values[1] else None,
        observed_number_agreement=keys[0] is not None and keys[0]==keys[1],warnings=warnings)

def title_structure(reading):
    """Ignore text-fragment boundaries, preserving each symbol's text anchor."""
    validate_reading(reading)
    symbols={s['after_text_part']:s['kind'] for s in reading['title_symbols']}
    sequence=[];text=''
    for i,part in enumerate(reading['title_text_parts']):
        # Keep literal reviews intact; normalize only typographic apostrophes
        # in this comparison key, never trainer names or mechanic markers.
        text+=compact(part).translate(str.maketrans({'’':"'",'‘':"'"}))
        if i in symbols:
            sequence.extend([('text',re.sub(r'eX$','ex',text)),('symbol',symbols[i])]);text=''
    # Mixed-case eX is the OCR rendering of a stylized ex suffix. Preserve
    # legacy all-capital EX and every other mechanic marker and literal name.
    if text:sequence.append(('text',re.sub(r'eX$','ex',text)))
    return sequence


def notation_context(row):
    """Describe literal mechanics and multiple numbers without choosing a SKU."""
    readings=[r['reading'] for r in row['reviews']]
    structures=[title_structure(r) for r in readings]
    prism=all(len(r['title_symbols'])==1 and r['title_symbols'][0]['kind']=='prism_star' for r in readings) and structures[0]==structures[1]
    base=all(core._compact_identity_text(''.join(r['title_text_parts']))==core._compact_identity_text(row['endpoint_snapshot']['name']) for r in readings)
    scopes=[]
    for r in readings:
        text=r['observed_number_text']
        parts=[]
        if text is not None and re.fullmatch(r'\s*\d{1,6}\s*/\s*\d{1,6}(?:\s*[,;]\s*|\s+)(?:\d{1,6}\s*/\s*\d{1,6})(?:(?:\s*[,;]\s*|\s+)\d{1,6}\s*/\s*\d{1,6})*\s*',text):
            parts=re.findall(r'\d{1,6}\s*/\s*\d{1,6}',text)
        scopes.append(dict(raw_text=text,complete_fraction_candidates=parts))
    return dict(schema='pokemon.source-image-notation-context.v1',
        title_mechanic='prism_star_observed_by_both' if prism else 'unconfirmed_or_other',
        base_title_catalog_correspondence=base if prism else None,
        title_symbol_anchors_agree=structures[0]==structures[1],
        number_layout='multiple_complete_fractions_observed' if any(x['complete_fraction_candidates'] for x in scopes) else 'single_or_unparsed',
        number_scope_candidates=scopes,
        number_namespace_assignment_established=False,catalog_mechanic_binding_established=False,
        print_run_quantity_established=False,identity_qualification_changed=False,physical_printing_verified=False,price_comparable=False)

def event_id(row):return 'source-image-fact:'+supported_catalog.digest({k:v for k,v in row.items() if k!='event_id'})

def validate(row):
    fields={'schema','event_id','revision','card_id','endpoint_snapshot','identity_sha256','source_ref','image_sha256',
        'source_file_sha256','pinned_source_hp','cohort_snapshot_sha256','reviews','recorded_at'}|set(FALSE_CLAIMS)
    if not isinstance(row,dict) or set(row)!=fields or row['schema']!=SCHEMA:raise ValueError('invalid image fact event schema')
    if type(row['revision'])!=int or row['revision']<1 or row['event_id']!=event_id(row):raise ValueError('invalid image fact event identity')
    if any(row[k] is not False for k in FALSE_CLAIMS):raise ValueError('image facts cannot approve identity or independent review')
    snap=row['endpoint_snapshot']
    if not isinstance(snap,dict) or set(snap)!=set(number_evidence.FIELDS) or snap['card_id']!=row['card_id']:raise ValueError('image fact endpoint mismatch')
    for k in ['identity_sha256','image_sha256','source_file_sha256','cohort_snapshot_sha256']:number_evidence._sha(row[k])
    if supported_catalog.digest(snap)!=row['identity_sha256']:raise ValueError('image fact endpoint hash differs')
    if not snap['provenance'].endswith(':sha256:'+row['source_file_sha256']):raise ValueError('HP source pin differs from endpoint')
    if row['pinned_source_hp'] is not None and (type(row['pinned_source_hp'])!=int or not 1<=row['pinned_source_hp']<=9999):raise ValueError('invalid pinned HP')
    number_evidence._source(row['source_ref']);end=core.parse_time(row['recorded_at'])
    if not isinstance(row['reviews'],list) or len(row['reviews'])!=2:raise ValueError('two separately recorded fact inspections required')
    actors=set();families=set()
    for r in row['reviews']:
        if not isinstance(r,dict) or set(r)!=REVIEW_FIELDS:raise ValueError('invalid image fact review fields')
        for k in ['actor','model_family']:number_evidence._text(r[k])
        if r['model_version'] is not None:number_evidence._text(r['model_version'])
        for k in ['prior_verdicts_visible','expected_catalog_context_visible']:
            if type(r[k])!=bool:raise ValueError('inspection context flag must be boolean')
        number_evidence._sha(r['review_record_sha256'])
        if r['source_ref']!=row['source_ref'] or r['image_sha256']!=row['image_sha256']:raise ValueError('image fact reviewer asset differs')
        if core.parse_time(r['reviewed_at'])>end:raise ValueError('image fact predates review')
        validate_reading(r['reading']);actors.add(r['actor'].casefold());families.add(r['model_family'].casefold())
    if len(actors)!=2 or len(families)!=2:raise ValueError('distinct fact reviewer families required')

def import_evidence(db,rows):
    from . import variant_dimension_hold
    prepared=list(rows)
    for r in prepared:
        validate(r)
        if variant_dimension_hold.held(db,r['card_id']):raise ValueError('image facts cannot bind a variant-dimension-held identity')
        if number_evidence.snapshot(db,r['card_id'])!=r['endpoint_snapshot']:raise ValueError('image fact endpoint is stale')
    with db:
        for r in prepared:
            body=json.dumps(r,ensure_ascii=False,sort_keys=True)
            old=db.execute('SELECT record_json FROM source_image_fact_evidence WHERE event_id=?',(r['event_id'],)).fetchone()
            if old:
                if old[0]!=body:raise ValueError('image fact event changed')
                continue
            head=db.execute('SELECT max(revision) FROM source_image_fact_evidence WHERE card_id=?',(r['card_id'],)).fetchone()[0] or 0
            if r['revision']!=head+1:raise ValueError('image fact revisions must be consecutive')
            db.execute('INSERT INTO source_image_fact_evidence VALUES (?,?,?,?)',(r['event_id'],r['card_id'],r['revision'],body))
    return len(prepared)

def context(db,card_id):
    from . import source_mechanic
    record=db.execute('SELECT record_json FROM source_image_fact_evidence WHERE card_id=? ORDER BY revision DESC LIMIT 1',(card_id,)).fetchone()
    if record is None:return None
    row=json.loads(record[0]);validate(row)
    current=number_evidence.snapshot(db,card_id)==row['endpoint_snapshot']
    result=outcomes(row) if current else dict(name_status='stale_endpoint',title_interpretations=[],hp_status='stale_endpoint',observed_hp=None,observed_number_agreement=False,warnings=['stale_source_image_facts'])
    return dict(schema='pokemon.source-image-fact-context.v1',event_id=row['event_id'],current_endpoint=current,
        source_notation=notation_context(row) if current else None,
        source_mechanic_binding=source_mechanic.context(db,card_id),
        inspection_tier=number_evidence.inspection_tier(row['reviews']),
        evidence_level='advisory_with_review_context_disclosed',source_ref=row['source_ref'],image_sha256=row['image_sha256'],
        pinned_source_hp=row['pinned_source_hp'],reviews=row['reviews'],**result,**{k:False for k in FALSE_CLAIMS},
        number_reading_qualification_changed=False,scope='Selected exact source scan only; no sibling, physical-copy, graph or commerce approval.')

def status(db):
    heads=db.execute('SELECT card_id FROM source_image_fact_evidence GROUP BY card_id').fetchall()
    contexts=[context(db,r[0]) for r in heads]
    return dict(source_image_fact_events=db.execute('SELECT count(*) FROM source_image_fact_evidence').fetchone()[0],
        source_image_fact_subjects=len(heads),current_title_correspondence_advisories=sum(c['name_status'] in {'literal_correspondence_advisory','symbol_correspondence_advisory'} for c in contexts),
        ocr_screening_source_fact_subjects=sum(c['inspection_tier']=='ocr_and_image_model_screening' for c in contexts),
        two_image_model_source_fact_subjects=sum(c['inspection_tier']=='two_image_model_families' for c in contexts),
        source_image_hp_conflicts=sum(c['hp_status']=='source_hp_conflict' for c in contexts),stale_source_image_facts=sum(not c['current_endpoint'] for c in contexts))
