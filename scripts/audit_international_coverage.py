"""Reproduce source-record coverage and bounded retrieval deltas, read-only."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from pokemon_index import core, catalog_locale, catalog_question_resolver_v2
from scripts.audit_catalog_graph_quality import release_completeness


def coverage(db):
    count=lambda sql: db.execute(sql).fetchone()[0]
    image_records=[json.loads(r[0]) for r in db.execute('SELECT record_json FROM source_image_fact_evidence')]
    return dict(source_records=count('SELECT count(*) FROM card'),
        language_counts={r[0]:r[1] for r in db.execute('SELECT language,count(*) FROM card GROUP BY language')},
        language_set_number_groups=count('SELECT count(*) FROM (SELECT 1 FROM card GROUP BY language,set_code,collector_number)'),
        distinct_internal_identity_tuples=count('SELECT count(*) FROM (SELECT 1 FROM card GROUP BY language,set_code,collector_number,variant)'),
        source_declared_variant_records=count("SELECT count(*) FROM card WHERE variant NOT LIKE 'unverified%'"),
        unresolved_label_records=count("SELECT count(*) FROM card WHERE variant LIKE 'unverified%'"),
        unresolved_coordinate_families=count("SELECT count(*) FROM (SELECT 1 FROM card WHERE variant LIKE 'unverified%' GROUP BY language,set_code,collector_number)"),
        independently_verified_physical_printings=None,
        structural_match_eligible=count('SELECT count(*) FROM card WHERE match_eligible=1'),
        display_permissions=count('SELECT count(*) FROM card WHERE display_allowed=1'),
        catalog_image_files=0, whole_catalog_image_availability='not inventoried; missing images are not missing identities',
        source_image_fact_subjects=len({r['card_id'] for r in image_records}),
        source_image_evidence_distinct_hashes=len({r['image_sha256'] for r in image_records}),
        image_display_permissions=0, automatic_offer_approvals=0, purchase_eligible=0,
        offers=count('SELECT count(*) FROM listing'),observations=count('SELECT count(*) FROM observation'),
        paid_sales=count('SELECT count(*) FROM verified_sale'),
        localized_bindings=count('SELECT count(*) FROM catalog_locale_evidence') if db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_locale_evidence'").fetchone() else 0,
        **release_completeness(db))


def facts(row, name):
    c=row['identity']
    return dict(object_type='single_card', primary_goal='price_comparison', transaction_context='prospective_buy',
        seller_channel='none', identity_tokens=dict(card_names=[name],set_name=c['set_code'],collector_number=c['collector_number'],
            language=c['language'],rarity=None,finish=c['variant'],grade=None),
        media_state='none',language_mentions=[c['language']],platform_refs=[],merchant_ref=None,destination=None)


def run(before_path, after_path, root):
    baseline_manifest=root/'catalog-build-manifest-source-binding-v1.json'
    pilot_manifest=root/'catalog-build-manifest-international-pilot-v1.json'
    original=json.loads(baseline_manifest.read_text()); pilot=json.loads(pilot_manifest.read_text())
    assert len(original['steps'])==65 and pilot['steps'][:65]==original['steps']
    for step in pilot['steps']:
        assert hashlib.sha256((root/step['path']).read_bytes()).hexdigest()==step['sha256']
    rows=[json.loads(l) for l in (root/'catalog/international-coverage-pilot-v1/locales.jsonl').read_text().splitlines()]
    with core.connect(before_path,readonly=True) as before, core.connect(after_path,readonly=True) as after:
        before_digest=hashlib.sha256(before_path.read_bytes()).hexdigest()
        after_digest=hashlib.sha256(after_path.read_bytes()).hexdigest()
        unchanged={table:[tuple(r) for r in before.execute('SELECT * FROM '+table+' ORDER BY rowid')]==[tuple(r) for r in after.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                   for table in ('card','card_reference','card_facet','observation','listing','source_policy')}
        graph_before=[dict(r) for r in before.execute('SELECT * FROM card_relationship_assertion ORDER BY rowid')]
        graph_after=[dict(r) for r in after.execute('SELECT * FROM card_relationship_assertion ORDER BY rowid')]
        timestamp_deltas=sum(x['asserted_at']!=y['asserted_at'] for x,y in zip(graph_before,graph_after))
        unchanged['relationships_excluding_builder_generated_asserted_at']=[{k:v for k,v in r.items() if k!='asserted_at'} for r in graph_before]==[{k:v for k,v in r.items() if k!='asserted_at'} for r in graph_after]
        if not all(unchanged.values()):raise ValueError('baseline records changed')
        queries=[]
        for row in rows:
            c=row['identity'];a=row['name_aliases'][0]
            translated=a['name_en' if c['language']=='ja' else 'name_ja']
            query=f"{translated} {c['language']} {c['set_code']} {c['collector_number']}"
            b=core.catalog_search_internal(before,query,limit=100);p=core.catalog_search_internal(after,query,limit=100)
            br=catalog_question_resolver_v2.resolve_question(before,facts(row,translated))
            ar=catalog_question_resolver_v2.resolve_question(after,facts(row,translated))
            native=core.catalog_search_internal(after,f"{c['name']} {c['language']} {c['set_code']} {c['collector_number']}",limit=100)
            queries.append(dict(card_id=c['card_id'],language=c['language'],query=query,before=b['total'],after=p['total'],
                after_contains_target=c['card_id'] in {r['card_id'] for r in p['cards']},
                native_contains_target=c['card_id'] in {r['card_id'] for r in native['cards']},
                resolver_before=br['resolution']['status'],resolver_after=ar['resolution']['status'],
                resolver_after_ids=ar['resolution']['candidate_ids']))
        assert all(q['after_contains_target'] and q['native_contains_target'] for q in queries)
        report=dict(schema='pokemon.international-coverage-audit.v1',relationship_rebuild_timestamp_differences=timestamp_deltas,
            relationship_timestamp_scope='Existing builder generates import timestamps when absent in source; only asserted_at excluded in independent rebuild comparison. Incremental pilot append below preserves every historical column.',baseline_commit='f499b46f7f0898c5c0478c53fef960d435f1765f',
            manifest_inputs_before=65,manifest_inputs_after=66,preserved_ordered_prefix=True,
            baseline_manifest_sha256=hashlib.sha256(baseline_manifest.read_bytes()).hexdigest(),
            pilot_manifest_sha256=hashlib.sha256(pilot_manifest.read_bytes()).hexdigest(),
            before=coverage(before),after=coverage(after),unchanged_tables=unchanged,
            pilot_by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
            queries=queries,queries_before_missing=sum(q['before']==0 for q in queries),
            queries_after_found=sum(q['after_contains_target'] for q in queries),
            scope='existing printing retrieval coverage; zero new identities, artwork, prices, rights or live capabilities')
        assert before_digest==hashlib.sha256(before_path.read_bytes()).hexdigest()
        assert after_digest==hashlib.sha256(after_path.read_bytes()).hexdigest()
    # Re-import only into a scratch copy, never into either audited snapshot.
    import tempfile,shutil
    with tempfile.TemporaryDirectory() as d:
        scratch=Path(d)/'reimport.sqlite3';shutil.copyfile(after_path,scratch)
        with core.connect(scratch) as db:
            reimport=catalog_locale.import_evidence(db,rows)
            assert reimport==dict(inserted=0,unchanged=len(rows),quarantined=0)
            report['idempotent_reimport']=reimport
    with tempfile.TemporaryDirectory() as d:
        scratch=Path(d)/'append.sqlite3';shutil.copyfile(before_path,scratch)
        with core.connect(scratch) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            original_rows={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
            core.init_db(db)
            appended=catalog_locale.import_evidence(db,rows)
            assert appended==dict(inserted=len(rows),unchanged=0,quarantined=0)
            report['incremental_append_all_existing_tables_unchanged']=all(original_rows[t]==[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables)
            assert report['incremental_append_all_existing_tables_unchanged']
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=run(a.before,a.after,Path.cwd())
    with a.output.open('x') as f:f.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('manifest_inputs_before','manifest_inputs_after','queries_before_missing','queries_after_found','idempotent_reimport')}))


if __name__=='__main__':main()
