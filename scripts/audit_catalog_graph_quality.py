"""Read-only whole-catalog integrity, completeness and graph evidence audit."""
import argparse,hashlib,json
from collections import Counter
from contextlib import closing
from pathlib import Path
from pokemon_index import core,card_metadata,coordinate_family,collector_evidence,supported_catalog


def audit(path,manifest,output,official_cache=None):
    if output.exists():raise FileExistsError(output)
    before=hashlib.sha256(path.read_bytes()).hexdigest();m=json.loads(manifest.read_text())
    checked=[]
    for s in m['steps']:
        p=manifest.parent/s['path'];actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if actual!=s['sha256']:raise ValueError('manifest input changed: '+s['path'])
        checked.append(s['path'])
    with closing(core.connect(path,readonly=True)) as db:
        def count(sql,params=()):return db.execute(sql,params).fetchone()[0]
        cards=[dict(r) for r in db.execute('SELECT * FROM card')]
        invalid_ids=[c['card_id'] for c in cards if c['card_id']!=core.card_id(c['language'],c['set_code'],c['collector_number'],c['variant'])]
        invalid_json=[c['card_id'] for c in cards if not db.execute('SELECT json_valid(?)',(c['attributes_json'],)).fetchone()[0]]
        missing={k:sum(not c[k] or not str(c[k]).strip() for c in cards) for k in ['name','language','set_code','collector_number','variant','provenance','rights_reference']}
        foreign_keys=[list(r) for r in db.execute('PRAGMA foreign_key_check')]
        structural_groups=[dict(r) for r in db.execute('SELECT language,set_code,collector_number,COUNT(*) AS n FROM card GROUP BY language,set_code,collector_number')]
        latest={}
        for a in db.execute('SELECT * FROM card_relationship_assertion ORDER BY rowid DESC'):
            latest.setdefault((a['left_card_id'],a['right_card_id'],a['relation_type']),dict(a))
        nodes={a[k] for a in latest.values() for k in ['left_card_id','right_card_id']}
        shared={}
        for kind in ['dex_id','illustrator']:
            rows=db.execute("SELECT lower(value),COUNT(DISTINCT language) AS languages,COUNT(DISTINCT f.card_id) AS cards FROM discovery_card_facet f JOIN card c ON c.card_id=f.card_id WHERE facet_type=? GROUP BY lower(value)",(kind,)).fetchall()
            shared[kind]=dict(distinct_values=len(rows),values_shared_across_languages=sum(r['languages']>1 for r in rows),
                             claim_scope='retrieval metadata only; not localization/artwork equivalence')
        artist_conflicts=[]
        for row in db.execute('SELECT card_id FROM active_card_metadata_evidence'):
            context=card_metadata.context(db,row[0])
            if context['facet_status']['illustrator']=='source_conflict':artist_conflicts.append(row[0])
        release_gaps=[dict(r) for r in db.execute("SELECT c.language,c.set_code,COUNT(*) AS records FROM card c LEFT JOIN catalog_set_localized s USING(language,set_code) WHERE s.name IS NULL OR s.name='' OR s.release_date IS NULL OR s.release_date='' GROUP BY c.language,c.set_code ORDER BY records DESC")]
        families=[]
        for row in db.execute('SELECT record_json FROM coordinate_family_evidence'):
            r=json.loads(row[0]);families.append(r)
        held_ids={c['card_id'] for r in families if r['status']=='evidence_hold' for c in r['snapshot']['cards']}
        disabled={c['card_id'] for c in cards if not c['match_eligible']}
        graph=dict(latest_assertions=len(latest),latest_states=dict(Counter(a['review_status'] for a in latest.values())),
            relation_types=dict(Counter(a['relation_type'] for a in latest.values())),assertion_nodes=len(nodes),
            proposed_pairs_touching_match_disabled=sum(a['review_status']=='proposed' and bool({a['left_card_id'],a['right_card_id']}&disabled) for a in latest.values()),
            proposed_pairs_touching_explicit_family_holds=sum(a['review_status']=='proposed' and bool({a['left_card_id'],a['right_card_id']}&held_ids) for a in latest.values()),
            structural_multiversion_groups=sum(g['n']>1 for g in structural_groups),
            structural_neighbor_pairs=sum(g['n']*(g['n']-1)//2 for g in structural_groups),
            structural_pair_scope='computed sibling pairs; not persisted verified relationships',facets=shared,
            declared_evolution_families=count('SELECT COUNT(*) FROM character_family'),
            collector_evidence=collector_evidence.status(db),verified_counterpart_price_comparability=False)
        summary=core.catalog_status(db);summary.pop('set_coverage')
        completeness=dict(language_counts=dict(Counter(c['language'] for c in cards)),
            source_families=dict(Counter(c['provenance'].split(':',1)[0] for c in cards)),
            language_set_number_groups=len(structural_groups),
            unverified_label_records=sum(c['variant'].startswith('unverified') for c in cards),
            raw_missing_or_none_rarity=sum(c['rarity'] is None or str(c['rarity']).strip().lower() in {'','none','null'} for c in cards),
            classification_records=count('SELECT COUNT(*) FROM card_classification'),
            release_gap_records=sum(r['records'] for r in release_gaps),release_gap_groups=len(release_gaps),release_gaps=release_gaps,
            artist_conflict_records=artist_conflicts)
        integrity=dict(foreign_key_violations=foreign_keys,invalid_card_ids=invalid_ids,invalid_attributes_json=invalid_json,
            required_field_missing=missing,duplicate_identity_tuples=count('SELECT COUNT(*) FROM (SELECT language,set_code,collector_number,variant FROM card GROUP BY 1,2,3,4 HAVING COUNT(*)>1)'),
            missing_number_contexts=count('SELECT COUNT(*) FROM card c LEFT JOIN card_number_context n USING(card_id) WHERE n.card_id IS NULL'),
            manifested_inputs_verified=len(checked))
        gates=dict(official_card_metadata=card_metadata.status(db),coordinate_family_evidence=coordinate_family.status(db),
            supported_status=supported_catalog.status(db),observations=count('SELECT COUNT(*) FROM observation'),
            paid_sales=count('SELECT COUNT(*) FROM verified_sale'),live_listing_rows=count('SELECT COUNT(*) FROM listing'))
        primary_check=None
        if official_cache is not None:
            from scripts.audit_japanese_metadata_batch import parse_page
            pages=[json.loads(r[0])['official'] for r in db.execute('SELECT record_json FROM active_card_metadata_evidence')]
            pages.extend(p for r in families for p in r['pages'])
            seen={};failures=[]
            for p in pages:
                key=(p['url'],p['page_sha256'])
                if key in seen:continue
                native=p['url'].rsplit('/',1)[1]
                try:
                    raw=(official_cache/(native+'.html')).read_bytes()
                    receipt=json.loads((official_cache/(native+'.receipt.json')).read_text())
                    if hashlib.sha256(raw).hexdigest()!=p['page_sha256'] or receipt['page_sha256']!=p['page_sha256'] or receipt['url']!=p['url'] or receipt['fetched_at']!=p['fetched_at']:raise ValueError('raw page/receipt binding differs')
                    observed=parse_page(raw)
                    if any(p[k]!=v for k,v in observed.items()):raise ValueError('primary metadata extraction differs')
                    seen[key]=True
                except Exception as e:failures.append(dict(url=p['url'],error_type=type(e).__name__,error=str(e)[:200]));seen[key]=False
            primary_check=dict(unique_pages=len(seen),passed=sum(seen.values()),failures=failures,
                scope='cache hash/receipt plus deterministic extraction parity; not independent OCR or semantic accuracy')
    if before!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('read-only audit mutated database')
    report=dict(schema='pokemon.catalog-graph-quality.v1',audited_date='2026-10-02',catalog_sha256=before,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),catalog_summary=summary,
        integrity=integrity,completeness=completeness,graph=graph,gates=gates,primary_page_parity=primary_check,
        independent_listing_precision_measured=False,physical_printing_count_verified=False,
        interpretation='Integrity and evidence coverage audit of internal source records; not an independent semantic/printing accuracy evaluation.')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','manifest','output']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--official-cache',type=Path)
    a=p.parse_args();r=audit(a.db,a.manifest,a.output,a.official_cache);print(json.dumps({k:r[k] for k in ['integrity','catalog_summary','graph','primary_page_parity']},ensure_ascii=False))
