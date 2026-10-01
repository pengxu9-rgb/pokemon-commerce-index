"""Offline synthetic inventory assertions on real, source-bound catalog IDs."""
from __future__ import annotations
import argparse
import json
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_inventory
from scripts.public_question_sandbox import sha_file


def run(db_path,output):
    if output.exists():raise FileExistsError('rehearsal output must be new')
    before=sha_file(db_path)
    with closing(core.connect(db_path,readonly=True)) as db:
        ids=[r[0] for r in db.execute('SELECT DISTINCT card_id FROM supported_card ORDER BY card_id')]
        # The positive metadata cohort is selected explicitly; ownership is synthetic.
        if len(ids)!=100:raise ValueError('expected 100 metadata targets')
        owned=[dict(item_id=f'synthetic-{i:03}',card_id=cid) for i,cid in enumerate(ids)]
        seen=[]
        for cid in ids:
            r=collector_inventory.compare(db,dict(question='Japanese '+cid,owned_items=owned))
            assert cid in {row['card_id'] for row in r['owned_in_scope']}
            assert cid not in {row['card_id'] for row in r['missing_catalog_records']}
            assert not r['prices'] and not r['live_offers'] and not r['ownership_assertions_verified']
            seen.append(cid)
        cid=ids[0];lang,code,number,version=cid.split(':')
        question='Japanese '+cid
        base=dict(question=question,owned_items=[dict(item_id='owned',card_id=cid)])
        exact=collector_inventory.compare(db,base)
        duplicate=collector_inventory.compare(db,dict(base,owned_items=base['owned_items']+[dict(item_id='duplicate',card_id=cid,quantity=2)]))
        assert duplicate['coverage']['asserted_owned_records']==exact['coverage']['asserted_owned_records']
        assert duplicate['duplicates'][0]['quantity']==3
        uncertain=collector_inventory.compare(db,dict(base,owned_items=[dict(item_id='uncertain',language=lang,set_code=code,collector_number=number)]))
        assert uncertain['status']=='inventory_review_needed' and uncertain['coverage']['asserted_owned_records']==0
        assert cid in {r['card_id'] for r in uncertain['possible_owned']}
        unknown=collector_inventory.compare(db,dict(base,owned_items=[dict(item_id='unknown',card_id='unknown:fixture')]))
        assert unknown['coverage']['unknown_inventory_may_cover_missing_records']
        empty=collector_inventory.compare(db,dict(base,owned_items=[]))
        assert empty['coverage']['not_in_resolved_inventory']>=1 and not empty['complete_missing_list_established']
        blocked=collector_inventory.compare(db,dict(question='Cheapest card for this collection',owned_items=owned))
        assert blocked['status']=='scope_clarification_needed' and not blocked['missing_catalog_records']
        assert not exact['inventory_persisted']
    assert sha_file(db_path)==before
    result=dict(schema='pokemon.synthetic-inventory-rehearsal.v1',catalog_sha256=before,synthetic=True,
                targets_checked=len(seen),target_card_ids=seen,checks={'100_asserted_catalog_targets_recognized':True,
                'duplicates_do_not_close_additional_gaps':True,'unspecified_version_remains_possible_only':True,
                'unknown_inventory_retains_review_blocker':True,'empty_inventory_is_relative_to_catalog':True,
                'market_scope_is_blocked':True,'inventory_not_persisted':True,'catalog_bytes_unchanged':True},
                ownership_verified=False,physical_printings_verified=False,real_user_inventory_accuracy_established=False)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(targets_checked=len(seen),checks=len(result['checks']),synthetic=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.db,a.output)
