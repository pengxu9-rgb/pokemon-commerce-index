"""Freeze prefix-by-prefix collector action replay without writing the catalog."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from contextlib import closing
from pokemon_index import core,collector_journey
from scripts.public_question_sandbox import sha_file


def response_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def run(db_path,suite_path,output):
    if output.exists():raise FileExistsError(output)
    suite=json.loads(suite_path.read_text())
    if suite['schema']!='pokemon.collector-journeys.v1':raise ValueError('unknown journey suite')
    rows=suite['journeys'];ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)) or not rows:raise ValueError('duplicate or empty journeys')
    before=sha_file(db_path);results=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        for journey in rows:
            turns=[]
            for i,step in enumerate(journey['steps']):
                turns.append(step['action']);request=dict(turns=list(turns),expected_revision=revision)
                actual=collector_journey.replay(db,request,revision=revision);e=step['expect'];errors=[]
                if actual['status']!=e['status']:errors.append('status differs')
                card_ids=[c['card_id'] for c in actual['candidate_cards']]
                selected=actual['selected_catalog_target']['card_id'] if actual['selected_catalog_target'] else None
                if 'selected_card_id' in e and selected!=e['selected_card_id']:errors.append('selected target differs')
                if 'required_card_id' in e and e['required_card_id'] not in card_ids:errors.append('required candidate absent')
                for k,field in [('only_language','language'),('only_set','set_code')]:
                    if k in e and (not actual['candidate_cards'] or {c[field] for c in actual['candidate_cards']}!={e[k]}):errors.append('scope differs: '+field)
                if e.get('ai_lead') and (card_ids or not actual['artwork_review_leads']):errors.append('AI lead promoted or absent')
                if 'preferences_currency' in e and actual['preferences'].get('currency')!=e['preferences_currency']:errors.append('preferences not retained')
                if 'duplicate_quantity' in e and actual['inventory']['duplicates'][0]['quantity']!=e['duplicate_quantity']:errors.append('duplicate quantity differs')
                for k in ['prices','live_offers','public_display_allowed','purchase_ready','physical_copy_verified',
                          'ready_for_offer_tracking','conversation_persisted','inventory_persisted','ownership_assertions_verified','complete_collection_established']:
                    if actual[k]:errors.append('unsupported approval/data: '+k)
                if actual['target_intent']:
                    intent=actual['target_intent']
                    if intent['transaction_ready'] or intent['automatic_offer_join_allowed'] or intent['priceable_unit_id'] or intent['quote'] or intent['product_url']:errors.append('unsupported commerce handoff')
                results.append(dict(id=journey['id']+':'+str(i+1),request=request,expect=e,
                    actual_status=actual['status'],returned_card_ids=card_ids,selected_card_id=selected,
                    response_sha256=response_digest(actual),passed=not errors,errors=errors))
    if sha_file(db_path)!=before:raise ValueError('journey mutated catalog')
    result=dict(schema='pokemon.collector-journey-rehearsal.v1',journeys=len(rows),steps=len(results),
        passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),results=results,
        catalog_revision=revision,catalog_sha256=before,suite_sha256=sha_file(suite_path),
        runtime_sha256={p:sha_file(Path(p)) for p in ['pokemon_index/collector_journey.py','pokemon_index/collector_discovery.py','pokemon_index/collector_inventory.py','pokemon_index/cli.py']},
        catalog_bytes_unchanged=True,inventory_assertions_synthetic=True,real_user_accuracy_established=False,
        interpretation=suite['scope'])
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['journeys','steps','passed','failed']}))
    if result['failed']:
        print(json.dumps([dict(id=r['id'],errors=r['errors'],actual_status=r['actual_status']) for r in results if not r['passed']]));raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.db,a.suite,a.output)
