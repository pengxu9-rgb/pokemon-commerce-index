"""Add exact-coordinate field evidence from four already authorized anchors.

Offline operator evidence only. No importer, network fallback or approval path.
PTCG and publisher observations are dependent sources, not independent reviews.
"""
import argparse
import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

from pokemon_index import catalog_locale, core, product_text
from scripts import qualify_international_product_documents as documents
from scripts.audit_japanese_metadata_batch import parse_page
from scripts.build_publisher_product_text import extract

REVISION='bc5a2698eb9af858feb0280d579fd5fd0f0273e2'
SCOPE='literal_provider_publisher_field_concordance_for_exact_held_coordinate_only'


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate source JSON field')
        result[key]=value
    return result


def source_coordinate(source):
    values=[source.get('number'),source.get('set_total')]
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,3}',v) or int(v)==0 for v in values):
        return None
    return dict(set_code=source.get('set_name'),collector_number='/'.join(v.zfill(3) for v in values))


def comparison(provider,publisher,*,empty=None):
    if provider==empty and publisher==empty:status='both_unreported'
    elif provider==empty:status='provider_unreported'
    elif publisher==empty:status='publisher_unreported'
    else:status='literal_match' if provider==publisher else 'conflict'
    return dict(provider_value=provider,publisher_value=publisher,status=status)


def record(outcome,caption,source,source_receipt,observed,products,inspected_at):
    core.parse_time(inspected_at)
    code=outcome['set_code'];native=documents.ANCHORS.get(code)
    if not native or (caption['card_id'],caption['candidate_id'],caption['evidence_id'])!=(
            outcome['card_id'],outcome['candidate_id'],outcome['caption_evidence_id']):
        raise ValueError('supplement must bind the exact existing caption and held outcome')
    if (outcome['language']!='ja' or outcome['status']!='held_anchor_binding_unqualified'
            or outcome['release_date'] is not None or outcome['physical_distribution_region'] is not None
            or any(outcome.get(k) is not False for k in product_text.FLAGS)):
        raise ValueError('supplement cannot widen held outcome claims')
    if caption['test_only'] is not False or any(caption.get(k) is not False for k in product_text.FLAGS):
        raise ValueError('supplement caption cannot grant permissions or identity approval')
    publisher=caption['publisher'];url='https://www.pokemon-card.com/card-search/details.php/card/'+native
    if publisher['native_id']!=native or publisher['url']!=url or publisher['language']!='ja':
        raise ValueError('publisher native coordinate differs')
    expected=dict(set_code=code,collector_number=outcome['collector_number'])
    if outcome['card_id']!=f"ja:{code}:{outcome['collector_number']}:unverified":
        raise ValueError('physical variant cannot inherit anchor field evidence')
    if (source_receipt['provider']!='ptcg-database' or source_receipt['revision']!=REVISION
            or source_receipt['native_id']!=f'data_jp/{code}/{native}.json'
            or source_receipt['sha256']!=outcome['anchor_source']['sha256']):
        raise ValueError('provider source namespace or pinned snapshot differs')
    entries=observed['numbered_entries']
    publisher_coordinate={k:entries[0][k] for k in ('set_code','collector_number')} if len(entries)==1 else None
    coordinates=comparison(source_coordinate(source),publisher_coordinate)
    identity_matches=(type(source.get('jp_id')) is int and str(source['jp_id'])==native
        and source.get('url')==url and publisher_coordinate==expected and source_coordinate(source)==expected
        and source.get('name')==observed['name'])
    authors=source.get('author');dex=source.get('pokedex_number')
    if authors is not None and (not isinstance(authors,list) or any(not isinstance(x,str) or not x.strip() for x in authors)
            or len(set(authors))!=len(authors)):
        raise ValueError('provider illustrator field is ambiguous')
    if dex is not None and (type(dex) is not int or not 1<=dex<=9999):
        raise ValueError('provider Pokedex field is unsupported')
    provider_products=[dict(name=s['name'],publisher_link=s.get('link'),link_kind=product_text.link_kind(s.get('link')))
        for s in source.get('sources',[]) if s.get('name','').startswith('ポケモンカードゲーム')]
    if not provider_products or len({p['name'] for p in provider_products})!=len(provider_products):
        raise ValueError('provider product captions missing or ambiguous')
    rarity=source.get('rarity');icons=entries[0]['rarity_icons'] if len(entries)==1 else []
    if rarity is not None and (not isinstance(rarity,str) or not re.fullmatch(r'rare_[a-z0-9_]+',rarity)):
        raise ValueError('provider rarity identifier unsupported')
    publisher_rarity=icons[0].removeprefix('ic_').removesuffix('.gif') if len(icons)==1 else None
    checks=dict(name=comparison(source.get('name'),observed['name']),coordinate=coordinates,
        illustrators=comparison(sorted(authors) if authors is not None else [],observed['illustrators'],empty=[]),
        pokedex_number=comparison(dex,observed['dex_id']),product_caption=comparison(provider_products,products),
        rarity_identifier=comparison(rarity,publisher_rarity))
    # Even matching artists/dex/rarity cannot override a foreign, repeated or
    # ambiguous coordinate. Only literal checks at the exact bound page qualify.
    qualified_fields=[k for k,v in checks.items() if identity_matches and v['status']=='literal_match']
    conflicts=list(outcome['unresolved_conflicts'])
    if not identity_matches:conflicts.append('source_or_publisher_coordinate_conflict_no_field_admission')
    conflicts.extend('field_'+k+'_'+v['status'] for k,v in checks.items() if v['status'] not in ('literal_match','both_unreported'))
    rarity_state=entries[0]['rarity_status'] if len(entries)==1 else 'ambiguous_coordinate'
    if rarity_state=='unrecognized_icon':conflicts.append('rarity_icon_semantics_unqualified')
    row=dict(schema='pokemon.anchor-qualification-fields.v1',card_id=outcome['card_id'],candidate_id=outcome['candidate_id'],
        language='ja',set_code=code,collector_number=outcome['collector_number'],prior_qualification_id=outcome['qualification_id'],
        caption_evidence_id=caption['evidence_id'],scope=SCOPE,inspected_at=inspected_at,
        status='qualified_literal_fields_anchor_still_held' if identity_matches else 'held_coordinate_conflict',
        provider_source=source_receipt,publisher_source=publisher,checks=checks,qualified_literal_fields=qualified_fields,
        publisher_rarity_interpretation=dict(status=rarity_state,normalized_value=entries[0]['rarity'] if len(entries)==1 else None,
            scope='existing_parser_icon_mapping_only_not_finish_or_price'),
        source_dependence='provider_metadata_derived_from_publisher_not_independent_physical_review',
        confidence=dict(pinned_source_bytes=1.0,literal_field_checks=1.0 if identity_matches else None,
            independent_semantic_accuracy=None,product_release_binding=None,physical_variant=None),
        unresolved_conflicts=conflicts,release_date=None,physical_distribution_region=None,test_only=False,
        **{k:False for k in product_text.FLAGS})
    row['evidence_id']='anchor-qualification-fields:'+catalog_locale.digest(row)
    return row


def build(db_path,root,cache,tcgdex_repo,ptcg_repo,inspected_at):
    core.parse_time(inspected_at);signatures={}
    def read(path):
        raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if path in signatures and signatures[path]!=sha:raise ValueError('supplement input changed')
        signatures[path]=sha;return raw
    prior_dir=root/'catalog/international-product-documents-v1'
    saved_documents=[json.loads(r) for r in read(prior_dir/'provider-documents.jsonl').splitlines()]
    saved_outcomes=[json.loads(r) for r in read(prior_dir/'anchor-outcomes.jsonl').splitlines()]
    saved_report=json.loads(read(prior_dir/'coverage-report.json'))
    for name,sha in saved_report['file_hashes'].items():
        path=prior_dir/name
        if not path.resolve().is_relative_to(prior_dir.resolve()) or hashlib.sha256(read(path)).hexdigest()!=sha:
            raise ValueError('prior compiled qualification artifact differs')
    prior_time=saved_documents[0]['inspected_at']
    fresh=documents.build(db_path,root,cache,tcgdex_repo,prior_time)
    if (fresh[0]!=saved_documents or fresh[1]!=saved_outcomes
            or fresh[2]!={k:v for k,v in saved_report.items() if k!='file_hashes'}):
        raise ValueError('prior qualification is stale or differs from current evidence')
    source_paths={code:f'data_jp/{code}/{native}.json' for code,native in documents.ANCHORS.items()}
    pins=documents.git_tree(ptcg_repo,['LICENSE',*source_paths.values()],revision=REVISION)
    if set(pins)!={'LICENSE',*source_paths.values()}:raise ValueError('fixed provider pin entries missing')
    license_raw=documents.checked_source(ptcg_repo,'LICENSE',pins['LICENSE'])
    if license_raw!=read(root/'catalog/PTCG-DATABASE-LICENSE'):raise ValueError('reviewed provider license differs')
    signatures[ptcg_repo/'LICENSE']=hashlib.sha256(license_raw).hexdigest()
    rows=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        captions=product_text.records(db);captions={c['evidence_id']:c for c in captions}
        for outcome in saved_outcomes:
            caption=captions[outcome['caption_evidence_id']];product_text.validate(db,caption)
            code=outcome['set_code'];path=source_paths[code]
            raw=documents.checked_source(ptcg_repo,path,pins[path]);sha=hashlib.sha256(raw).hexdigest()
            signatures[ptcg_repo/path]=sha;source=json.loads(raw,object_pairs_hook=unique_object)
            publisher=caption['publisher'];page=cache/('card-'+code+'.html');body=read(page)
            receipt_path=cache/('card-'+code+'.receipt.json');receipt_raw=read(receipt_path);receipt=json.loads(receipt_raw)
            if (hashlib.sha256(body).hexdigest()!=publisher['sha256'] or receipt['sha256']!=publisher['sha256']
                    or receipt['url']!=publisher['url'] or receipt.get('final_url',receipt['url'])!=publisher['url']
                    or receipt['fetched_at']!=publisher['retrieved_at']):
                raise ValueError('exact cached publisher receipt differs')
            source_receipt=dict(provider='ptcg-database',native_id=path,revision=REVISION,git_blob_id=pins[path],sha256=sha,
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',
                rights_status='existing_reviewed_MIT_metadata_no_display_grant',license_git_blob_id=pins['LICENSE'],
                license_sha256=hashlib.sha256(license_raw).hexdigest(),rights_reference=f'https://github.com/type-null/PTCG-database/blob/{REVISION}/LICENSE')
            row=record(outcome,caption,source,source_receipt,parse_page(body),extract(body,publisher['url']),inspected_at)
            row['publisher_source']={**publisher,'receipt_sha256':hashlib.sha256(receipt_raw).hexdigest()}
            row['evidence_id']='anchor-qualification-fields:'+catalog_locale.digest({k:v for k,v in row.items() if k!='evidence_id'})
            rows.append(row)
    again=documents.build(db_path,root,cache,tcgdex_repo,prior_time)
    if again!=fresh:raise ValueError('catalogue qualification changed during supplement inspection')
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=sha for p,sha in signatures.items()):
        raise ValueError('supplement inputs changed during inspection')
    report=dict(schema='pokemon.anchor-qualification-fields-build.v1',inspected_at=inspected_at,field_evidence_records=len(rows),
        qualified_literal_field_subjects=sum(r['status']=='qualified_literal_fields_anchor_still_held' for r in rows),
        field_literal_match_counts={k:sum(k in r['qualified_literal_fields'] for r in rows) for k in rows[0]['checks']},
        held_coordinate_conflicts=sum(r['status']=='held_coordinate_conflict' for r in rows),
        unresolved_rarity_semantics=sum('rarity_icon_semantics_unqualified' in r['unresolved_conflicts'] for r in rows),
        new_identities=0,new_source_mappings=0,new_release_dates=0,new_aliases=0,new_permissions=0,
        qualified_publisher_product_bindings=0,qualified_cross_provider_anchor_bindings=0,
        before_inventory=fresh[2]['catalogue_inventory'],after_inventory=fresh[2]['catalogue_inventory'],
        prior_snapshot=fresh[2]['snapshot'],prior_qualification_artifacts_preserved=True,database_bytes_unchanged=True,
        original_source_inputs=65,manifest_inputs=68,held_candidates=65,quarantine_entries=65,scope=SCOPE)
    return rows,report,license_raw


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('db','cache','tcgdex-repo','ptcg-repo','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--inspected-at',required=True);args=parser.parse_args()
    if args.output_dir.exists():raise FileExistsError('supplement output already exists')
    rows,report,license_raw=build(args.db,Path.cwd(),args.cache,args.tcgdex_repo,args.ptcg_repo,args.inspected_at)
    args.output_dir.mkdir(parents=True)
    evidence=args.output_dir/'evidence.jsonl';evidence.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    (args.output_dir/'PTCG-LICENSE').write_bytes(license_raw)
    report['file_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (evidence,args.output_dir/'PTCG-LICENSE')}
    (args.output_dir/'coverage-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('field_evidence_records','qualified_literal_field_subjects','new_identities','new_release_dates')}))


if __name__=='__main__':main()
