"""Verify the private staging collector against a source-qualified local replay."""
from __future__ import annotations
import argparse
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import closing
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from scripts.public_question_sandbox import sha_file
from pokemon_index import core,collector_inventory


def graph_semantic_response(response):
    """Exclude rebuild application time only for imported, proposed AI edges.

    Identity, evidence, review status and source retrieval times stay bound.
    The original responses retain timestamps in the deployment diagnostic.
    """
    value=json.loads(json.dumps(response))
    for item in value.get('ai_artwork_candidates',[]):
        if item.get('asserted_by')=='ai-artwork-review-v1' and item.get('review_status')=='proposed':
            core.parse_time(item['asserted_at'])
            item.pop('asserted_at')
    return value


def verify(local_report: Path, output: Path, inventory_db: Path | None = None, evidence_rehearsal: Path | None = None, expansion_rehearsal: Path | None = None, manifest: Path = Path('catalog-build-manifest-evidence-v1.json'), journey_rehearsal: Path | None = None, verified_date='2026-10-01'):
    if output.exists():raise FileExistsError('deployment evidence must be new')
    project='pivota-staging';region='us-west1';name='pokemon-commerce-index'
    def gcloud(*args):
        return json.loads(subprocess.check_output(['gcloud',*args,'--project='+project,'--format=json'],text=True))
    service=gcloud('run','services','describe',name,'--region='+region)
    iam=gcloud('run','services','get-iam-policy',name,'--region='+region)
    revision=service['status']['latestReadyRevisionName']
    detail=gcloud('run','revisions','describe',revision,'--region='+region)
    if any(m in {'allUsers','allAuthenticatedUsers'} for b in iam.get('bindings',[]) for m in b['members']):
        raise ValueError('public invoker binding')
    assert sum(t['percent'] for t in service['status']['traffic'] if t.get('revisionName')==revision)==100
    token=subprocess.check_output(['gcloud','auth','print-identity-token'],text=True).strip()
    url=service['status']['url']
    transient_errors=[]; error_lock=threading.Lock(); request_counts={'authenticated':0,'unauthenticated':0}
    def query(path,params=None,auth=True,body=None,raw_body=None):
        headers={'Authorization':'Bearer '+token} if auth else {}
        data=json.dumps(body).encode() if body is not None else raw_body
        if data is not None:headers['Content-Type']='application/json'
        request=Request(url+path+('?' + urlencode(params) if params else ''),
                        headers=headers,data=data)
        with error_lock:request_counts['authenticated' if auth else 'unauthenticated']+=1
        for attempt in range(1,4):
            try:
                with urlopen(request,timeout=30) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,None
            except (URLError,TimeoutError) as error:
                with error_lock:transient_errors.append(dict(path=path,attempt=attempt,error_type=type(error).__name__))
                if attempt==3:raise
    assert query('/health')[0]==200
    expected_catalog=json.loads(manifest.read_text())['expected']
    code,status=query('/catalog-status');assert code==200 and all(status[key]==expected_catalog[key] for key in ('printings','sets','match_eligible','display_approved','reference_records'))
    code,support=query('/supported-status');assert code==200 and support['current_supported_targets']==100 and support['automatic_offer_join_ready']==0
    for key in ('official_metadata_events','current_official_metadata_cards','official_metadata_stale_cards','official_known_rarity_cards','official_numbered_parts_cards','coordinate_family_events','current_coordinate_families','held_coordinate_families','stale_coordinate_families'):
        if key in expected_catalog:
            assert support[key]==expected_catalog[key],key
    assert query('/health',auth=False)[0]==403
    assert query('/collector-discovery',{'q':'Eevee','limit':101})[0]==400
    for q in ['Japanese card 151/165','English card 151/165']:
        code,guard=query('/collector-discovery',{'q':q})
        assert code==200 and guard['task']=='need_release_scope' and not guard['cards']
    code,ordinary=query('/collector-discovery',{'q':'Help me figure out only Japanese Pikachu cards','limit':1})
    assert code==200 and ordinary['task']=='character_cards' and ordinary['cards']
    assert ordinary['languages']==['ja']
    local=json.loads(local_report.read_text())
    assert local['cases'] and local['failed']==0
    def case(expected):
        offset=0;cards=[];requests=0;first=None
        while True:
            code,page=query('/collector-discovery',{'q':expected['question'],'limit':100,'offset':offset})
            assert code==200
            requests+=1
            if first is None:first=page
            cards.extend(c['card_id'] for c in page['cards'])
            assert not page['prices'] and not page['live_offers'] and not page['public_display_allowed']
            assert not page['complete_answer_established']
            if not page.get('coverage',{}).get('has_more'):break
            offset+=100
            if offset>100000:raise ValueError('unbounded cloud pagination')
        assert cards==expected['returned_card_ids'],expected['id']
        for key in ['task','status','unfulfilled_constraints','next_question']:
            assert first.get(key)==expected['first_page'].get(key),(expected['id'],key)
        return dict(id=expected['id'],task=first['task'],matched_records=len(cards),requests=requests,passed=True)
    with ThreadPoolExecutor(max_workers=3) as pool:checks=list(pool.map(case,local['results']))
    metadata_journey_checks=[];metadata_graph_checks=[]
    for item in local.get('numbered_part_journey_checks',[]):
        payload=dict(turns=[dict(type='ask',question=item['question'])])
        code,actual=query('/collector-journey',body=payload)
        assert code==200 and actual==item['result'],item['question']
        assert not actual['selection_allowed'] and not actual['target_intent']
        assert 'numbered_part_copy_evidence' in actual['selection_blockers']
        metadata_journey_checks.append(dict(question=item['question'],passed=True))
    for expected in local.get('graph_checks',[]):
        code,actual=query('/catalog-neighborhood',{'card_id':expected['card_id']})
        assert code==200 and graph_semantic_response(actual)==graph_semantic_response(expected),expected['card_id']
        metadata_graph_checks.append(dict(card_id=expected['card_id'],passed=True,
            ai_import_application_times=dict(local=[x['asserted_at'] for x in expected.get('ai_artwork_candidates',[])],
                                             cloud=[x['asserted_at'] for x in actual.get('ai_artwork_candidates',[])])))
    family_journey_checks=[]
    for item in local.get('coordinate_family_journey_checks',[]):
        code,actual=query('/collector-journey',body=dict(turns=[dict(type='ask',question=item['question'])]))
        assert code==200 and actual==item['result'],item['question']
        assert not actual['selection_allowed'] and not actual['target_intent'] and 'coordinate_family_copy_evidence' in actual['selection_blockers']
        family_journey_checks.append(dict(question=item['question'],passed=True))
    family_broad_select_guard=False
    if family_journey_checks:
        assert query('/collector-journey',body=dict(turns=[dict(type='ask',question='Japanese SV8A cards'),
            dict(type='select',card_id='ja:SV8A:001/187:normal')]))[0]==400
        family_broad_select_guard=True
    inventory_checks=[]
    if inventory_db is not None:
        before=sha_file(inventory_db)
        cid='ja:SV4A:347/190:holo'; question='Japanese SV4A 347/190'
        owned=dict(item_id='synthetic-owned',card_id=cid)
        payloads=[('empty_scoped_inventory',dict(question=question,owned_items=[])),
            ('asserted_exact_record',dict(question=question,owned_items=[owned])),
            ('duplicate_quantity',dict(question=question,owned_items=[owned,dict(item_id='synthetic-duplicate',card_id=cid,quantity=2)])),
            ('unspecified_version',dict(question=question,owned_items=[dict(item_id='synthetic-uncertain',language='ja',set_code='SV4A',collector_number='347/190')])),
            ('unknown_record',dict(question=question,owned_items=[dict(item_id='synthetic-unknown',card_id='unknown:fixture')])),
            ('market_evidence_blocker',dict(question='Cheapest Pikachu card',owned_items=[])),
            ('missing_page_1',dict(question='Japanese Pikachu cards',owned_items=[],limit=3)),
            ('missing_page_2',dict(question='Japanese Pikachu cards',owned_items=[],limit=3,offset=3))]
        with closing(core.connect(inventory_db,readonly=True)) as db:
            assert db.execute('SELECT card_id FROM card WHERE card_id=?',(cid,)).fetchone()
            for case_id,payload in payloads:
                expected=collector_inventory.compare(db,payload)
                code,actual=query('/collector-inventory',body=payload)
                assert code==200,(case_id,code)
                for key in ['status','inventory_entries','owned_in_scope','possible_owned','duplicates',
                            'outside_scope','unresolved_items','coverage','unfulfilled_constraints','next_question',
                            'comparison_complete_for_submitted_catalog_scope','complete_missing_list_established']:
                    assert actual.get(key)==expected.get(key),(case_id,key)
                assert [c['card_id'] for c in actual['missing_catalog_records']]==[c['card_id'] for c in expected['missing_catalog_records']],case_id
                for key in ['inventory_persisted','ownership_assertions_verified','physical_copy_verification','public_display_allowed','prices','live_offers']:
                    assert not actual[key],(case_id,key)
                inventory_checks.append(dict(id=case_id,passed=True,synthetic=True,
                    payload=payload,status=actual['status'],coverage=actual.get('coverage')))
        assert query('/collector-inventory',body=dict(question=question,owned_items=[dict(owned,quantity=True)]))[0]==400
        assert query('/collector-inventory',raw_body=b'not json')[0]==400
        assert query('/collector-inventory',body=dict(question=question,owned_items=[]),auth=False)[0]==403
        assert sha_file(inventory_db)==before
    evidence_checks=[]
    if evidence_rehearsal is not None:
        rehearsal=json.loads(evidence_rehearsal.read_text())
        code,current=query('/collector-evidence-status')
        assert code==200 and current==rehearsal['status']
        for item in rehearsal['source_queries']:
            code,actual=query('/collector-discovery',{'q':item['question']})
            assert code==200 and actual==item['actual'],item['question']
            evidence_checks.append(dict(question=item['question'],passed=True))
        code,mew=query('/collector-discovery',{'q':'Japanese Mew cameos in card art'})
        assert code==200 and mew==rehearsal['mew_proposed_only'] and not mew['cards']
        code,context=query('/catalog-evidence',{'card_id':'ja:SV2A:173/165:holo'})
        assert code==200 and context==rehearsal['source_queries'][0]['actual']['cards'][0]['collector_evidence']
        for k in ['synthetic_owned_inventory','ai_only_inventory_blocker']:
            expected=rehearsal[k]
            payload=dict(question=expected['question'],owned_items=[dict(item_id='synthetic',card_id='ja:SV2A:173/165:holo')] if k=='synthetic_owned_inventory' else [])
            code,actual=query('/collector-inventory',body=payload)
            assert code==200 and actual==expected,k
        assert query('/catalog-evidence',{'card_id':'unknown'})[0]==400
        for question in ['Japanese 151 Mew cameos','Japanese Mew cameos SV-P 120/SV-P',
                         'Japanese Gengar cameos SV2A 180/165','English Gengar cameos','Japanese Gengar cameos master ball']:
            code,scoped=query('/collector-discovery',{'q':question})
            assert code==200 and not scoped['cards'] and not scoped.get('artwork_review_leads'),question
            evidence_checks.append(dict(question=question,passed=True,scope_guard=True))
        evidence_checks.extend([dict(id=k,passed=True) for k in ['status','mew_proposed_only','card_context','owned_cameo_inventory','ai_only_inventory_blocked','unknown_card_rejected']])
    expansion_checks=[]
    if expansion_rehearsal is not None:
        expansion=json.loads(expansion_rehearsal.read_text())
        for item in expansion['queries']:
            code,actual=query('/collector-discovery',{'q':item['question']})
            assert code==200 and actual==item['actual'],item['question']
            expansion_checks.append(dict(question=item['question'],passed=True))
        for item in expansion['inventory']:
            code,actual=query('/collector-inventory',body=item['payload'])
            assert code==200 and actual==item['actual']
            expansion_checks.append(dict(payload=item['payload'],passed=True,synthetic=True))
    journey_checks=[];journey_guard_checks=[]
    if journey_rehearsal is not None:
        from scripts.rehearse_collector_journeys import response_digest
        journey=json.loads(journey_rehearsal.read_text())
        assert journey['failed']==0
        def journey_case(item):
            code,actual=query('/collector-journey',body=item['request'])
            assert code==200,(item['id'],code)
            assert response_digest(actual)==item['response_sha256'],item['id']
            return dict(id=item['id'],passed=True,status=actual['status'],synthetic=True)
        with ThreadPoolExecutor(max_workers=3) as pool:journey_checks=list(pool.map(journey_case,journey['results']))
        first=journey['results'][0]['request']
        invalid=[dict(first,purchase_ready=True),dict(first,expected_revision='0'*64),
                 dict(turns=[dict(type='ask',question='Pikachu cards')]*21),
                 dict(turns=[dict(type='ask',question='Japanese Mew cameos in card art'),
                             dict(type='select',card_id='ja:SV-P:197/SV-P:normal')]),
                 dict(turns=[dict(type='ask',question='Pikachu cards'),
                             dict(type='select',card_id='unknown:fixture')])]
        for payload in invalid:assert query('/collector-journey',body=payload)[0]==400
        assert query('/collector-journey',body=first,auth=False)[0]==403
        from pokemon_index import collector_journey
        guard_requests=[dict(turns=[dict(type='ask',question='Japanese Pikachu cards excluding SV2A')]),
            dict(turns=[dict(type='ask',question='Japanese Gengar cameos in card art'),
                dict(type='select',card_id='ja:SV2A:173/165:holo'),dict(type='reply',text='Maybe another character'),
                dict(type='preferences',preferences=dict(destination='HK'))])]
        assert inventory_db is not None
        with closing(core.connect(inventory_db,readonly=True)) as db:
            for payload in guard_requests:
                expected=collector_journey.replay(db,payload,revision=journey['catalog_revision'])
                code,actual=query('/collector-journey',body=payload)
                assert code==200 and actual==expected and not actual['target_intent'] and not actual['selection_allowed']
                journey_guard_checks.append(dict(payload=payload,passed=True,status=actual['status']))
    # Detect another rollout during the diagnostic instead of attributing mixed results.
    assert gcloud('run','services','describe',name,'--region='+region)['status']['latestReadyRevisionName']==revision
    report=dict(project=project,region=region,service=name,revision=revision,url=url,
                image_digest=detail['status']['imageDigest'],private_iam_verified=True,
                unauthenticated_http_status=403,catalog_status=status,supported_status=support,
                collector_checks=checks,inventory_checks=inventory_checks,
                metadata_numbered_part_journey_checks=metadata_journey_checks,
                metadata_graph_checks=metadata_graph_checks,
                coordinate_family_journey_checks=family_journey_checks,
                coordinate_family_broad_select_guard=family_broad_select_guard,
                collector_evidence_checks=evidence_checks,
                collector_expansion_checks=expansion_checks,
                collector_journey_checks=journey_checks,
                collector_journey_guard_checks=journey_guard_checks,
                journey_invalid_input_checks=5 if journey_rehearsal is not None else 0,
                journey_unauthenticated_http_status=403 if journey_rehearsal is not None else None,
                journey_rehearsal_sha256=sha_file(journey_rehearsal) if journey_rehearsal is not None else None,
                expansion_rehearsal_sha256=sha_file(expansion_rehearsal) if expansion_rehearsal is not None else None,
                inventory_invalid_input_checks=2 if inventory_db is not None else 0,
                inventory_unauthenticated_http_status=403 if inventory_db is not None else None,
                inventory_assertions_synthetic=True if inventory_db is not None else None,
                authenticated_http_requests=request_counts['authenticated'],
                unauthenticated_http_requests=request_counts['unauthenticated'],
                numeric_release_guard_checks=2,
                ordinary_figure_out_phrase_check=True,
                invalid_pagination_http_status=400,source_replay_sha256=sha_file(local_report),
                transport_errors=transient_errors,transport_attempts_per_request_max=3,
                deployed_source_files_sha256={p:sha_file(Path(p)) for p in ['pokemon_index/collector_discovery.py','pokemon_index/collector_inventory.py','pokemon_index/collector_journey.py','pokemon_index/collector_evidence.py','pokemon_index/card_metadata.py','pokemon_index/coordinate_family.py','pokemon_index/metadata_views.sql','pokemon_index/discovery_graph.py','pokemon_index/card_rarity.py','pokemon_index/schema.sql','pokemon_index/cli.py','pokemon_index/core.py','pokemon_index/supported_catalog.py','Dockerfile',str(manifest)]},
                verified_date=verified_date,real_market_observations=0,live_feed_enabled=False,
                interpretation='Private staging logical equivalence against a development replay; no live marketplace or complete user-answer accuracy is established.')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(revision=revision,collector_cases=len(checks),inventory_cases=len(inventory_checks),authenticated_http_requests=report['authenticated_http_requests'],unauthenticated_status=403)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--inventory-db',type=Path)
    p.add_argument('--evidence-rehearsal',type=Path)
    p.add_argument('--expansion-rehearsal',type=Path)
    p.add_argument('--manifest',type=Path,default=Path('catalog-build-manifest-evidence-v1.json'))
    p.add_argument('--journey-rehearsal',type=Path)
    p.add_argument('--verified-date',default='2026-10-01')
    a=p.parse_args();verify(a.local_report,a.output,a.inventory_db,a.evidence_rehearsal,a.expansion_rehearsal,a.manifest,a.journey_rehearsal,a.verified_date)
