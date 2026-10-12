"""Offline operator freeze of versioned mixed sessions; never run during CI.

Preserve v1 bytes and its sixteen intent/axis/language/action patterns. Only
previously shown source-record references displaced by scan-first ranking may
change. Native and accelerated replays plus independent SQL/trace invariants
must pass before exclusive publication of the new static fixture.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,sys,time
from collections import Counter
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'tests/fixtures/collector-mixed-workload-v1.json'
OLD_SHA='e7eb0adf0ddd3d7bbbdc81ac885224ea4cfc82e6fd9e54bdda8008e63f858bbe'
NEW=ROOT/'tests/fixtures/collector-mixed-workload-v2.json'
RECEIPT=ROOT/'catalog/mixed-workload-v2-review/receipt.json'
EXPECTED_DB_SHA='0e6787ece29fc83ab21a9d986eab66f4d689469a342b1727c02795dd39009256'
GATES=('conversation_persisted','inventory_persisted','ownership_assertions_verified',
       'physical_copy_verified','ready_for_offer_tracking','purchase_ready',
       'complete_collection_established','public_display_allowed','preferences_applied_to_market')


def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def normalized(value):
    if isinstance(value,list):return [normalized(item) for item in value]
    if isinstance(value,dict):return {key:normalized(item) for key,item in value.items() if key not in {'catalog_revision','expected_revision'}}
    return value


def freeze(db_path,fixture_path=NEW,receipt_path=RECEIPT):
    from pokemon_index import core,collector_journey,collector_runtime,catalog_media,variant_dimension_hold
    from scripts import benchmark_collector_caller as bench,benchmark_collector_mixed as mixed,collector_catalog_evidence as evidence
    db_path=Path(db_path).resolve();fixture_path=Path(fixture_path);receipt_path=Path(receipt_path)
    if fixture_path.exists() or receipt_path.exists():raise FileExistsError('new static fixture/receipt already exists')
    old_bytes=OLD.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest()!=OLD_SHA:raise ValueError('v1 frozen bytes changed')
    if file_sha(db_path)!=EXPECTED_DB_SHA:raise ValueError('explicit current65 build differs')
    old=json.loads(old_bytes);mixed.validate_workload(old)
    source_before=bench.source_receipt(ROOT)
    helper_paths=[Path(__file__),ROOT/'scripts/benchmark_collector_mixed.py',ROOT/'scripts/benchmark_collector_caller.py',ROOT/'scripts/collector_catalog_evidence.py']
    helpers_before={str(p.relative_to(ROOT)):file_sha(p) for p in helper_paths}
    with closing(core.connect(db_path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        logical=evidence.catalog_evidence_digest(db,schema=evidence.LOCALIZED_SCHEMA)
        current_v2=evidence.catalog_evidence_digest(db)
        cards={r['card_id']:dict(r) for r in db.execute('SELECT * FROM card')}
        facets={}
        for row in db.execute('SELECT card_id,facet_type,value,provenance,rights_reference FROM discovery_card_facet'):
            facets.setdefault(row['card_id'],[]).append(dict(row))
        official_metadata={row['evidence_id']:dict(row) for row in db.execute('SELECT * FROM active_card_metadata_evidence')}
        printed_corrections={row['event_id']:dict(row) for row in db.execute("SELECT * FROM active_source_correction_evidence WHERE kind='printed_artist'")}
        actual_held={r['identity']['card_id'] for r in variant_dimension_hold.rows_for(db)}
        # The65-input CI build intentionally has no appended hold ledger. Still
        # exclude the documented44 legacy size-loss IDs from these sample choices.
        known_hold_path=ROOT/'catalog/variant-dimension-holds-v1/holds.jsonl'
        known_held={json.loads(line)['identity']['card_id'] for line in known_hold_path.read_text().splitlines() if line.strip()}
        if len(known_held)!=44:raise ValueError('known legacy size hold inventory differs')
        held=actual_held|known_held
        references={turn[key] for session in old['sessions'] for turn in session['payload']['turns']
                    for key in ('card_id','left_card_id','right_card_id') if key in turn}
        subjects=catalog_media.subjects(db)
        media={cid:catalog_media.availability(db,cid) for cid in subjects|references}
        catalog_records=db.execute('SELECT count(*) FROM card').fetchone()[0]
        market_counts={name:db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('priceable_unit','listing','observation','landed_quote','verified_sale')}
        if catalog_records!=70006 or any(market_counts.values()):raise ValueError('CI catalog/trading baseline differs')
    with closing(core.connect(db_path,readonly=True)) as base:
        model=collector_runtime.CatalogReadModel(base)
    cache={}
    def replay(payload,accelerated=False):
        key=(accelerated,bench.json_hash(payload))
        if key not in cache:
            with closing(core.connect(db_path,readonly=True)) as db:
                if accelerated:
                    with model.request(db):result=collector_journey.replay(db,copy.deepcopy(payload),revision=revision)
                else:
                    db.execute('PRAGMA query_only=ON');result=collector_journey.replay(db,copy.deepcopy(payload),revision=revision)
            cache[key]=result
        return cache[key]
    def prefix(payload,count):return dict(turns=copy.deepcopy(payload['turns'][:count]),limit=payload['limit'])
    def ids(result):return [card['card_id'] for card in result['candidate_cards']]
    def gate(result):
        return all(result.get(k) is False for k in GATES) and result['prices']==[] and result['live_offers']==[]
    def source_axis_proofs(cid,session):
        card=cards[cid];axis=session['axis']
        kind,value=('illustrator',axis['value']) if axis['kind']=='illustrator' else ('dex_id',str(axis['dex_id']))
        proofs=[]
        if card['language']!=session['language']:return proofs
        for f in facets.get(cid,[]):
            if f['facet_type']!=kind or f['value']!=value:continue
            if f['provenance']==card['provenance'] and f['rights_reference']==card['rights_reference']:
                proofs.append(dict(f,basis='exact_native_source_facet'));continue
            metadata=official_metadata.get(f['provenance'])
            if metadata and metadata['card_id']==cid:
                record=json.loads(metadata['record_json']);official=record['official']
                supported=(str(official.get('dex_id'))==value if kind=='dex_id' else value in official['illustrators'])
                if supported and f['rights_reference']==official['url']:
                    proofs.append(dict(f,basis='active_exact_official_metadata_facet',record_sha256=bench.json_hash(record)));continue
            correction=printed_corrections.get(f['provenance'])
            if correction and kind=='illustrator':
                record=json.loads(correction['record_json']);parent=json.loads(record['parent_record_json'])
                if record['value']==value and cid in {c['card_id'] for c in record['snapshot']['cards']} and f['rights_reference']==parent['sources'][0]['url']:
                    proofs.append(dict(f,basis='active_exact_printed_artist_correction',record_sha256=bench.json_hash(record)))
        return proofs
    def axis_valid(cid,session):return bool(source_axis_proofs(cid,session))
    def usable(cid,session,result):
        return cid not in held and cards[cid]['match_eligible']==1 and axis_valid(cid,session) and not result['card_selection_blockers'].get(cid)
    def choose(old_id,session,result):
        shown=ids(result)
        if old_id in shown and usable(old_id,session,result):return old_id
        choices=[cid for cid in shown if usable(cid,session,result) and cid in media and media[cid]['with_source_scans_eligible']]
        if not choices:raise ValueError('scan-first rebinding lacks a current shown same-axis eligible scan: '+session['name'])
        if not axis_valid(old_id,session) or old_id in held or media[old_id]['with_source_scans_eligible']:raise ValueError('previous reference change is not a safe documented scan-tier displacement')
        return choices[0]
    def independent(result,session,count,*,final=False):
        if not gate(result) or result['turn_count']!=count:raise ValueError('commercial gates or replay length changed')
        if result['goal_question']!=session['payload']['turns'][0]['question']:raise ValueError('original goal changed')
        for cid in ids(result):
            if cid not in cards or not axis_valid(cid,session):raise ValueError('candidate escaped exact source axis/language')
            record=next(c for c in result['candidate_cards'] if c['card_id']==cid)
            if record['provenance']!=cards[cid]['provenance']:raise ValueError('candidate source identity changed')
        if final and result['discovery']['coverage'].get('matched_catalog_records')!=session['preflight']['pool_records']:raise ValueError('original final scoped pool count changed')
        return True
    sessions=[];changes=[];checks_by_session=[]
    for original in old['sessions']:
        session=copy.deepcopy(original);payload=session['payload'];turns=payload['turns'];pattern=session['pattern'];index=session['index'];checks={}
        initial=replay(prefix(payload,3));independent(initial,session,3)
        checks.update(initial_nonempty_recommendation=bool(initial['candidate_cards']) and initial['discovery']['task']=='collector_recommendations',language_scope=initial['scope_filters']=={'language':session['language']})
        if not all(checks.values()):raise ValueError('original initial axis/lang intent no longer valid')
        if pattern=='character_feedback_hidden_clear_restore':
            old_id=turns[3]['card_id'];chosen=choose(old_id,session,initial)
            if chosen!=old_id:
                turns[3]['card_id']=chosen;turns[5]['card_id']=chosen
                changes.extend(dict(session=index,turn=i+1,field='card_id',old=old_id,new=chosen,reason='prior scan-less first-page reference displaced by current source-scan tier',old_scan=media[old_id],new_scan=media[chosen]) for i in (3,5))
            dismissed=replay(prefix(payload,4));hidden=replay(prefix(payload,5));cleared_hidden=replay(prefix(payload,6));restored=replay(prefix(payload,7))
            for result,count in [(dismissed,4),(restored,7)]:independent(result,session,count)
            checks.update(dismiss_hides_card=chosen not in ids(dismissed),
                feedback_hidden_clear_restoration=chosen not in ids(hidden) and chosen not in ids(cleared_hidden)
                    and restored['candidate_cards']==initial['candidate_cards'] and restored['recommendation']==initial['recommendation']
                    and restored['discovery']['coverage']==initial['discovery']['coverage'])
        elif pattern=='artist_ownership_resolve_restore':
            old_id=turns[4]['card_id'];chosen=choose(old_id,session,initial)
            if chosen!=old_id:
                c=cards[chosen];item=turns[3]['owned_items'][0]
                for key in ('language','set_code','collector_number'):
                    if item[key]!=c[key]:changes.append(dict(session=index,turn=4,field='owned_items[0].'+key,old=item[key],new=c[key],reason='same synthetic uncertain owned-item assertion points to rebound shown source record'));item[key]=c[key]
                turns[4]['card_id']=chosen;changes.append(dict(session=index,turn=5,field='card_id',old=old_id,new=chosen,reason='prior scan-less first-page reference displaced by current source-scan tier',old_scan=media[old_id],new_scan=media[chosen]))
            uncertain=replay(prefix(payload,4));resolved=replay(prefix(payload,5));restored=replay(prefix(payload,6))
            independent(restored,session,6)
            checks.update(ownership_resolution_restoration=uncertain['status']=='inventory_review_needed' and bool(uncertain['inventory']['unresolved_items']) and uncertain['selected_catalog_target'] is None and resolved['inventory']['unresolved_items']==[] and chosen not in ids(resolved) and ids(restored)==ids(initial),
                unresolved_ownership_blocks_target=not uncertain['selection_allowed'],inventory_clear_restores_scope=restored['inventory']['inventory_entries']==[])
        elif pattern=='character_compare_focus_select':
            before_compare=replay(prefix(payload,17));independent(before_compare,session,17)
            shown={cid for row in before_compare['trace'] for cid in row['displayed_card_ids']}
            compare=turns[17];old_left,old_right=compare['left_card_id'],compare['right_card_id'];selected=[]
            for field,old_id in [('left_card_id',old_left),('right_card_id',old_right)]:
                chosen=old_id if old_id in shown and usable(old_id,session,before_compare) else None
                if chosen is None:
                    eligible=[cid for row in before_compare['trace'] for cid in row['displayed_card_ids'] if cid not in selected and usable(cid,session,before_compare) and cid in media and media[cid]['with_source_scans_eligible']]
                    if not eligible or media[old_id]['with_source_scans_eligible'] or not axis_valid(old_id,session):raise ValueError('comparison displacement lacks source-scan justification')
                    chosen=eligible[0];compare[field]=chosen;changes.append(dict(session=index,turn=18,field=field,old=old_id,new=chosen,reason='old comparison reference not shown in unchanged page pattern after source-scan ranking',old_scan=media[old_id],new_scan=media[chosen]))
                selected.append(chosen)
            old_focus=turns[18]['card_id'];new_focus=selected[0]
            if turns[18]['side']!='left' or old_focus!=old_left or turns[19]['card_id']!=old_left:raise ValueError('original left-focus-select semantics differ')
            for i in (18,19):
                if turns[i]['card_id']!=new_focus:changes.append(dict(session=index,turn=i+1,field='card_id',old=turns[i]['card_id'],new=new_focus,reason='preserve explicit left-side focus followed by separate select'));turns[i]['card_id']=new_focus
            compared=replay(prefix(payload,18));focused=replay(prefix(payload,19));final=replay(payload)
            independent(focused,session,19);independent(final,session,20,final=True)
            checks.update(comparison_unselected=compared['selected_catalog_target'] is None and compared['target_intent'] is None and compared['discovery']['task']=='two_card_comparison',
                focus_unselected=focused['selected_catalog_target'] is None and focused['target_intent'] is None,
                focus_exact=ids(focused)==[new_focus],selection_separate=final['selected_catalog_target']['card_id']==new_focus and final['target_intent']['card_id']==new_focus,
                no_held_selection=new_focus not in held and final['target_intent']['transaction_ready'] is False and final['target_intent']['priceable_unit_id'] is None)
        elif pattern=='artist_preference_change_restore':
            alternate=replay(prefix(payload,4));restored=replay(prefix(payload,6));independent(restored,session,6)
            original_artist=turns[1]['preferences']['collecting']['preferred_illustrators'];alternative_artist=turns[3]['preferences']['collecting']['preferred_illustrators']
            checks.update(artist_preference_change_restoration=alternate['preferences']['collecting']['preferred_illustrators']==alternative_artist and restored['preferences']['collecting']['preferred_illustrators']==original_artist and ids(restored)==ids(initial))
        else:raise ValueError('unknown original mixed pattern')
        # Only named reference fields may differ, never goal/preference/axis/counts.
        allowed={(c['turn']-1,c['field']) for c in changes if c['session']==index}
        for i,(a,b) in enumerate(zip(original['payload']['turns'],turns)):
            if a==b:continue
            x=copy.deepcopy(b)
            for turn,field in allowed:
                if turn!=i:continue
                if field.startswith('owned_items[0].'):
                    k=field.split('.',1)[1];x['owned_items'][0][k]=a['owned_items'][0][k]
                else:x[field]=a[field]
            if x!=a:raise ValueError('synthetic intent/action changed beyond reviewed references')
        final=replay(payload);accelerated=replay(payload,True)
        independent(final,session,20,final=True)
        checks.update(twenty_turns=len(turns)==20,all_commercial_gates_closed=gate(final),
            native_accelerated_equal=final==accelerated,source_axis_identifiers_preserved=True,
            final_scoped_pool_count_preserved=final['discovery']['coverage']['matched_catalog_records']==original['preflight']['pool_records'],
            no_held_selection=final['selected_catalog_target'] is None or final['selected_catalog_target']['card_id'] not in held)
        if not all(checks.values()):raise ValueError('independent mixed semantics checks failed '+str(index)+' '+str(checks))
        session['payload_sha256']=bench.json_hash(payload)
        session['expected_result_semantic_sha256']=bench.json_hash(normalized(final))
        session['preflight']=dict(checks=checks,status=final['status'],task=final['discovery']['task'],pool_records=final['discovery']['coverage']['matched_catalog_records'])
        sessions.append(session);checks_by_session.append(dict(index=index,checks=checks,final_source_ids=ids(final),source_axis_proofs={cid:source_axis_proofs(cid,session) for cid in ids(final)},trace_semantic_sha256=bench.json_hash(normalized(final['trace'])),expected_result_semantic_sha256=session['expected_result_semantic_sha256']))
        print(json.dumps(dict(frozen_sessions=len(sessions),index=index,pattern=pattern,reference_changes=sum(c['session']==index for c in changes))),flush=True)
    if len(sessions)!=16 or len({s['payload_sha256'] for s in sessions})!=16 or Counter(s['pattern'] for s in sessions)!=Counter(s['pattern'] for s in old['sessions']):raise ValueError('distinct16 session/pattern inventory changed')
    fixture=dict(schema='pokemon.collector-mixed-workload.v2',catalog_sha256=EXPECTED_DB_SHA,catalog_revision=revision,
                 catalog_evidence=dict(schema=evidence.LOCALIZED_SCHEMA,sha256=logical),source=source_before,sessions=sessions,
                 payloads_sha256=bench.json_hash([s['payload'] for s in sessions]),cpu_affinity=None,catalog_unchanged=True,source_unchanged=True,
                 prior_fixture_sha256=OLD_SHA,
                 scope='Versioned static sixteen distinct twenty-turn synthetic sessions; same original goals/axes/languages/patterns/limits/pages/pool counts and authority separation. Explicit offline rebinding only; no blind accuracy, real-user utility, live market or capacity result.')
    mixed.validate_workload(fixture)
    if OLD.read_bytes()!=old_bytes or file_sha(db_path)!=EXPECTED_DB_SHA or bench.source_receipt(ROOT)!=source_before or any(file_sha(ROOT/p)!=h for p,h in helpers_before.items()):raise ValueError('source/database/v1/helper drift during freeze')
    receipt=dict(schema='pokemon.collector-mixed-workload-freeze.v2',frozen_at=datetime.now(timezone.utc).isoformat(),
                 original_fixture=dict(path=str(OLD.relative_to(ROOT)),sha256=OLD_SHA,preserved=True),database=dict(path=str(db_path),sha256_before=EXPECTED_DB_SHA,sha256_after=file_sha(db_path),ordered_manifest='catalog-build-manifest-source-binding-v1.json',ordered_inputs=65,records=70006),
                 source=source_before,source_unchanged=True,helpers=helpers_before,
                 versioning=dict(old_workload='pokemon.collector-mixed-workload.v1',old_evidence=evidence.SCHEMA,old_frozen_evidence=old['catalog_evidence']['sha256'],current_default_v2_evidence=current_v2,new_workload=fixture['schema'],new_evidence=evidence.LOCALIZED_SCHEMA,new_evidence_sha256=logical,
                                 reason='Versioned full-schema identity and five additional locale/source/concept/review/quarantine tables; strict v1/v2 compatibility pairing and original digest behavior retained.'),
                 fixture_payloads_sha256=fixture['payloads_sha256'],sessions=16,turns_per_session=20,patterns=dict(Counter(s['pattern'] for s in sessions)),languages=dict(Counter(s['language'] for s in sessions)),
                 reference_changes=changes,checks_by_session=checks_by_session,native_accelerated_equal_all=True,known_size_loss_ids_excluded=44,actual_active_holds=len(actual_held),market_table_counts=market_counts,
                 comparison_focus_selection_separation_preserved=True,old_fixture_intent_semantics_preserved=True,
                 freeze_scope='Deterministic operator checks against actual source facets and replay traces; selected examples are synthetic development workloads, not new independent blind/user accuracy or real market behavior. Capacity is a separate actual caller/HTTP Linux run.',
                 ci_regenerates_fixture=False,network=False,imports=False,frontend=False,deployment=False,push=False,trading=False)
    fixture_bytes=(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n').encode();receipt['fixture_sha256']=hashlib.sha256(fixture_bytes).hexdigest()
    fixture_path.parent.mkdir(parents=True,exist_ok=True);receipt_path.parent.mkdir(parents=True,exist_ok=True)
    with fixture_path.open('xb') as handle:handle.write(fixture_bytes)
    with receipt_path.open('x') as handle:json.dump(receipt,handle,ensure_ascii=False,indent=2);handle.write('\n')
    return dict(fixture=str(fixture_path),fixture_sha256=file_sha(fixture_path),receipt=str(receipt_path),receipt_sha256=file_sha(receipt_path),reference_changes=len(changes),native_accelerated_equal_all=True,original_fixture_preserved=file_sha(OLD)==OLD_SHA,database_unchanged=file_sha(db_path)==EXPECTED_DB_SHA)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,default=NEW);parser.add_argument('--receipt',type=Path,default=RECEIPT)
    args=parser.parse_args();print(json.dumps(freeze(args.db,args.fixture,args.receipt)),flush=True)


if __name__=='__main__':main()
