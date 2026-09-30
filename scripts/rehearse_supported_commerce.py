"""Offline commerce rehearsal on the supported catalog coordinates; synthetic only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from contextlib import closing
from pathlib import Path
from pokemon_index import core, supported_catalog, ingestion_worker as worker, buyship_partner

ROOT=Path(__file__).resolve().parents[1]
SOURCE='supported_slice_synthetic_fixture'
AT='2026-10-01T00:00:00Z'
NOW='2026-10-01T00:05:00Z'
LATER='2026-10-01T00:06:00Z'
TARGET='ja:SV4A:347/190:holo'


def rehearse(catalog: Path, state: Path) -> dict:
    if state.exists():
        raise ValueError('rehearsal state must be a fresh path; existing durable state is preserved')
    state.parent.mkdir(parents=True,exist_ok=True)
    with closing(core.connect(catalog,readonly=True)) as seed, closing(core.connect(state)) as db:
        seed.backup(db)
        ids=[r[0] for r in db.execute('SELECT card_id FROM supported_card ORDER BY card_id')
             if supported_catalog.support_for_card(db,r[0])['status']=='supported_for_internal_review']
        if len(ids)!=100 or TARGET not in ids:
            raise ValueError('rehearsal requires the frozen 100-target cohort')
        # An isolated test copy, never the catalog image or a source approval.
        db.execute('UPDATE card SET display_allowed=1 WHERE card_id IN (SELECT card_id FROM supported_card)')
        db.commit()
        core.register_source(db,dict(source=SOURCE,rights_reference='synthetic rehearsal only; no real marketplace rights',
            ingest_allowed=True,display_allowed=True,price_statistics_allowed=True,
            cross_source_use_allowed=False,partner_handoff_allowed=True,
            partner_quote_store_allowed=True,retention_days=1,listing_ttl_hours=1))
        worker.initialize(db)
        rows=[]
        for i,cid in enumerate(ids):
            c=db.execute('SELECT * FROM card WHERE card_id=?',(cid,)).fetchone()
            native=f'fixture-{i:03d}'
            rows.append(dict(source=SOURCE,native_id=native,
                title=f"{c['name']} {c['set_code']} {c['collector_number']} {c['variant']}",
                url=f'https://example.invalid/{native}',language='ja',condition_bucket='A',
                observed_at=AT,status='on_sale',price_minor=380000 if cid==TARGET else 380000+i*1000,
                currency='JPY',evidence_ref=f'synthetic:{native}:v1'))
        worker.enqueue(db,'slice-v1',SOURCE,{'product_ids':ids},now=NOW)
        def transient(_):raise worker.RetryableFeedError()
        first=worker.run_next(db,transient,source=SOURCE,now=NOW,calls_per_day=5)
    # Reopen the actual file between failure and retry, then again before quotes.
    with closing(core.connect(state)) as db:
        imported=worker.run_next(db,lambda _:rows,source=SOURCE,now=LATER,calls_per_day=5)
        worker.enqueue(db,'slice-replay',SOURCE,{'product_ids':ids},now=LATER)
        replay=worker.run_next(db,lambda _:rows,source=SOURCE,now=LATER,calls_per_day=5)
        unresolved=db.execute('SELECT COUNT(*) FROM listing WHERE unit_id IS NULL').fetchone()[0]
        units={r['native_id']:r['unit_id'] for r in db.execute('SELECT * FROM listing')}
        actual_ids={r[0] for r in db.execute('SELECT DISTINCT u.card_id FROM listing l JOIN priceable_unit u ON u.unit_id=l.unit_id')}
        if actual_ids!=set(ids) or unresolved:
            raise ValueError('synthetic slice did not resolve to the pinned targets')
        target_row=next(r for r in rows if units[r['native_id']].startswith(TARGET+'|'))
        target_unit=units[target_row['native_id']]
        bundle_unit,_=core.resolve(db,dict(target_row,title=target_row['title']+' 2枚セット'))
        unknown_condition=dict(target_row);unknown_condition.pop('condition_bucket')
        unknown_unit,_=core.resolve(db,unknown_condition)
        db.commit()
        unknown_quote=core.recommend(db,unknown_unit,'HK',LATER)
        missing_cost_blocked=False
        try:
            core.import_quotes(db,[dict(source=SOURCE,native_id=target_row['native_id'],destination='HK',
                currency='HKD',components={'item':21000},quoted_at=LATER,
                expires_at='2026-10-01T00:20:00Z',evidence_ref='synthetic:missing-costs',assumptions={'synthetic':True})])
        except ValueError:
            db.rollback();missing_cost_blocked=True
        index=core.index_for_unit(db,target_unit,'2026-10-01',as_of=LATER)
        fixture=json.loads((ROOT/'examples/buyship_partner_preview.json').read_text())
        fixture['resolve']['url']=target_row['url']
        fixture['resolve']['product']['name']='Synthetic supported-target fixture'
        fixture['quote']['items'][0]['name']='Synthetic supported-target fixture'
        fixture['quote']['expires_at']='2026-10-01T00:20:00Z'
        client=buyship_partner.FixturePartnerClient(copy.deepcopy(fixture))
        preview=buyship_partner.preview_quote(db,card_id=TARGET,unit_id=target_unit,
            source=SOURCE,native_id=target_row['native_id'],destination={'country':'HK'},
            client=client,now=LATER)
        buyship_partner.persist_quote_preview(db,preview)
    with closing(core.connect(state)) as db:
        recommendation=core.recommend(db,target_unit,'HK',LATER)
        expired=core.recommend(db,target_unit,'HK','2026-10-01T00:20:00Z')
        # A mutated same-timestamp observation must fail atomically.
        changed=dict(target_row,price_minor=390000)
        worker.enqueue(db,'conflict',SOURCE,{'native_ids':[target_row['native_id']]},now=LATER)
        conflict=worker.run_next(db,lambda _:[changed],source=SOURCE,now=LATER,calls_per_day=5)
        intact=db.execute('SELECT current_price_minor FROM listing WHERE source=? AND native_id=?',
                          (SOURCE,target_row['native_id'])).fetchone()[0]==380000
        # A legitimate newer observation makes the earlier quote unusable.
        changed.update(observed_at='2026-10-01T00:07:00Z',evidence_ref='synthetic:price-edit')
        worker.enqueue(db,'edit',SOURCE,{'native_ids':[target_row['native_id']]},now='2026-10-01T00:07:00Z')
        edit=worker.run_next(db,lambda _:[changed],source=SOURCE,now='2026-10-01T00:07:00Z',calls_per_day=5)
        invalidated=core.recommend(db,target_unit,'HK','2026-10-01T00:08:00Z')['recommendation'] is None
        fresh=worker.monitor(db,source=SOURCE,now=LATER)
        stale=worker.monitor(db,source=SOURCE,now='2026-10-01T02:00:00Z')
        purge=worker.purge(db,now='2026-10-03T00:00:00Z')
        checks=dict(retry_survived_restart=first['status']=='retry' and imported['status']=='done',
            exact_slice_resolved=actual_ids==set(ids),replay_idempotent=replay['duplicates']==100,
            bundle_abstains=bundle_unit is None,
            unknown_condition_not_merged=unknown_unit!=target_unit and unknown_quote['recommendation'] is None,
            missing_costs_block=missing_cost_blocked,
            quote_survived_restart=recommendation['recommendation_type']=='price_only',
            quote_expiry_blocks=expired['recommendation'] is None,
            conflicting_observation_blocks=conflict['status']=='failed' and intact,
            newer_observation_invalidates_quote=edit['status']=='done' and invalidated,
            freshness_monitor_detects_expiry=stale['stale_on_sale']==100,
            retention_removes_observations=purge['observation']==101,
            retention_removes_journal=purge['feed_job']==4 and purge['ingest_receipt']==101,
            no_orders=preview['order_created'] is False and preview['purchasable'] is False)
    return dict(schema='pokemon.supported-commerce-rehearsal.v1',scope='synthetic_engineering_rehearsal_only',
        catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest(),targets=len(ids),
        real_marketplace_observations=0,automatic_live_offer_approval=False,
        display_override_scope='isolated rehearsal database only; source catalog remains unapproved',
        retry=first,ingestion=imported,replay=replay,ask=index,
        quote_preview=preview,price_only_recommendation=recommendation,
        fresh_monitor=fresh,stale_monitor=stale,retention=purge,checks=checks,
        passed=all(checks.values()),limitations=['No live adapter, scheduled cloud worker or managed market storage enabled',
        'Fixture titles cannot estimate real printing, variant, grade or condition precision',
        'Deployment remains a separate private read-only catalog snapshot'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',required=True,type=Path)
    parser.add_argument('--state',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();report=rehearse(args.catalog,args.state)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'checks':report['checks'],'targets':report['targets']}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
