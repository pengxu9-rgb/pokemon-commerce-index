from pathlib import Path
import json,sqlite3,hashlib
from collections import Counter
root=Path('catalog/source-binding-v1')
old=sqlite3.connect('file:/tmp/pokemon-source-notation-v1.sqlite3?mode=ro',uri=True)
new=sqlite3.connect('file:/tmp/pokemon-source-binding-v1.sqlite3?mode=ro',uri=True)
old.row_factory=new.row_factory=sqlite3.Row
append={'card_number_reading_evidence','source_image_fact_evidence'}
old_tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
new_tables=[r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
assert set(new_tables)-set(old_tables)=={'source_mechanic_binding'} and not (set(old_tables)-set(new_tables))
tables=[t for t in old_tables if t not in append];results=[];changes=[]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def normalize(table,row):
 d=dict(row);ignored=[]
 if table in ['card_identity_exception','card_number_conflict_rule','card_rarity_correction']:ignored=['applied_at']
 elif table=='card_relationship_assertion' and d['review_status']=='proposed' and d['asserted_by']=='ai-artwork-review-v1':ignored=['asserted_at']
 clocks={k:d.pop(k) for k in ignored}
 return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')),clocks
for table in tables:
 before=[normalize(table,r) for r in old.execute('SELECT * FROM '+table)];after=[normalize(table,r) for r in new.execute('SELECT * FROM '+table)]
 assert Counter(k for k,v in before)==Counter(k for k,v in after),table
 a={k:v for k,v in after}
 for k,v in before:
  dif={field:dict(before=value,after=a[k][field]) for field,value in v.items() if a[k][field]!=value}
  if dif:changes.append(dict(table=table,semantic_row_sha256=hashlib.sha256(k.encode()).hexdigest(),changes=dif))
 results.append(dict(table=table,rows=len(before),semantic_sha256=digest(sorted(k for k,v in before)),semantic_values_preserved=True))
counts={}
for table in append:
 before=[dict(r) for r in old.execute('SELECT * FROM '+table)];after=[dict(r) for r in new.execute('SELECT * FROM '+table)]
 assert not (Counter(digest(r) for r in before)-Counter(digest(r) for r in after))
 assert len(after)-len(before)==17
 counts[table]=len(before)
report=dict(schema='pokemon.source-binding-preservation.v1',base_tables_preserved=len(tables),tables=results,bookkeeping_timestamp_differences=changes,
 prior_number_events_preserved=counts['card_number_reading_evidence'],prior_source_fact_events_preserved=counts['source_image_fact_evidence'],
 prior_graph_history_preserved=old.execute('SELECT COUNT(*) FROM card_relationship_assertion').fetchone()[0],
 new_number_events=17,new_fact_events=17,new_mechanic_bindings=new.execute('SELECT COUNT(*) FROM source_mechanic_binding').fetchone()[0],
 catalog_coordinates_changed=False,new_graph_assertions=0)
(root/'preservation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['base_tables_preserved','prior_number_events_preserved','prior_source_fact_events_preserved','prior_graph_history_preserved']}))

