"""Source-image readings and manufacturer declarations, without copy approval.

Printed artist/subtitle/stamp readings are auditable observations of publisher
assets. They do not establish physical foil, edition completeness or the copy
offered by a seller. This overlay deliberately never alters seed identities.
"""
import json,re
from . import core,coordinate_family,supported_catalog,collector_evidence

FALSE_CLAIMS = coordinate_family.FALSE_CLAIMS + ('copy_condition_verified',)
SCHEMA = '''CREATE TABLE IF NOT EXISTS printing_source_evidence (
    event_id TEXT PRIMARY KEY, subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
    record_json TEXT NOT NULL, UNIQUE(subject_kind,subject_id,revision)
)'''


def identity(db,kind,subject):
    if kind=='coordinate':
        parts=subject.split(':')
        if len(parts)!=3 or parts[0]!='ja':raise ValueError('invalid coordinate scope')
        result=coordinate_family.snapshot(db,*parts)
        if not result['cards']:raise ValueError('unknown coordinate')
        return result
    if kind=='release':
        parts=subject.split(':')
        if len(parts)!=2 or parts[0]!='ja':raise ValueError('invalid release scope')
        if not db.execute('SELECT 1 FROM card WHERE language=? AND set_code=? LIMIT 1',parts).fetchone():raise ValueError('unknown release')
        return dict(language=parts[0],set_code=parts[1],scope='namespace; not a printing membership declaration')
    raise ValueError('invalid printing source subject')


def event_id(row):
    return 'printing-source:'+supported_catalog.digest({k:v for k,v in row.items() if k!='event_id'})


def _sha(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('invalid source SHA')


def _text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>2000:raise ValueError('invalid source text')


def import_evidence(db,rows):
    prepared=[]
    for row in rows:
        allowed={'schema','event_id','revision','subject_kind','subject_id','identity_sha256',
            'status','hold_reason','sources','observations','reviewers','recorded_at'}|set(FALSE_CLAIMS)
        if set(row)!=allowed or row['schema']!='pokemon.printing-source-evidence.v1':raise ValueError('invalid printing source schema')
        if any(row[k] is not False for k in FALSE_CLAIMS):raise ValueError('source reading cannot approve a physical printing, copy or commerce')
        if type(row['revision']) is not int or row['revision']<1 or row['event_id']!=event_id(row):raise ValueError('invalid event revision or digest')
        _sha(row['identity_sha256']);core.parse_time(row['recorded_at'])
        current=identity(db,row['subject_kind'],row['subject_id'])
        if supported_catalog.digest(current)!=row['identity_sha256']:raise ValueError('printing source identity is stale')
        if row['status'] not in {'source_observed','evidence_hold'}:raise ValueError('invalid source reading status')
        if row['status']=='evidence_hold':_text(row['hold_reason'])
        elif row['hold_reason'] is not None:raise ValueError('source observation cannot hide a hold')
        sources=row['sources'];observations=row['observations'];reviewers=row['reviewers']
        if not isinstance(sources,list) or not isinstance(observations,list) or not isinstance(reviewers,list):raise ValueError('invalid evidence collections')
        if row['status']=='source_observed' and (not sources or not observations or not reviewers):raise ValueError('positive observation needs sources, readings and reviewers')
        urls=set()
        for source in sources:
            if set(source)!={'url','page_sha256','fetched_at','image_url','image_sha256'}:raise ValueError('invalid source fields')
            collector_evidence.official_url(source['url']);_sha(source['page_sha256']);core.parse_time(source['fetched_at'])
            if source['url'] in urls:raise ValueError('duplicate source page')
            urls.add(source['url'])
            if row['subject_kind']=='coordinate':
                permitted={'https://www.pokemon-card.com/card-search/details.php/card/'+r['native_id'] for r in current['references']}
                if source['url'] not in permitted:raise ValueError('source is outside coordinate references')
                collector_evidence.official_url(source['image_url'],True);_sha(source['image_sha256'])
                native=source['url'].rsplit('/',1)[-1]
                if not source['image_url'].rsplit('/',1)[-1].startswith(native.zfill(6)+'_'):raise ValueError('publisher image does not bind the referenced page ID')
            elif source['url']!='https://www.pokemon-card.com/ex/'+row['subject_id'].split(':')[1].lower()+'/index.html' or source['image_url'] is not None or source['image_sha256'] is not None:
                raise ValueError('release declaration cannot assign a stock image to a printing')
        for observation in observations:
            if set(observation)!={'claim','value','source_url','locator','coordinate','scope'}:raise ValueError('invalid observation fields')
            _text(observation['value']);_text(observation['locator'])
            if observation['source_url'] not in urls:raise ValueError('reading has no bound source')
            if row['subject_kind']=='release':
                if observation['claim']!='manufacturer_finish_declaration' or observation['scope']!='release_only' or observation['coordinate'] is not None:raise ValueError('release evidence cannot verify individual finish')
            else:
                if observation['claim'] not in {'printed_artist','printed_qualifier','printed_stamp','printed_number'} or observation['scope']!='publisher_asset_only':raise ValueError('unsupported printed reading')
                coordinate=observation['coordinate']
                if not isinstance(coordinate,dict) or set(coordinate)!={'language','set_code','collector_number'} or coordinate['language']!='ja':raise ValueError('printed coordinate missing')
                actual=':'.join(coordinate[k] for k in ('language','set_code','collector_number'))
                if row['status']=='source_observed' and actual!=row['subject_id']:raise ValueError('different printed coordinate requires explicit hold')
        actors=set()
        for reviewer in reviewers:
            if set(reviewer)!={'actor','method','reviewed_at','source_image_sha256s','observations_sha256'} or reviewer['method'] not in {'direct_image_reading','official_release_text'}:raise ValueError('invalid reviewer scope')
            _text(reviewer['actor']);core.parse_time(reviewer['reviewed_at'])
            if reviewer['actor'] in actors:raise ValueError('duplicate reviewer')
            actors.add(reviewer['actor'])
            if reviewer['observations_sha256']!=supported_catalog.digest(observations):raise ValueError('reviewer is not bound to exact readings')
            expected=sorted(s['image_sha256'] for s in sources if s['image_sha256'])
            if reviewer['source_image_sha256s']!=expected:raise ValueError('reviewer is not bound to exact images')
            if row['subject_kind']=='coordinate' and reviewer['method']!='direct_image_reading':raise ValueError('printed facts need image readings')
            if row['subject_kind']=='release' and reviewer['method']!='official_release_text':raise ValueError('release needs text reading')
        prepared.append((row,json.dumps(row,ensure_ascii=False,sort_keys=True)))
    with db:
        db.execute(SCHEMA)
        for row,encoded in prepared:
            previous=db.execute('SELECT * FROM printing_source_evidence WHERE subject_kind=? AND subject_id=? ORDER BY revision DESC LIMIT 1',(row['subject_kind'],row['subject_id'])).fetchone()
            if previous and previous['event_id']==row['event_id']:
                if previous['record_json']!=encoded:raise ValueError('printing event collision')
                continue
            if row['revision']!=(previous['revision']+1 if previous else 1):raise ValueError('nonconsecutive printing source revision')
            db.execute('INSERT INTO printing_source_evidence VALUES (?,?,?,?,?)',(row['event_id'],row['subject_kind'],row['subject_id'],row['revision'],encoded))
    return len(prepared)


def records(db,subjects=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='printing_source_evidence'").fetchone():return []
    query='SELECT record_json FROM printing_source_evidence e WHERE NOT EXISTS(SELECT 1 FROM printing_source_evidence x WHERE x.subject_kind=e.subject_kind AND x.subject_id=e.subject_id AND x.revision>e.revision)'
    params=[]
    if subjects:
        query+=' AND ('+' OR '.join('(e.subject_kind=? AND e.subject_id=?)' for _ in subjects)+')'
        params=[v for pair in sorted(subjects) for v in pair]
    rows=db.execute(query+' ORDER BY subject_kind,subject_id',params)
    result=[]
    for row in rows:
        r=json.loads(row[0])
        try:r['current_identity']=supported_catalog.digest(identity(db,r['subject_kind'],r['subject_id']))==r['identity_sha256']
        except ValueError:r['current_identity']=False
        result.append(r)
    return result


def context(db,card_id):
    c=db.execute('SELECT language,set_code,collector_number FROM card WHERE card_id=?',(card_id,)).fetchone()
    if c is None:return None
    subjects={('coordinate',':'.join(c)),('release',':'.join(c[:2]))}
    rows=records(db,subjects)
    if not rows:return None
    return dict(schema='pokemon.printing-source-context.v1',findings=[r for r in rows if r['current_identity']],
        stale_findings=sum(not r['current_identity'] for r in rows),copy_evidence_needed=True,
        interpretation='Publisher image readings and release declarations; seed conflicts, physical finish, actual seller copies and complete editions remain separate.',
        **{k:False for k in FALSE_CLAIMS})


def supported_artist(db,card_id):
    """Current exact publisher credit read in two distinct source inspections.

    Returns an overlay fact, not permission to mutate the seed or join offers.
    """
    ctx=context(db,card_id)
    if not ctx:return None
    for r in ctx['findings']:
        if r['subject_kind']!='coordinate' or r['status']!='source_observed' or len(r['reviewers'])<2:continue
        current=identity(db,r['subject_kind'],r['subject_id'])
        required={'https://www.pokemon-card.com/card-search/details.php/card/'+x['native_id'] for x in current['references']}
        readings=[o for o in r['observations'] if o['claim']=='printed_artist']
        values={o['value'] for o in readings}
        covered={o['source_url'] for o in readings}
        if len(values)==1 and required and covered==required and {s['url'] for s in r['sources']}==required:
            return dict(value=next(iter(values)),evidence_id=r['event_id'],basis='publisher printed image; two distinct visual inspections',
                reviewer_actors=[x['actor'] for x in r['reviewers']],independent_blind_accuracy_measurement=False)
    return None


def status(db):
    rows=records(db)
    artist_subjects=[]
    for r in rows:
        if r['current_identity'] and r['subject_kind']=='coordinate' and r['status']=='source_observed':
            c=identity(db,r['subject_kind'],r['subject_id'])['cards'][0]['card_id']
            if supported_artist(db,c):artist_subjects.append(r['subject_id'])
    return dict(printing_source_events=db.execute('SELECT COUNT(*) FROM printing_source_evidence').fetchone()[0] if rows else 0,
        current_printing_source_observations=sum(r['current_identity'] and r['status']=='source_observed' for r in rows),
        held_printing_sources=sum(r['current_identity'] and r['status']=='evidence_hold' for r in rows),
        stale_printing_sources=sum(not r['current_identity'] for r in rows),two_review_printed_artist_coordinates=len(artist_subjects),physical_printing_approvals=0,automatic_offer_approvals=0)
