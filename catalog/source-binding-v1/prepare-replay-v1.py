from pathlib import Path
import sqlite3,json,hashlib
from pokemon_index import number_evidence as n,source_image_facts as f
r=Path('catalog/source-binding-v1');db=sqlite3.connect('file:/tmp/pokemon-source-binding-v1.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row
queue=[json.loads(l) for l in (r/'frozen-cohort-v1.jsonl').read_text().splitlines()]
extra=[json.loads(l) for l in Path('catalog/source-notation-v1/number-evidence-v1.jsonl').read_text().splitlines()]
subjects=[q['priority']['card_id'] for q in queue]+[q['card_id'] for q in extra];assert len(set(subjects))==58
facts=[];outcomes=[]
for cid in subjects:
 raw=db.execute('SELECT record_json FROM source_image_fact_evidence WHERE card_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()
 number=n.context(db,cid)
 if raw:facts.append(json.loads(raw[0]))
 outcomes.append(dict(card_id=cid,number_event_id=number['event_id'] if number else None))
(r/'replay-facts-v1.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in facts))
(r/'replay-outcomes-v1.json').write_text(json.dumps(dict(outcomes=outcomes),indent=2)+'\n')
questions=[
 dict(id='binding-question-01',kind='source_mechanic',question='比较 ja:SM12A:011/173:normal 和 ja:SM12A:021/173:holo：官方棱镜星符号能确认实物品相和价格吗？',held_card_id='ja:SM12A:011/173:normal'),
 dict(id='binding-question-02',kind='plain',question='比较 ja:M6A:124/103:holo 和 ja:M6A:104/103:holo：新增官方图片能直接匹配卖家报价吗？'),
 dict(id='binding-question-03',kind='number_conflict',question='比较 en:SM12:143/236:standard 和 en:SM12:129/236:standard：143a与143的冲突解决了吗？'),
 dict(id='binding-question-04',kind='source_mechanic',question='比较 ja:SM8B:047/150:holo 和 ja:SM8B:058/150:holo：棱镜星机制与普通同名卡可以合价吗？',held_card_id='ja:SM8B:047/150:holo'),
 dict(id='binding-question-05',kind='plain',question='比较 ja:S8B:056/184:holo 和 ja:S8B:057/184:holo：组合图可以验证单张品相吗？',held_card_id='ja:S8B:056/184:holo'),
 dict(id='binding-question-06',kind='auxiliary_number',question='比较 ja:M6A:017/103:normal 和 ja:M6A:018/103:normal：第二套编号01/30是不是只印了30张？',held_card_id='ja:M6A:017/103:normal',auxiliary_number_texts=['01/30']),
 dict(id='binding-question-07',kind='plain',question='比较 ja:M6A:119/103:holo 和 ja:M6A:121/103:holo：未找到官方卡图可以用同名卡代替吗？'),
 dict(id='binding-question-08',kind='plain',question='比较 ja:M6A:00G/103:holo 和 ja:M6A:00R/103:holo：新找到AR卡图也能补齐RGB Mew吗？'),
 dict(id='binding-question-09',kind='plain',question='比较 ja:SV4A:191/190:holo 和 ja:SV4A:192/190:holo：先前S编号解释有没有被覆盖？'),
 dict(id='binding-question-10',kind='plain',question='Compare ja:M6A:115/103:holo and ja:M6A:117/103:holo: can the two regional Meowth names share seller-copy and price evidence?'),
 dict(id='binding-question-11',kind='reviewed_artwork',question='Compare en:SV02:004/193:normal and en:SV04.5:001/091:normal: is the previous exact artwork relation still available?'),
 dict(id='binding-question-12',kind='hp_conflict',question='比较 en:HGSSP:HGSS01/000025:holo 和 en:HGSSP:HGSS02/000025:holo：原有HP冲突还存在吗？')
]
(r/'questions-v1.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in questions));print(json.dumps(dict(fact_subjects=len(facts),unavailable=len(subjects)-len(facts),questions=len(questions))))

