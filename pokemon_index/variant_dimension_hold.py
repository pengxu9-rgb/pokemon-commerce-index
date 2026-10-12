"""Conservative source-dimension holds; legacy IDs and raw metadata survive."""
import hashlib,json,re
from . import catalog_locale,tcgdex_source,core

SCHEMA='pokemon.variant-dimension-hold.v1'
PREFIX='variant-dimension-hold:'


def rows_for(db,cid=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_identity_quarantine'").fetchone():return []
    where="quarantine_id GLOB 'variant-dimension-hold:*'"
    params=()
    if cid is not None:where+=" AND json_extract(record_json,'$.identity.card_id')=?";params=(cid,)
    records=db.execute('SELECT quarantine_id,record_json FROM catalog_identity_quarantine WHERE '+where,params)
    result=[]
    for stored in records:
        row=json.loads(stored['record_json'])
        if row.get('schema')==SCHEMA and (cid is None or row.get('identity',{}).get('card_id')==cid):result.append(row)
    return result


def held(db,cid):return bool(rows_for(db,cid))


def check_reimport(db,cid,row):
    for hold in rows_for(db,cid):
        identity=hold['identity']
        if any(row.get(k)!=identity[k] for k in ('name','rarity','provenance','rights_reference')):
            raise ValueError('reimport differs from immutable variant-dimension hold')


def event_id(row):return PREFIX+catalog_locale.digest({k:v for k,v in row.items() if k!='event_id'})


def validate(db,row):
    fields={'schema','event_id','revision','identity','source','declared_size','legacy_variant',
        'prior_structural_match_eligible','recorded_at','parent_audit_sha256','reason','confidence','unresolved_conflicts'}|set(catalog_locale.FALSE_CLAIMS)
    if not isinstance(row,dict) or set(row)!=fields or row['schema']!=SCHEMA:
        raise ValueError('invalid variant-dimension hold fields')
    if any(row[k] is not False for k in catalog_locale.FALSE_CLAIMS):raise ValueError('hold cannot grant physical/display/commerce rights')
    if type(row['revision']) is not int or row['revision']!=1 or row['event_id']!=event_id(row):raise ValueError('invalid immutable hold revision/digest')
    if type(row['prior_structural_match_eligible']) is not bool:raise ValueError('hold needs explicit prior eligibility')
    identity=row['identity'];cid=identity['card_id']
    if catalog_locale.snapshot(db,cid)!=identity or row['legacy_variant']!=identity['variant']:raise ValueError('hold identity is stale')
    source=row['source']
    required={'provider','language','region','native_id','revision','git_blob','sha256','text','rights_reference','rights_status',
        'license_sha256','retrieved_at','retrieval_status','inspected_at','physical_distribution_region'}
    if not isinstance(source,dict) or set(source)!=required or source['provider']!='tcgdex' or source['language']!=identity['language'] or source['region']!='ZZ':raise ValueError('hold source namespace differs')
    for digest in (source['sha256'],source['license_sha256'],row['parent_audit_sha256']):
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('hold source hash invalid')
    if not isinstance(source['revision'],str) or not re.fullmatch('[0-9a-f]{40}',source['revision']):raise ValueError('hold pin invalid')
    if not isinstance(source['text'],str) or len(source['text'])>100000:raise ValueError('hold source text invalid')
    raw=source['text'].encode('utf-8')
    if hashlib.sha256(raw).hexdigest()!=source['sha256'] or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=source['git_blob']:raise ValueError('hold source bytes differ')
    expected=f"tcgdex:{source['revision']}:{source['native_id']}:sha256:{source['sha256']}"
    if expected!=identity['provenance'] or source['rights_reference']!=identity['rights_reference']:raise ValueError('hold source does not bind legacy provenance')
    if source['rights_status']!='metadata_internal_reviewed' or source['retrieved_at'] is not None or source['physical_distribution_region'] is not None or source['retrieval_status']!='historical_snapshot_time_not_recorded':raise ValueError('hold cannot infer rights/region/retrieval')
    if core.parse_time(row['recorded_at'])<core.parse_time(source['inspected_at']):raise ValueError('hold predates inspection')
    matches=[x for x in tcgdex_source.variant_dimension_losses(source['text']) if x['legacy_variant']==row['legacy_variant']]
    if len(matches)!=1 or matches[0]['source_size']!=row['declared_size']:raise ValueError('hold size declaration missing or ambiguous')
    if row['confidence']!={'pinned_source_bytes':1.0,'physical_size':None,'canonical_identity':None} or not isinstance(row['reason'],str) or not row['reason'].strip() or row['unresolved_conflicts']!=[row['reason']]:raise ValueError('hold confidence/conflict scope invalid')
    return cid


def install_guards(db):
    db.execute("CREATE INDEX IF NOT EXISTS variant_dimension_hold_card_id ON catalog_identity_quarantine (json_extract(record_json,'$.identity.card_id')) WHERE quarantine_id GLOB 'variant-dimension-hold:*'")
    # Preserve holds under direct flag updates as well as normal seed reimports.
    predicate="EXISTS (SELECT 1 FROM catalog_identity_quarantine q WHERE q.quarantine_id LIKE 'variant-dimension-hold:%' AND json_extract(q.record_json,'$.schema')='pokemon.variant-dimension-hold.v1' AND json_extract(q.record_json,'$.identity.card_id')=NEW.card_id)"
    for operation in ('INSERT','UPDATE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS variant_dimension_hold_card_{operation.lower()} AFTER {operation} ON card WHEN (NEW.match_eligible=1 OR NEW.display_allowed=1) AND {predicate} BEGIN UPDATE card SET match_eligible=0,display_allowed=0 WHERE card_id=NEW.card_id; END")


def import_evidence(db,rows):
    prepared=[];seen=set()
    for row in rows:
        cid=validate(db,row)
        if cid in seen:raise ValueError('duplicate held identity in batch')
        seen.add(cid);prior=rows_for(db,cid)
        encoded=catalog_locale.encoded(row)
        if prior and (len(prior)!=1 or catalog_locale.encoded(prior[0])!=encoded):raise ValueError('immutable hold changed')
        if not prior and db.execute('SELECT match_eligible FROM card WHERE card_id=?',(cid,)).fetchone()[0]!=int(row['prior_structural_match_eligible']):raise ValueError('prior hold eligibility differs')
        prepared.append((row,cid,encoded,bool(prior)))
    counts=dict(inserted=0,unchanged=0,eligibility_withdrawn=0)
    with db:
        install_guards(db)
        for row,cid,encoded,prior in prepared:
            old=db.execute('SELECT match_eligible FROM card WHERE card_id=?',(cid,)).fetchone()[0]
            if not prior:db.execute('INSERT INTO catalog_identity_quarantine VALUES (?,?,?)',(row['event_id'],row['reason'],encoded))
            db.execute('UPDATE card SET match_eligible=0,display_allowed=0 WHERE card_id=?',(cid,))
            counts['unchanged' if prior else 'inserted']+=1;counts['eligibility_withdrawn']+=old
    return counts


def import_manifest_evidence(db,rows):
    result=import_evidence(db,rows);return result['inserted']+result['unchanged']


def context(db,cid):
    rows=rows_for(db,cid)
    if not rows:return None
    row=rows[0]
    try:validate(db,row);status='held_legacy_variant_dimensions'
    except (ValueError,KeyError,TypeError):status='stale_hold_source_changed'
    return dict(schema='pokemon.variant-dimension-context.v1',status=status,event_id=row['event_id'],
        legacy_card_id=cid,legacy_variant=row['legacy_variant'],declared_source_size=row['declared_size'],
        source_revision=row['source']['revision'],source_sha256=row['source']['sha256'],
        dimension_complete_identity=False,canonical_replacement_card_id=None,replacement_relationships=[],
        reason=row['reason'],physical_size_verified=False,**{k:False for k in catalog_locale.FALSE_CLAIMS})


def status(db):
    rows=rows_for(db);ids={r['identity']['card_id'] for r in rows}
    return dict(events=len(rows),held_legacy_ids=len(ids),canonical_replacements=0,scope='source-declared size loss; IDs retained and matching/display withdrawn')
