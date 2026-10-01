"""Append-only source-bound depictions and release-level variant declarations.

Official descriptions support scoped facts; AI image findings remain proposals.
Neither tier verifies physical finish or card-pair/price equivalence.
"""
from __future__ import annotations
import json,re,sqlite3
from urllib.parse import urlparse
from . import core,supported_catalog

def _hash(x):
    if not isinstance(x,str) or not re.fullmatch('[0-9a-f]{64}',x):raise ValueError('invalid evidence SHA-256')

def _text(x):
    if not isinstance(x,str) or not x.strip() or len(x)>2000:raise ValueError('invalid evidence text')

def official_url(x,image=False):
    if not isinstance(x,str):raise ValueError('invalid official URL')
    u=urlparse(x)
    paths=(r'/assets/images/card_images/(?:large|legend)/[^/]+/[^/]+\.jpg|/ex/[a-z0-9]+/assets/images/[a-zA-Z0-9_-]+\.(?:png|jpg)' if image
           else r'/card-search/details\.php/card/[0-9]+|/ex/[a-z0-9]+/index\.html')
    if (u.scheme!='https' or u.netloc!='www.pokemon-card.com' or u.query or u.fragment
            or not re.fullmatch(paths,u.path)):raise ValueError('evidence URL is not official')

def identity(db,kind,subject):
    if kind=='card':
        r=db.execute('SELECT * FROM card WHERE card_id=?',(subject,)).fetchone()
        if r is None:raise ValueError('unknown evidence card')
        return supported_catalog.identity_snapshot(r)
    if kind!='release' or not isinstance(subject,str) or subject.count(':')!=1:raise ValueError('invalid evidence subject')
    language,code=subject.split(':')
    r=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',(language,code)).fetchone()
    if r is None:raise ValueError('unknown evidence release')
    return {k:r[k] for k in ['language','set_code','name','release_date','provenance']}

def _key(row):
    return (row['subject_kind'],row['subject_id'],row['claim'],str(row['value']),row['role'],row['evidence']['kind'])

def import_evidence(db,rows):
    prepared=[]
    for r in rows:
        if not isinstance(r,dict) or set(r)-{'schema','event_id','subject_kind','subject_id','claim','value','role','status','identity_sha256','evidence','actor','recorded_at','expected_head'}:
            raise ValueError('unsupported collector evidence fields')
        core._required(r,'schema','event_id','subject_kind','subject_id','claim','value','role',
                       'status','identity_sha256','evidence','actor','recorded_at')
        if r['schema']!='pokemon.collector-evidence.v1':raise ValueError('unknown collector evidence schema')
        for k in ['event_id','actor']:_text(r[k])
        core.parse_time(r['recorded_at']);_hash(r['identity_sha256'])
        if supported_catalog.digest(identity(db,r['subject_kind'],r['subject_id']))!=r['identity_sha256']:
            raise ValueError('collector evidence differs from current identity')
        if r['status'] not in {'source_supported','proposed','withdrawn'}:raise ValueError('invalid evidence status')
        e=r['evidence']
        if not isinstance(e,dict):raise ValueError('invalid evidence object')
        for k in ['locator','finding']:_text(e.get(k))
        official_url(e.get('source_url'));_hash(e.get('source_page_sha256'))
        if r['claim']=='depicted_pokemon':
            if r['subject_kind']!='card' or type(r['value']) is not int or not 1<=r['value']<=1025 or r['role'] not in {'subject','cameo'}:
                raise ValueError('invalid depicted Pokemon claim')
            official_url(e.get('image_url'),True);_hash(e.get('image_sha256'))
            official_url(e.get('official_card_url'));_hash(e.get('official_card_page_sha256'))
            if not re.fullmatch(r'https://www\.pokemon-card\.com/card-search/details\.php/card/[0-9]+',e['official_card_url']):
                raise ValueError('depiction needs a card-specific official identity page')
            if e.get('kind') not in {'official_description','ai_visual'}:raise ValueError('invalid depiction evidence kind')
        elif r['claim']=='finish_exists':
            if (r['subject_kind']!='release' or r['role']!='release_declaration' or e.get('kind')!='official_release_text'
                    or r['value'] not in {'reverse_pokeball','reverse_masterball','mirror'}):raise ValueError('invalid release variant claim')
        else:raise ValueError('unsupported collector claim')
        if r['status']=='source_supported' and e['kind']=='ai_visual':raise ValueError('AI visual findings must remain proposed')
        if e['kind']=='ai_visual':
            review=e.get('review')
            if not isinstance(review,dict) or review.get('identity_match')!='match':raise ValueError('AI depiction lacks image identity check')
            for k in ['model','prompt_version']:_text(review.get(k))
            for k in ['prompt_sha256','response_sha256']:_hash(review.get(k))
        if 'expected_head' not in r:raise ValueError('evidence requires explicit expected_head')
        encoded=json.dumps(r,ensure_ascii=False,sort_keys=True)
        prepared.append((r,encoded))
    count=0
    with db:
        for r,encoded in prepared:
            existing=db.execute('SELECT record_json FROM catalog_collector_evidence WHERE event_id=?',(r['event_id'],)).fetchone()
            if existing:
                if existing[0]!=encoded:raise ValueError('collector event ID collision')
                continue
            head=db.execute('SELECT event_id FROM catalog_collector_evidence WHERE subject_kind=? AND subject_id=? AND claim=? AND value=? AND role=? AND evidence_kind=? ORDER BY rowid DESC LIMIT 1',_key(r)).fetchone()
            if r['expected_head']!=(head[0] if head else None):raise ValueError('stale collector evidence head')
            if r['status']=='withdrawn' and head is None:raise ValueError('withdrawal needs an existing finding')
            db.execute('INSERT INTO catalog_collector_evidence VALUES (?,?,?,?,?,?,?,?,?,?)',
                (r['event_id'],*_key(r),r['status'],r['identity_sha256'],encoded));count+=1
    return count

def records(db,kind=None,subject=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_collector_evidence'").fetchone():return []
    where=[];params=[]
    for field,value in [('subject_kind',kind),('subject_id',subject)]:
        if value is not None:where.append(field+'=?');params.append(value)
    query='SELECT record_json FROM catalog_collector_evidence'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY rowid DESC'
    latest={}
    for item in db.execute(query,params):
        r=json.loads(item[0]);latest.setdefault(_key(r),r)
    result=[]
    for r in latest.values():
        if r['status']=='withdrawn':continue
        r=dict(r,current_identity=supported_catalog.digest(identity(db,r['subject_kind'],r['subject_id']))==r['identity_sha256'])
        result.append(r)
    return sorted(result,key=lambda r:r['event_id'])

def card_context(db,card_id):
    c=identity(db,'card',card_id)
    rows=records(db,'card',card_id)+records(db,'release',c['language']+':'+c['set_code'])
    return dict(schema='pokemon.collector-evidence-context.v1',findings=[r for r in rows if r['current_identity']],
        stale_findings=sum(not r['current_identity'] for r in rows),physical_finish_verified=False,
        copy_condition_verified=False,card_pair_relationship_verified=False,price_comparable=False,
        interpretation='Official source declarations and AI proposals, scoped to pinned artwork or a release. No copy, comprehensive variant or cross-region equivalence approval.')

def artwork_candidates(db,dex_ids,languages):
    strong=set();proposed=[]
    for r in records(db,'card'):
        if not r['current_identity'] or r['claim']!='depicted_pokemon' or r['role']!='cameo' or r['value'] not in dex_ids:continue
        if r['subject_id'].split(':')[0] not in languages:continue
        if r['status']=='source_supported':strong.add(r['subject_id'])
        elif r['status']=='proposed':proposed.append(r)
    return sorted(strong),proposed

def status(db):
    rows=records(db)
    return dict(active_source_supported=sum(r['current_identity'] and r['status']=='source_supported' for r in rows),
        active_proposed=sum(r['current_identity'] and r['status']=='proposed' for r in rows),
        stale_findings=sum(not r['current_identity'] for r in rows),
        physical_finish_approvals=0,verified_card_pair_edges_added=0,automatic_offer_join_approvals=0)
