"""Audit the exact frozen 85-Japanese/25-English follow-up without SKU merges."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from scripts import audit_international_coverage_expansion as history
from scripts import build_pokemon_name_followup as compiler
from scripts.build_international_coverage_expansion import RetrievalScope

MANIFEST = 'catalog-build-manifest-international-pokemon-followup-v1.json'
PRIOR = 'catalog-build-manifest-international-pokemon-thousand-v1.json'
LOCALES = compiler.DIRECTORY+'/locales.jsonl'
SCOPE = RetrievalScope('pokemon-name-followup',compiler.SETS,compiler.JAPANESE)
PROFILE = history.AuditProfile(PRIOR,MANIFEST,LOCALES,72,SCOPE,True)


def checked_name_scopes(rows,plan, *, english=compiler.ENGLISH):
    if any(not isinstance(r.get('name_aliases'),list) or len(r['name_aliases'])!=1 for r in rows):
        raise ValueError('one exact reviewed alias required per record')
    if ([r['identity'] for r in rows if r['identity']['language']=='ja'] != [r['card'] for r in plan['records']]
            or len({r['name_aliases'][0]['concept_id'] for r in rows if r['identity']['language']=='en'})!=english):
        raise ValueError('frozen identities or distinct English comparisons differ')
    for row in rows:
        scope = row.get('character_scope',{})
        if (scope.get('category')!='Pokemon' or scope.get('form_inheritance_allowed') is not False
                or scope.get('full_name')!=row['identity']['name'] or type(scope.get('dex_id')) is not int
                or not 1<=scope['dex_id']<=151 or len(row['name_aliases'])!=1 or row['name_aliases'][0]['category']!='Pokemon'):
            raise ValueError('literal Pokemon name scope differs')
    japanese = [r for r in rows if r['identity']['language']=='ja']
    concepts = {}
    for row,item in zip(japanese,plan['records']):
        pair = item['full_name_pair'];alias = row['name_aliases'][0]
        if (row['character_scope']['dex_id']!=pair['dex_id']
                or alias['name_ja']!=pair['name_ja'] or alias['name_en']!=pair['name_en']):
            raise ValueError('locale name/Dex differs from frozen planned pair')
        if 'name_alias' in item and alias!=item['name_alias']:
            raise ValueError('locale alias revision differs from frozen planned review')
        if 'frozen_source' in item:
            source=row['source'];expected={k:source[k] for k in ('native_id','git_blob','sha256','rights_reference','license_sha256')}
            expected['source_revision']=source['revision']
            if expected!=item['frozen_source']:raise ValueError('locale source witness differs from frozen proposal')
        expected = (alias,pair['dex_id'])
        if alias['concept_id'] in concepts and concepts[alias['concept_id']]!=expected:
            raise ValueError('planned concept maps to conflicting exact names/Dex')
        concepts[alias['concept_id']]=expected
    for row in rows:
        if row['identity']['language']=='en':
            alias=row['name_aliases'][0]
            if concepts.get(alias['concept_id'])!=(alias,row['character_scope']['dex_id']):
                raise ValueError('English comparison outside exact planned Japanese concept scope')


def settings_for(profile,audit_profile):
    settings=compiler.profile_or_default(profile)
    auditing=history.profile_or_default(PROFILE if audit_profile is None else audit_profile)
    expected_scope=RetrievalScope(settings.name,settings.sets,settings.japanese,settings.english,settings.expanded_batch)
    if (auditing.locales!=settings.directory+'/locales.jsonl' or auditing.scope!=expected_scope
            or auditing.allow_bound_name_resolution_growth is not True):
        raise ValueError('compiler and audit profile scope differs')
    return settings,auditing


def inputs(root, *, profile=None, audit_profile=None):
    settings,auditing=settings_for(profile,audit_profile)
    directory = root/settings.directory
    raw = (directory/'basis-plan.json').read_bytes();plan = compiler.checked_plan(raw,profile=settings)
    if raw != (root/settings.plan).read_bytes():raise ValueError('frozen basis plan differs from prior review')
    rows = [json.loads(line) for line in (directory/'locales.jsonl').read_text().splitlines()]
    history.bounded(rows,scope=auditing.scope);checked_name_scopes(rows,plan,english=settings.english)
    if settings.expanded_batch:
        excluded=compiler.checked_expanded_exclusions(plan)
        english_witnesses=compiler.expanded_english_witnesses(plan)
        if any(tuple(row['identity'][k] for k in ('language','set_code','collector_number')) in excluded for row in rows):
            raise ValueError('expanded locale includes a priority-image coordinate group')
        image=(root/compiler.EXPANDED_IMAGE_HANDOFF).read_bytes()
        if hashlib.sha256(image).hexdigest()!=plan.get('held_image_handoff_sha256'):
            raise ValueError('expanded priority-image source witness differs')
        for row in rows:
            if row['identity']['language']=='en':
                frozen=english_witnesses.get(row['identity']['card_id'])
                if (frozen is None or frozen['identity']!=row['identity'] or frozen['name_alias']!=row['name_aliases'][0]
                        or frozen['dex_id']!=row['character_scope']['dex_id'] or frozen['release_snapshot']!=row['release_snapshot']
                        or any(frozen[k]!=row['source'][k] for k in ('native_id','git_blob','sha256','rights_reference','license_sha256'))
                        or frozen['source_revision']!=row['source']['revision']):
                    raise ValueError('locale differs from frozen qualified English witness')
    prior = json.loads((root/auditing.prior_manifest).read_text());manifest = json.loads((root/auditing.manifest).read_text())
    if (len(prior['steps'])!=auditing.prior_inputs or len(manifest['steps'])!=auditing.prior_inputs+1 or manifest['steps'][:-1]!=prior['steps']
            or manifest['expected']!=prior['expected'] or manifest['steps'][-1]['operation']!='import-catalog-locales'
            or manifest['steps'][-1]['path']!=auditing.locales):
        raise ValueError('follow-up manifest prefix or inventory differs')
    # Audit/report prose is an output, never a recursively hashed compiler input.
    paths = [root/auditing.prior_manifest,root/auditing.manifest,root/settings.plan,
             *sorted(directory/name for name in ('basis-plan.json','locales.jsonl','selection.json','TCGDEX-LICENSE'))]
    if settings.expanded_batch:paths.append(root/compiler.EXPANDED_IMAGE_HANDOFF)
    for step in manifest['steps']:
        path = (root/step['path']).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=step['sha256']:
            raise ValueError('manifest input hash/path differs')
    return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def append(before_path, output, root, *, profile=None, audit_profile=None):
    if output.exists():raise FileExistsError('follow-up snapshot already exists')
    settings,auditing=settings_for(profile,audit_profile)
    kwargs={} if profile is None and audit_profile is None else dict(profile=settings,audit_profile=auditing)
    signatures = inputs(root,**kwargs)
    if hashlib.sha256(before_path.read_bytes()).hexdigest()!=settings.before_sha:
        raise ValueError('immutable input snapshot differs')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        scratch = Path(directory)/'candidate.sqlite3'
        result = history.append(before_path,scratch,root,profile=auditing)
        if inputs(root,**kwargs)!=signatures:raise ValueError('follow-up evidence drifted during append')
        with output.open('xb') as handle:handle.write(scratch.read_bytes())
    return result


def run(before_path, after_path, rebuilt_path, root, *, profile=None, audit_profile=None):
    settings,auditing=settings_for(profile,audit_profile)
    kwargs={} if profile is None and audit_profile is None else dict(profile=settings,audit_profile=auditing)
    signatures = inputs(root,**kwargs)
    if hashlib.sha256(before_path.read_bytes()).hexdigest()!=settings.before_sha:
        raise ValueError('immutable input snapshot differs')
    report = history.run(before_path,after_path,rebuilt_path,root,profile=auditing)
    if inputs(root,**kwargs)!=signatures:raise ValueError('follow-up evidence drifted during audit')
    report.update(schema='pokemon.pokemon-name-followup-audit.v1',basis_plan_sha256=settings.plan_sha,
                  new_name_concepts=0,new_review_events=0,evidence_input_sha256=signatures)
    if profile is not None:report.update(schema='pokemon.pokemon-name-profile-audit.v1',batch_profile=settings.name)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();report=run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__=='__main__':main()
