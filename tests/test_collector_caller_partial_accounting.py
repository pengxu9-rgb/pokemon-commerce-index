"""Per-case planned denominators must survive interrupted caller journals."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import benchmark_collector_caller as bench
from scripts import benchmark_collector_mixed as mixed


def result(category='completed'):
    return {'category': category, 'elapsed_ms': None if category == 'unsettled' else 1,
        'fetch_attempts': []}


class PartialSummaryTests(unittest.TestCase):
    def test_partial_case_uses_planned_not_observed_denominator(self):
        case = {'planned_requests': 16, 'wall_ms': 0,
            'results': [result(), result('unsettled')]}
        before = copy.deepcopy(case)
        counts = bench.summarize(case)
        self.assertEqual(counts['all_requests'], 16)
        self.assertEqual(counts['completion_fraction'], .0625)
        self.assertEqual(counts['planned_requests'], 16)
        self.assertEqual(counts['started_requests'], 2)
        self.assertEqual(counts['not_started_requests'], 14)
        self.assertEqual(counts['completed'], 1)
        self.assertEqual(counts['unsettled'], 1)
        self.assertEqual(sum(counts[name] for name in bench.CATEGORIES), 2)
        self.assertEqual(counts['all_request_latency_ms']['maximum'], 1)
        self.assertIsNone(counts['completed_per_second'])
        self.assertEqual(case, before, 'Summary must not invent or rewrite observations')

    def test_zero_observations_keep_the_entire_positive_plan(self):
        counts = bench.summarize({'planned_requests': 16, 'wall_ms': 0, 'results': []})
        self.assertEqual(counts['all_requests'], 16)
        self.assertEqual(counts['completion_fraction'], 0)
        self.assertEqual(counts['started_requests'], 0)
        self.assertEqual(counts['not_started_requests'], 16)
        self.assertEqual(sum(counts[name] for name in bench.CATEGORIES), 0)
        for latency in ['all_request_latency_ms', 'completion_latency_ms']:
            self.assertTrue(all(value is None for value in counts[latency].values()))

    def test_empty_legacy_and_explicit_zero_plan_keep_undefined_fraction(self):
        case = {'wall_ms': 0, 'results': []}
        legacy = bench.summarize(case)
        explicit = bench.summarize({**case, 'planned_requests': 0})
        self.assertEqual(explicit, legacy)
        self.assertEqual(legacy['all_requests'], 0)
        self.assertIsNone(legacy['completion_fraction'])
        self.assertEqual(legacy['not_started_requests'], 0)

    def test_legacy_inputs_without_a_plan_keep_observed_denominator(self):
        counts = bench.summarize({'wall_ms': 1000,
            'results': [result(), result('explicit_rejection'), result('timeout')]})
        self.assertEqual(counts['all_requests'], 3)
        self.assertEqual(counts['completion_fraction'], .333333)
        self.assertEqual(counts['completed_per_second'], 1)
        self.assertEqual(counts['not_started_requests'], 0)

    def test_complete_case_metrics_are_identical_with_explicit_plan(self):
        rows = [result(category) for category in bench.CATEGORIES]
        case = {'wall_ms': 1000, 'results': rows}
        self.assertEqual(bench.summarize(case),
            bench.summarize({**case, 'planned_requests': len(rows)}))

    def test_invalid_planned_counts_are_rejected_without_mutation(self):
        for planned in [None, True, False, '16', 16.0, -1, float('nan'), float('inf'), [], {}]:
            with self.subTest(planned=planned), self.assertRaises(ValueError):
                bench.summarize({'planned_requests': planned, 'wall_ms': 0, 'results': []})
        for planned in [0, 1]:
            case = {'planned_requests': planned, 'wall_ms': 0,
                'results': [result(), result('unsettled')]}
            before = copy.deepcopy(case)
            with self.subTest(planned=planned), self.assertRaises(ValueError):
                bench.summarize(case)
            self.assertEqual(case, before)

    def test_unknown_observed_categories_remain_rejected(self):
        with self.assertRaises(ValueError):
            bench.summarize({'planned_requests': 16, 'wall_ms': 0,
                'results': [result('not_started')]})


@unittest.skipUnless(shutil.which('node'), 'Node is required for journal regressions')
class PartialJournalAccountingTests(unittest.TestCase):
    def run_plan(self, directory, plan, *, stop_after=None, hang=False, metadata=None, overflow_first=False):
        """Protocol-only fixture: no HTTP request, accepted response, or deployment."""
        runner = Path(directory) / 'runner.cjs'
        runner.write_text("""'use strict';
const plan = PLAN, stopAfter = STOP, metadata = METADATA;
const emit = event => process.stdout.write(JSON.stringify({schema:'pokemon.collector-journal.v1', ...event})+'\\n');
process.stdin.resume();
process.stdin.on('end', () => {
  emit({event:'run_started', planned_requests:plan.reduce((n,c)=>n+c[1],0), client_mode:'current_required', node_version:process.version});
  let request = 0;
  for (let c = 0; c < plan.length; c++) {
    emit({event:'case_started', case:{case_id:c+1,phase:plan[c][0],clients:4,...metadata}});
    for (let i = 0; i < plan[c][1] + (OVERFLOW && c === 0 ? 1 : 0); i++) {
      if (stopAfter === request) { if (HANG) setInterval(()=>{},1000); return; }
      emit({event:'request_started', request_id:++request, case_id:c+1});
      if (stopAfter === request) { if (HANG) setInterval(()=>{},1000); return; }
      emit({event:'request_completed', row:{request_id:request,category:'completed',elapsed_ms:1,input_unchanged:true}});
    }
    emit({event:'case_completed', case_id:c+1, wall_ms:1});
  }
  emit({event:'run_completed',node_version:process.version,client_mode:'current_required'});
});
""".replace('PLAN', json.dumps(plan)).replace('STOP', json.dumps(stop_after))
            .replace('METADATA', json.dumps(metadata or {})).replace('HANG', json.dumps(hang))
            .replace('OVERFLOW', json.dumps(overflow_first)))
        journal = Path(directory) / 'journal.jsonl'
        report = bench.run_node('http://127.0.0.1:1', {}, repo_root=bench.ROOT, local=True,
            execution_plan=plan, runner_path=runner, journal_path=journal, watchdog_seconds=.5)
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        return report, events

    def test_interrupted_case_uses_authoritative_plan_with_or_without_metadata(self):
        for metadata in [{}, {'scheduled_requests': 16},
                         {'planned_requests': 999, 'scheduled_requests': 999}]:
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as directory:
                report, events = self.run_plan(directory, [('sustained', 16)],
                    stop_after=2, hang=True, metadata=metadata)
            self.assertFalse(report['runner_complete'])
            self.assertEqual(report['runner_failure_code'], 'node_watchdog_timeout')
            self.assertEqual(report['request_accounting'], {'planned_requests': 16,
                'started_requests': 2, 'settled_requests': 1,
                'unsettled_requests': 1, 'not_started_requests': 14})
            case = report['cases'][0]
            self.assertTrue(case['partial'])
            self.assertEqual(case['planned_requests'], 16)
            self.assertEqual(len(case['results']), 2)
            self.assertEqual(bench.summarize(case)['completion_fraction'], .0625)
            self.assertEqual(bench.summarize(case)['not_started_requests'], 14)
            self.assertEqual(events[-1]['event'], 'receipt_marker')
            self.assertEqual(events[-1]['completion'], 'partial')
            for key, value in report['request_accounting'].items():
                self.assertEqual(events[-1][key], value)
            self.assertEqual(sum(event['event'] == 'request_started' for event in events), 2)
            self.assertEqual(sum(event['event'] == 'request_completed' for event in events), 1)

    def test_started_case_without_observations_keeps_plan_and_partial_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            report, events = self.run_plan(directory, [('simultaneous_burst', 16)], stop_after=0)
        self.assertFalse(report['runner_complete'])
        self.assertEqual(report['runner_failure_code'], 'node_incomplete_journal')
        case = report['cases'][0]
        self.assertEqual(case['results'], [])
        self.assertEqual(bench.summarize(case)['completion_fraction'], 0)
        self.assertEqual(bench.summarize(case)['not_started_requests'], 16)
        self.assertEqual(events[-1]['completion'], 'partial')
        self.assertEqual(events[-1]['started_requests'], 0)
        self.assertEqual(events[-1]['not_started_requests'], 16)

    def test_complete_97_request_plan_preserves_existing_summary_metrics(self):
        plan = [(case['phase'], len(case['indices'])) for case in mixed.plan()]
        self.assertEqual(sum(count for _, count in plan), 97)
        with tempfile.TemporaryDirectory() as directory:
            report, events = self.run_plan(directory, plan)
        self.assertTrue(report['runner_complete'], report)
        self.assertEqual(report['request_accounting'], {'planned_requests': 97,
            'started_requests': 97, 'settled_requests': 97,
            'unsettled_requests': 0, 'not_started_requests': 0})
        self.assertEqual(events[-1]['completion'], 'complete')
        for case, (_, planned) in zip(report['cases'], plan, strict=True):
            self.assertEqual(case['planned_requests'], planned)
            self.assertEqual(len(case['results']), planned)
            counts = bench.summarize(case)
            self.assertEqual(counts['all_requests'], planned)
            self.assertEqual(counts['completion_fraction'], 1)
            self.assertEqual(counts['not_started_requests'], 0)
            legacy_case = {key: value for key, value in case.items() if key != 'planned_requests'}
            self.assertEqual(counts, bench.summarize(legacy_case))

    def test_case_overflow_fails_before_mutation_and_keeps_structured_partial_summary(self):
        plan = [('serial_first_use', 1), ('sustained', 16)]
        with tempfile.TemporaryDirectory() as directory:
            report, events = self.run_plan(directory, plan, overflow_first=True)
        self.assertFalse(report['runner_complete'])
        self.assertEqual(report['runner_failure_code'], 'node_protocol_or_runner_failed')
        self.assertEqual(report['request_accounting'], {'planned_requests': 17,
            'started_requests': 1, 'settled_requests': 1,
            'unsettled_requests': 0, 'not_started_requests': 16})
        self.assertEqual(len(report['cases']), 1)
        summary = bench.summarize(report['cases'][0])
        self.assertEqual(summary['all_requests'], 1)
        self.assertEqual(summary['completed'], 1)
        self.assertEqual(summary['completion_fraction'], 1)
        self.assertEqual(events[-1]['completion'], 'partial')
        self.assertEqual(events[-1]['planned_requests'], 17)
        self.assertEqual(events[-1]['not_started_requests'], 16)
        self.assertEqual(sum(event['event'] == 'request_started' for event in events), 1)
        # Both ordinary report serialization and mixed-case summarization survive.
        json.dumps({**report, 'summaries': [bench.summarize(case) for case in report['cases']]})


if __name__ == '__main__':
    unittest.main()
