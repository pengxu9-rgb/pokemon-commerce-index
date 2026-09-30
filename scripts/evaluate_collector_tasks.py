"""Evaluate executed development tasks, preserving scope and result errors."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from pokemon_index import core,collector_discovery
from contextlib import closing


def evaluate(db_path: Path, frozen_dir: Path) -> dict:
    inputs=frozen_dir/'tasks-frozen.jsonl'
    lock=json.loads((frozen_dir/'tasks-lock.json').read_text())
    if hashlib.sha256(inputs.read_bytes()).hexdigest()!=lock['questions_sha256']:
        raise ValueError('frozen task questions changed')
    results=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        for case in [json.loads(l) for l in inputs.read_text().splitlines()]:
            expected=case['expectation']; errors=[]; cards=[]; page=None; offset=0
            while True:
                current=collector_discovery.execute(db,case['question'],limit=100,offset=offset)
                if page is None:page=current
                cards.extend(current['cards'])
                if not current.get('coverage',{}).get('has_more'):break
                offset+=100
            if page['task']!=expected['task']:errors.append('task mismatch')
            if page['prices'] or page['live_offers']:errors.append('unsupported market result')
            if page['languages']!=expected['languages'] and 'reference_card_ids' in expected:
                errors.append('language scope mismatch')
            actual=[c['card_id'] for c in cards]; reference=expected.get('reference_card_ids')
            missing=sorted(set(reference or [])-set(actual)); extra=sorted(set(actual)-set(reference or []))
            if reference is not None:
                if missing:errors.append('missing scoped catalog members')
                if extra:errors.append('unsupported catalog members')
            if expected.get('family_id'):
                if page.get('family_id')!=expected['family_id']:errors.append('wrong family')
                members={m['dex_id'] for m in page.get('family',{}).get('members',[])}
                if members!=set(expected['member_dex_ids']):errors.append('wrong evolution membership')
                if members & set(expected.get('excluded_dex_ids',[])):errors.append('unsupported paradox family member')
            if page['task']=='artist_cards':
                if not actual:errors.append('empty artist result')
                for cid in actual:
                    if not db.execute("SELECT 1 FROM card_facet WHERE card_id=? AND facet_type='illustrator' AND value=?",(cid,page.get('illustrator'))).fetchone():
                        errors.append('unsupported artist credit');break
            dates=[c['release_date'] for c in cards if c['release_date']]
            if dates!=sorted(dates):errors.append('incorrect date ordering')
            found_unknown=False
            for card in cards:
                if not card['release_date']:found_unknown=True
                elif found_unknown:errors.append('known date after unknown date');break
            if page.get('coverage',{}).get('global_printing_completeness_established'):
                errors.append('unproven complete checklist claim')
            results.append({'id':case['id'],'question':case['question'],'task':page['task'],
                'status':page['status'],'passed':not errors,'errors':errors,'returned_cards':len(actual),
                'expected_cards':len(reference) if reference is not None else None,
                'missing_cards':missing,'extra_cards':extra if reference is not None else [],
                'coverage':page.get('coverage'),'next_question':page['next_question']})
    return {'schema':'pokemon.collector-development-results.v1','cases':len(results),
            'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
            'results':results,'questions_sha256':lock['questions_sha256'],
            'catalog_sha256':hashlib.sha256(db_path.read_bytes()).hexdigest(),
            'executor_sha256':hashlib.sha256(Path(collector_discovery.__file__).read_bytes()).hexdigest(),
            'interpretation':'Authored source-backed development tasks, not fresh real-user or blind marketplace accuracy. Some controls test explicit evidence blockers; exact printing/alias behavior is tested separately.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True)
    p.add_argument('--frozen-dir',type=Path,default=Path('catalog/supported-discovery-v1'))
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=evaluate(a.db,a.frozen_dir)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('cases','passed','failed','interpretation')},indent=2))
if __name__=='__main__':main()
