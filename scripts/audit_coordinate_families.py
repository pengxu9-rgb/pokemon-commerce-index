"""Audit unresolved coordinate families without assigning pages to finishes."""
import argparse
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from scripts.audit_japanese_metadata_batch import fetch,parse_page
from scripts.audit_jp_source_conflicts import compact


def audit(queue,cache,output):
    if output.exists():raise FileExistsError(output)
    cache.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(l) for l in queue.read_text().splitlines()]
    def check(row):
        result=dict(group=row,pages=[],decision='pending')
        if not row['references']:
            result['decision']='missing_reference_hold';return result
        try:
            source_names={compact(c['name']) for c in row['catalog_records']}
            for ref in row['references']:
                url='https://www.pokemon-card.com/card-search/details.php/card/'+ref['native_id']
                raw,receipt=fetch(url,cache);page={**receipt,**parse_page(raw)}
                result['pages'].append(page)
                selected=[e for e in page['numbered_entries'] if (e['set_code'],e['collector_number'])==(row['set_code'],row['collector_number'])]
                if len(selected)!=1:raise ValueError('official coordinate differs')
                page.update(selected[0])
                if compact(ref['name'])!=compact(page['name']):raise ValueError('reference and current official title differ')
            official_names={compact(p['name']) for p in result['pages']}
            if official_names==source_names:
                result['decision']='coordinate_family_supported'
            elif len(source_names)==1 and all(re.fullmatch(re.escape(next(iter(source_names)))+r'[（(][^）)]+[）)]',n) for n in official_names):
                result['decision']='coordinate_supported_name_qualifier'
            else:result['decision']='source_name_conflict_hold'
        except Exception as e:
            result.update(decision='fetch_or_identity_hold',error_type=type(e).__name__,error=str(e)[:250])
        return result
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for item in pool.map(check,rows):
            results.append(item)
            if len(results)%25==0:print(json.dumps(dict(reviewed=len(results),total=len(rows),decisions=dict(Counter(r['decision'] for r in results)))),flush=True)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in results))
    summary=dict(schema='pokemon.coordinate-family-audit.v1',groups=len(rows),pages=sum(len(r['pages']) for r in results),
        decisions=dict(Counter(r['decision'] for r in results)),queue_sha256=hashlib.sha256(queue.read_bytes()).hexdigest(),
        audit_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        scope='coordinate-family evidence only; page-to-finish assignment and copy/price equivalence unverified')
    output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['queue','cache','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit(a.queue,a.cache,a.output)))
