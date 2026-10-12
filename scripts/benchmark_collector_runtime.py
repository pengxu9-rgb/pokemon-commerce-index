"""Read-only bounded collector profiling against a supplied catalog snapshot.

No marketplace/network calls. Reports measured pools rather than claiming that
an available real-catalog axis contains exactly the synthetic 10,000-row ceiling.
Structural SQL budgets are gating; timing is reported and a generous SQLite
execution deadline stops runaway diagnostics without implying a Cloud Run SLA.
"""
from __future__ import annotations
import argparse,hashlib,json,resource,time
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_journey,collector_inventory,collector_recommendation


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def choose_axis(db):
    for kind in ['illustrator','dex_id']:
        rows=db.execute("SELECT value,count(DISTINCT card_id) n FROM discovery_card_facet WHERE facet_type=? GROUP BY value HAVING n BETWEEN 1 AND 10000 ORDER BY n DESC,value",(kind,)).fetchall()
        for row in rows:
            if kind=='illustrator':
                profile={'preferred_illustrators':[row['value']]};question='Cards by '+row['value']
            else:
                dex=int(row['value'])
                if not 1<=dex<=1025:continue
                name=db.execute("SELECT c.name FROM card c JOIN discovery_card_facet f ON f.card_id=c.card_id WHERE f.facet_type='dex_id' AND f.value=? AND c.language IN ('en','ja') AND NOT EXISTS(SELECT 1 FROM discovery_card_facet x WHERE x.card_id=c.card_id AND x.facet_type='dex_id' AND x.value<>f.value) ORDER BY c.language<>'en',length(c.name),c.name LIMIT 1",(row['value'],)).fetchone()
                if name is None:continue
                profile={'preferred_dex_ids':[dex]};question=name[0]+' cards'
            return dict(facet_type=kind,value=row['value'],catalog_axis_records=row['n'],profile=profile,inventory_question=question)
    raise ValueError('no usable bounded source-backed recommendation axis')


def benchmark(path, *, deadline_seconds=25, max_sql=50000, max_rss_mib=450):
    before=file_hash(path);cases=[]
    with closing(core.connect(path,readonly=True)) as db:
        catalog_records=db.execute('SELECT count(*) FROM card').fetchone()[0]
        start=time.perf_counter();db.set_progress_handler(lambda:time.perf_counter()-start>deadline_seconds,10000)
        revision=collector_journey.catalog_revision(db);axis=choose_axis(db);db.set_progress_handler(None,0)
    prefix=[dict(type='ask',question='What should I collect next?'),dict(type='preferences',preferences={'collecting':axis['profile']})]
    plans=[('recommendation_page_1',prefix),('recommendation_20_turn_pages',prefix+[dict(type='page',offset=i*5) for i in range(1,19)]),
           ('recommendation_20_distinct_preferences',prefix+[dict(type='preferences',preferences={'collecting':{'subjective_notes':[f'unapplied note {i}']}}) for i in range(18)]),
           ('inventory_bounded_pool',None)]
    for name,turns in plans:
        start=time.perf_counter();queries=0;row={'case':name}
        with closing(core.connect(path,readonly=True)) as db:
            def trace(_):
                nonlocal queries
                queries+=1
            db.set_trace_callback(trace)
            db.set_progress_handler(lambda:time.perf_counter()-start>deadline_seconds,10000)
            try:
                out=(collector_inventory.compare(db,dict(question=axis['inventory_question'],owned_items=[],limit=5)) if turns is None else
                     collector_journey.replay(db,dict(turns=turns,limit=5),revision=revision))
                coverage=out.get('discovery',out).get('coverage',{})
                if not coverage.get('scoped_catalog_records',coverage.get('matched_catalog_records',0)):
                    raise ValueError('benchmark query did not establish a nonempty bounded pool')
                if out.get('purchase_ready',False) or out.get('public_display_allowed',False) or out['prices'] or out['live_offers']:
                    raise ValueError('catalog authority boundary changed')
                row.update(status='ok',coverage=coverage,response_bytes=len(json.dumps(out,ensure_ascii=False).encode()))
            except Exception as exc:row.update(status='error',error_type=type(exc).__name__,error=str(exc))
        row.update(elapsed_seconds=round(time.perf_counter()-start,4),sql_statements=queries,
                   process_peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2))
        row['passed']=row['status']=='ok' and queries<=max_sql and row['process_peak_rss_mib']<=max_rss_mib
        cases.append(row)
    after=file_hash(path)
    return dict(schema='pokemon.collector-runtime-benchmark.v1',catalog_records=catalog_records,
        catalog_sha256=before,catalog_unchanged=before==after,catalog_revision=revision,axis=axis,cases=cases,
        limits=dict(pool_records=collector_inventory.MAX_SCOPE,transcript_turns=collector_journey.MAX_TURNS,
                    sqlite_deadline_seconds=deadline_seconds,sql_statements_per_case=max_sql,process_peak_rss_mib=max_rss_mib),
        deployment_scope='Local single-process measurements, not Cloud Run CPU, concurrency or end-to-end latency guarantees.',
        passed=before==after and all(c['passed'] for c in cases))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--deadline-seconds',type=float,default=25);parser.add_argument('--max-sql',type=int,default=50000);parser.add_argument('--max-rss-mib',type=float,default=450)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    if not 1<=args.deadline_seconds<=120 or not 1000<=args.max_sql<=1000000 or not 32<=args.max_rss_mib<=4096:parser.error('invalid diagnostic budget')
    try:report=benchmark(args.db,deadline_seconds=args.deadline_seconds,max_sql=args.max_sql,max_rss_mib=args.max_rss_mib)
    except Exception as exc:report=dict(schema='pokemon.collector-runtime-benchmark.v1',passed=False,error_type=type(exc).__name__,error=str(exc))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],output=str(args.output))))
    raise SystemExit(0 if report['passed'] else 1)

if __name__=='__main__':main()
