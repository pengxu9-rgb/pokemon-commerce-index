"""Replay source-qualified collector requests; preserve initial diagnostic results.

Acceptance includes explicitly scoped partial results and useful evidence blockers.
It does not measure population accuracy or complete answers to collector requests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from contextlib import closing
from pathlib import Path
from pokemon_index import core, collector_discovery
from scripts.public_question_sandbox import read_jsonl, sha_file


def catalog_fingerprint(db, *, include_collector_evidence=True) -> str:
    """Stable discovery identity/facet evidence, independent of SQLite file layout."""
    h=hashlib.sha256()
    tables=['card','card_facet','catalog_set_localized','catalog_vocabulary',
            'character_family','character_family_member']
    if (include_collector_evidence and db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_collector_evidence'").fetchone()
            and db.execute('SELECT 1 FROM catalog_collector_evidence LIMIT 1').fetchone()):
        tables.append('catalog_collector_evidence')
    for table in tables:
        columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
        h.update(json.dumps([table,columns]).encode())
        for row in db.execute('SELECT * FROM '+table+' ORDER BY '+','.join(columns)):
            h.update(json.dumps(list(row),ensure_ascii=False,separators=(',',':')).encode())
            h.update(b'\n')
    return h.hexdigest()


def evaluate(db_path: Path, directory: Path, *, initial=False, eligible_ids=None) -> dict:
    lock=json.loads((directory/'collection_lock.json').read_text())
    for key,name in [('source_sha256','source_questions.jsonl'),('evidence_sha256','source_evidence.jsonl'),
                     ('expectations_sha256','expectations.jsonl')]:
        if sha_file(directory/name)!=lock[key]:raise ValueError('frozen input changed: '+name)
    catalog_sha=sha_file(db_path)
    with closing(core.connect(db_path,readonly=True)) as db:
        fingerprint=catalog_fingerprint(db)
    if catalog_sha!=lock['catalog_sha256']:
        equivalent=json.loads((directory/'catalog-equivalence-lock.json').read_text())
        if initial or equivalent['baseline_catalog_sha256']!=lock['catalog_sha256'] or equivalent['discovery_evidence_sha256']!=fingerprint:
            raise ValueError('reference discovery evidence changed')
    if initial:
        for name,digest in lock['initial_runtime_sha256'].items():
            if sha_file(Path(name))!=digest:raise ValueError('initial runtime changed: '+name)
    root_labels={r['id']:r for r in read_jsonl(directory/'codex_preflight.jsonl')}
    cases=read_jsonl(directory/'source_questions.jsonl')
    expectations={r['id']:r for r in read_jsonl(directory/'expectations.jsonl')}
    results=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        for case in cases:
            if root_labels[case['id']]['status']!='faithful':continue
            if eligible_ids is not None and case['id'] not in eligible_ids:continue
            expected=expectations[case['id']]; pages=[];cards=[]; offset=0; errors=[]
            while True:
                page=collector_discovery.execute(db,case['question'],limit=100,offset=offset)
                pages.append(page);cards.extend(page['cards'])
                if not page.get('coverage',{}).get('has_more'):break
                offset+=100
                if offset>100000:raise ValueError('unbounded pagination')
            result=pages[0]; actual=[c['card_id'] for c in cards]
            kind=expected['kind']; reference=expected.get('reference_card_ids')
            task={'artist':'artist_cards','species':'character_cards','set':'set_cards'}.get(kind,kind)
            if result['task']!=task:errors.append('task mismatch')
            missing=sorted(set(reference or [])-set(actual));extra=sorted(set(actual)-set(reference or []))
            if reference is not None:
                if missing:errors.append('missing scoped catalog records')
                if extra:errors.append('unsupported catalog records')
                if not actual:errors.append('no useful catalog records')
            else:
                if not result.get('next_question') or not result.get('required_evidence'):
                    errors.append('blocker lacks specific clarification or evidence')
                if actual:errors.append('unsupported card answer to evidence-blocked request')
            for gap in expected['required_unfulfilled']:
                if gap not in result.get('unfulfilled_constraints',[]):errors.append('unacknowledged constraint: '+gap)
            if result['prices'] or result['live_offers']:errors.append('unsupported market evidence')
            if result['public_display_allowed']:errors.append('unsupported public display approval')
            if result.get('coverage',{}).get('global_printing_completeness_established'):errors.append('unsupported complete checklist')
            if any(c.get('price_comparable') or c.get('automatic_offer_join_allowed') for c in cards):
                errors.append('unsupported equivalence or automatic offer approval')
            if len(actual)!=len(set(actual)):errors.append('pagination duplicated identities')
            dates=[c['release_date'] for c in cards if c['release_date']]
            if dates!=sorted(dates):errors.append('release ordering incorrect')
            unknown=False
            for card in cards:
                if not card['release_date']:unknown=True
                elif unknown:errors.append('dated record after unknown date');break
            results.append(dict(id=case['id'],question=case['question'],source_url=case['source_url'],
                passed=not errors,errors=errors,expected_task=task,actual_task=result['task'],
                returned_cards=len(cards),expected_cards=len(reference) if reference is not None else None,
                missing_cards=missing,extra_cards=extra if reference is not None else [],
                outcome='scoped_catalog_partial' if reference is not None else 'evidence_blocker',
                first_page=result,page_count=len(pages),returned_card_ids=actual))
    return dict(schema='pokemon.collector-source-diagnostic.v1',cases=len(results),
        passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),
        passing_catalog_partials=sum(r['passed'] and r['outcome']=='scoped_catalog_partial' for r in results),
        passing_evidence_blockers=sum(r['passed'] and r['outcome']=='evidence_blocker' for r in results),
        complete_answers_established=0,results=results,source_sha256=lock['source_sha256'],
        expectations_sha256=lock['expectations_sha256'],catalog_sha256=catalog_sha,
        baseline_catalog_sha256=lock['catalog_sha256'],discovery_evidence_sha256=fingerprint,
        executor_sha256=sha_file(Path(collector_discovery.__file__)),
        interpretation='Purposive source-backed diagnostic, not blind user accuracy. Scoped partial results and evidence blockers are counted separately; no complete collector answer is established.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True)
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--initial',action='store_true')
    p.add_argument('--eligible',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('diagnostic output must be new')
    ids={r['id'] for r in read_jsonl(a.eligible)} if a.eligible else None
    report=evaluate(a.db,a.directory,initial=a.initial,eligible_ids=ids)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['cases','passed','failed','passing_catalog_partials','passing_evidence_blockers']}))
if __name__=='__main__':main()
