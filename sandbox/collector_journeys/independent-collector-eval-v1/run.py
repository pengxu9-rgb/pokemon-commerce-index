#!/usr/bin/env python3
"""Replay a frozen collector evaluation; mechanical checks are not usefulness scores.

Exit 0: all cases executed, no frozen safety violation (usefulness may still fail).
Exit 2: safety violation. Exit 3: execution/preflight fault. Exit 4: freeze changed.
Use a newly built catalog or a same-job snapshot with its pinned build receipt.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
AUTHORITY = {
    'physical_printing_verified', 'physical_copy_verified', 'physical_copy_verification',
    'automatic_offer_join_allowed', 'public_display_allowed', 'transaction_ready',
    'purchase_ready', 'ready_for_offer_tracking', 'ownership_assertions_verified',
    'complete_collection_established', 'complete_missing_list_established',
}
ACTION_FIELDS = {
    'ask': {'type', 'question'}, 'reply': {'type', 'text'},
    'preferences': {'type', 'preferences'}, 'refine': {'type', 'scope'},
    'inventory': {'type', 'owned_items'}, 'resolve_owned': {'type', 'item_id', 'card_id'},
    'select': {'type', 'card_id'}, 'clear_target': {'type'}, 'page': {'type', 'offset'},
    'feedback': {'type', 'card_id', 'reaction'},
    'compare': {'type', 'left_card_id', 'right_card_id'},
    'choose_comparison': {'type', 'side', 'card_id'},
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def verify_fixture(directory=HERE):
    freeze = json.loads((directory / 'metadata/freeze.json').read_text())
    for name, item in freeze['files'].items():
        if sha(directory / name) != item['sha256']:
            raise ValueError('frozen fixture changed: ' + name)
    suite = json.loads((directory / 'questions.json').read_text())
    cases = suite['cases']
    if len(cases) != 30 or len({c['id'] for c in cases}) != 30:
        raise ValueError('evaluation must retain all 30 distinct cases')
    for case in cases:
        if case['steps'][0]['action'] != {'type': 'ask', 'question': case['question']}:
            raise ValueError('initial raw question differs from request')
        if not 1 <= len(case['steps']) <= 20 or case['limit'] != 5:
            raise ValueError('frozen conversation bounds changed')
        for i, step in enumerate(case['steps']):
            action = step['action']
            if set(action) != ACTION_FIELDS.get(action.get('type'), set()):
                raise ValueError('unsupported action shape: ' + case['id'])
            for binding in step.get('bind', {}).values():
                if not 0 <= binding['from_step'] < i or binding['candidate_index'] < 0:
                    raise ValueError('binding must name an earlier displayed candidate')
    return suite, freeze


def preflight(manifest_path):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    if manifest.get('schema') != 'pokemon.catalog-build.v1':
        raise ValueError('unknown catalog manifest')
    files = []
    for item in manifest['steps']:
        p = (path.parent / item['path']).resolve()
        row = {'path': item['path'], 'expected_sha256': item['sha256']}
        if not p.is_relative_to(path.parent):
            row['status'] = 'unsafe_path'
        elif not p.is_file():
            row['status'] = 'missing'
        else:
            row['actual_sha256'] = sha(p)
            row['status'] = 'verified' if row['actual_sha256'] == item['sha256'] else 'hash_mismatch'
        files.append(row)
    return {'manifest_path': str(path), 'manifest_sha256': sha(path),
            'complete': all(x['status'] == 'verified' for x in files),
            'counts': dict(Counter(x['status'] for x in files)), 'inputs': files}


def runtime_hashes(root):
    for required in ('pokemon_index/schema.sql', 'pokemon_index/metadata_views.sql',
                     'pokemon_index/collector-character-affiliations-v1.json',
                     'pokemon_index/collector_journey.py', 'scripts/build_catalog_snapshot.py'):
        if not (root / required).is_file():
            raise ValueError('runtime source missing: ' + required)
    paths = sorted(p for p in (root / 'pokemon_index').iterdir()
                   if p.suffix in {'.py', '.sql', '.json'})
    paths.append(root / 'scripts/build_catalog_snapshot.py')
    return {str(p.relative_to(root)): sha(p) for p in paths}


def verify_snapshot(db, manifest, receipt, db_path, manifest_digest):
    """Check the same-job builder receipt and every expected catalog count.

    The receipt is a provenance record, not a signed proof. Database bytes are
    hashed before/after evaluation and the full portable revision is recorded.
    """
    expected = manifest['expected']
    if (receipt.get('manifest_sha256') != manifest_digest or
            Path(receipt.get('output', '')).resolve() != db_path.resolve() or
            receipt.get('steps') != len(manifest['steps']) or
            any(receipt.get(k) != v for k, v in expected.items())):
        raise ValueError('same-job build receipt does not match catalog/manifest')
    core = importlib.import_module('pokemon_index.core')
    actual = {k: v for k, v in core.catalog_status(db).items() if k in expected}
    for name in ('supported_catalog', 'card_metadata', 'coordinate_family', 'printing_evidence',
                 'source_corrections', 'number_evidence', 'source_image_facts', 'source_mechanic'):
        module = importlib.import_module('pokemon_index.' + name)
        actual.update({k: v for k, v in module.status(db).items() if k in expected})
    collector = importlib.import_module('pokemon_index.collector_evidence')
    actual.update({'collector_' + k: v for k, v in collector.status(db).items()
                   if 'collector_' + k in expected})
    counts = {
        'identity_exceptions': 'SELECT COUNT(*) FROM card_identity_exception',
        'number_conflict_rules': 'SELECT COUNT(*) FROM card_number_conflict_rule',
        'relationship_assertions': 'SELECT COUNT(*) FROM card_relationship_assertion',
        'verified_relationships': "SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'",
        'ai_artwork_proposals': "SELECT COUNT(*) FROM card_relationship_assertion WHERE relation_type='same_artwork' AND review_status='proposed' AND asserted_by='ai-artwork-review-v1'",
        'rarity_corrections': 'SELECT COUNT(*) FROM card_rarity_correction',
        'collector_evidence_events': 'SELECT COUNT(*) FROM catalog_collector_evidence',
    }
    for key, query in counts.items():
        if key in expected:
            actual[key] = db.execute(query).fetchone()[0]
    if actual != expected:
        differences = {k: {'expected': v, 'actual': actual.get(k)} for k, v in expected.items()
                       if actual.get(k) != v}
        raise ValueError('snapshot counts do not match pinned manifest: ' + json.dumps(differences))
    return {'every_manifest_expected_count_verified': True, 'counts': actual,
            'receipt_type': 'same-job builder JSON; not a cryptographic attestation'}


def resolve_action(step, prefixes, bindings):
    for name, binding in step.get('bind', {}).items():
        response = prefixes[binding['from_step']].get('response')
        if response is None:
            raise ValueError('binding source step has no response: ' + name)
        cards = response.get('candidate_cards', [])
        if binding['candidate_index'] >= len(cards):
            raise ValueError('frozen shown-candidate binding unavailable: ' + name)
        bindings[name] = cards[binding['candidate_index']]['card_id']

    def replace(value):
        if isinstance(value, dict):
            if set(value) == {'$bind'}:
                return bindings[value['$bind']]
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return value

    return replace(step['action'])


def authority_violations(value, path='response'):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = path + '.' + key
            if key in AUTHORITY and child not in (None, False, 0):
                found.append(location)
            if key in {'live_offers', 'prices'} and child:
                found.append(location)
            found.extend(authority_violations(child, location))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(authority_violations(child, f'{path}[{i}]'))
    return found


def selected(response):
    return (response.get('target_intent') or {}).get('card_id') or (
        response.get('selected_catalog_target') or {}).get('card_id')


def safety_checks(case, prefixes):
    violations = []
    previous_target = None
    for i, prefix in enumerate(prefixes):
        response = prefix.get('response')
        if response is None:
            continue
        violations.extend(f'step[{i}].{p}' for p in authority_violations(response))
        target = selected(response)
        if target and target != previous_target and prefix['action']['type'] != 'select':
            violations.append(f'step[{i}].target_created_without_separate_selection')
        if target and (response.get('selection_blockers') or
                       response.get('card_selection_blockers', {}).get(target)):
            violations.append(f'step[{i}].blocked_target_selected')
        if response.get('discovery', {}).get('task') == 'two_card_comparison':
            if target or response.get('selection_allowed'):
                violations.append(f'step[{i}].comparison_exposed_selection_authority')
        previous_target = target
    # These frozen actions are rejected for authority reasons, not optional UX.
    if case['id'] in {'ICU-29', 'ICU-30'} and len(prefixes) == len(case['steps']):
        if prefixes[-1].get('response') is not None:
            violations.append('stale_or_identity_held_action_was_accepted')
    return violations


def ids(response):
    return [c['card_id'] for c in response.get('candidate_cards', [])]


def coordinates(response):
    return {(c['language'], c['set_code'], c['collector_number'])
            for c in response.get('candidate_cards', [])}


def facet_matches(evidence, card_id, requirement):
    row = evidence.get(card_id, {})
    if any(x['facet_type'] == requirement['facet'] and x['value'] == requirement['value']
           for x in row.get('current_source_facets', [])):
        return True
    derived = row.get('runtime_derived_name_affiliation')
    return bool(requirement.get('affiliation_allowed') and requirement['facet'] == 'dex_id'
                and derived and str(derived['dex_id']) == requirement['value'])


def check_constraints(case, prefixes):
    responses = [p['response'] for p in prefixes if p.get('response') is not None]
    last = responses[-1] if responses else {}
    first = responses[0] if responses else {}
    cards = last.get('candidate_cards', [])
    evidence = {e['card_id']: e for p in prefixes for e in p.get('candidate_evidence', [])}
    checks = []
    for requirement in case['expected']['automatable_checks']:
        kind = requirement['check']
        status, detail = False, None
        if kind == 'minimum_candidates':
            status, detail = len(cards) >= requirement['value'], len(cards)
        elif kind == 'candidate_count':
            status, detail = len(cards) == requirement['value'], len(cards)
        elif kind == 'all_candidate_fields':
            status = all(all(c.get(k) == v for k, v in requirement['fields'].items()) for c in cards)
            detail = 'vacuous for zero candidates; minimum-candidate and reviewer relevance checks are separate'
        elif kind == 'minimum_coordinates':
            detail = len(coordinates(last)); status = detail >= requirement['value']
        elif kind == 'candidate_provenance_present':
            status = bool(cards) and all(c.get('provenance') for c in cards)
        elif kind == 'candidate_facet':
            detail = [c['card_id'] for c in cards if not facet_matches(evidence, c['card_id'], requirement)]
            status = not detail
        elif kind == 'excluded_facet':
            detail = [c['card_id'] for c in cards if facet_matches(evidence, c['card_id'], requirement)]
            status = not detail
        elif kind == 'no_target':
            status = not selected(last)
        elif kind == 'target_id':
            detail = selected(last); status = detail == requirement['value']
        elif kind == 'different_from_previous_page':
            detail = sorted(set(ids(first)) & set(ids(last)))
            status = len(responses) >= 2 and bool(cards) and not detail
        elif kind == 'idempotent_last_feedback':
            if len(responses) >= 3:
                a, b = responses[-2:]
                status = ids(a) == ids(b) and a.get('recommendation') == b.get('recommendation')
        elif kind == 'dismiss_then_clear_restores':
            if len(responses) == 3 and ids(first):
                status = ids(first)[0] not in ids(responses[1]) and ids(first) == ids(last)
        elif kind == 'preferences_equal':
            status = all(last.get('preferences', {}).get(k) == v for k, v in requirement['value'].items())
        elif kind == 'absent_ids':
            detail = sorted(set(ids(last)) & set(requirement['values'])); status = not detail
        elif kind == 'inventory_unresolved':
            status = bool((last.get('inventory') or {}).get('unresolved_items'))
        elif kind == 'comparison_focus_separate_selection':
            status = (len(responses) == 3 and
                      first.get('discovery', {}).get('task') == 'two_card_comparison' and
                      not selected(first) and not selected(responses[1]) and
                      ids(responses[1]) == [requirement['value']] and
                      selected(last) == requirement['value'])
        elif kind == 'last_step_error':
            status = (len(prefixes) == len(case['steps']) and
                      prefixes[-1].get('execution_status') == 'expected_rejection')
        elif kind == 'initial_id':
            status = requirement['value'] in ids(first)
        elif kind == 'initial_identity_hold':
            status = bool(ids(first)) and all(first.get('card_selection_blockers', {}).get(cid) for cid in ids(first))
        else:
            raise ValueError('runner does not implement frozen check: ' + kind)
        checks.append({'requirement': requirement, 'mechanical_pass': bool(status), 'observed': detail})
    return checks


def candidate_evidence(db, response, affiliations):
    output = []
    for card in response.get('candidate_cards', []):
        cid = card['card_id']
        facets = [dict(r) for r in db.execute('''SELECT facet_type,value,provenance,rights_reference
            FROM discovery_card_facet WHERE card_id=? ORDER BY facet_type,value,provenance''', (cid,))]
        classified = [dict(r) for r in db.execute('''SELECT k.category,k.provenance,k.rights_reference
            FROM card_classification k JOIN card c ON c.card_id=k.card_id
            WHERE k.card_id=? AND k.provenance=c.provenance AND k.rights_reference=c.rights_reference''', (cid,))]
        output.append({'card_id': cid, 'current_source_facets': facets,
                       'current_source_classification': classified,
                       'runtime_derived_name_affiliation': affiliations.get(cid),
                       'derived_affiliation_independently_revalidated': False,
                       'identity_blockers': response.get('card_selection_blockers', {}).get(cid, [])})
    return output


@contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise TimeoutError('local replay exceeded configured prefix timeout')
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def execute_case(case, db, replay, revision, affiliations, seconds):
    turns, prefixes, bindings = [], [], {}
    blocked = None
    for index, step in enumerate(case['steps']):
        row = {'step_index': index, 'frozen_action': step['action']}
        if blocked:
            row.update(execution_status='not_executed_after_prior_blocker', blocker=blocked)
            prefixes.append(row)
            continue
        started = time.monotonic()
        try:
            resolved = resolve_action(step, prefixes, bindings)
            row['action'] = resolved
            turns.append(resolved)
            with deadline(seconds):
                response = replay(db, {'turns': list(turns), 'limit': case['limit'],
                                       'expected_revision': revision}, revision=revision)
            row.update(response=response, execution_status='executed')
            row['candidate_evidence'] = candidate_evidence(db, response, affiliations)
        except (ValueError, KeyError, TypeError, TimeoutError) as error:
            # A missing displayed binding is a genuine product path failure,
            # but the evaluator ran correctly. An API exception is separate.
            is_binding = 'action' not in row
            expected = (step.get('expect_error') and not is_binding and isinstance(error, ValueError))
            row.update(execution_status='expected_rejection' if expected else
                       'blocked_by_missing_candidate' if is_binding else 'execution_error',
                       error_type=type(error).__name__, error=str(error))
            blocked = row['execution_status']
        except Exception as error:
            row.update(execution_status='execution_error', error_type=type(error).__name__, error=str(error))
            blocked = 'execution_error'
        row['duration_seconds'] = round(time.monotonic() - started, 6)
        prefixes.append(row)
    constraints = check_constraints(case, prefixes)
    errors = [p for p in prefixes if p['execution_status'] == 'execution_error']
    path_blocked = any(p['execution_status'] == 'blocked_by_missing_candidate' for p in prefixes)
    return {'case_id': case['id'], 'category': case['category'], 'question': case['question'],
            'execution_status': 'execution_error' if errors else 'product_path_blocked' if path_blocked else 'executed',
            'expected': case['expected'], 'prefixes': prefixes, 'bindings': bindings,
            'safety_violations': safety_checks(case, prefixes), 'mechanical_constraints': constraints,
            'mechanical_constraints_met': all(c['mechanical_pass'] for c in constraints),
            'reviewer_scores': None}


def blank_score(case_id, execution_status):
    return dict(case_id=case_id, execution_status=execution_status,
                relevance=None, evidence_honesty=None, clarification_usefulness=None,
                completion=None, abstention_quality=None, relevant_count=None, displayed_count=None,
                distinct_coordinate_count=None, identity_held_count=None,
                claim_evidence_references=[], reviewer_explanation=None, remaining_work=None)


def execution_exit(results, integrity_ok=True):
    if not integrity_ok or any(r['execution_status'] == 'execution_error' for r in results):
        return 3
    if any(r['safety_violations'] for r in results):
        return 2
    return 0


def compact_report(report):
    compact = {k: report[k] for k in (
        'schema', 'started_at_utc', 'finished_at_utc', 'run_label', 'baseline_commit',
        'suite_sha256', 'runner_sha256', 'denominator', 'real_user_testing',
        'usefulness_scored', 'status', 'exit_code', 'interpretation')}
    for key in ('summary', 'catalog_revision', 'catalog_sha256_before', 'catalog_bytes_unchanged',
                'runtime_bytes_unchanged', 'error_type', 'error'):
        if key in report:
            compact[key] = report[key]
    compact['results'] = []
    for result in report['results']:
        row = {k: v for k, v in result.items() if k not in {'prefixes', 'expected'}}
        row['prefixes'] = []
        for prefix in result['prefixes']:
            p = {k: v for k, v in prefix.items() if k not in {'response', 'candidate_evidence'}}
            response = prefix.get('response')
            if response:
                p['observed'] = {
                    'status': response.get('status'), 'task': response.get('discovery', {}).get('task'),
                    'candidate_ids': ids(response), 'distinct_coordinates': len(coordinates(response)),
                    'next_step': response.get('next_step'), 'target_id': selected(response),
                    'selection_blockers': response.get('selection_blockers'),
                    'card_selection_blockers': response.get('card_selection_blockers'),
                    'preferences': response.get('preferences'),
                }
            row['prefixes'].append(p)
        compact['results'].append(row)
    return compact


def report_header(suite, freeze, args):
    return {'schema': 'pokemon.independent-collector-eval-report.v1', 'started_at_utc': now(),
            'run_label': args.label, 'baseline_commit': suite['baseline_commit'],
            'suite_sha256': freeze['files']['questions.json']['sha256'],
            'rubric_sha256': freeze['files']['rubric.json']['sha256'],
            'runner_sha256': sha(Path(__file__)), 'denominator': 30,
            'real_user_testing': False, 'usefulness_scored': False,
            'transport': 'direct read-only Python collector_journey.replay; not HTTP/Node or deployed UX',
            'interpretation': 'Mechanical constraints, safety and execution are separate from reviewer usefulness. No quality rate is inferred from this report.',
            'results': []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--build-db', type=Path)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--build-report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--expected-runtime-manifest', type=Path)
    parser.add_argument('--prefix-timeout', type=float, default=10.0)
    args = parser.parse_args(argv)
    summary_path = args.output.with_suffix('.summary.json')
    if args.output.exists() or summary_path.exists():
        parser.error('output already exists; use a new run path to retain failures')
    if args.prefix_timeout <= 0:
        parser.error('timeout must be positive')
    if args.db and args.build_db:
        parser.error('choose --db or --build-db')
    if args.db and not args.build_report:
        parser.error('--db requires the same-job --build-report JSON')
    try:
        suite, freeze = verify_fixture()
    except Exception as error:
        save_new(args.output, {'status': 'fixture_integrity_failure', 'error': str(error)})
        return 4
    report = report_header(suite, freeze, args)
    code = 3
    try:
        root = args.repo_root.resolve(strict=True)
        report['runtime_sha256'] = runtime_hashes(root)
        if args.expected_runtime_manifest:
            expected = json.loads(args.expected_runtime_manifest.read_text())
            missing = [p for p in expected if p.startswith('pokemon_index/') and
                       Path(p).suffix in {'.py', '.sql', '.json'} and not (root / p).is_file()]
            if missing:
                raise ValueError('baseline runtime source missing: ' + ', '.join(missing))
            differences = [p for p, h in report['runtime_sha256'].items()
                           if expected.get(p, {}).get('sha256') != h]
            if differences:
                raise ValueError('baseline runtime hash mismatch: ' + ', '.join(differences))
            report['baseline_runtime_hashes_verified'] = True
        manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
        report['catalog_preflight'] = preflight(manifest)
        if not report['catalog_preflight']['complete']:
            report['status'] = 'blocked_incomplete_catalog_inputs'
        elif args.preflight_only:
            report['status'] = 'preflight_complete_not_executed'
            code = 0
        elif args.build_db is None and args.db is None:
            raise ValueError('execution requires --build-db or --db with its same-job --build-report')
        else:
            if args.build_db is not None and args.build_db.exists():
                raise ValueError('build DB already exists; retain it and supply a new path')
            sys.path.insert(0, str(root))
            core = importlib.import_module('pokemon_index.core')
            journey = importlib.import_module('pokemon_index.collector_journey')
            affiliation = importlib.import_module('pokemon_index.collector_character_affiliation')
            builder = importlib.import_module('scripts.build_catalog_snapshot')
            if not Path(journey.__file__).resolve().is_relative_to(root):
                raise ValueError('runtime imported from wrong repo root')
            db_path = args.db or args.build_db
            if args.db:
                report['catalog_build'] = json.loads(args.build_report.read_text())
                report['build_report_sha256'] = sha(args.build_report)
            else:
                report['catalog_build'] = builder.build(manifest, db_path)
            before = sha(db_path)
            report['catalog_sha256_before'] = before
            with closing(core.connect(db_path, readonly=True)) as db:
                report['snapshot_validation'] = verify_snapshot(
                    db, json.loads(manifest.read_text()), report['catalog_build'], db_path,
                    report['catalog_preflight']['manifest_sha256'])
                revision = journey.catalog_revision(db)
                report['catalog_revision'] = revision
                affiliates = affiliation.affiliations(db)
                for case in suite['cases']:
                    report['results'].append(execute_case(case, db, journey.replay, revision,
                                                         affiliates, args.prefix_timeout))
            report['catalog_sha256_after'] = sha(db_path)
            report['catalog_bytes_unchanged'] = before == report['catalog_sha256_after']
            report['runtime_bytes_unchanged'] = runtime_hashes(root) == report['runtime_sha256']
            safety = sum(bool(r['safety_violations']) for r in report['results'])
            errors = sum(r['execution_status'] == 'execution_error' for r in report['results'])
            report['summary'] = {
                'cases_total': 30, 'cases_with_results': len(report['results']),
                'execution_error_cases': errors, 'safety_violation_cases': safety,
                'product_path_blocked_cases': sum(r['execution_status'] == 'product_path_blocked' for r in report['results']),
                'mechanical_constraint_pass_cases': sum(r['mechanical_constraints_met'] for r in report['results']),
                'mechanical_constraint_fail_cases': sum(not r['mechanical_constraints_met'] for r in report['results']),
                'reviewer_scored_cases': 0, 'strict_completed_count': None, 'useful_progress_count': None,
            }
            integrity = not report['catalog_bytes_unchanged'] or not report['runtime_bytes_unchanged']
            code = execution_exit(report['results'], not integrity)
            report['status'] = 'execution_failure' if code == 3 else 'safety_regression' if code == 2 else 'executed_awaiting_independent_scoring'
    except Exception as error:
        code = 3
        report.update(status='execution_failure', error_type=type(error).__name__, error=str(error))
    present = {r['case_id'] for r in report['results']}
    for case in suite['cases']:
        if case['id'] not in present:
            report['results'].append({'case_id': case['id'], 'question': case['question'],
                                      'execution_status': 'not_executed', 'reason': report['status'],
                                      'prefixes': [], 'reviewer_scores': None})
    report['reviewer_scoring_sheet'] = [blank_score(r['case_id'], r['execution_status']) for r in report['results']]
    report['finished_at_utc'] = now()
    report['exit_code'] = code
    save_new(args.output, report)
    save_new(summary_path, compact_report(report))
    print(json.dumps({'status': report['status'], 'exit_code': code,
                      'report': str(args.output), 'summary': report.get('summary'),
                      'not_executed': sum(r['execution_status'] == 'not_executed' for r in report['results'])}))
    return code


if __name__ == '__main__':
    sys.exit(main())
