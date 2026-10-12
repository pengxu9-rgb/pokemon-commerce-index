"""Requalify the frozen 85-Japanese/25-English offline discovery follow-up."""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts import build_pokemon_name_coverage as names
from scripts.build_international_coverage_expansion import ALIAS_FIELDS, RIGHTS, source_fields, translated_query
from scripts.build_international_coverage_expansion import RetrievalScope,MAX_EXPANDED_ENGLISH
from scripts.qualify_international_product_documents import REVISION, checked_source, git_tree

DIRECTORY = 'catalog/international-pokemon-followup-v1'
PLAN = 'catalog/international-pokemon-thousand-v1/next-batch-plan.json'
PLAN_SHA = '03b902152be82b527ab9e7fc87b86ae6e339095ed77cee26da5b2e936159305c'
BEFORE_SHA = '2778cafe8b7e2e1e57fc775f0ce84c3963bc7eca0067fc5d92a8a2505552a7e0'
SETS = ('SM1S','SV6','M6','SM11B','M3','S11A','SV1V','S9')
JAPANESE = 85
ENGLISH = 25
EXPANDED_IMAGE_HANDOFF = 'catalog/international-pokemon-extended-v1/image-priority-handoff.json'
EXPANDED_IMAGE_TARGETS = (
    'en:BASE1:058/102:normal', 'ja:PMCG5:036/096:normal',
    'ja:PMCG1:035/102:normal', 'ja:PMCG1:035/102:normal_no_rarity', 'ja:PMCG2:024/048:normal',
)


@dataclass(frozen=True)
class FollowupProfile:
    name: str
    directory: str
    plan: str
    plan_sha: str
    before_sha: str
    sets: tuple[str, ...]
    japanese: int
    plan_schema: str
    strict_variant_dimensions: bool = False
    english: int = ENGLISH
    expanded_batch: bool = False

    def __post_init__(self):
        RetrievalScope(self.name,self.sets,self.japanese,self.english,self.expanded_batch)
        for path in (self.directory,self.plan):
            if not isinstance(path,str) or not path or Path(path).is_absolute() or '..' in Path(path).parts:
                raise ValueError('profile requires repository-relative artifact paths')
        if (any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{64}',v) for v in (self.plan_sha,self.before_sha))
                or self.plan_schema not in {'pokemon.name-coverage-next-batch.v1','pokemon.followup-next-batch-plan.v1'}
                or type(self.strict_variant_dimensions) is not bool
                or self.expanded_batch and self.strict_variant_dimensions is not True):
            raise ValueError('profile requires frozen hashes and supported plan schema')


def profile_or_default(profile):
    if profile is not None and not isinstance(profile,FollowupProfile):
        raise ValueError('explicit follow-up profile must be validated')
    return profile if profile is not None else FollowupProfile('pokemon-name-followup',DIRECTORY,PLAN,PLAN_SHA,BEFORE_SHA,SETS,JAPANESE,
                                                              'pokemon.name-coverage-next-batch.v1')


def checked_plan(raw, *, profile=None):
    settings = profile_or_default(profile)
    plan = json.loads(raw)
    count_field = 'japanese_records' if settings.plan_schema=='pokemon.name-coverage-next-batch.v1' else 'proposed_japanese_records'
    if (hashlib.sha256(raw).hexdigest() != settings.plan_sha
            or plan.get('schema') != settings.plan_schema
            or plan.get('applied') is not False or type(plan.get(count_field)) is not int or plan.get(count_field) != settings.japanese
            or type(plan.get('english_comparison_target')) is not int or plan.get('english_comparison_target') != settings.english):
        raise ValueError('frozen reviewed follow-up plan differs')
    if settings.plan_schema=='pokemon.followup-next-batch-plan.v1':
        proposals=plan.get('proposals',[])
        if any(p.get('status')!='source_qualified_proposed_unapplied'
                or type(p.get('dex_id')) is not int or not 1<=p['dex_id']<=151
                or any(p.get(k) is not False for k in catalog_locale.FALSE_CLAIMS) for p in proposals):
            raise ValueError('proposed records are not offline qualified metadata')
        plan={**plan,'records':[dict(card=p['identity'],name_alias=p['name_alias'],
            full_name_pair=dict(name_ja=p['name_alias']['name_ja'],name_en=p['name_alias']['name_en'],dex_id=p['dex_id']),
            status='source_qualified_not_applied',
            frozen_source={k:p[k] for k in ('source_revision','native_id','git_blob','sha256','rights_reference','license_sha256')})
            for p in proposals]}
    if settings.expanded_batch:
        checked_expanded_exclusions(plan)
    records = plan.get('records', [])
    if (len(records) != settings.japanese or len({r['card']['card_id'] for r in records}) != settings.japanese
            or any(r['card']['language'] != 'ja' or r.get('status') != 'source_qualified_not_applied' for r in records)
            or {r['card']['set_code'] for r in records} != set(settings.sets)):
        raise ValueError('exact planned Japanese scope differs')
    return plan


def expanded_excluded_groups():
    groups = {tuple(cid.split(':',3)[:3]) for cid in EXPANDED_IMAGE_TARGETS}
    return [dict(zip(('language','set_code','collector_number'),group)) for group in sorted(groups)]


def checked_expanded_exclusions(plan):
    if (plan.get('expanded_batch') is not True
            or plan.get('excluded_image_target_ids') != sorted(EXPANDED_IMAGE_TARGETS)
            or plan.get('excluded_image_target_groups') != expanded_excluded_groups()):
        raise ValueError('expanded priority-image group exclusions differ')
    groups = {tuple(group[k] for k in ('language','set_code','collector_number')) for group in expanded_excluded_groups()}
    if any(tuple(item['card'][k] for k in ('language','set_code','collector_number')) in groups for item in plan.get('records',[])):
        raise ValueError('expanded plan includes a priority-image coordinate group')
    return groups


def expanded_english_witnesses(plan):
    ids=plan.get('qualified_english_candidate_ids');witnesses=plan.get('english_candidate_witnesses')
    if (not isinstance(ids,list) or any(not isinstance(cid,str) or not cid.startswith('en:') for cid in ids)
            or ids!=sorted(set(ids)) or len(ids)<plan['english_comparison_target']
            or not isinstance(witnesses,list) or len(witnesses)!=len(ids)):
        raise ValueError('frozen qualified English pool differs')
    result={w['identity']['card_id']:w for w in witnesses}
    if sorted(result)!=ids or any(w.get(k) is not False for w in witnesses for k in catalog_locale.FALSE_CLAIMS):
        raise ValueError('frozen qualified English witnesses differ')
    return result


def expanded_releases(db,plan,raws,blobs):
    from scripts.pokemon_release_witness import release_path,inspect_release
    result={}
    for witness in plan.get('localized_release_witnesses',[]):
        release=witness['snapshot'];key=(release['language'],release['set_code'])
        current=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',key).fetchone()
        path=release_path(release,REVISION,RIGHTS)
        if (key in result or current is None or dict(current)!=release
                or witness['native_id']!=path or witness['git_blob']!=blobs[path]
                or witness['sha256']!=hashlib.sha256(raws[path]).hexdigest()
                or witness['facts']!=inspect_release(release,raws[path])
                or any(witness.get(k) is not False for k in catalog_locale.FALSE_CLAIMS)):
            raise ValueError('frozen localized release witness differs')
        result[key]=witness
    return result


def bound_ids(db):
    return {r[0] for r in db.execute('SELECT card_id FROM catalog_locale_evidence UNION SELECT card_id FROM catalog_source_mapping')}


def current_alias(db, card):
    rows = db.execute('''WITH latest AS (SELECT *,row_number() OVER
        (PARTITION BY concept_id ORDER BY revision DESC) AS rank FROM bilingual_concept_revision)
        SELECT * FROM latest WHERE rank=1 AND status='approved' AND category='Pokemon'
        AND (CASE WHEN ?='ja' THEN name_ja ELSE name_en END)=?''', (card['language'],card['name'])).fetchall()
    if len(rows) != 1:
        raise ValueError('missing or ambiguous current Pokemon full-name review')
    alias = {key:rows[0][key] for key in ALIAS_FIELDS}
    catalog_locale.approved_alias(db,alias)
    event = db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(alias['review_event_id'],)).fetchone()
    if not event:
        raise ValueError('source-bound name review missing')
    review = json.loads(event[0])
    body = {k:v for k,v in review.items() if k!='event_id'}
    frozen = review['proposal']['source_snapshot']['frozen']
    if (names.spaced_digest(body) != alias['review_event_id'] or review['event_id'] != alias['review_event_id']
            or review['review'].get('requires_card_binding') is not True
            or review['review'].get('decision') != 'approve'
            or frozen.get('category') != 'Pokemon'
            or any(frozen.get(k) != alias[k] for k in ('name_ja','name_en'))
            or type(frozen.get('dex_id')) is not int or not 1<=frozen['dex_id']<=151):
        raise ValueError('retained full-name review scope differs')
    return alias,frozen['dex_id']


def planned_japanese(db, plan):
    bound = bound_ids(db); selected = []
    for item in plan['records']:
        card = catalog_locale.snapshot(db,item['card']['card_id'])
        if card != item['card'] or card['card_id'] in bound:
            raise ValueError('planned identity changed or already bound')
        alias,dex = current_alias(db,card)
        if (item['full_name_pair'] != dict(name_ja=alias['name_ja'],name_en=alias['name_en'],dex_id=dex)
                or 'name_alias' in item and item['name_alias']!=alias):
            raise ValueError('planned exact name/Dex review differs')
        selected.append((card,alias,dex))
    ids = {card['card_id'] for card,_,_ in selected}
    for card,_,_ in selected:
        # Every eligible unbound sibling must be present in the frozen plan.
        siblings = db.execute('''SELECT c.card_id,c.name,cl.category FROM card c LEFT JOIN card_classification cl USING(card_id)
            WHERE c.language='ja' AND c.set_code=? AND c.collector_number=?
            AND c.match_eligible=1 AND c.variant NOT LIKE 'unverified%' ''',(card['set_code'],card['collector_number']))
        if any(s['name']!=card['name'] or s['category']!='Pokemon' or s['card_id'] not in ids|bound for s in siblings):
            raise ValueError('planned coordinate has an unqualified or omitted eligible sibling')
    return selected


def english_pool(db, japanese):
    used = {alias['concept_id'] for _,alias,_ in japanese};bound = bound_ids(db);pool = []
    for record in db.execute('''SELECT c.* FROM card c JOIN card_classification cl USING(card_id)
            WHERE c.language='en' AND c.match_eligible=1 AND cl.category='Pokemon' ORDER BY c.card_id'''):
        card = dict(record)
        if card['card_id'] in bound or card['variant'].startswith('unverified') or not card['set_code'].startswith(('SM','SWSH','SV')):
            continue
        try:
            alias,dex = current_alias(db,card);source_fields(card)
        except ValueError:
            continue
        if alias['concept_id'] in used:
            release = db.execute('SELECT name,official_card_count FROM catalog_set_localized WHERE language=? AND set_code=?',
                                 ('en',card['set_code'])).fetchone()
            if release and release[0] and release[1]:pool.append((card,alias,dex))
    return pool


def choose_english(pool, *, count=ENGLISH):
    # Prefer female Nidoran and punctuation cases available in this Japanese
    # slice, then source-normal variants and distinct exact reviewed concepts.
    if type(count) is not int or not 1 <= count <= MAX_EXPANDED_ENGLISH:
        raise ValueError('invalid bounded English comparison count')
    order = sorted(pool,key=lambda p:(0 if p[2] in (29,83) else 1,p[2],
        0 if p[0]['variant'] in ('normal','holo','standard') else 1,p[0]['card_id']))
    chosen = [];used = set()
    for pair in order:
        if pair[1]['concept_id'] not in used:
            chosen.append(pair);used.add(pair[1]['concept_id'])
        if len(chosen)==count:break
    if len(chosen)!=count:
        raise ValueError(f'{count} qualified distinct reviewed English comparisons unavailable')
    return chosen


def compile(db_path, repo, root, inspected_at, *, profile=None):
    settings = profile_or_default(profile)
    core.parse_time(inspected_at)
    before_sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
    if before_sha != settings.before_sha:
        raise ValueError('immutable input database differs')
    plan_bytes = (root/settings.plan).read_bytes();plan = checked_plan(plan_bytes,profile=settings)
    excluded_groups = checked_expanded_exclusions(plan) if settings.expanded_batch else set()
    image_bytes = (root/EXPANDED_IMAGE_HANDOFF).read_bytes() if settings.expanded_batch else None
    if settings.expanded_batch and hashlib.sha256(image_bytes).hexdigest() != plan.get('held_image_handoff_sha256'):
        raise ValueError('expanded priority-image source witness differs')
    with closing(core.connect(db_path,readonly=True)) as db:
        db.execute('BEGIN');japanese = planned_japanese(db,plan);pool = english_pool(db,japanese)
        paths = {source_fields(card)[0] for card,_,_ in japanese+pool};paths.add('LICENSE')
        english_witnesses=expanded_english_witnesses(plan) if settings.expanded_batch else {}
        if settings.expanded_batch:
            if not set(english_witnesses).issubset({c['card_id'] for c,_,_ in pool}):
                raise ValueError('frozen English pool no longer matches current scope')
            paths.update(plan['release_header_inventory'])
        blobs = git_tree(repo,sorted(paths),revision=REVISION)
        if set(blobs)!=paths:raise ValueError('pinned sources/licence unavailable')
        raws = {path:checked_source(repo,path,blob) for path,blob in blobs.items()}
        licence = (root/'catalog/TCGDEX-LICENSE').read_bytes()
        if raws['LICENSE']!=licence:raise ValueError('existing reviewed metadata licence differs')
        releases={}
        if settings.expanded_batch:
            for path,witness in plan['release_header_inventory'].items():
                if witness!=dict(git_blob=blobs[path],sha256=hashlib.sha256(raws[path]).hexdigest(),bytes=len(raws[path])):
                    raise ValueError('frozen release header source differs')
            releases=expanded_releases(db,plan,raws,blobs)
        for item in plan['records']:
            if 'frozen_source' in item:
                card=item['card'];path,sha=source_fields(card)
                expected=dict(source_revision=REVISION,native_id=path,git_blob=blobs[path],sha256=sha,
                              rights_reference=card['rights_reference'],license_sha256=hashlib.sha256(licence).hexdigest())
                if item['frozen_source']!=expected:raise ValueError('frozen proposed source witness differs')
        qualified = [];holds = []
        for card,alias,dex in japanese+pool:
            hold_status = 'held_no_name_binding'
            try:
                if settings.strict_variant_dimensions:
                    hold_status = 'held_source_dimension'
                    losses = tcgdex_source.variant_dimension_losses(raws[source_fields(card)[0]].decode('utf-8'))
                    if any(loss['legacy_variant'] == card['variant'] for loss in losses):
                        raise ValueError('source size omitted from legacy variant; separate identity review required')
                hold_status = 'held_no_name_binding'
                metadata,release = names.inspect(db,card,raws[source_fields(card)[0]])
                if metadata['dex_id']!=dex:raise ValueError('singleton Dex differs from retained review')
                if settings.expanded_batch:
                    release_witness=releases.get((card['language'],card['set_code']))
                    if release_witness is None:raise ValueError('source-qualified localized release missing')
                    if card['language']=='en':
                        frozen=english_witnesses.get(card['card_id']);path,sha=source_fields(card)
                        header_expected=dict(provider='tcgdex',revision=REVISION,native_id=release_witness['native_id'],
                            git_blob=release_witness['git_blob'],sha256=release_witness['sha256'],
                            rights_reference=RIGHTS,license_sha256=hashlib.sha256(licence).hexdigest())
                        if (frozen is None or frozen['identity']!=catalog_locale.snapshot(db,card['card_id'])
                                or frozen['name_alias']!=alias or frozen['dex_id']!=dex
                                or frozen['release_snapshot']!=release or frozen['release_facts']!=release_witness['facts']
                                or frozen['source_revision']!=REVISION or frozen['native_id']!=path
                                or frozen['git_blob']!=blobs[path] or frozen['sha256']!=sha
                                or frozen['rights_reference']!=RIGHTS or frozen['license_sha256']!=hashlib.sha256(licence).hexdigest()
                                or any(frozen['release_header'].get(k)!=v for k,v in header_expected.items())):
                            raise ValueError('frozen English source/name/release witness differs')
            except (ValueError,SyntaxError) as error:
                if card['language']=='ja':raise ValueError('planned Japanese requalification failed: '+card['card_id']) from error
                hold = dict(card_id=card['card_id'],reason=str(error),status=hold_status)
                if hold_status == 'held_source_dimension':
                    path,sha = source_fields(card)
                    hold.update(identity=catalog_locale.snapshot(db,card['card_id']),
                        source=dict(provider='tcgdex',native_id=path,revision=REVISION,git_blob=blobs[path],sha256=sha,
                            license_sha256=hashlib.sha256(licence).hexdigest(),rights_reference=RIGHTS,
                            rights_status='metadata_internal_reviewed',inspected_at=inspected_at,retrieved_at=None,
                            retrieval_status='historical_snapshot_time_not_recorded',physical_distribution_region=None),
                        confidence=None,confidence_scope='unresolved legacy size dimension; no binding',
                        unresolved_conflicts=[str(error)],**{k:False for k in catalog_locale.FALSE_CLAIMS})
                holds.append(hold)
                continue
            if card['language']=='en':qualified.append((card,alias,dex))
        if settings.expanded_batch and {c['card_id'] for c,_,_ in qualified}!=set(english_witnesses):
            raise ValueError('frozen qualified English pool failed requalification')
        selected = japanese+choose_english(qualified,count=settings.english);rows = [];gaps = []
        if any(tuple(card[k] for k in ('language','set_code','collector_number')) in excluded_groups for card,_,_ in selected):
            raise ValueError('expanded selection includes a priority-image coordinate group')
        for card,alias,dex in selected:
            path,sha = source_fields(card);metadata,release = names.inspect(db,card,raws[path])
            query = translated_query(card,alias)
            result = core.catalog_search_internal(db,query,set_code=card['set_code'],limit=100)
            if card['card_id'] in {c['card_id'] for c in result['cards']}:
                raise ValueError('selected target already retrievable')
            row = dict(schema='pokemon.catalog-locale.v1',identity=catalog_locale.snapshot(db,card['card_id']),
                source=dict(provider='tcgdex',language=card['language'],region='ZZ',release_id='tcgdex-product:'+card['set_code'],
                    native_id=path,source_variant=card['variant'],revision=REVISION,git_blob=blobs[path],sha256=sha,
                    license_git_blob=blobs['LICENSE'],license_sha256=hashlib.sha256(licence).hexdigest(),
                    retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                    physical_distribution_region=None,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed'),
                release_snapshot=release,name_aliases=[alias],
                character_scope=dict(dex_id=dex,full_name=card['name'],category='Pokemon',form_inheritance_allowed=False),
                confidence=1.0,confidence_scope='checked pinned tuple and retained exact full-name translation only',
                unresolved_conflicts=[],test_only=False,**{key:False for key in catalog_locale.FALSE_CLAIMS})
            row['evidence_id']='catalog-locale:'+catalog_locale.digest(row);catalog_locale.validate(db,row);rows.append(row)
            gaps.append(dict(card_id=card['card_id'],query=query,before_contains_target=False,before_total=result['total']))
    if (git_tree(repo,sorted(paths),revision=REVISION)!=blobs
            or any(checked_source(repo,path,blobs[path])!=raw for path,raw in raws.items())
            or (root/'catalog/TCGDEX-LICENSE').read_bytes()!=licence or (root/settings.plan).read_bytes()!=plan_bytes
            or hashlib.sha256(db_path.read_bytes()).hexdigest()!=before_sha
            or settings.expanded_batch and (root/EXPANDED_IMAGE_HANDOFF).read_bytes()!=image_bytes):
        raise ValueError('source,licence,plan or input snapshot drifted')
    selection = dict(schema='pokemon.pokemon-name-followup-selection.v1',inspected_at=inspected_at,
        input_database_sha256=before_sha,basis_plan_sha256=settings.plan_sha,source_revision=REVISION,
        japanese=settings.japanese,english=settings.english,by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
        japanese_coordinate_groups=len({(c['set_code'],c['collector_number']) for c,_,_ in japanese}),
        japanese_full_name_concepts=len({a['concept_id'] for _,a,_ in japanese}),english_full_name_concepts=settings.english,
        english_preliminary_candidates=len(pool),english_qualified_candidates=len(qualified),holds=holds,gaps=gaps,
        source_inventory={path:dict(git_blob=blobs[path],sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for path,raw in sorted(raws.items())},
        new_card_identities=0,new_concepts=0,new_review_events=0,new_counterpart_relationships=0,
        physical_distribution_region=None,historical_retrieval_time=None,
        selection_reason='Exact frozen remaining85 Japanese records;complete eligible groups;25 distinct existing reviewed-name English comparisons. No new translation or counterpart assertions.',
        demand='Japan-to-US discovery objective;set-level demand unmeasured',authorized_supply='metadata only;live Buy&Ship availability unknown')
    if profile is not None:
        selection.update(schema='pokemon.pokemon-name-profile-selection.v1',batch_profile=settings.name,
            selection_reason=f'Exact frozen {settings.japanese} Japanese records across {len(settings.sets)} named scopes;complete eligible groups;{settings.english} distinct existing reviewed-name English comparisons. No new translation or counterpart assertions.')
    if settings.strict_variant_dimensions:
        selection['strict_variant_dimensions'] = True
    if settings.expanded_batch:
        selection.update(expanded_batch=True,excluded_image_target_groups=expanded_excluded_groups(),
                         held_image_handoff_sha256=plan['held_image_handoff_sha256'],
                         frozen_english_pool_records=len(english_witnesses),release_header_inputs=len(plan['release_header_inventory']))
    return rows,selection,licence,plan_bytes


def build(db_path,repo,root,output,inspected_at, *, profile=None):
    if output.exists():raise FileExistsError('follow-up artifact directory already exists')
    rows,selection,licence,plan_bytes = compile(db_path,repo,root,inspected_at,profile=profile)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.pokemon-followup-',dir=output.parent))
    try:
        (temporary/'locales.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
        (temporary/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
        (temporary/'basis-plan.json').write_bytes(plan_bytes);(temporary/'TCGDEX-LICENSE').write_bytes(licence)
        if output.exists():raise FileExistsError('follow-up output appeared during compilation')
        os.rename(temporary,output)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return {k:selection[k] for k in ('japanese','english','by_set','english_qualified_candidates')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--inspected-at',required=True);a=p.parse_args()
    print(json.dumps(build(a.db,a.source_repo,Path.cwd(),a.output,a.inspected_at)))


if __name__=='__main__':main()
