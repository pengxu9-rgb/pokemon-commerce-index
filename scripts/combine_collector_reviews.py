"""Combine an original source gate and context-only recovery without hiding failures."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pokemon_index import collector_discovery
from scripts.public_question_sandbox import read_jsonl,sha_file


def combine(directory,base_report,recovery_report,output):
    if output.exists():raise FileExistsError('combined output must be new')
    recovery=directory/'evidence_recovery'
    original={r['id']:r for r in read_jsonl(directory/'source_questions.jsonl')}
    recovered={r['id']:r for r in read_jsonl(recovery/'source_questions.jsonl')}
    expect={r['id']:r for r in read_jsonl(directory/'expectations.jsonl')}
    for r in read_jsonl(recovery/'expectations.jsonl'):
        if r!=expect[r['id']]:raise ValueError('recovery changed reference expectations')
    for item_id,row in recovered.items():
        if row!=original[item_id]:raise ValueError('recovery changed a source question')
    a=json.loads((directory/'source_gate/report.json').read_text())
    b=json.loads((recovery/'source_gate/report.json').read_text())
    accepted={r['id'] for r in a['decisions'] if r['accepted']}
    recovered_ids={r['id'] for r in b['decisions'] if r['accepted']}
    if accepted&recovered_ids:raise ValueError('duplicate accepted question')
    if not recovered_ids<=set(recovered)-accepted:raise ValueError('unexpected recovery acceptance')
    reports=[json.loads(path.read_text()) for path in [base_report,recovery_report]]
    for report,ids in zip(reports,[accepted,recovered_ids]):
        if {r['id'] for r in report['results']}!=ids:raise ValueError('replay differs from gate')
        if report['executor_sha256']!=sha_file(Path(collector_discovery.__file__)):
            raise ValueError('replay does not describe current executor')
    baseline=json.loads((directory/'initial-codex-qualified-report.json').read_text())
    baseline_by={r['id']:r for r in baseline['results']}
    recovered_first=json.loads((recovery/'initial-codex-qualified-report.json').read_text())
    if any(baseline_by[r['id']]!=r for r in recovered_first['results']):
        raise ValueError('recovery first replay differs from baseline')
    rows=sorted(reports[0]['results']+reports[1]['results'],key=lambda r:r['id'])
    summary=dict(schema='pokemon.collector-source-diagnostic.v1',cases=len(rows),
         passed=sum(r['passed'] for r in rows),failed=sum(not r['passed'] for r in rows),
         passing_catalog_partials=sum(r['passed'] and r['outcome']=='scoped_catalog_partial' for r in rows),
         passing_evidence_blockers=sum(r['passed'] and r['outcome']=='evidence_blocker' for r in rows),
         complete_answers_established=0,results=rows,source_qualification=dict(
             candidates=len(original),original_accepted=a['accepted'],original_rejected=a['rejected'],
             context_only_recovered=len(recovered_ids),unique_qualified_originals=len(accepted|recovered_ids),
             unqualified_originals=sorted(set(original)-accepted-recovered_ids),
             questions_and_expectations_unchanged=True),first_runtime_passed=baseline['passed'],
         executor_sha256=sha_file(Path(collector_discovery.__file__)),
         evidence_file_sha256={str(path):sha_file(path) for path in [base_report,recovery_report,directory/'source_gate/report.json',recovery/'source_gate/report.json',directory/'collection_lock.json',recovery/'collection_lock.json']},
         interpretation='Fresh public originals with retained context-only evidence recovery. Corrected development outcomes split into scoped catalog partials and evidence blockers; not blind or complete answer accuracy.')
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['cases','passed','failed','passing_catalog_partials','passing_evidence_blockers']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['directory','base-report','recovery-report','output']:p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();combine(a.directory,a.base_report,a.recovery_report,a.output)
