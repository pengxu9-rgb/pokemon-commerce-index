import sqlite3,json,hashlib
from pathlib import Path
from collections import Counter
root=Path('catalog/source-facts-thousand-v1')
old=sqlite3.connect('file:/tmp/pokemon-cross-release-source-facts-v1.sqlite3?mode=ro',uri=True);new=sqlite3.connect('file:/tmp/pokemon-source-facts-thousand-v1.sqlite3?mode=ro',uri=True);old.row_factory=new.row_factory=sqlite3.Row
append={'card_number_reading_evidence','source_image_fact_evidence'};tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if r[0] not in append];results=[];changes=[]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def normalize(table,row):
 d=dict(row);ignored=[]
 if table in ['card_identity_exception','card_number_conflict_rule','card_rarity_correction']:ignored=['applied_at']
 elif table=='card_relationship_assertion' and d['review_status']=='proposed' and d['asserted_by']=='ai-artwork-review-v1':ignored=['asserted_at']
 clocks={k:d.pop(k) for k in ignored};return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')),clocks
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
 before=[tuple(r) for r in old.execute('SELECT * FROM '+table)];after=[tuple(r) for r in new.execute('SELECT * FROM '+table)]
 assert not (Counter(before)-Counter(after)),table;counts[table]=len(before)
report=dict(schema='pokemon.source-facts-thousand-preservation.v1',base_tables_preserved=len(tables),tables=results,bookkeeping_timestamp_differences=changes,prior_number_events_preserved=counts['card_number_reading_evidence'],prior_source_fact_events_preserved=counts['source_image_fact_evidence'],catalog_coordinates_and_graph_decisions_changed=False)
(root/'preservation-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['base_tables_preserved','prior_number_events_preserved','prior_source_fact_events_preserved']}))
