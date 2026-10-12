# Populated effective-view runtime reproduction

This is a **synthetic engineering stress fixture**, not the pinned catalog or an accuracy evaluation. It uses the unchanged production SQL views, 70,000 synthetic filler/anchor rows, 27 explicitly synthetic-qualified target shapes, 2,497 current synthetic official overlays, one current synthetic source correction, and a 10,000-record artist pool. Almost all filler names are distinct, deliberately stressing name matching. Physical, public-display and commerce authority remain disabled.

Run from the repository root with its test dependencies installed. Keep generated databases and receipts outside Git. The commands below create new files under `/tmp`; choose a new directory for each run. Build in a separate process so fixture construction does not inflate the HTTP process's peak-RSS measurement.

## 1. Build the fixture

```sh
mkdir /tmp/pokemon-effective-view-repro
PYTHONPATH=.:tests python - <<'PY'
import json
from pathlib import Path
from tests.test_affiliation_runtime_scaling import build_fixture
root=Path('/tmp/pokemon-effective-view-repro')
db=root/'catalog.sqlite3'
assert not db.exists()
fixture=build_fixture(db,total=70000,metadata_count=2497)
(root/'fixture.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
print({key:fixture[key] for key in ('catalog_records','metadata_count')})
PY
```

The support adapter overrides only the 27 synthetic qualifications. Other cards use the normal `support_for_card` implementation. The fixture is not a replacement for real-catalog CI.

## 2. Compare the published unbatched query oracle with the current helper

The checked-in oracle reproduces the helper published at `7382318`; only its imports and binding-file location are adjusted for tests. The unmodified published helper's SHA-256 is `738be34a1cfc8b2d222a040953ade70f0b6e98c54dcb1044112a9cb6749f5980` (Git blob `0b110665e92b30dd2aee38b213ca21563bdba645`).

```sh
PYTHONPATH=.:tests timeout 90s python - <<'PY'
import hashlib,importlib.util,json,time
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_character_affiliation as current
from tests.test_affiliation_runtime_scaling import synthetic_support
root=Path('/tmp/pokemon-effective-view-repro');db_path=root/'catalog.sqlite3'
fixture=json.loads((root/'fixture.json').read_text())
spec=importlib.util.spec_from_file_location('unbatched_oracle',
    'tests/fixtures/collector_character_affiliation_7382318.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
before=hashlib.sha256(db_path.read_bytes()).hexdigest();rows=[];outputs=[]
for label,module in [('published_unbatched_oracle',old),('current_batch',current)]:
    with closing(core.connect(db_path,readonly=True)) as db,synthetic_support(fixture,module=module):
        queries=[];ticks=[0];start=time.monotonic();cpu=time.process_time()
        def progress():
            ticks[0]+=1
            return time.monotonic()-start>30
        db.set_trace_callback(queries.append);db.set_progress_handler(progress,1000)
        out=module.affiliations(db);outputs.append(out)
        rows.append(dict(case=label,seconds=time.monotonic()-start,cpu_seconds=time.process_time()-cpu,
            sql_statements=len(queries),effective_view_queries=sum('discovery_card_facet' in q for q in queries),
            sqlite_progress_callbacks=ticks[0],affiliations=len(out)))
report=dict(cases=rows,complete_outputs_equal=outputs[0]==outputs[1],catalog_sha256=before,
    catalog_unchanged=before==hashlib.sha256(db_path.read_bytes()).hexdigest())
output=root/'helper-profile.json';assert not output.exists()
output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
assert report['complete_outputs_equal'] and report['catalog_unchanged']
PY
```

Complete equality includes deterministic representative ordering, anchor counts and full proof hashes. The regression test also requires 51 effective-view statements to become two and at least a fivefold reduction in SQLite VM progress callbacks. It does not impose a machine-dependent wall-clock assertion.

## 3. Run the actual HTTP workload

```sh
PYTHONPATH=.:tests timeout 180s python - <<'PY'
import json
from pathlib import Path
from tests.test_affiliation_runtime_scaling import synthetic_support
from scripts.benchmark_collector_concurrency import benchmark
root=Path('/tmp/pokemon-effective-view-repro')
fixture=json.loads((root/'fixture.json').read_text())
with synthetic_support(fixture):
    report=benchmark(root/'catalog.sqlite3',fixture_label='synthetic')
output=root/'http-report.json';assert not output.exists()
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'output':str(output)}))
raise SystemExit(0 if report['passed'] else 1)
PY
```

This keeps the eight-second cooperative computation budget, ten-second HTTP client timeout, one active worker, bounded FIFO queue and separate health path. It reports first-use/warm requests, 20-page and 20-note transcripts, inventory, bursts of 1/2/4/16 clients and recovery. Accepted, overloaded, deadline and transport outcomes remain separate; overload is unsuccessful work. This is Python HTTP, without Node token acquisition or a Cloud Run measurement.

## 4. Run the focused regressions

```sh
PYTHONPATH=.:tests python -m unittest tests.test_affiliation_runtime_scaling tests.test_character_affiliation_batching tests.test_runtime_safety_adversarial tests.test_collector_recommendation tests.test_collector_journey -q
```

These include complete proof equivalence, current raw/official anchor consensus, no derivation for clarification-only preferences, later positive/liked-example validation, note-cache/uncached output equality, fresh note disclosure, target/comparison invalidation, and 4,013 original-versus-optimized literal/boundary matching cases.

## Retained diagnostic history

- `affiliation-scaling-profile-v1.json` is **invalid as a before/after comparison**: the attempted baseline copy raced a concurrent edit and was already batched. Its invalidity is explicitly recorded; do not use it as speedup evidence.
- `affiliation-scaling-profile-v2.json` and `v3.json` use verified published pre-fix bytes and retain exact output equality and measured SQL/VM work.
- `affiliation-effective-http-report.json` preserves the first dense failure. Its minimal non-target support mock was subsequently replaced with the real support lookup; it is not an isolated timing comparison with later runs.
- `affiliation-effective-http-after-notes.json` preserves the subsequent unique-name matching failure. It and `affiliation-effective-http-after-literal.json` use the same final support adapter and unchanged database. The latter passes all diagnostic checks; it does not validate deployed capacity.
- Unsupported subjective notes are excluded only from the request-local ranking key. Every response rebuilds their disclosure, and complete preferences still invalidate journey targets/comparison authority. Other ranking inputs remain bound.

The final pinned-catalog CI rerun, with unchanged questions, safety gates and budgets, is required before claiming the real-catalog regression is resolved.
