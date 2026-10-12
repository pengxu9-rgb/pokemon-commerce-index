"""Compile a reviewed, source-bound 1,000-Japanese-name discovery batch offline.

Name concepts never assert card counterparts. New concepts require an exact
current locale binding before the structured resolver can use a translation.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts.build_international_coverage_expansion import ALIAS_FIELDS, RIGHTS, source_fields, translated_query
from scripts.qualify_international_product_documents import REVISION, checked_source, git_tree, header_fields

SETS = ('SV2A','SV4A','SV8A','S8B','S12A','SM8B','SM12A','S10A','SM9','M2A',
        'SM10','M6A','MC','SV3','M1L','SM9B','SM9A','SM1S','SV6','M6','SM11B','M3','S11A','SV1V','S9')
JAPANESE_LIMIT = 1000
ENGLISH_COUNT = 25
PREFERRED_EN_DEX = (29,32,83,122,151,6,3,9)


def spaced_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def names(value):
    if not isinstance(value,str) or not value.startswith('{') or not value.endswith('}'):
        raise ValueError('literal localized name object required')
    body=tcgdex_source._balanced(value,0,'{','}')
    if len(body)+2!=len(value):raise ValueError('unsupported name object suffix')
    pattern=re.compile(r'\s*('+tcgdex_source.LITERAL+r'|[a-z][a-z0-9-]*)\s*:\s*'+tcgdex_source.LITERAL+r'\s*(?:,|$)')
    values={};offset=0
    while body[offset:].strip():
        match=pattern.match(body,offset)
        if not match:raise ValueError('unsupported localized name syntax')
        # LITERAL has capturing groups; named extraction uses the full part.
        part=body[offset:match.end()].strip().rstrip(',').strip()
        key_text,field=part.split(':',1)
        key=ast.literal_eval(key_text) if key_text[0] in "'\"" else key_text
        from pokemon_index.languages import normalize_language
        language=normalize_language(key);name=ast.literal_eval(field.strip())
        if language in values or not isinstance(name,str) or not name.strip():
            raise ValueError('duplicate or empty localized name')
        values[language]=name;offset=match.end()
    if not values:raise ValueError('missing localized names')
    return values


def metadata(raw):
    fields=header_fields(raw.decode('utf-8'),declaration_name='card',declaration_type='Card')
    if fields.get('category') is None or ast.literal_eval(fields['category'])!='Pokemon':
        raise ValueError('literal Pokemon category required')
    value=fields.get('dexId','')
    if not re.fullmatch(r'\[\s*\d+\s*,?\s*\]',value):
        raise ValueError('exact singleton Dex required; multi-character or missing fields held')
    number=ast.literal_eval(value)[0]
    if type(number) is not int or not 1<=number<=151:
        raise ValueError('outside reviewed Kanto name scope')
    return dict(category='Pokemon',dex_id=number,names=names(fields.get('name')))


def inspect(db,card,raw):
    language=card['language'];path,sha=source_fields(card)
    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('source differs from identity provenance')
    if card['variant'].startswith('unverified') or not db.execute('SELECT match_eligible FROM card WHERE card_id=?',(card['card_id'],)).fetchone()[0]:
        raise ValueError('unresolved family cannot receive a name binding')
    category=db.execute('SELECT category FROM card_classification WHERE card_id=?',(card['card_id'],)).fetchone()
    release=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',(language,card['set_code'])).fetchone()
    if not category or category[0]!='Pokemon' or not release or not release['name'] or not release['official_card_count']:
        raise ValueError('current Pokemon classification and localized release required')
    facts=metadata(raw)
    if facts['names'].get(language)!=card['name']:raise ValueError('source full name differs')
    parsed=tcgdex_source.parse_card_source(raw.decode('utf-8'),set_id=card['set_code'],official_count=release['official_card_count'],
        path=path,revision=REVISION,language=language,source_directory=PurePosixPath(path).parent.name)
    fields=('language','set_code','collector_number','variant','name','provenance','rights_reference')
    if not any(all(row[key]==card[key] for key in fields) for row in parsed):
        raise ValueError('source printing tuple differs')
    return facts,dict(release)


def checked_review(draft_bytes,review):
    if (review.get('schema')!='pokemon.independent-name-review.v1' or review.get('reviewer')!='GPT-6.1 Sol high'
            or review.get('proposal_sha256')!=hashlib.sha256(draft_bytes).hexdigest()
            or review.get('decision')!='approve_all_exact_pairs' or review.get('rejected_pairs')!=[]
            or review.get('uncertain_pairs')!=[]):
        raise ValueError('exact independent semantic review missing or differs')
    proposals=json.loads(draft_bytes)
    if review.get('approved_pairs')!=len(proposals) or not proposals:
        raise ValueError('semantic review pair count differs')
    keys={(p['name_ja'],p['name_en']) for p in proposals}
    if len(keys)!=len(proposals) or len({p['name_ja'] for p in proposals})!=len(proposals) or len({p['name_en'] for p in proposals})!=len(proposals):
        raise ValueError('ambiguous full-name translation proposals')
    return proposals


def bundle(db,proposals,raws,blobs,license_sha,semantic_sha,inspected_at):
    events=[];concepts=[]
    for pair in proposals:
        witness={};urls={}
        for language in ('ja','en'):
            card=pair[language]
            if catalog_locale.snapshot(db,card['card_id'])!=card or card['language']!=language:
                raise ValueError('semantic witness identity changed')
            path,sha=source_fields(card);facts,release=inspect(db,card,raws[path])
            if facts['dex_id']!=pair['dex_id'] or card['name']!=pair['name_'+language]:
                raise ValueError('semantic witness name/Dex differs')
            urls[language]=f'https://github.com/tcgdex/cards-database/blob/{REVISION}/'+quote(path,safe='/')
            witness[language]=dict(identity=card,dex_id=facts['dex_id'],category='Pokemon',native_id=path,
                revision=REVISION,git_blob=blobs[path],sha256=sha,license_sha256=license_sha,
                rights_reference=RIGHTS,rights_status='metadata_internal_reviewed',retrieved_at=None,
                retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                physical_distribution_region=None,release_snapshot=release)
        frozen=dict(category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],
            source_ja=urls['ja'],source_en=urls['en'],rights_reference=RIGHTS,
            ja_card_id=pair['ja']['card_id'],en_card_id=pair['en']['card_id'],dex_id=pair['dex_id'],retrieval_only=True)
        frozen['proposal_id']='pokemon-name-proposal:'+catalog_locale.digest(frozen)
        snapshot=dict(frozen=frozen,ja_provenance=pair['ja']['provenance'],en_provenance=pair['en']['provenance'],
                      witnesses=witness,scope='exact full-name metadata translation; no printing counterpart',
                      **{key:False for key in catalog_locale.FALSE_CLAIMS})
        proposal={**frozen,'ja_provenance':snapshot['ja_provenance'],'en_provenance':snapshot['en_provenance'],
                  'source_snapshot':snapshot,'source_snapshot_sha256':spaced_digest(snapshot)}
        review=dict(decision='approve',review_revision=1,reviewer='ai-independent:gpt-6.1-sol-high',
            reviewed_at=inspected_at,ja_identity_checked=True,en_identity_checked=True,translation_checked=True,
            identity_attestation_scope='existing pinned metadata tuples only; no physical-copy verification',
            requires_card_binding=True,semantic_review_sha256=semantic_sha,
            evidence_note='Independent GPT-6.1 Sol high approves this exact literal full-name pair and singleton-Dex/category scope. '
                'Actual pinned witnesses rechecked. No regional/owner/mechanic inheritance, artwork, counterpart, physical or price approval.',
            **{key:False for key in catalog_locale.FALSE_CLAIMS})
        event=dict(schema='pokemon.concept_review.v1',proposal=proposal,review=review)
        event['event_id']=spaced_digest(event);events.append(event)
        cid='pokemon-name:'+catalog_locale.digest({'ja':pair['name_ja'],'en':pair['name_en'],'dex_id':pair['dex_id']})
        if db.execute('SELECT 1 FROM bilingual_concept_revision WHERE concept_id=?',(cid,)).fetchone():
            raise ValueError('name concept already represented; explicit revision review required')
        concepts.append(dict(concept_id=cid,revision=1,category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],
            source_ja=urls['ja'],source_en=urls['en'],rights_reference=RIGHTS,reviewer=review['reviewer'],
            reviewed_at=inspected_at,status='approved',review_event_id=event['event_id']))
    return dict(schema='pokemon.concept_review_bundle.v1',review_events=events,concept_revisions=concepts)


def candidates(db,proposals):
    names_by_language={lang:{p['name_'+lang]:p for p in proposals} for lang in ('ja','en')}
    bound={r[0] for r in db.execute('SELECT card_id FROM catalog_locale_evidence UNION SELECT card_id FROM catalog_source_mapping')}
    eligible=[]
    for card in db.execute('''SELECT c.* FROM card c JOIN card_classification cl USING(card_id)
            WHERE cl.category='Pokemon' AND match_eligible=1 AND language IN ('ja','en') ORDER BY card_id'''):
        if card['card_id'] in bound or card['variant'].startswith('unverified'):continue
        language=card['language']
        if language=='ja' and card['set_code'] not in SETS:continue
        if language=='en' and not card['set_code'].startswith(('SV','SWSH','SM')):continue
        if card['name'] not in names_by_language[language]:continue
        release=db.execute('SELECT name,official_card_count FROM catalog_set_localized WHERE language=? AND set_code=?',
                           (language,card['set_code'])).fetchone()
        if not release or not release[0] or not release[1]:continue
        try:source_fields(card)
        except ValueError:continue
        eligible.append((dict(card),names_by_language[language][card['name']]))
    return eligible


def choose(japanese,english):
    groups=defaultdict(list)
    for pair in japanese:groups[(pair[0]['set_code'],pair[0]['collector_number'])].append(pair)
    selected=[];used=set()
    # Cover every fixed scope first, then take complete eligible coordinate groups
    # in the stated set order. A group is never split to pad the count.
    for code in SETS:
        keys=sorted(key for key in groups if key[0]==code)
        if not keys:raise ValueError('no qualified names for fixed scope: '+code)
        selected.extend(groups[keys[0]]);used.add(keys[0])
    for code in SETS:
        for key in sorted(key for key in groups if key[0]==code and key not in used):
            if len(selected)+len(groups[key])<=JAPANESE_LIMIT:
                selected.extend(groups[key]);used.add(key)
    if len(selected)!=JAPANESE_LIMIT:raise ValueError('qualified whole-group Japanese batch falls short of1000')
    selected_names={pair['name_en'] for _,pair in selected}
    pool=[pair for pair in english if pair[0]['name'] in selected_names]
    order=sorted(pool,key=lambda item:(PREFERRED_EN_DEX.index(item[1]['dex_id']) if item[1]['dex_id'] in PREFERRED_EN_DEX else 999,
                                     item[1]['dex_id'],item[0]['name'],item[0]['card_id']))
    comparison=[];seen=set()
    for pair in order:
        if pair[0]['name'] not in seen:
            comparison.append(pair);seen.add(pair[0]['name'])
        if len(comparison)==ENGLISH_COUNT:break
    if len(comparison)!=ENGLISH_COUNT:raise ValueError('25 qualified distinct-name English comparisons required')
    return selected+comparison


def compile(db_path,repo,root,draft_path,review_path,inspected_at):
    core.parse_time(inspected_at)
    before_sha=hashlib.sha256(db_path.read_bytes()).hexdigest()
    draft_bytes=draft_path.read_bytes();review_bytes=review_path.read_bytes()
    review=json.loads(review_bytes);proposals=checked_review(draft_bytes,review)
    with closing(core.connect(db_path,readonly=True)) as original:
        original.execute('BEGIN');pool=candidates(original,proposals)
        paths={source_fields(card)[0] for card,_ in pool}
        paths.update(source_fields(pair[lang])[0] for pair in proposals for lang in ('ja','en'));paths.add('LICENSE')
        blobs=git_tree(repo,sorted(paths),revision=REVISION)
        if set(blobs)!=paths:raise ValueError('required pinned card/licence unavailable')
        raws={path:checked_source(repo,path,blob) for path,blob in blobs.items()}
        license_bytes=(root/'catalog/TCGDEX-LICENSE').read_bytes()
        if raws['LICENSE']!=license_bytes:raise ValueError('existing reviewed licence differs')
        license_sha=hashlib.sha256(license_bytes).hexdigest()
        review_bundle=bundle(original,proposals,raws,blobs,license_sha,hashlib.sha256(review_bytes).hexdigest(),inspected_at)
        holds=[];qualified={'ja':[],'en':[]}
        for card,pair in pool:
            path,_=source_fields(card)
            try:
                facts,_=inspect(original,card,raws[path])
                if facts['dex_id']!=pair['dex_id']:raise ValueError('singleton Dex differs from reviewed full name')
                qualified[card['language']].append((card,pair))
            except (ValueError,SyntaxError) as error:
                holds.append(dict(card_id=card['card_id'],reason=str(error),source_provenance=card['provenance'],
                    status='held_no_name_binding',**{key:False for key in catalog_locale.FALSE_CLAIMS}))
        # One unsupported eligible sibling holds that coordinate group.
        bad={tuple(row['card_id'].split(':')[1:3]) for row in holds if row['card_id'].startswith('ja:')}
        qualified['ja']=[pair for pair in qualified['ja'] if (pair[0]['set_code'],pair[0]['collector_number']) not in bad]
        selected=choose(qualified['ja'],qualified['en'])
        with tempfile.TemporaryDirectory() as directory:
            scratch=Path(directory)/'names.sqlite3';shutil.copyfile(db_path,scratch)
            with closing(core.connect(scratch)) as db:
                imported=core.import_concept_review_bundle(db,review_bundle)
                rows=[];gaps=[]
                for card,pair in selected:
                    path,sha=source_fields(card);facts,release=inspect(db,card,raws[path])
                    alias=db.execute('''SELECT * FROM bilingual_concept_revision WHERE category='Pokemon'
                        AND name_ja=? AND name_en=? ORDER BY revision DESC LIMIT 1''',
                        (pair['name_ja'],pair['name_en'])).fetchone()
                    query=translated_query(card,alias)
                    prior=core.catalog_search_internal(original,query,set_code=card['set_code'],limit=100)
                    if card['card_id'] in {c['card_id'] for c in prior['cards']}:
                        raise ValueError('selected target already found by translated query')
                    row=dict(schema='pokemon.catalog-locale.v1',identity=catalog_locale.snapshot(db,card['card_id']),
                        source=dict(provider='tcgdex',language=card['language'],region='ZZ',release_id='tcgdex-product:'+card['set_code'],
                            native_id=path,source_variant=card['variant'],revision=REVISION,git_blob=blobs[path],sha256=sha,
                            license_git_blob=blobs['LICENSE'],license_sha256=license_sha,retrieved_at=None,
                            retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                            physical_distribution_region=None,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed'),
                        release_snapshot=release,name_aliases=[{key:alias[key] for key in ALIAS_FIELDS}],
                        character_scope={'dex_id':facts['dex_id'],'full_name':card['name'],'category':'Pokemon','form_inheritance_allowed':False},
                        confidence=1.0,confidence_scope='checked pinned tuples and independent exact full-name translation only',
                        unresolved_conflicts=[],test_only=False,**{key:False for key in catalog_locale.FALSE_CLAIMS})
                    row['evidence_id']='catalog-locale:'+catalog_locale.digest(row)
                    catalog_locale.validate(db,row);rows.append(row)
                    gaps.append(dict(card_id=card['card_id'],query=query,before_contains_target=False,before_total=prior['total']))
    if (git_tree(repo,sorted(paths),revision=REVISION)!=blobs
            or any(checked_source(repo,path,blobs[path])!=raw for path,raw in raws.items())
            or (root/'catalog/TCGDEX-LICENSE').read_bytes()!=license_bytes
            or draft_path.read_bytes()!=draft_bytes or review_path.read_bytes()!=review_bytes
            or hashlib.sha256(db_path.read_bytes()).hexdigest()!=before_sha):
        raise ValueError('source,review,licence or input snapshot drifted')
    selection=dict(schema='pokemon.pokemon-name-coverage-selection.v1',inspected_at=inspected_at,
        input_database_sha256=before_sha,japanese=JAPANESE_LIMIT,english=ENGLISH_COUNT,
        by_set=dict(Counter(row['identity']['language']+':'+row['identity']['set_code'] for row in rows)),
        concept_reviews=imported,exact_name_pairs=len(proposals),source_revision=REVISION,
        source_inventory={path:dict(git_blob=blobs[path],sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for path,raw in sorted(raws.items())},
        preliminary_pool=dict(Counter(card['language'] for card,_ in pool)),qualified_pool={lang:len(values) for lang,values in qualified.items()},
        selected_coordinate_groups=len({(row['identity']['set_code'],row['identity']['collector_number']) for row in rows if row['identity']['language']=='ja'}),
        gaps=gaps,holds=holds,new_card_identities=0,new_counterpart_relationships=0,
        semantic_review_sha256=hashlib.sha256(review_bytes).hexdigest(),proposal_sha256=hashlib.sha256(draft_bytes).hexdigest(),
        selection_reason='Kanto exact full-name translations;25 fixed modern physical sets;complete eligible coordinate groups and25 English name comparisons;new translations require per-record source bindings.',
        physical_distribution_region=None,demand='Japan-to-US discovery objective;set-level demand unmeasured',
        authorized_supply='metadata only;live Buy&Ship availability unknown')
    return review_bundle,rows,selection,license_bytes


def build(db_path,repo,root,draft_path,review_path,output,inspected_at):
    if output.exists():raise FileExistsError('name-coverage artifact directory already exists')
    draft_bytes=draft_path.read_bytes();review_bytes=review_path.read_bytes()
    bundle_data,rows,selection,license_bytes=compile(db_path,repo,root,draft_path,review_path,inspected_at)
    if (hashlib.sha256(draft_bytes).hexdigest()!=selection['proposal_sha256']
            or hashlib.sha256(review_bytes).hexdigest()!=selection['semantic_review_sha256']):
        raise ValueError('frozen artifact inputs differ from reviewed compilation')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='.pokemon-name-coverage-',dir=output.parent))
    try:
        for name,value in [('concept-review-bundle.json',bundle_data),('selection.json',selection),
                           ('semantic-review.json',json.loads(review_bytes))]:
            (temporary/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        (temporary/'proposals.json').write_bytes(draft_bytes)
        (temporary/'locales.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows))
        (temporary/'TCGDEX-LICENSE').write_bytes(license_bytes)
        if output.exists():raise FileExistsError('artifact directory appeared during compilation')
        os.rename(temporary,output)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return {key:selection[key] for key in ('japanese','english','exact_name_pairs','by_set','qualified_pool')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','proposals','semantic-review','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.proposals,a.semantic_review,a.output,a.inspected_at)))


if __name__=='__main__':main()
