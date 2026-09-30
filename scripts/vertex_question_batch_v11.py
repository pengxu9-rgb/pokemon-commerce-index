"""Checkpoint independent frozen question calls in a bounded concurrent batch.

Source fidelity sees transcribed question context, not fetched pages. Failures
remain as unverifiable source decisions or failed extraction rows.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts import vertex_public_question_preflight as audit
from scripts import vertex_public_question_facts_v7 as facts


def source_one(candidate, evidence, source_sha, evidence_sha, project, location, token):
    request, prompt_sha = audit._request(candidate, evidence)
    request['generationConfig']['maxOutputTokens'] = 8192
    row = dict(id=candidate['id'], model_family='google', source_sha256=source_sha,
               evidence_sha256=evidence_sha, requested_model=audit.MODEL,
               prompt_version=audit.PROMPT_VERSION, prompt_sha256=prompt_sha)
    errors = []
    for attempt in (1, 2):
        response = None
        try:
            response = audit._call_model(project, location, token, request)
            choices = response.get('candidates') or []
            if not choices or choices[0].get('finishReason') != 'STOP':
                raise ValueError('incomplete candidate')
            raw = ''.join(p.get('text', '') for p in choices[0].get('content', {}).get('parts', []))
            answer = json.loads(raw)
            if (not isinstance(answer, dict) or set(answer) != {'status', 'reason'} or
                    answer['status'] not in audit.STATUSES or not isinstance(answer['reason'], str)
                    or not answer['reason'].strip()):
                raise ValueError('invalid source decision')
            row.update(answer, attempts=attempt, attempt_errors=errors,
                       model_version=response.get('modelVersion'),
                       response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                       generation_config=dict(request['generationConfig']),
                       usage_metadata=response.get('usageMetadata'))
            return row
        except Exception as exc:
            reason = ((response.get('candidates') or [{}])[0].get('finishReason') if response else None)
            errors.append(dict(attempt=attempt, error_type=type(exc).__name__, finish_reason=reason))
            if reason == 'MAX_TOKENS':
                request['generationConfig']['maxOutputTokens'] = 16384
    return dict(row, status='unverifiable', reason='Bounded source review failed; retain and exclude.',
                attempts=2, attempt_errors=errors)


def run(stage, directory, checkpoint, project, location, workers=3):
    if stage == 'source':
        source, evidence_path = directory/'source_questions.jsonl', directory/'source_evidence.jsonl'
        questions = read_jsonl(source)
        evidence = {r['id']:r for r in read_jsonl(evidence_path)}
        if set(evidence) != {r['id'] for r in questions}:
            raise ValueError('source evidence IDs differ')
        source_sha, evidence_sha = sha_file(source), sha_file(evidence_path)
        lock = json.loads((directory/'source_review_lock.json').read_text())
        for key, path in [('runner_sha256', Path(__file__)), ('source_sha256', source),
                          ('evidence_sha256', evidence_path), ('prompt_module_sha256', Path(audit.__file__))]:
            if lock[key] != sha_file(path):
                raise ValueError('source review lock changed')
    else:
        manifest = json.loads((directory/'manifest.json').read_text())
        for key, path in [('batch_runner_sha256', Path(__file__)),
                          ('blind_sha256', directory/'blind_questions.jsonl'),
                          ('v7_planner_sha256', Path(facts.routing.__file__)),
                          ('v7_fact_extractor_sha256', Path(facts.__file__))]:
            if manifest[key] != sha_file(path):
                raise ValueError('fact extraction lock changed')
        for path, digest in manifest['runtime_dependency_sha256'].items():
            if sha_file(Path(path)) != digest:
                raise ValueError('runtime dependency changed')
        questions = read_jsonl(directory/'blind_questions.jsonl')
    if len({q['id'] for q in questions}) != len(questions):
        raise ValueError('duplicate question IDs')
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {r['id']:r for r in existing}
    if len(by_id)!=len(existing) or set(by_id)-{q['id'] for q in questions}:
        raise ValueError('checkpoint IDs differ')
    for question in questions:
        row = by_id.get(question['id'])
        if row is None:
            continue
        if stage == 'source':
            expected = dict(source_sha256=source_sha, evidence_sha256=evidence_sha,
                            prompt_sha256=audit._request(question, evidence[question['id']])[1])
        else:
            expected = dict(question_sha256=question['question_sha256'],
                            prompt_sha256=facts._request(question)[1], prompt_version=facts.PROMPT_VERSION)
        if (row.get('model_family') != 'google' or row.get('requested_model') != audit.MODEL
                or any(row.get(k)!=v for k,v in expected.items())):
            raise ValueError('checkpoint inputs differ')
    pending = [q for q in questions if q['id'] not in by_id]
    token = subprocess.check_output(['gcloud','auth','print-access-token'], text=True,
                                    stderr=subprocess.DEVNULL).strip() if pending else ''
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool, checkpoint.open('a') as handle:
        tasks = {pool.submit(source_one, q, evidence[q['id']], source_sha, evidence_sha, project, location, token)
                 if stage=='source' else pool.submit(facts._extract_one, q, project, location, token):q['id']
                 for q in pending}
        for task in as_completed(tasks):
            row = task.result()
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+'\n');handle.flush()
            print(json.dumps(dict(id=row['id'],status=row['status'])),flush=True)
    rows = read_jsonl(checkpoint)
    return dict(stage=stage, questions=len(questions), reviewed=len(rows),
                statuses={s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['source','facts'], required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--location',default='global')
    args=parser.parse_args()
    print(json.dumps(run(args.stage,args.directory,args.checkpoint,args.project,args.location)))


if __name__=='__main__':main()
