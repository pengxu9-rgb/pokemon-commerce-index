"""Frozen source-led retrieval diagnostics; never a marketplace accuracy score."""
import argparse, hashlib, json
from contextlib import closing
from pathlib import Path
from pokemon_index import core, collector_discovery, collector_journey, discovery_graph, source_corrections


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(db_path, root, output):
    if output.exists():
        raise FileExistsError(output)
    cohort = root / 'catalog/source-corrections-next-v1'
    questions = cohort / 'questions-frozen-v2.jsonl'
    lock = json.loads((cohort / 'questions-lock-v2.json').read_text())
    if sha(questions) != lock['questions_sha256']:
        raise ValueError('frozen questions changed')
    before = sha(db_path)
    runtime_files = [Path(m.__file__) for m in (core, collector_discovery, collector_journey, discovery_graph, source_corrections)]
    runtime_files.append(Path(core.__file__).with_name('metadata_views.sql'))
    runtime_sha256 = {p.name:sha(p) for p in runtime_files}
    cases = []
    with closing(core.connect(db_path, readonly=True)) as db:
        revision = collector_journey.catalog_revision(db)
        for row in map(json.loads, questions.read_text().splitlines()):
            result = collector_discovery.execute(db, row['question'], limit=50)
            cards = result['cards']
            passed = not result['prices'] and not result['live_offers'] and not result['public_display_allowed']
            details = []
            kind = row['kind']
            if kind in {'artist', 'coordinate', 'references', 'family'}:
                passed = passed and bool(cards) and all(c['language'] == 'ja' and
                    c['set_code'] == row['expected_set'] and c['collector_number'] == row['expected_number'] for c in cards)
                for c in cards:
                    detail = core.catalog_card_internal(db, c['card_id'])
                    details.append(detail)
                    if kind == 'artist':
                        passed = passed and any(f['facet_type'] == 'illustrator' and
                            f['value'] == row['expected_artist'] for f in detail['discovery_facets'])
                    if kind in {'references', 'family'}:
                        passed = passed and sorted(r['native_id'] for r in detail['reference_records']) == row['expected_native_ids']
                    if kind == 'family':
                        passed = passed and not detail['card']['match_eligible'] and not detail['card']['display_allowed']
            elif kind == 'empty':
                passed = passed and not cards and bool(result.get('next_question') or result.get('unfulfilled_constraints'))
            elif kind == 'ambiguous':
                passed = passed and (len(cards) > 1 or not cards) and bool(result.get('next_question'))
            elif kind == 'target':
                links = result.get('verified_links', [])
                passed = passed and any(r['other_card_id'] == row['expected_card_id'] and
                    not r['price_comparable'] for r in links)
            elif kind == 'abstain':
                passed = passed and bool(result.get('unfulfilled_constraints') or result.get('next_question'))
            cases.append(dict(id=row['id'], question=row['question'], limit=50, passed=bool(passed),
                expected=row, result=result, catalog_details=details))
        graphs = []
        for edge in map(json.loads, (root / 'catalog/relationship-expansion-v2/verified-artwork-events.jsonl').read_text().splitlines()):
            actual = discovery_graph.card_neighborhood(db, edge['left_card_id'])
            matches = [r for r in actual['relationships'] if r['assertion_id'] == edge['assertion_id']]
            passed = len(matches) == 1 and not matches[0]['price_comparable'] and not matches[0]['endpoint_identity_review_required']
            graphs.append(dict(card_id=edge['left_card_id'], passed=passed, result=actual))
    if sha(db_path) != before:
        raise ValueError('read-only diagnostic changed catalog')
    if runtime_sha256 != {p.name:sha(p) for p in runtime_files}:
        raise ValueError('runtime changed during diagnostic')
    report = dict(schema='pokemon.source-corrections-development-rehearsal.v1', cases=len(cases),
        passed=sum(r['passed'] for r in cases), failed=sum(not r['passed'] for r in cases),
        graph_checks=graphs, graph_failures=sum(not r['passed'] for r in graphs), results=cases,
        catalog_revision=revision, catalog_sha256=before, questions_sha256=sha(questions),
        runtime_sha256=runtime_sha256,
        independent_held_out_accuracy_measurement=False,
        interpretation='Source-led authored development queries and precise evidence guards. Shared-model image review and runtime fixes do not establish population accuracy or real-listing precision.')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return {k:report[k] for k in ('cases', 'passed', 'failed', 'graph_failures')}


def combined(db_path, root, output):
    """Combine existing source/copy regressions with the new frozen queries."""
    from scripts.rehearse_next_priorities import run as legacy_run
    if output.exists():raise FileExistsError(output)
    legacy = output.with_name(output.stem + '-legacy.json')
    fresh = output.with_name(output.stem + '-fresh.json')
    legacy_run(db_path, root, legacy)
    run(db_path, root, fresh)
    report = json.loads(legacy.read_text())
    current = json.loads(fresh.read_text())
    report['schema'] = 'pokemon.source-corrections-integrated-development-rehearsal.v1'
    report['failed'] += current['failed'] + current['graph_failures']
    report['graph_checks'].extend(r['result'] for r in current['graph_checks'])
    report['priority_source_checks'].extend(dict(id=r['id'], question=r['question'],
        limit=r['limit'], result=r['result']) for r in current['results'])
    report['correction_detail_checks'] = [d for r in current['results'] for d in r['catalog_details']]
    report['correction_questions'] = current['cases']
    with closing(core.connect(db_path, readonly=True)) as db:
        question = 'Japanese SV-P 154/SV-P'
        cid = db.execute("SELECT card_id FROM card WHERE language='ja' AND set_code='SV-P' AND collector_number='154/SV-P'").fetchone()[0]
        payload = dict(turns=[dict(type='ask', question=question)])
        result = collector_journey.replay(db, payload, revision=current['catalog_revision'])
        assert not result['selection_allowed'] and 'source_family_copy_evidence' in result['selection_blockers']
        invalid = dict(turns=[dict(type='ask', question='Japanese SV-P cards'), dict(type='select', card_id=cid)])
        try:collector_journey.replay(db, invalid, revision=current['catalog_revision'])
        except ValueError:pass
        else:raise AssertionError('broad source-only family selection allowed')
        report['source_family_journey_check'] = dict(request=payload, result=result, invalid_select_request=invalid)
    report['component_report_sha256'].update({p.name:sha(p) for p in (legacy, fresh)})
    report['runtime_sha256'] = current['runtime_sha256']
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return dict(failed=report['failed'], family_questions=report['cases'],
        fresh_questions=current['cases'], graph_checks=len(report['graph_checks']),
        exact_card_detail_checks=len(report['correction_detail_checks']))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('db', 'output'):p.add_argument('--' + k, type=Path, required=True)
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--combined', action='store_true')
    a = p.parse_args()
    print(json.dumps((combined if a.combined else run)(a.db, a.root, a.output)))
