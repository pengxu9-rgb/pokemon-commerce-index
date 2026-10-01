"""Rehearse a declared evidence enrichment against unchanged source expectations."""
from __future__ import annotations
import argparse,copy,json
from pathlib import Path
from contextlib import closing
from pokemon_index import core,collector_discovery,collector_inventory,collector_evidence
from scripts.evaluate_collector_sources import catalog_fingerprint
from scripts.public_question_sandbox import sha_file

def run(db_path,directory):
    directory.mkdir(parents=True,exist_ok=True)
    paths=[directory/'collector-source-replay.json',directory/'rehearsal.json']
    if any(p.exists() for p in paths):raise FileExistsError('rehearsal output must be new')
    before=sha_file(db_path);base=Path('sandbox/collector_questions/v2/combined-release-replay-report.json')
    old=json.loads(base.read_text());results=[];changed=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        baseline=json.loads(Path('sandbox/collector_questions/v2/catalog-equivalence-lock.json').read_text())
        assert catalog_fingerprint(db,include_collector_evidence=False)==baseline['discovery_evidence_sha256']
        full=catalog_fingerprint(db)
        assert full!=baseline['discovery_evidence_sha256']
        for r in old['results']:
            first=None;cards=[];offset=0;requests=0
            while True:
                page=collector_discovery.execute(db,r['question'],limit=100,offset=offset);requests+=1
                if first is None:first=page
                cards.extend(c['card_id'] for c in page['cards'])
                assert not page['prices'] and not page['live_offers'] and not page['public_display_allowed']
                if not page.get('coverage',{}).get('has_more'):break
                offset+=100
                if offset>10000:raise ValueError('unbounded rehearsal pagination')
            assert cards==r['returned_card_ids'],r['id']
            assert first['task']==r['actual_task'],r['id']
            if first!=r['first_page']:changed.append(r['id'])
            item=copy.deepcopy(r);item.update(first_page=first,page_count=requests,returned_card_ids=cards,
                returned_cards=len(cards),passed=True,errors=[],artwork_review_leads=len(first.get('artwork_review_leads',[])))
            results.append(item)
        queries=[]
        for name,cid in [('Gengar','ja:SV2A:173/165:holo'),('Jigglypuff','ja:SV2A:173/165:holo'),
                         ('Butterfree','ja:SV2A:173/165:holo'),('Growlithe','ja:SV2A:173/165:holo'),
                         ('Kabuto','ja:SV2A:180/165:holo'),('Omastar','ja:SV2A:180/165:holo')]:
            q='Japanese '+name+' cameos in card art';r=collector_discovery.execute(db,q)
            assert [c['card_id'] for c in r['cards']]==[cid]
            assert not r['complete_answer_established'] and not r['coverage']['global_printing_completeness_established']
            queries.append(dict(question=q,expected_card_ids=[cid],actual=r))
        mew=collector_discovery.execute(db,'Japanese Mew cameos in card art')
        assert mew['cards']==[] and mew['artwork_review_leads'][0]['subject_id']=='ja:SV-P:197/SV-P:normal'
        assert all(r['status']=='proposed' for r in mew['artwork_review_leads'])
        for q in ['Japanese 151 Mew cameos','Japanese Mew cameos SV-P 120/SV-P','Japanese Gengar cameos SV2A 180/165','English Gengar cameos','Japanese Gengar cameos master ball']:
            scoped=collector_discovery.execute(db,q)
            assert not scoped['cards'] and not scoped.get('artwork_review_leads'),q
        # A shared attack name does not transfer a depiction to another promo.
        assert not any(r['value']==151 for r in collector_evidence.card_context(db,'ja:SV-P:120/SV-P:normal')['findings'])
        context=collector_evidence.card_context(db,'ja:SV2A:173/165:holo')
        assert any(r['claim']=='finish_exists' and r['subject_kind']=='release' for r in context['findings'])
        assert not context['physical_finish_verified'] and not context['price_comparable']
        owned=collector_inventory.compare(db,dict(question='Japanese Gengar cameos in card art',owned_items=[dict(item_id='synthetic',card_id='ja:SV2A:173/165:holo')]))
        assert not owned['missing_catalog_records'] and owned['owned_in_scope']
        uncertain=collector_inventory.compare(db,dict(question='Japanese Mew cameos in card art',owned_items=[]))
        assert uncertain['status']=='scope_clarification_needed' and not uncertain['missing_catalog_records']
        assert db.execute("SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0]==0
        status=collector_evidence.status(db)
    assert sha_file(db_path)==before
    source=dict(schema='pokemon.collector-evidence-enriched-replay.v1',cases=len(results),passed=len(results),failed=0,
        results=results,baseline_report_sha256=sha_file(base),baseline_identity_fingerprint=baseline['discovery_evidence_sha256'],
        current_evidence_fingerprint=full,catalog_sha256=before,changed_first_page_ids=changed,
        executor_sha256=sha_file(Path(collector_discovery.__file__)),
        complete_answers_established=0,interpretation='Declared enrichment on the same frozen development cohort; original expected card IDs unchanged. Not catalog equivalence or a new held-out measurement.')
    paths[0].write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n')
    report=dict(status=status,source_queries=queries,mew_proposed_only=mew,
        synthetic_owned_inventory=owned,ai_only_inventory_blocker=uncertain,
        checks=dict(original_30_card_memberships_unchanged=True,base_identity_fingerprint_unchanged=True,
        full_evidence_fingerprint_changed=True,six_official_cameo_queries=True,ai_only_leads_not_confirmed=True,
        same_attack_does_not_transfer_depiction=True,release_finish_not_copy_approval=True,
        depiction_scope_honors_release_number_language_and_finish=True,
        supported_cameo_inventory_comparison=True,ai_only_inventory_no_gaps=True,
        verified_pair_edges_still_zero=True,catalog_bytes_unchanged=True),synthetic_inventory=True,
        real_inventory_accuracy_established=False)
    paths[1].write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(queries=len(queries),checks=len(report['checks']),source_replays=len(results))))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();run(a.db,a.directory)
