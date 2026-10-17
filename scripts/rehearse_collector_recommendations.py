"""Frozen synthetic recommendation conversations through real Python HTTP and Node."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,tempfile,threading
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_journey
from pokemon_index.cli import create_server

SUITE=Path('sandbox/collector_journeys/recommendation-v1/reviewed-suite.json')


def _synthetic_node_env():
    """Bypass inherited proxies only for this runner's fixed loopback server."""
    env=os.environ.copy()
    # Node may prefer lowercase no_proxy, so preserve and extend either spelling.
    for key in ('NO_PROXY','no_proxy'):
        if key=='NO_PROXY' or key in env:
            value=env.get(key,'')
            if '127.0.0.1' not in {entry.strip() for entry in value.split(',')}:
                env[key]=value+(',' if value else '')+'127.0.0.1'
    return env


def create_fixture(path,suite):
    if path.exists():raise FileExistsError(path)
    with closing(core.connect(path)) as db:
        core.init_db(db)
        for row in suite['cards']:
            record={k:v for k,v in row.items() if k not in {'dex_id','illustrator'}}
            core.import_cards(db,[record]);cid=core.card_id(row['language'],row['set_code'],row['collector_number'],row['variant'])
            for kind,value in [('dex_id',str(row['dex_id'])),('illustrator',row['illustrator'])]:
                db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,kind,value,row['provenance'],row['rights_reference']))
        for language in ['ja','en']:
            db.execute('INSERT INTO catalog_set_localized(language,set_code,name,official_card_count,provenance,rights_reference,display_allowed) VALUES (?,?,?,?,?,?,?)',(language,'FIX','Synthetic Collector Set',100,'synthetic:collector-recommendation-v1','synthetic:no-display',0))
        db.commit()


def check_result(db,result,expect):
    errors=[];cards=result['candidate_cards'];ids=[c['card_id'] for c in cards]
    if 'task' in expect and result['discovery']['task']!=expect['task']:errors.append('task')
    if 'status' in expect and result['status']!=expect['status']:errors.append('status')
    if 'count' in expect and len(cards)!=expect['count']:errors.append('count')
    if 'ids' in expect and ids!=expect['ids']:errors.append('ids')
    if 'first' in expect and (not ids or ids[0]!=expect['first']):errors.append('first')
    if set(expect.get('absent',[]))&set(ids):errors.append('absent')
    if 'before' in expect:
        a,b=expect['before']
        if a not in ids or b not in ids or ids.index(a)>=ids.index(b):errors.append('rank')
    if 'only_language' in expect and (not cards or {c['language'] for c in cards}!={expect['only_language']}):errors.append('language')
    if 'only_dex' in expect and (not cards or any(not db.execute("SELECT 1 FROM discovery_card_facet WHERE card_id=? AND facet_type='dex_id' AND value=?",(cid,str(expect['only_dex']))).fetchone() for cid in ids)):errors.append('dex')
    if 'selection_allowed' in expect and result['selection_allowed']!=expect['selection_allowed']:errors.append('selection')
    if 'target' in expect and (result['target_intent']['card_id'] if result['target_intent'] else None)!=expect['target']:errors.append('target')
    if 'blocker' in expect and expect['blocker'] not in result['selection_blockers']:errors.append('blocker')
    if 'budget_minor' in expect and result['preferences'].get('budget_minor')!=expect['budget_minor']:errors.append('budget')
    if 'unapplied_contains' in expect and not any(expect['unapplied_contains'] in v['value'] for v in result['recommendation']['unapplied_preferences']):errors.append('unapplied')
    if result['prices'] or result['live_offers'] or result['purchase_ready'] or result['public_display_allowed']:errors.append('commerce')
    return errors


def run(suite_path,output):
    if output.exists():raise FileExistsError(output)
    suite=json.loads(suite_path.read_text())
    if suite['schema']!='pokemon.collector-recommendation-diagnostic.v1':raise ValueError('unknown suite')
    with tempfile.TemporaryDirectory() as temp:
        db_path=Path(temp)/'catalog.sqlite3';create_fixture(db_path,suite)
        before=hashlib.sha256(db_path.read_bytes()).hexdigest()
        with create_server(str(db_path),'127.0.0.1',0,True) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                config=dict(baseUrl='http://127.0.0.1:'+str(server.server_address[1]),allowLoopback=True,journeys=[dict(j,limit=suite['limit']) for j in suite['journeys']])
                returned=json.loads(subprocess.check_output(['node','integrations/pivota/replay.cjs'],input=json.dumps(config),text=True,timeout=120,env=_synthetic_node_env()))
            finally:server.shutdown();thread.join(timeout=5)
        returned={r['id']:r for r in returned};results=[]
        with closing(core.connect(db_path,readonly=True)) as db:
            revision=collector_journey.catalog_revision(db)
            for journey in suite['journeys']:
                turns=[]
                for i,step in enumerate(journey['steps'],1):
                    turns.append(step['action']);key=journey['id']+':'+str(i);row=returned.get(key,{})
                    expected=step['expect'];errors=[];call=row.get('call');actual=call.get('result') if call else None
                    if 'error' in expected:
                        if row.get('error_code')!=expected['error']:errors.append('caller did not reject')
                        try:collector_journey.replay(db,dict(turns=turns,limit=suite['limit']),revision=revision)
                        except ValueError:pass
                        else:errors.append('direct replay did not reject')
                    elif not actual:errors.append(row.get('error_code') or 'missing response')
                    else:
                        local=collector_journey.replay(db,dict(turns=turns,limit=suite['limit']),revision=revision)
                        if actual!=local:errors.append('caller/direct response mismatch')
                        errors.extend(check_result(db,actual,expected))
                    results.append(dict(id=key,family=journey['family'],passed=not errors,errors=errors,action=step['action'],expect=expected,call=call,error_code=row.get('error_code')))
        immutable=before==hashlib.sha256(db_path.read_bytes()).hexdigest()
        report=dict(schema='pokemon.collector-recommendation-diagnostic-report.v1',scope=suite['scope'],
            transport='real_local_python_http_to_node_caller',journeys=len(suite['journeys']),prefix_requests=len(results),
            passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),
            catalog_bytes_unchanged=immutable,catalog_revision=revision,suite_sha256=hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            runtime_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('pokemon_index/collector_journey.py'),Path('pokemon_index/collector_recommendation.py'),Path('pokemon_index/collector_inventory.py'),Path('integrations/pivota/collectorClient.cjs')]},
            source_selection_independent=False,real_user_quality_established=False,live_prices_available=False,results=results)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ['journeys','prefix_requests','passed','failed','catalog_bytes_unchanged']}))
        if report['failed'] or not immutable:
            print(json.dumps([dict(id=r['id'],errors=r['errors']) for r in results if not r['passed']]))
            raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',type=Path,default=SUITE);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.suite,a.output)
