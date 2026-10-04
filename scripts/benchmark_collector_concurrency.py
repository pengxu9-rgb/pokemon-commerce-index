"""Bounded actual-HTTP collector load receipt, with overload kept in the denominator.

Uses the supplied read-only catalog; no marketplace or network service calls.
Run in a fresh process to make peak RSS meaningful. Timing is diagnostic, not a
Cloud Run SLA. A successful guard receipt does not mean every burst succeeded.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import resource
import threading
import time
from contextlib import closing

from pokemon_index import core
from pokemon_index.cli import create_server
from scripts.benchmark_collector_runtime import choose_axis, file_hash


def create_synthetic(path):
    """Explicitly artificial 70,000 records / 10,000-primary-character pool."""
    if path.exists():raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(core.connect(path)) as db:
        core.init_db(db)
        cards=[];facets=[]
        for i in range(70000):
            code='FX'+str(i//700).zfill(3);number=str(i%700+1).zfill(3)+'/700'
            cid=f'ja:{code}:{number}:normal';match=i<10000
            source='synthetic:runtime-safety'
            cards.append((cid,'ja',code,number,'normal','Pikachu' if match else 'Mew',None,source,source,0,1,'{}'))
            facets.extend([(cid,'dex_id','25' if match else '151',source,source),
                           (cid,'illustrator','Fixture Artist',source,source)])
        db.executemany('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',cards)
        db.executemany('INSERT INTO card_facet VALUES(?,?,?,?,?)',facets);db.commit()


def benchmark(path, *, fixture_label, client_timeout=10, workers=None, bursts=(1,2,4,16)):
    before=file_hash(path)
    with closing(core.connect(path,readonly=True)) as db:
        count=db.execute('SELECT count(*) FROM card').fetchone()[0]
        axis=choose_axis(db)
    prefix=[{'type':'ask','question':'Recommend '+axis['inventory_question']},
            {'type':'preferences','preferences':{'collecting':axis['profile']}}]
    plans=[('recommendation_20_turn_pages','/collector-journey',{'turns':prefix+[
                {'type':'page','offset':i*5} for i in range(1,19)],'limit':5}),
           ('recommendation_20_distinct_preferences','/collector-journey',{'turns':prefix+[
                {'type':'preferences','preferences':{'collecting':{'subjective_notes':[f'unapplied note {i}']}}}
                for i in range(18)],'limit':5}),
           ('inventory_bounded_pool','/collector-inventory',{'question':axis['inventory_question'],
                'owned_items':[],'limit':5})]
    cases=[]
    started=time.monotonic()
    options={} if workers is None else {'catalog_workers':workers}
    with create_server(str(path),'127.0.0.1',0,True,**options) as server:
        startup=time.monotonic()-started
        server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        def call(route,payload,barrier=None):
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=client_timeout)
            if barrier is not None:barrier.wait()
            start=time.monotonic()
            try:
                if route=='/health':client.request('GET',route)
                else:client.request('POST',route,json.dumps(payload),{'Content-Type':'application/json'})
                response=client.getresponse();body=response.read();out=json.loads(body)
                row=dict(status=response.status,error=out.get('error'),response_bytes=len(body))
                if response.status==200 and route!='/health':
                    coverage=out.get('discovery',out).get('coverage',{})
                    row.update(coverage=coverage,catalog_revision=out.get('catalog_revision'),
                        exercised_pool_records=coverage.get('scoped_catalog_records',coverage.get('matched_catalog_records',0)),
                        gates_closed=not any(out.get(key,False) for key in
                            ['purchase_ready','physical_copy_verified','public_display_allowed','ready_for_offer_tracking'])
                            and not out.get('prices') and not out.get('live_offers'))
            except Exception as exc:
                row=dict(status='transport_error',error_type=type(exc).__name__,error=str(exc))
            finally:client.close()
            row['elapsed_seconds']=round(time.monotonic()-start,4)
            return row
        try:
            for name,route,payload in plans:
                # Both first-use and repeated requests are reported; no warm-only
                # claim is substituted for the initial measured request.
                for phase in ['first_use','warm']:
                    cases.append(dict(case=name,phase=phase,clients=1,results=[call(route,payload)]))
            for clients in bursts:
                barrier=threading.Barrier(clients+1)
                name,route,payload=plans[0]
                start=time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as executor:
                    futures=[executor.submit(call,route,payload,barrier) for _ in range(clients)]
                    barrier.wait()
                    health=call('/health',None)
                    results=[f.result() for f in futures]
                cases.append(dict(case=name,phase='simultaneous_burst',clients=clients,results=results,
                    health=health,wall_seconds=round(time.monotonic()-start,4)))
            name,route,payload=plans[0]
            cases.append(dict(case=name,phase='after_bursts_recovery',clients=1,results=[call(route,payload)]))
        finally:
            server.shutdown();server_thread.join(timeout=5)
    for case in cases:
        rows=case['results']
        case['counts']={name:sum(row['status']==value for row in rows) for name,value in
            [('accepted',200),('deadline',504),('transport_errors','transport_error')]}
        case['counts']['overloaded']=sum(row['status']==503 and row.get('error')=='catalog_busy' for row in rows)
        case['counts']['snapshot_changed']=sum(row.get('error')=='catalog_snapshot_changed' for row in rows)
        case['counts']['other']=len(rows)-sum(case['counts'].values())
        case['accepted_throughput_per_second']=(round(case['counts']['accepted']/case['wall_seconds'],4)
            if case.get('wall_seconds') else None)
    after=file_hash(path)
    all_rows=[row for case in cases for row in case['results']]
    health_rows=[case['health'] for case in cases if 'health' in case]
    peak_rss=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2)
    passed=(before==after and all(row['status'] in (200,503) and
                (row.get('gates_closed',False) and 0<row.get('exercised_pool_records',0)<=10000
                 if row['status']==200 else row.get('error')=='catalog_busy') for row in all_rows)
            and all(case['results'][0]['status']==200 for case in cases if case['phase']!='simultaneous_burst')
            and all(row['status']==200 and row['elapsed_seconds']<1 for row in health_rows)
            and peak_rss<=450
            and all(case['counts']['accepted']>=1 for case in cases if case['phase']=='simultaneous_burst'))
    return dict(schema='pokemon.collector-http-concurrency.v1',fixture_label=fixture_label,
        catalog_records=count,catalog_sha256=before,catalog_unchanged=before==after,axis=axis,
        startup_seconds=round(startup,4),configured_workers=workers if workers is not None else 'server_default',
        client_timeout_seconds=client_timeout,cpu_affinity_count=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
        process_peak_rss_mib=peak_rss,cases=cases,
        health_counts=dict(accepted=sum(row['status']==200 for row in health_rows),
            failed=sum(row['status']!=200 for row in health_rows),
            max_elapsed_seconds=max(row['elapsed_seconds'] for row in health_rows)),
        limits=dict(process_peak_rss_mib=450,health_seconds=1),
        deployment_scope='Local actual HTTP, no Node token acquisition or deployed Cloud Run measurement. Overload is unsuccessful work and remains in every denominator.',
        passed=passed)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture-label',required=True,choices=['synthetic','real_pinned_catalog'])
    parser.add_argument('--create-synthetic',action='store_true')
    parser.add_argument('--workers',type=int,choices=range(1,17))
    parser.add_argument('--client-timeout',type=float,default=10)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    if not 1<=args.client_timeout<=15:parser.error('client timeout must be 1–15 seconds')
    if args.create_synthetic:
        if args.fixture_label!='synthetic':parser.error('synthetic creation requires synthetic label')
        create_synthetic(args.db)
    try:
        report=benchmark(args.db,fixture_label=args.fixture_label,workers=args.workers,client_timeout=args.client_timeout)
    except Exception as exc:
        report=dict(schema='pokemon.collector-http-concurrency.v1',passed=False,error_type=type(exc).__name__,error=str(exc))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],output=str(args.output))))
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
