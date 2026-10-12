"""Prove a bounded hold migration preserves everything except declared flags."""
import argparse,hashlib,json,shutil,tempfile
from contextlib import closing
from pathlib import Path
from pokemon_index import core,catalog_locale,variant_dimension_hold as holds,catalog_media
from scripts import audit_international_coverage_expansion as history
from scripts import build_variant_dimension_holds as compiler

DIRECTORY='catalog/variant-dimension-holds-v1'
MANIFEST='catalog-build-manifest-international-image-fix-v1.json'
PRIOR='catalog-build-manifest-international-pokemon-classic-v1.json'
GUARD_NAMES=('variant_dimension_hold_card_id','variant_dimension_hold_card_insert','variant_dimension_hold_card_update')


def installed(db,rows):
    with closing(core.connect(':memory:')) as reference:
        core.init_db(reference);holds.install_guards(reference)
        query="SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name IN (?,?,?) ORDER BY name"
        expected=[tuple(r) for r in reference.execute(query,GUARD_NAMES)]
    if [tuple(r) for r in db.execute(query,GUARD_NAMES)]!=expected:raise ValueError('installed hold retention guards differ')
    for row in rows:
        found=db.execute('SELECT quarantine_id,reason,record_json FROM catalog_identity_quarantine WHERE quarantine_id=?',(row['event_id'],)).fetchone()
        if not found or tuple(found)!=(row['event_id'],row['reason'],catalog_locale.encoded(row)):raise ValueError('installed hold SQL binding differs')
    return True


def inputs(root):
    prior=json.loads((root/PRIOR).read_text());manifest=json.loads((root/MANIFEST).read_text())
    expected={**prior['expected'],'match_eligible':prior['expected']['match_eligible']-9,
              'variant_dimension_hold_events':44,'variant_dimension_held_ids':44}
    if (len(prior['steps'])!=76 or len(manifest['steps'])!=77 or manifest['steps'][:-1]!=prior['steps']
            or manifest['expected']!=expected or manifest['steps'][-1]['operation']!='import-variant-dimension-holds'
            or manifest['steps'][-1]['path']!=DIRECTORY+'/holds.jsonl'):raise ValueError('hold manifest scope differs')
    for step in manifest['steps']:
        path=(root/step['path']).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=step['sha256']:raise ValueError('manifest source drift')
    rows=[json.loads(line) for line in (root/DIRECTORY/'holds.jsonl').read_text().splitlines()]
    if len(rows)!=44 or len({r['identity']['card_id'] for r in rows})!=44 or sum(r['prior_structural_match_eligible'] for r in rows)!=9:raise ValueError('hold cohort differs')
    return rows


def input_signatures(root):
    inputs(root)
    paths=[root/PRIOR,root/MANIFEST,root/compiler.AUDIT,
           *[root/DIRECTORY/name for name in ('holds.jsonl','selection.json','TCGDEX-LICENSE')]]
    return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def preservation(before,after,rows):
    if history.tables(before)!=history.tables(after):raise ValueError('hold table inventory changed')
    ids={r['identity']['card_id'] for r in rows};checks={}
    installed(after,rows)
    columns=[r[1] for r in before.execute('PRAGMA table_info(card)')]
    id_at=columns.index('card_id');match_at=columns.index('match_eligible');display_at=columns.index('display_allowed')
    for table in history.tables(before):
        old=history.records(before,table);new=history.records(after,table)
        if table=='card':
            expected=[]
            for record in old:
                values=list(record)
                if record[id_at] in ids:values[match_at]=0;values[display_at]=0
                expected.append(tuple(values))
            checks[table]=expected==new
        elif table=='catalog_identity_quarantine':
            checks[table]=new[:len(old)]==old and len(new)==len(old)+44
        else:checks[table]=old==new
    if not all(checks.values()):raise ValueError('unexpected history change: '+str([k for k,v in checks.items() if not v]))
    return checks


def append(before_path,output,root):
    if output.exists():raise FileExistsError('hold snapshot exists')
    rows=inputs(root);signatures=input_signatures(root)
    if hashlib.sha256(before_path.read_bytes()).hexdigest()!=compiler.BEFORE_SHA:raise ValueError('pre-hold snapshot differs')
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        pending=Path(directory)/'held.sqlite3';shutil.copyfile(before_path,pending)
        with closing(core.connect(pending)) as db:
            result=holds.import_evidence(db,rows)
            if result!=dict(inserted=44,unchanged=0,eligibility_withdrawn=9):raise ValueError('hold append differs')
        with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(pending,readonly=True)) as after:preservation(before,after,rows)
        if hashlib.sha256(before_path.read_bytes()).hexdigest()!=compiler.BEFORE_SHA or input_signatures(root)!=signatures:raise ValueError('append input drift')
        with output.open('xb') as handle:handle.write(pending.read_bytes())
    return result


def run(before_path,after_path,rebuilt_path,root):
    rows=inputs(root);evidence_signatures=input_signatures(root);paths=[before_path,after_path,rebuilt_path]
    signatures={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if signatures[str(before_path)]!=compiler.BEFORE_SHA:raise ValueError('pre-hold snapshot differs')
    with closing(core.connect(before_path,readonly=True)) as before,closing(core.connect(after_path,readonly=True)) as after,closing(core.connect(rebuilt_path,readonly=True)) as rebuilt:
        checks=preservation(before,after,rows);rebuild_checks={};timestamps={}
        installed(rebuilt,rows)
        for table in history.tables(after):
            left,right=history.records(after,table),history.records(rebuilt,table)
            if table in history.GENERATED_COLUMNS:
                column=history.GENERATED_COLUMNS[table];at=[r[1] for r in after.execute('PRAGMA table_info('+table+')')].index(column)
                timestamps[table]=dict(column=column,changed=sum(a[at]!=b[at] for a,b in zip(left,right)))
                left=[r[:at]+r[at+1:] for r in left];right=[r[:at]+r[at+1:] for r in right]
            rebuild_checks[table]=left==right
        if not all(rebuild_checks.values()):raise ValueError('hold rebuild differs')
        for db in (before,after,rebuilt):
            if list(db.execute('PRAGMA foreign_key_check')) or db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('snapshot integrity failure')
        for row in rows:
            if catalog_locale.snapshot(after,row['identity']['card_id'])!=row['identity']:raise ValueError('held ID was reassigned')
            if holds.context(after,row['identity']['card_id'])['status']!='held_legacy_variant_dimensions':raise ValueError('hold context is not current')
            if catalog_media.availability(after,row['identity']['card_id'])['status']!='identity_hold':raise ValueError('held media gate differs')
        report=dict(schema='pokemon.variant-dimension-hold-audit.v1',database_sha256=signatures,held_ids=44,
            evidence_input_sha256=evidence_signatures,installed_guard_definitions_verified=True,exact_installed_hold_sql_verified=True,
            structural_match_eligible_before=core.catalog_status(before)['match_eligible'],structural_match_eligible_after=core.catalog_status(after)['match_eligible'],
            renamed_ids=0,canonical_replacements=0,exact_identity_snapshots_preserved=True,expected_history_transform=checks,
            allowed_card_flag_downgrades=9,quarantine_appended=44,new_source_images=0,new_display_or_purchase_permissions=0,
            rebuild_tables_equal=rebuild_checks,rebuild_generated_timestamp_differences=timestamps,
            source_scan_coverage=catalog_media.status(after),manifest_inputs_before=76,manifest_inputs_after=77)
    with tempfile.TemporaryDirectory() as directory:
        scratch=Path(directory)/'repeat.sqlite3';shutil.copyfile(after_path,scratch)
        with closing(core.connect(scratch)) as db:
            original={t:history.records(db,t) for t in history.tables(db)};result=holds.import_evidence(db,rows)
            if result!=dict(inserted=0,unchanged=44,eligibility_withdrawn=0) or any(history.records(db,t)!=v for t,v in original.items()):raise ValueError('hold reimport changed history')
            report['idempotent_reimport']=result
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=signatures[str(p)] for p in paths) or input_signatures(root)!=evidence_signatures:raise ValueError('audited snapshot/evidence drift')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as f:f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('held_ids','allowed_card_flag_downgrades','structural_match_eligible_after','idempotent_reimport')}))


if __name__=='__main__':main()
