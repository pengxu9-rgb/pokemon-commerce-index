"""Bind literal source-scan mechanics to exact official coordinates.

These overlays preserve the original image readings and catalog identities.
They qualify only a manufacturer-declared mechanic, never a seller copy.
"""
import json,re
from . import core,number_evidence as n,supported_catalog as s
SCHEMA='pokemon.source-mechanic-binding.v1'
FALSE_CLAIMS=n.FALSE_CLAIMS+('independent_accuracy_established',)
FIELDS={'schema','event_id','revision','card_id','endpoint_snapshot','identity_sha256',
 'source_fact_event_id','source_fact_sha256','reference','official','mechanic','recorded_at'}|set(FALSE_CLAIMS)
def event_id(row):return 'source-mechanic:'+s.digest({k:v for k,v in row.items() if k!='event_id'})
def fact_head(db,cid):
 row=db.execute('SELECT record_json FROM source_image_fact_evidence WHERE card_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()
 return json.loads(row[0]) if row else None
def validate(row):
 if not isinstance(row,dict) or set(row)!=FIELDS or row['schema']!=SCHEMA:raise ValueError('invalid source mechanic schema')
 if row['mechanic']!='prism_star' or type(row['revision'])!=int or row['revision']<1 or row['event_id']!=event_id(row):raise ValueError('invalid source mechanic identity')
 if any(row[k] is not False for k in FALSE_CLAIMS):raise ValueError('mechanic binding cannot approve identity or commerce')
 snap=row['endpoint_snapshot']
 if set(snap)!=set(n.FIELDS) or snap['card_id']!=row['card_id'] or snap['language']!='ja' or s.digest(snap)!=row['identity_sha256']:raise ValueError('mechanic endpoint mismatch')
 for key in ['identity_sha256','source_fact_sha256']:n._sha(row[key])
 n._text(row['source_fact_event_id']);core.parse_time(row['recorded_at'])
 ref=row['reference'];off=row['official']
 if not isinstance(ref,dict) or set(ref)!={'source','native_id','name','provenance'}:raise ValueError('invalid mechanic reference')
 if not isinstance(off,dict) or set(off)!={'url','page_sha256','fetched_at','name','set_code','collector_number','title_symbol','special_rule','page_kind'}:raise ValueError('invalid official mechanic fields')
 n._sha(off['page_sha256']);n._source(off['url']);core.parse_time(off['fetched_at'])
 if (off['url']!='https://www.pokemon-card.com/card-search/details.php/card/'+ref['native_id'] or
  off['title_symbol']!='prism_star' or off['special_rule']!='prism_star' or off['page_kind']!='single_number' or
  (off['set_code'],off['collector_number'])!=(snap['set_code'],snap['collector_number']) or
  core._compact_identity_text(off['name'])!=core._compact_identity_text(snap['name'])):raise ValueError('official mechanic coordinate mismatch')
 if core.parse_time(row['recorded_at'])<core.parse_time(off['fetched_at']):raise ValueError('binding predates official page')
def current(db,row):
 from . import source_image_facts as f
 fact=fact_head(db,row['card_id'])
 refs=[dict(r) for r in db.execute('SELECT source,native_id,name,provenance FROM card_reference WHERE set_code=? AND collector_number=?',(row['endpoint_snapshot']['set_code'],row['endpoint_snapshot']['collector_number']))]
 if n.snapshot(db,row['card_id'])!=row['endpoint_snapshot'] or refs!=[row['reference']] or fact is None:return False
 f.validate(fact);notation=f.notation_context(fact)
 return (fact['event_id']==row['source_fact_event_id'] and s.digest(fact)==row['source_fact_sha256'] and
  fact['endpoint_snapshot']==row['endpoint_snapshot'] and notation['title_mechanic']=='prism_star_observed_by_both' and
  notation['base_title_catalog_correspondence'] is True and core.parse_time(row['recorded_at'])>=core.parse_time(fact['recorded_at']))
def import_evidence(db,rows):
 prepared=list(rows)
 for row in prepared:
  validate(row)
  if not current(db,row):raise ValueError('mechanic binding source or endpoint is stale')
 with db:
  for row in prepared:
   encoded=json.dumps(row,ensure_ascii=False,sort_keys=True)
   head=db.execute('SELECT * FROM source_mechanic_binding WHERE card_id=? ORDER BY revision DESC LIMIT 1',(row['card_id'],)).fetchone()
   if head and head['event_id']==row['event_id']:
    if head['record_json']!=encoded:raise ValueError('mechanic binding event changed')
    continue
   if row['revision']!=(head['revision']+1 if head else 1):raise ValueError('mechanic revisions must be consecutive')
   db.execute('INSERT INTO source_mechanic_binding VALUES (?,?,?,?)',(row['event_id'],row['card_id'],row['revision'],encoded))
 return len(prepared)
def context(db,cid):
 if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_mechanic_binding'").fetchone():return None
 saved=db.execute('SELECT record_json FROM source_mechanic_binding WHERE card_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()
 if saved is None:return None
 row=json.loads(saved[0]);validate(row);is_current=current(db,row)
 return dict(schema='pokemon.source-mechanic-context.v1',event_id=row['event_id'],mechanic=row['mechanic'],
  status='official_coordinate_mechanic_supported' if is_current else 'stale_binding',current_endpoint_and_fact=is_current,
  official=row['official'] if is_current else None,source_fact_event_id=row['source_fact_event_id'],
  scope='Exact official coordinate plus existing independent scan-symbol readings; catalog name, number qualification, physical copy and price remain separate.',
  **{k:False for k in FALSE_CLAIMS})
def status(db):
 if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_mechanic_binding'").fetchone():return dict(source_mechanic_binding_events=0,current_source_mechanic_bindings=0,stale_source_mechanic_bindings=0)
 ids=[r[0] for r in db.execute('SELECT DISTINCT card_id FROM source_mechanic_binding')]
 states=[context(db,cid)['current_endpoint_and_fact'] for cid in ids]
 return dict(source_mechanic_binding_events=db.execute('SELECT COUNT(*) FROM source_mechanic_binding').fetchone()[0],
  current_source_mechanic_bindings=sum(states),stale_source_mechanic_bindings=sum(not x for x in states))

