"""Compile one frozen, independently reviewed offline full-name scale batch.

Existing IDs survive. Exact translation retrieval bindings do not approve
printings, counterparts, artwork, display, offers or transactions.
"""
import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from pokemon_index import catalog_locale, core, tcgdex_source, variant_dimension_hold
from pokemon_index import catalog_locale_indexes as lookup_indexes
from pokemon_index import collector_runtime
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_coverage as names
from scripts import build_pokemon_name_followup as previous
from scripts import build_pokemon_name_johto_pilot as johto
from scripts import build_pokemon_name_eight_followup as eight
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts as resolution_facts
from scripts.audit_variant_dimension_holds import installed as installed_hold_guards
from scripts.build_international_coverage_expansion import ALIAS_FIELDS, RIGHTS, translated_query
from scripts.pokemon_release_witness import release_path, inspect_release
from scripts.qualify_international_product_documents import REVISION, checked_source, git_tree, header_fields

PACKET_SHA = '71e793ddf1f62fc1d6b0ddae6b16070e259415c9bfda0303a7dacb68882515ad'
REVIEW_SHA = '8f9c21ccc027f3d9921cce3ce8dc2e773abd73279b5dacf31fb6f8deb857f574'
BEFORE_SHA = '4ea456e8163d7c8b0d562daacdf1f160ac28c469ede2fabac1da2fda578d0790'
BATCH_COUNTS = dict(ja=2952,en=1000,total=3952,newpairs=400,existing_ja=244,new_ja=2708,existing_en=123,new_en=877)
CODE_INPUTS = dict(eight.CODE_INPUTS)
PENDING_SEMANTIC_REVIEW = johto.PENDING_SEMANTIC_REVIEW
INDEXES = {name:(table,lookup_indexes.SQL[name]) for name,table in lookup_indexes.SPECIFICATIONS}


def signature(raw):return hashlib.sha256(raw).hexdigest()
def require(value, reason):
    if not value:raise ValueError(reason)
def false_claims(value):
    require(all(value.get(k) is False for k in catalog_locale.FALSE_CLAIMS),'offline metadata cannot grant printing, image, display or trading approval')
def claims():return {k:False for k in catalog_locale.FALSE_CLAIMS}
def triple(pair):return (pair['dex_id'],pair['name_ja'],pair['name_en'])
def coordinate(card):return tuple(card[k] for k in ('language','set_code','collector_number'))


def compiler_inputs():
    root=Path(__file__).resolve().parents[1]
    modules=(sys.modules[__name__],core,catalog_locale,resolver,tcgdex_source,variant_dimension_hold,lookup_indexes,previous,johto,eight,history)
    paths={root/p for p in CODE_INPUTS.values()}|{Path(m.__file__).resolve() for m in modules}
    paths.update((root/'pokemon_index/schema.sql',root/'pokemon_index/collector_runtime.py',root/'scripts/audit_variant_dimension_holds.py',root/'scripts/audit_international_coverage.py',root/'scripts/build_catalog_snapshot.py'))
    return {p:p.read_bytes() for p in paths}


def source_fields(card):
    found=re.fullmatch(r'tcgdex:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})',card['provenance'])
    require(found and found[1]==REVISION and card['rights_reference']==RIGHTS,'existing reviewed physical TCGdex pin/rights required')
    path=PurePosixPath(found[2])
    require(not path.is_absolute() and '..' not in path.parts and path.suffix=='.ts'
        and path.parts[0] in ('data','data-asia') and not any(p.casefold() in ('pocket','digital') for p in path.parts),
        'physical source path required; Pocket/digital excluded')
    return str(path),found[3]


def tree_chunks(repo,paths):
    entries={};paths=sorted(paths)
    for start in range(0,len(paths),512):
        part=git_tree(repo,paths[start:start+512],revision=REVISION)
        require(not entries.keys()&part.keys(),'duplicate pinned source entry across chunks');entries.update(part)
    return entries


def checked_packet(packet_raw,review_raw):
    require(signature(packet_raw)==PACKET_SHA and signature(review_raw)==REVIEW_SHA,'frozen scale packet or independent review differs')
    packet=json.loads(packet_raw);review=json.loads(review_raw)
    require(packet.get('schema')=='pokemon.stage19-scale-source-qualification.v1' and packet.get('applied') is False
        and packet.get('input_database_sha256')==BEFORE_SHA and packet.get('source_pin')==REVISION
        and packet.get('rights_reference')==RIGHTS,'scale source/database/rights scope differs');false_claims(packet)
    counts=packet['selection_counts']
    require(BATCH_COUNTS is not None and counts==BATCH_COUNTS and all(type(counts.get(k)) is int for k in ('ja','en','total','newpairs'))
        and 1<=counts['ja']<=5000 and 1<=counts['en']<=3000 and 1000<=counts['total']<=8000
        and counts['ja']+counts['en']==counts['total'] and 1<=counts['newpairs']<=400,'frozen thousand-level selection counts differ')
    proposals=packet['new_name_proposals'];existing=packet['existing_review_witnesses'];new=packet['new_name_witnesses'];english=packet['english_witnesses']
    selected=existing+new+english;ids=[w['identity']['card_id'] for w in selected]
    require(len(ids)==len(set(ids))==counts['total'] and sorted(ids)==packet['selected_card_ids']
        and len(existing)+len(new)==counts['ja'] and len(english)==counts['en'] and len(proposals)==counts['newpairs']
        and all(w['identity']['language']=='ja' for w in existing+new) and all(w['identity']['language']=='en' for w in english),
        'exact distinct selected IDs or languages differ')
    require(counts.get('existing_ja')==len(existing) and counts.get('new_ja')==len(new)
        and counts.get('existing_en')==sum(bool(w.get('name_alias')) for w in english)
        and counts.get('new_en')==sum(not w.get('name_alias') for w in english),'existing/new witness lane counts differ')
    require(all(core.card_id(w['identity']['language'],w['identity']['set_code'],w['identity']['collector_number'],w['identity']['variant'])==w['identity']['card_id'] for w in selected),
        'selected ID and language/release/number/variant tuple differ')
    pairs=[triple(p) for p in proposals]
    require(len(set(pairs))==len(proposals) and len({p['name_ja'] for p in proposals})==len(proposals)
        and len({p['name_en'] for p in proposals})==len(proposals)
        and all(type(p['dex_id']) is int and 1<=p['dex_id']<=1025 and all(isinstance(p[k],str) and p[k].strip()==p[k] and p[k] for k in ('name_ja','name_en')) for p in proposals),
        'new proposal exact full-name/singleton-Dex whitelist differs')
    by_id={w['identity']['card_id']:w for w in selected};potential=[]
    for pair in proposals:
        false_claims(pair)
        require(pair.get('unresolved_conflicts') in ([],[PENDING_SEMANTIC_REVIEW]) and pair.get('unresolved_source_conflicts',[])==[]
            and pair['ja']['identity']['language']=='ja' and pair['en']['identity']['language']=='en','conflicted new full-name proposal')
        require(pair['potential_ja_bindings'] and pair['ja'] in pair['potential_ja_bindings']
            and all(by_id.get(w['identity']['card_id'])==w for w in [*pair['potential_ja_bindings'],pair['en']]),
            'proposal and selected full witnesses differ')
        require(all(w['identity']['name']==pair['name_ja'] and w['dex_id']==pair['dex_id'] for w in pair['potential_ja_bindings'])
            and pair['en']['identity']['name']==pair['name_en'] and pair['en']['dex_id']==pair['dex_id'],'proposal native names/Dex differ')
        potential.extend(w['identity']['card_id'] for w in pair['potential_ja_bindings'])
    require(len(potential)==len(set(potential)) and set(potential)=={w['identity']['card_id'] for w in new},'new Japanese witness union differs')
    require(sorted(packet.get('five_image_targets_excluded',[]))==sorted(previous.EXPANDED_IMAGE_TARGETS),'five frozen priority image targets differ')
    excluded={coordinate(g) for g in previous.expanded_excluded_groups()}
    require(all(coordinate(w['identity']) not in excluded and w['identity']['set_code']!='SV4A' for w in selected),
        'priority-image coordinate or raw SV4A header conflict selected')
    require(review.get('schema') in ('pokemon.independent-name-review.v1','pokemon.independent-scale-name-review.v1')
        and review.get('reviewer')=='GPT-6.1 Sol high' and review.get('proposal_sha256')==PACKET_SHA
        and review.get('decision')=='approve_all_exact_pairs' and type(review.get('approved_pairs')) is int
        and review['approved_pairs']==len(proposals) and review.get('rejected_pairs')==[] and review.get('uncertain_pairs')==[]
        and review.get('approved_into_catalog') is False and review.get('sources_fetched') is False,'selected exact independent semantic approval absent or changed')
    approved=review.get('approved_exact_pairs',[])
    require(len(approved)==len(proposals) and len({triple(p) for p in approved})==len(proposals) and {triple(p) for p in approved}==set(pairs),
        'independent approved full-name pair whitelist differs')
    require(isinstance(review.get('review_completed_at'),str) and review.get('review_completed_at_status')=='attested_by_UTC_clock_after_independent_review',
        'actual independently attested semantic review time required');core.parse_time(review['review_completed_at'])
    require(review.get('historical_retrieved_at') is None and review.get('historical_retrieval_status') in ('unknown','historical_snapshot_time_not_recorded'),
        'semantic review cannot infer source acquisition time')
    for w in selected:
        false_claims(w);require(type(w.get('dex_id')) is int and w.get('unresolved_conflicts') in ([],[PENDING_SEMANTIC_REVIEW]) and w.get('unresolved_source_conflicts',[])==[],
            'conflicted selected witness')
    return packet,proposals,existing,new,english


def current_concepts(db,packet):
    audit=[];events={};aliases={}
    for c in db.execute('''WITH latest AS(SELECT *,row_number() OVER(PARTITION BY concept_id ORDER BY revision DESC) rank
        FROM bilingual_concept_revision) SELECT * FROM latest WHERE rank=1 AND status='approved' AND category='Pokemon' ORDER BY concept_id'''):
        alias={k:c[k] for k in ALIAS_FIELDS};catalog_locale.approved_alias(db,alias)
        stored=db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(c['review_event_id'],)).fetchone();require(stored,'retained exact-name event missing')
        event=json.loads(stored[0]);frozen=event['proposal']['source_snapshot']['frozen'];dex=frozen.get('dex_id')
        require(names.spaced_digest({k:v for k,v in event.items() if k!='event_id'})==c['review_event_id'] and event['event_id']==c['review_event_id']
            and event['review'].get('decision')=='approve' and event['review'].get('requires_card_binding') is True
            and frozen.get('category')=='Pokemon' and all(frozen.get(k)==alias[k] for k in ('name_ja','name_en'))
            and type(dex) is int and (1<=dex<=151 or (dex,c['name_ja'],c['name_en']) in johto.JOHTO_PAIRS|eight.PAIRS),
            'retained current exact full-name review scope changed');false_claims(event['review'])
        item=dict(concept_id=c['concept_id'],revision=c['revision'],name_ja=c['name_ja'],name_en=c['name_en'],
            review_event_id=c['review_event_id'],dex_id=dex,requires_exact_card_binding=True)
        audit.append(item);events[c['concept_id']]=event;aliases[c['concept_id']]=(alias,dex)
    require(len(audit)==packet.get('current_approved_pokemon_full_name_concepts')==196 and len(packet['current_concept_audit'])==196,'current196 full-name inventory differs')
    for actual,declared in zip(audit,packet['current_concept_audit']):
        require(all(declared.get(k)==v for k,v in actual.items()),'retained exact concept audit differs')
        if 'category' in declared:require(declared['category']=='Pokemon','retained audit category differs')
        if 'review_record_sha256' in declared:
            require(declared['review_record_sha256']==signature(catalog_locale.encoded(events[actual['concept_id']]).encode()),'retained event record hash differs')
    return audit,events,aliases


def literal_metadata(raw,dex,name,language,*,strict=True):
    text=raw.decode('utf-8');fields=header_fields(text,declaration_name='card',declaration_type='Card')
    require(fields.get('category') and ast.literal_eval(fields['category'])=='Pokemon','literal Pokemon category required')
    require(re.fullmatch(r'\[\s*\d+\s*,?\s*\]',fields.get('dexId','')) is not None,'exact singleton Dex absent or ambiguous')
    ids=ast.literal_eval(fields['dexId']);require(ids==[dex] and type(ids[0]) is int,'source singleton Dex differs from exact reviewed full name')
    localized=names.names(fields.get('name'));require(localized.get(language)==name,'literal native full name differs')
    if strict:
        variants=tcgdex_source._strict_variant_fields(text);require(variants,'nonempty literal variants absent; default standard remains held')
        require(all(not set(v)-{'type','foil','subtype','stamp','size','thirdParty'} for v in variants),'unknown source variant property requires identity review')
        require(not tcgdex_source.variant_dimension_losses(text),'source dimensions omitted by legacy identity')
    return dict(category='Pokemon',dex_id=dex,names=localized)


def inspect_witness(db,witness,raws,blobs,scope,cache=None):
    cache={} if cache is None else cache;false_claims(witness);card=witness['identity'];cid=card['card_id'];lang=card['language']
    require(lang in ('ja','en') and catalog_locale.snapshot(db,cid)==card,'frozen printing identity/language changed')
    require(card['name']==scope['name_'+lang] and witness['dex_id']==scope['dex_id'],'selected exact full-name/Dex scope differs')
    require(all(witness.get(k) is True for k in ('literal_variant_structure_verified','literal_nonempty_variants','source_tuple_reconstructed_eligible'))
        and witness.get('variant_dimension_losses')==[],'strict literal variant/source-eligibility assertions required')
    require(db.execute('SELECT match_eligible FROM card WHERE card_id=?',(cid,)).fetchone()[0]==1
        and not card['variant'].startswith('unverified') and not variant_dimension_hold.held(db,cid),'ineligible, unresolved or held printing')
    path,digest=source_fields(card);src=witness['source'];raw=raws[path]
    require(src.get('provider')=='tcgdex' and src.get('revision')==REVISION and src.get('native_id')==path
        and src.get('git_blob')==blobs[path] and src.get('sha256')==digest==signature(raw) and src.get('bytes')==len(raw)
        and src.get('rights_reference')==RIGHTS and src.get('rights_status')=='metadata_internal_reviewed'
        and src.get('license_sha256')==signature(raws['LICENSE']) and src.get('retrieved_at') is None
        and src.get('retrieval_status')=='historical_snapshot_time_not_recorded' and src.get('physical_distribution_region') is None,
        'frozen source pin/hash/licence/retrieval/rights differs')
    key=('metadata',path,scope['dex_id'],card['name'],lang)
    if key not in cache:cache[key]=literal_metadata(raw,scope['dex_id'],card['name'],lang)
    metadata=cache[key];require(metadata['names']==witness['localized_names'],'literal localized names differ')
    cl=db.execute('SELECT * FROM card_classification WHERE card_id=?',(cid,)).fetchone()
    facets=list(db.execute("SELECT * FROM card_facet WHERE card_id=? AND facet_type='dex_id' ORDER BY value",(cid,)))
    require(cl and cl['category']=='Pokemon' and cl['provenance']==card['provenance'] and cl['rights_reference']==RIGHTS
        and len(facets)==1 and facets[0]['value']==str(scope['dex_id']) and facets[0]['provenance']==card['provenance']
        and facets[0]['rights_reference']==RIGHTS,'current classification or singleton Dex facet source differs')
    release_row=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',(lang,card['set_code'])).fetchone()
    release=dict(release_row) if release_row else None;product=witness['release_source'];false_claims(product)
    require(release and release==witness['release_snapshot']==product['snapshot'],'current localized release differs')
    rp=release_path(release,REVISION,RIGHTS);release_key=('release',lang,card['set_code'])
    if release_key not in cache:cache[release_key]=inspect_release(release,raws[rp])
    require(product.get('native_id')==rp and product.get('revision')==REVISION and product.get('git_blob')==blobs[rp]
        and product.get('sha256')==signature(raws[rp]) and product.get('bytes')==len(raws[rp]) and product.get('facts')==cache[release_key]
        and product.get('rights_reference')==RIGHTS and product.get('rights_status')=='metadata_internal_reviewed'
        and product.get('license_sha256')==signature(raws['LICENSE']) and product.get('retrieved_at') is None
        and product.get('retrieval_status')=='historical_snapshot_time_not_recorded' and product.get('physical_distribution_region') is None,
        'pinned localized release header/date/count/rights differs')
    parse_key=('printing',path,lang,card['set_code'],release['official_card_count'])
    if parse_key not in cache:
        cache[parse_key]=tcgdex_source.parse_card_source(raw.decode(),set_id=card['set_code'],official_count=release['official_card_count'],
            path=path,revision=REVISION,language=lang,source_directory=PurePosixPath(path).parent.name,strict_variant_dimensions=True)
    keys=('language','set_code','collector_number','variant','name','provenance','rights_reference')
    matches=[r for r in cache[parse_key] if all(r[k]==card[k] for k in keys)]
    require(len(matches)==1 and matches[0]['match_eligible'] is True,'exact eligible literal printing tuple differs')
    rarity=matches[0]['rarity'];require((rarity==card['rarity'] or rarity is None and card['rarity']=='None')
        and witness.get('source_rarity') in (rarity,card['rarity']),'source rarity differs from preserved identity')
    return metadata,release


def inspect_existing_semantics(db,alias,dex,event,raws,blobs):
    frozen=event['proposal']['source_snapshot']['frozen'];witnesses=event['proposal']['source_snapshot'].get('witnesses',{})
    require(set(witnesses)=={'ja','en'} and frozen['dex_id']==dex,'retained semantic witness pair/Dex absent')
    for lang,witness in witnesses.items():
        card=witness['identity'];require(card['language']==lang and card['name']==alias['name_'+lang]
            and catalog_locale.snapshot(db,card['card_id'])==card,'retained semantic identity changed')
        path,digest=source_fields(card);require(path in raws,'retained semantic source unavailable')
        literal_metadata(raws[path],dex,card['name'],lang,strict=False)
        require(signature(raws[path])==digest==witness.get('sha256') and witness.get('native_id')==path
            and witness.get('revision')==REVISION and witness.get('git_blob')==blobs[path] and witness.get('license_sha256')==signature(raws['LICENSE']),
            'retained semantic name source pin/hash differs')
        release=dict(db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',(lang,card['set_code'])).fetchone())
        if 'release_snapshot' in witness:require(witness['release_snapshot']==release,'retained semantic localized release changed')
        rp=release_path(release,REVISION,RIGHTS);require(rp in raws,'retained semantic release source unavailable');inspect_release(release,raws[rp])


def review_bundle(db,proposals,raws,blobs,licence_sha,review_sha,inspected_at,semantic_reviewed_at,cache=None):
    events=[];concepts=[];cache={} if cache is None else cache
    for pair in proposals:
        witnesses={};urls={}
        for lang in ('ja','en'):
            w=pair[lang];meta,release=inspect_witness(db,w,raws,blobs,pair,cache);card=w['identity'];path,digest=source_fields(card)
            urls[lang]=f'https://github.com/tcgdex/cards-database/blob/{REVISION}/'+quote(path,safe='/')
            witnesses[lang]=dict(identity=card,dex_id=meta['dex_id'],category='Pokemon',native_id=path,revision=REVISION,
                git_blob=blobs[path],sha256=digest,license_sha256=licence_sha,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed',
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                physical_distribution_region=None,release_snapshot=release)
        frozen=dict(category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],dex_id=pair['dex_id'],source_ja=urls['ja'],
            source_en=urls['en'],rights_reference=RIGHTS,ja_card_id=pair['ja']['identity']['card_id'],en_card_id=pair['en']['identity']['card_id'],retrieval_only=True)
        frozen['proposal_id']='pokemon-name-proposal:'+catalog_locale.digest(frozen)
        snapshot=dict(frozen=frozen,ja_provenance=pair['ja']['identity']['provenance'],en_provenance=pair['en']['identity']['provenance'],
            witnesses=witnesses,scope='exact independently reviewed full-name metadata translation; no printing counterpart',**claims())
        proposal=dict(**frozen,ja_provenance=snapshot['ja_provenance'],en_provenance=snapshot['en_provenance'],source_snapshot=snapshot,
            source_snapshot_sha256=names.spaced_digest(snapshot))
        review=dict(decision='approve',review_revision=1,reviewer='ai-independent:gpt-6.1-sol-high',reviewed_at=inspected_at,
            ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True,semantic_review_sha256=review_sha,
            semantic_reviewed_at=semantic_reviewed_at,semantic_review_time_status='recorded_in_independent_approval_packet',
            identity_attestation_scope='existing pinned metadata tuples only; no physical-copy verification',
            evidence_note='The frozen GPT-6.1 Sol high packet approves this exact full-name pair and singleton Dex. '
                'reviewed_at records the compiler metadata recheck; semantic_reviewed_at records the independent review completion. '
                'No form inheritance, artwork, counterpart, physical, display or trading approval.',**claims())
        event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review);event['event_id']=names.spaced_digest(event);events.append(event)
        cid='pokemon-name:'+catalog_locale.digest(dict(ja=pair['name_ja'],en=pair['name_en'],dex_id=pair['dex_id']))
        require(not db.execute("SELECT 1 FROM bilingual_concept_revision WHERE concept_id=? OR category='Pokemon' AND (name_ja=? OR name_en=?)",
            (cid,pair['name_ja'],pair['name_en'])).fetchone(),'existing or colliding concept needs explicit revision review')
        concepts.append(dict(concept_id=cid,revision=1,category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],source_ja=urls['ja'],source_en=urls['en'],
            rights_reference=RIGHTS,reviewer=review['reviewer'],reviewed_at=inspected_at,status='approved',review_event_id=event['event_id']))
    return dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts)


def complete_groups(db,japanese,bound):
    selected={w['identity']['card_id'] for w in japanese};require(not selected&bound,'selected printing already bound')
    grouped=defaultdict(list)
    for row in db.execute("SELECT c.card_id,c.language,c.set_code,c.collector_number,c.name,cl.category FROM card c LEFT JOIN card_classification cl USING(card_id) WHERE c.language='ja' AND c.match_eligible=1 AND c.variant NOT LIKE 'unverified%'"):
        grouped[coordinate(row)].append(row)
    for w in japanese:
        c=w['identity'];siblings=grouped[coordinate(c)]
        require(siblings and all(r['name']==c['name'] and r['category']=='Pokemon' and r['card_id'] in selected|bound for r in siblings),
            'incomplete or ambiguous whole eligible Japanese coordinate group')


def install_indexes(db):
    lookup_indexes.import_manifest_evidence(db,[lookup_indexes.RECORD])


def schema_preserved(before,after):
    old={(r[0],r[1]):tuple(r) for r in before.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')}
    actual={(r[0],r[1]):tuple(r) for r in after.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')}
    expected=dict(old)
    for name,(table,sql) in INDEXES.items():
        row=('index',name,table,sql);require(('index',name) not in old or old[('index',name)]==row,'original index drift')
        expected[('index',name)]=row
    require(actual==expected,'SQL schema changed beyond the exact two nonunique lookup indexes')
    return True


@collector_runtime.catalog_request
def search_release(db,rows):
    cache={}
    for row in rows:
        card=row['identity'];alias=row['name_aliases'][0];name=alias['name_en' if card['language']=='ja' else 'name_ja']
        key=(name,card['language'],card['set_code'],card['variant'])
        if key not in cache:
            offset=0;ids=set();total=None
            while total is None or offset<total:
                result=core.catalog_search_internal(db,name,language=card['language'],set_code=card['set_code'],variant=card['variant'],limit=100,offset=offset)
                require(total is None or total==result['total'],'search population changed during grouped verification')
                total=result['total'];ids.update(c['card_id'] for c in result['cards']);offset+=100
            cache[key]=dict(card_ids=ids,total=total)
    return cache


def grouped_search(db,rows):
    require(not db.in_transaction,'native search verification requires a committed immutable snapshot')
    releases=defaultdict(list)
    for row in rows:releases[(row['identity']['language'],row['identity']['set_code'])].append(row)
    cache={}
    for selected in releases.values():cache.update(search_release(db,selected))
    return cache


def search_key(row):
    c=row['identity'];a=row['name_aliases'][0]
    return (a['name_en' if c['language']=='ja' else 'name_ja'],c['language'],c['set_code'],c['variant'])


def compile(db_path,repo,root,packet_path,semantic_review_path,inspected_at):
    core.parse_time(inspected_at);packet_raw=packet_path.read_bytes();review_raw=semantic_review_path.read_bytes()
    packet,proposals,existing,new,english=checked_packet(packet_raw,review_raw);counts=packet['selection_counts'];selected=existing+new+english
    semantic_reviewed_at=json.loads(review_raw)['review_completed_at']
    require(core.parse_time(semantic_reviewed_at)<=core.parse_time(inspected_at),'compiler inspection predates actual semantic review')
    require(signature(db_path.read_bytes())==BEFORE_SHA,'immutable input database differs')
    code_root=Path(__file__).resolve().parents[1];compilation_inputs=compiler_inputs();inputs=dict(compilation_inputs)
    require(all(signature(inputs[code_root/p])==packet['parsing_source_sha256'][k] for k,p in CODE_INPUTS.items()),'qualification parser checkpoint differs')
    licence_path=root/'catalog/TCGDEX-LICENSE';licence=licence_path.read_bytes();inputs[licence_path]=licence
    require(signature(licence)==packet['license_sha256'],'reviewed metadata licence differs')
    census_inputs={}
    for name,digest in packet.get('qualification_census_sha256',{}).items():
        require(isinstance(name,str) and PurePosixPath(name).name==name and name.endswith('.json'),'census reference must be a local report basename')
        path=packet_path.parent/name;raw=path.read_bytes();require(signature(raw)==digest,'frozen qualification census changed')
        inputs[path]=raw;census_inputs[name]=digest
    inventory=packet['source_inventory'];require(1<=len(inventory)<=10000 and 'LICENSE' in inventory,'bounded pinned source inventory required')
    for p in inventory:
        path=PurePosixPath(p);require(not path.is_absolute() and '..' not in path.parts and (p=='LICENSE' or path.suffix=='.ts' and path.parts[0] in ('data','data-asia'))
            and not any(v.casefold() in ('pocket','digital') for v in path.parts),'only existing pinned physical metadata/licence paths allowed')
    blobs=tree_chunks(repo,inventory);require(set(blobs)==set(inventory),'pinned inventory entries missing')
    raws={p:checked_source(repo,p,b) for p,b in blobs.items()}
    for p,raw in raws.items():
        require(all(inventory[p].get(k)==v for k,v in dict(provider='tcgdex',native_id=p,revision=REVISION,git_blob=blobs[p],sha256=signature(raw),bytes=len(raw),
            rights_reference=RIGHTS,rights_status='metadata_internal_reviewed',license_sha256=signature(licence),retrieved_at=None,
            retrieval_status='historical_snapshot_time_not_recorded',physical_distribution_region=None,available=True).items()),'source inventory bytes/pin/licence/rights changed')
    require(raws['LICENSE']==licence,'cached original source licence differs')
    pair_by_name={(lang,p['name_'+lang]):p for p in proposals for lang in ('ja','en')};projection_cache={}
    with closing(core.connect(db_path,readonly=True)) as original:
        original.execute('BEGIN');audit,events,current_aliases=current_concepts(original,packet);bound=previous.bound_ids(original)
        require(len(bound)==packet.get('current_localized_bindings')==2412 and catalog_locale.digest(sorted(bound))==packet['current_bound_card_ids_sha256']
            and original.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0]==2412
            and original.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0]==packet.get('current_source_mappings')==2412,'current binding inventory differs')
        require(not {w['identity']['card_id'] for w in selected}&bound,'selected printing already bound');complete_groups(original,existing+new,bound)
        holds=variant_dimension_hold.rows_for(original);require(len(holds)==packet.get('identity_holds_preserved')==44,'44 historical hold inventory differs');installed_hold_guards(original,holds)
        for hold in holds:
            variant_dimension_hold.validate(original,hold)
            require(tuple(original.execute('SELECT match_eligible,display_allowed FROM card WHERE card_id=?',(hold['identity']['card_id'],)).fetchone())==(0,0),'identity hold flags changed')
        used_aliases={};scopes={}
        for witness in selected:
            card=witness['identity'];alias=witness.get('name_alias')
            if alias:
                require(alias.get('concept_id') in current_aliases,'selected retained alias not current')
                checked,dex=current_aliases[alias['concept_id']];require(alias==checked and card['name']==alias['name_'+card['language']] and witness['dex_id']==dex,'selected retained alias full scope differs')
                scope=dict(**alias,dex_id=dex);used_aliases[alias['concept_id']]=(alias,dex)
            else:
                scope=pair_by_name.get((card['language'],card['name']));require(scope is not None,'selected full name has no exact current/new review')
            require((witness in existing)==bool(alias) if card['language']=='ja' else True,'Japanese existing/new review lane differs')
            inspect_witness(original,witness,raws,blobs,scope,projection_cache);scopes[card['card_id']]=scope
        for concept_id,(alias,dex) in used_aliases.items():inspect_existing_semantics(original,alias,dex,events[concept_id],raws,blobs)
        if 'existing_semantic_reviews' in packet:
            refs=packet['existing_semantic_reviews'];require(len(refs)==len(used_aliases),'used existing semantic review reference inventory differs')
            require(len({r['name_alias']['concept_id'] for r in refs})==len(refs),'duplicate retained semantic review reference')
            for ref in refs:
                alias=ref['name_alias'];require(alias['concept_id'] in used_aliases and alias==used_aliases[alias['concept_id']][0],'retained semantic alias reference differs')
                event=events[alias['concept_id']];snapshot=event['proposal']['source_snapshot']
                stored=original.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(alias['review_event_id'],)).fetchone()[0]
                require(ref['event_record_sha256']==signature(stored.encode())
                    and ref['source_snapshot_sha256']==event['proposal']['source_snapshot_sha256']==names.spaced_digest(snapshot),'retained event/source snapshot reference hash differs')
        bundle=review_bundle(original,proposals,raws,blobs,signature(licence),signature(review_raw),inspected_at,semantic_reviewed_at,projection_cache)
        new_aliases={(lang,c['name_'+lang]):{k:c[k] for k in ALIAS_FIELDS} for c in bundle['concept_revisions'] for lang in ('ja','en')}
        rows=[]
        for witness in selected:
            card=witness['identity'];alias=witness.get('name_alias') or new_aliases[(card['language'],card['name'])];path,digest=source_fields(card)
            row=dict(schema='pokemon.catalog-locale.v1',identity=card,source=dict(provider='tcgdex',language=card['language'],region='ZZ',release_id='tcgdex-product:'+card['set_code'],
                native_id=path,source_variant=card['variant'],revision=REVISION,git_blob=blobs[path],sha256=digest,license_git_blob=blobs['LICENSE'],license_sha256=signature(licence),
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,physical_distribution_region=None,
                rights_reference=RIGHTS,rights_status='metadata_internal_reviewed'),release_snapshot=witness['release_snapshot'],name_aliases=[alias],
                character_scope=dict(dex_id=witness['dex_id'],full_name=card['name'],category='Pokemon',form_inheritance_allowed=False),confidence=1.0,
                confidence_scope='checked pinned source tuples and exact independently reviewed full-name translation only',unresolved_conflicts=[],test_only=False,**claims())
            row['evidence_id']='catalog-locale:'+catalog_locale.digest(row);rows.append(row)
        original.commit();before_search=grouped_search(original,rows)
        with tempfile.TemporaryDirectory() as directory:
            scratch=Path(directory)/'scale.sqlite3';shutil.copyfile(db_path,scratch)
            with closing(core.connect(scratch)) as db:
                install_indexes(db);imported=core.import_concept_review_bundle(db,bundle)
                require(imported==dict(review_events=len(proposals),concept_revisions=len(proposals)),'exact review append differs')
                gaps=[]
                for row in rows:
                    cid=row['identity']['card_id'];alias=row['name_aliases'][0];before=before_search[search_key(row)]
                    require(cid not in before['card_ids'],'selected translated target already retrievable')
                    catalog_locale.validate(db,row)
                    require(not catalog_locale.has_current_alias(db,cid,[alias]),'concept-only record binding unexpectedly exists')
                    result=resolver.resolve_question(db,resolution_facts(row,search_key(row)[0]))
                    require(result['resolution']['status']=='not_attempted' and result['reason']=='reviewed_name_record_binding_required','concept approval widened an unbound printing')
                    gaps.append(dict(card_id=cid,query=translated_query(row['identity'],alias),grouped_query=search_key(row)[0],
                        before_contains_target=False,before_total=before['total']))
                locales=catalog_locale.import_evidence(db,rows);require(locales==dict(inserted=len(rows),unchanged=0,quarantined=0),'exact locale append differs')
                after_search=grouped_search(db,rows)
                for row,gap in zip(rows,gaps):
                    cid=row['identity']['card_id'];found=after_search[search_key(row)]
                    require(cid in found['card_ids'] and catalog_locale.snapshot(db,cid)==row['identity'] and catalog_locale.has_current_alias(db,cid,row['name_aliases']),
                        'bound translated retrieval failed or existing ID changed')
                    result=resolver.resolve_question(db,resolution_facts(row,search_key(row)[0]))
                    require(result['resolution']['status'] in ('unique','multiple_candidates') and cid in result['resolution']['candidate_ids'],'bound translated resolution failed')
                    gap.update(after_contains_target=True,after_total=found['total'],resolver_after=result['resolution'])
                additions=dict(bilingual_concept_revision=len(proposals),concept_review_event=len(proposals),catalog_locale_evidence=len(rows),catalog_source_mapping=len(rows));preserved={}
                require(history.tables(original)==history.tables(db),'historical table inventory changed')
                for table in history.tables(original):
                    old,after=history.records(original,table),history.records(db,table)
                    preserved[table]=(after[:len(old)]==old and len(after)==len(old)+additions[table]) if table in additions else after==old
                require(all(preserved.values()),'historical rows changed outside four exact append tables');schema_preserved(original,db);installed_hold_guards(db,holds)
                repeat_bundle=core.import_concept_review_bundle(db,bundle);repeat_locales=catalog_locale.import_evidence(db,rows)
                require(repeat_bundle==dict(review_events=0,concept_revisions=0) and repeat_locales==dict(inserted=0,unchanged=len(rows),quarantined=0),'idempotent reimport changed evidence')
                require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall(),'scratch integrity or references failed')
    require(tree_chunks(repo,inventory)==blobs and all(checked_source(repo,p,blobs[p])==raw for p,raw in raws.items()),'source tree or bytes drifted during compile')
    require(all(p.read_bytes()==raw for p,raw in inputs.items()) and packet_path.read_bytes()==packet_raw and semantic_review_path.read_bytes()==review_raw
        and signature(db_path.read_bytes())==BEFORE_SHA,'compiler/parser/licence/packet/review/database drifted during compile')
    selection=dict(schema='pokemon.full-name-scale-selection.v1',inspected_at=inspected_at,input_database_sha256=BEFORE_SHA,proposal_sha256=PACKET_SHA,
        semantic_review_sha256=REVIEW_SHA,semantic_reviewed_at=semantic_reviewed_at,semantic_review_time_status='recorded_in_independent_approval_packet',source_revision=REVISION,
        japanese=counts['ja'],english=counts['en'],exact_name_pairs=len(proposals),japanese_existing_review_records=len(existing),japanese_new_name_records=len(new),
        japanese_coordinate_groups=len({coordinate(w['identity']) for w in existing+new}),by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
        source_inventory=inventory,qualification_census_sha256=census_inputs,
        compilation_source_sha256={str(p.relative_to(code_root)):signature(raw) for p,raw in compilation_inputs.items()},
        concept_reviews=imported,locale_import=locales,idempotent_reimport=dict(concepts=repeat_bundle,locales=repeat_locales),
        historical_tables_preserved=preserved,historical_schema_preserved_except_two_lookup_indexes=True,lookup_index_names=sorted(INDEXES),
        concepts_without_record_bindings_abstain=len(rows),gaps=gaps,strict_variant_dimensions=True,preserved_identity_holds=44,
        excluded_image_target_ids=sorted(previous.EXPANDED_IMAGE_TARGETS),excluded_image_target_groups=previous.expanded_excluded_groups(),
        new_card_identities=0,new_counterpart_relationships=0,new_source_images=0,new_prices=0,physical_distribution_region=None,
        demand=packet['demand'],authorized_supply=packet['authorized_supply'],scope='Exact full-name retrieval only; distinct printings/variants remain separate identities and prices.',**claims())
    return bundle,rows,selection,licence,packet_raw,review_raw


publish_exclusive=eight.publish_exclusive


def build(db_path,repo,root,packet_path,semantic_review_path,output,inspected_at):
    if output.exists():raise FileExistsError('scale artifact destination already exists')
    bundle,rows,selection,licence,packet_raw,review_raw=compile(db_path,repo,root,packet_path,semantic_review_path,inspected_at)
    output.parent.mkdir(parents=True,exist_ok=True);temporary=Path(tempfile.mkdtemp(prefix='.pokemon-name-scale-',dir=output.parent))
    try:
        for name,value in [('concept-review-bundle.json',bundle),('selection.json',selection)]:
            (temporary/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        (temporary/'locales.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
        (temporary/'basis-qualification.json').write_bytes(packet_raw);(temporary/'semantic-review.json').write_bytes(review_raw);(temporary/'TCGDEX-LICENSE').write_bytes(licence)
        (temporary/'lookup-indexes.jsonl').write_text(json.dumps(lookup_indexes.RECORD,sort_keys=True)+'\n')
        require(packet_path.read_bytes()==packet_raw and semantic_review_path.read_bytes()==review_raw and signature(db_path.read_bytes())==BEFORE_SHA,'publication inputs changed after compile')
        inventory=selection['source_inventory'];blobs=tree_chunks(repo,inventory)
        require(blobs=={p:w['git_blob'] for p,w in inventory.items()} and all(signature(checked_source(repo,p,blobs[p]))==w['sha256'] for p,w in inventory.items())
            and (root/'catalog/TCGDEX-LICENSE').read_bytes()==licence,'source/licence drift before publication')
        current={str(p.relative_to(Path(__file__).resolve().parents[1])):signature(raw) for p,raw in compiler_inputs().items()}
        require(current==selection['compilation_source_sha256'],'compiler dependency drift before publication')
        require(all(signature((packet_path.parent/name).read_bytes())==digest for name,digest in selection['qualification_census_sha256'].items()),'qualification census drift before publication')
        publish_exclusive(temporary,output)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return {k:selection[k] for k in ('japanese','english','exact_name_pairs','by_set','idempotent_reimport')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('db','source-repo','qualification','semantic-review','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--inspected-at',required=True);args=parser.parse_args()
    print(json.dumps(build(args.db,args.source_repo,Path.cwd(),args.qualification,args.semantic_review,args.output,args.inspected_at)))


if __name__=='__main__':main()
