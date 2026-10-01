"""Exercise new scoped cameo facts and disclose AI calibration disagreements."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from contextlib import closing
from pokemon_index import core,collector_evidence,collector_discovery,collector_inventory
from scripts.public_question_sandbox import read_jsonl,sha_file
from scripts.build_collector_evidence_expansion import qualified,pairs

def run(db_path,directory):
    output=directory/'expansion-rehearsal.json'
    if output.exists():raise FileExistsError(output)
    before=sha_file(db_path);queries=[];inventory=[]
    cases=[('Japanese Gurdurr cameos in card art',['ja:SV6:109/101:holo']),
           ('日本語 ドテッコツ カメオ',['ja:SV6:109/101:holo']),
           ('Japanese Finizen cameos in card art',['ja:SV4A:339/190:holo']),
           ('日本語 ナミイルカ カメオ',['ja:SV4A:339/190:holo'])]
    for name,release,number,wrong in [('Gurdurr','SV6','109/101','110/101'),('Finizen','SV4A','339/190','340/190')]:
        cases.extend([(f'English {name} cameos',[]),
                      (f'Japanese {name} cameos SV2A',[]),
                      (f'Japanese {name} cameos {release} {wrong}',[]),
                      (f'Japanese {name} cameos {release} {number} non-holo',[]),
                      (f'Japanese {name} cameos {release} {number} master ball',[])])
    with closing(core.connect(db_path,readonly=True)) as db:
        for question,expected in cases:
            actual=collector_discovery.execute(db,question)
            assert [c['card_id'] for c in actual['cards']]==expected,question
            if not expected:assert not actual.get('artwork_review_leads'),question
            assert not actual['complete_answer_established'] and not actual['prices'] and not actual['live_offers']
            for c in actual['cards']:
                assert not c['automatic_offer_join_allowed'] and not c['price_comparable']
                assert not c['collector_evidence']['physical_finish_verified']
            queries.append(dict(question=question,expected_card_ids=expected,actual=actual))
        for question,ids in cases[:1]+cases[2:3]:
            for owned in [[],[dict(item_id='synthetic',card_id=ids[0])]]:
                payload=dict(question=question,owned_items=owned);actual=collector_inventory.compare(db,payload)
                assert [c['card_id'] for c in actual['missing_catalog_records']]==([] if owned else ids)
                assert not actual['complete_missing_list_established'] and not actual['ownership_assertions_verified']
                inventory.append(dict(payload=payload,actual=actual,synthetic=True))
        strong=[r for r in collector_evidence.records(db,'card') if r['status']=='source_supported']
    assert sha_file(db_path)==before
    q={r['card_id']:r for r in read_jsonl(directory/'visual-queue.jsonl')}
    r={r['card_id']:r for r in read_jsonl(directory/'gemini-visual-review.jsonl')}
    audit=json.loads((directory/'build-audit.json').read_text());comparisons=audit['comparisons']
    misses=[dict(card_id=s['subject_id'],dex_id=s['value'],role=s['role']) for s in strong
            if s['subject_id'] in r and qualified(r[s['subject_id']],q[s['subject_id']])
            and (s['value'],s['role']) not in pairs(r[s['subject_id']])]
    # Compare positive observations only. Unknown/omitted is never a negative label.
    calibration=dict(official_named_depictions_not_returned_by_fresh_model=misses,
        old_valid_reviews=sum(c['old_status']=='reviewed' for c in comparisons),
        same_positive_species_role_sets=sum(c['old_status']==c['fresh_status']=='reviewed' and c['old_pairs']==c['fresh_pairs'] for c in comparisons),
        changed_positive_sets=[c['card_id'] for c in comparisons if c['old_status']==c['fresh_status']=='reviewed' and c['old_pairs']!=c['fresh_pairs']],
        recovered_prior_failed_reviews=[c['card_id'] for c in comparisons if c['old_status']!='reviewed' and c['fresh_status']=='reviewed'],
        codex_positive_differences=[dict(card_id=c['card_id'],codex_only=sorted(set(map(tuple,c['codex_pairs']))-set(map(tuple,c['fresh_pairs']))),
            gemini_only=sorted(set(map(tuple,c['fresh_pairs']))-set(map(tuple,c['codex_pairs']))))
            for c in comparisons if c['codex_pairs'] is not None and set(map(tuple,c['codex_pairs']))!=set(map(tuple,c['fresh_pairs']))],
        interpretation='Differences between positive species/role observations and official named facts; not precision/recall, because neither AI enumeration is a complete human ground truth. Same-family agreement cannot resolve shared omissions.')
    result=dict(schema='pokemon.collector-expansion-rehearsal.v1',queries=queries,inventory=inventory,
        checks=dict(new_bilingual_source_scopes=True,release_number_language_finish_guards=True,
            inventory_uses_only_official_scope=True,ai_findings_not_promoted=True,no_live_or_physical_approvals=True,catalog_bytes_unchanged=True),
        catalog_sha256=before,calibration=calibration,real_market_observations=0,
        baseline_replay_sha256=sha_file(directory/'release-scope-replay/collector-source-replay.json'))
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(queries=len(queries),inventory_cases=len(inventory),calibration=calibration)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();run(a.db,a.directory)
