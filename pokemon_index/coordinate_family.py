"""Official coordinate-family facts; never map a page to a physical finish."""
import hashlib
import json
import re
from . import core,supported_catalog,card_metadata

FALSE_CLAIMS=card_metadata.FALSE_CLAIMS+('page_to_variant_mapping_verified','names_are_exact_aliases')


def snapshot(db,language,code,number):
    cards=[supported_catalog.identity_snapshot(c) for c in db.execute(
        'SELECT * FROM card WHERE language=? AND set_code=? AND collector_number=? ORDER BY card_id',(language,code,number))]
    refs=[{k:r[k] for k in ('source','native_id','name','provenance')} for r in db.execute(
        'SELECT * FROM card_reference WHERE set_code=? AND collector_number=? ORDER BY source,native_id',(code,number))]
    return dict(cards=cards,references=refs)


def event_id(row):
    return 'coordinate-family:'+supported_catalog.digest({k:v for k,v in row.items() if k!='evidence_id'})


def name_status(names,pages):
    seed={core._compact_identity_text(n) for n in names}
    official={core._compact_identity_text(p['name']) for p in pages}
    if official==seed:return 'exact_name'
    if len(seed)==1 and all(re.fullmatch(re.escape(next(iter(seed)))+r'[（(][^）)]+[）)]',n) for n in official):
        return 'official_name_qualifier'
    raise ValueError('unresolved source name conflict')


def import_evidence(db,rows):
    count=0
    with db:
        for r in rows:
            allowed={'schema','evidence_id','revision','language','set_code','collector_number','snapshot','pages','name_status','status','hold_reason','queue_sha256','audit_sha256'}|set(FALSE_CLAIMS)
            if set(r)!=allowed or r['schema']!='pokemon.coordinate-family-evidence.v1':raise ValueError('invalid family evidence schema')
            if any(r[k] is not False for k in FALSE_CLAIMS):raise ValueError('family evidence cannot approve a printing or exact alias')
            if r['language']!='ja' or type(r['revision']) is not int or r['revision']<1 or r['evidence_id']!=event_id(r):raise ValueError('family revision/digest invalid')
            for k in ('queue_sha256','audit_sha256'):
                if not re.fullmatch('[0-9a-f]{64}',r[k]):raise ValueError('family lineage SHA missing')
            hold=r['status']=='evidence_hold'
            if r['status'] not in {'source_supported','evidence_hold'}:raise ValueError('invalid family evidence status')
            if hold and (r['name_status']!='unresolved' or not r['hold_reason']):raise ValueError('hold needs explicit reason')
            if not hold and r['hold_reason'] is not None:raise ValueError('supported family cannot have a hold')
            identity=snapshot(db,r['language'],r['set_code'],r['collector_number'])
            if not identity['cards'] or identity!=r['snapshot']:raise ValueError('family snapshot stale')
            urls={'https://www.pokemon-card.com/card-search/details.php/card/'+ref['native_id']:ref for ref in identity['references']}
            seen={p['url'] for p in r['pages']}
            if len(seen)!=len(r['pages']) or not seen.issubset(urls):raise ValueError('family page coverage invalid')
            if not hold and (not urls or seen!=set(urls)):raise ValueError('family page coverage incomplete')
            for p in r['pages']:
                if not re.fullmatch(r'https://www\.pokemon-card\.com/card-search/details\.php/card/[0-9]+',p['url']):raise ValueError('page outside official scope')
                if not re.fullmatch('[0-9a-f]{64}',p['page_sha256']):raise ValueError('page hash invalid')
                core.parse_time(p['fetched_at'])
                if not hold and core._compact_identity_text(p['name'])!=core._compact_identity_text(urls[p['url']]['name']):raise ValueError('official/reference name differs')
                entries=p['numbered_entries']
                if not 1<=len(entries)<=4 or len({(e['set_code'],e['collector_number']) for e in entries})!=len(entries):raise ValueError('ambiguous page numbers')
                selected=[e for e in entries if (e['set_code'],e['collector_number'])==(r['set_code'],r['collector_number'])]
                if not hold and (len(selected)!=1 or any(p.get(k)!=v for k,v in selected[0].items())):raise ValueError('official family coordinates differ')
                for e in entries:
                    icons=e['rarity_icons']
                    if len(icons)>1:raise ValueError('ambiguous rarity')
                    rarity=card_metadata.OFFICIAL_ICON_RARITIES.get(icons[0]) if icons else None
                    state='recognized_icon' if rarity else 'unrecognized_icon' if icons else 'no_rarity_icon'
                    if e['rarity']!=rarity or e['rarity_status']!=state:raise ValueError('invented official rarity')
                if p['page_kind']!=('single_number' if len(entries)==1 else 'numbered_parts'):raise ValueError('invalid page kind')
                if not isinstance(p['illustrators'],list) or any(not isinstance(a,str) or not a.strip() or len(a)>160 for a in p['illustrators']):raise ValueError('invalid artist labels')
                if p['dex_id'] is not None and (type(p['dex_id']) is not int or not 1<=p['dex_id']<=9999):raise ValueError('invalid species')
            if not hold and r['name_status']!=name_status([c['name'] for c in identity['cards']],r['pages']):raise ValueError('name agreement scope differs')
            key=(r['language'],r['set_code'],r['collector_number'])
            prior=db.execute('SELECT * FROM coordinate_family_evidence WHERE language=? AND set_code=? AND collector_number=? ORDER BY revision DESC LIMIT 1',key).fetchone()
            encoded=json.dumps(r,ensure_ascii=False,sort_keys=True)
            if prior and prior['evidence_id']==r['evidence_id']:
                if prior['record_json']!=encoded:raise ValueError('family event collision')
            elif r['revision']!=(prior['revision']+1 if prior else 1):raise ValueError('nonconsecutive family revision')
            else:db.execute('INSERT INTO coordinate_family_evidence VALUES (?,?,?,?,?,?)',(r['evidence_id'],*key,r['revision'],encoded))
            count+=1
    return count


def _available(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='coordinate_family_evidence'").fetchone())


def context(db,cid):
    if not _available(db):return None
    c=db.execute('SELECT language,set_code,collector_number FROM card WHERE card_id=?',(cid,)).fetchone()
    if c is None:return None
    row=db.execute('SELECT record_json FROM coordinate_family_evidence WHERE language=? AND set_code=? AND collector_number=? ORDER BY revision DESC LIMIT 1',tuple(c)).fetchone()
    if not row:return None
    r=json.loads(row[0]);current=snapshot(db,*tuple(c))
    if current!=r['snapshot']:return dict(status='stale_coordinate_family_evidence',copy_evidence_needed=True,**{k:False for k in FALSE_CLAIMS})
    return dict(status='coordinate_family_evidence_hold' if r['status']=='evidence_hold' else 'official_coordinate_family_supported',evidence_id=r['evidence_id'],
        scope='coordinate family; official page-to-source-variant assignment unverified',
        name_status=r['name_status'],hold_reason=r['hold_reason'],official_names=sorted({p['name'] for p in r['pages']}),
        official_pages=r['pages'],source_record_count=len(current['cards']),reference_count=len(current['references']),
        copy_evidence_needed=True,**{k:False for k in FALSE_CLAIMS})


def status(db):
    if not _available(db):return dict(coordinate_family_events=0,current_coordinate_families=0,held_coordinate_families=0,stale_coordinate_families=0)
    rows=db.execute('SELECT * FROM coordinate_family_evidence e WHERE NOT EXISTS(SELECT 1 FROM coordinate_family_evidence x WHERE x.language=e.language AND x.set_code=e.set_code AND x.collector_number=e.collector_number AND x.revision>e.revision)').fetchall()
    active=[json.loads(r['record_json']) for r in rows if snapshot(db,r['language'],r['set_code'],r['collector_number'])==json.loads(r['record_json'])['snapshot']]
    return dict(coordinate_family_events=db.execute('SELECT COUNT(*) FROM coordinate_family_evidence').fetchone()[0],
        current_coordinate_families=sum(r['status']=='source_supported' for r in active),
        held_coordinate_families=sum(r['status']=='evidence_hold' for r in active),stale_coordinate_families=len(rows)-len(active))
