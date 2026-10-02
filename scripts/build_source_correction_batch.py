"""Derive scoped correction proposals from already imported actual image reviews."""
import argparse,hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from pokemon_index import source_corrections,printing_evidence,core,supported_catalog
from scripts.audit_japanese_metadata_batch import parse_page


def build(db_path,cache,output):
    if output.exists():raise FileExistsError(output)
    db=core.connect(db_path,readonly=True);rows=[];recorded_at=datetime.now(timezone.utc).isoformat()
    for parent in printing_evidence.records(db):
        if parent['subject_kind']!='coordinate' or not parent['current_identity'] or len(parent['reviewers'])<2:continue
        language,code,number=parent['subject_id'].split(':');original=dict(parent);original.pop('current_identity');encoded=db.execute('SELECT record_json FROM printing_source_evidence WHERE event_id=?',(parent['event_id'],)).fetchone()[0]
        kinds={o['claim'] for o in parent['observations']}&{'printed_artist','printed_qualifier'}
        if parent['subject_id']=='ja:SV-P:153/SV-P':kinds={'reference_boundary'}
        for kind in sorted(kinds):
            r=dict(schema='pokemon.source-correction.v1',revision=1,kind=kind,language=language,set_code=code,collector_number=number,
                correction_key=':'.join([kind,language,code,number]),snapshot=source_corrections.snapshot(db,language,code,number),
                parent_event_id=parent['event_id'],parent_record_json=encoded,parent_record_sha256=supported_catalog.digest(original),
                value=None,reference_exclusion=None,new_card=None,new_reference=None,official_page=None,recorded_at=recorded_at,
                **{k:False for k in source_corrections.FALSE_CLAIMS})
            if kind!='reference_boundary':
                readings=[o for o in parent['observations'] if o['claim']==kind];values={o['value'] for o in readings}
                if len(values)!=1:raise ValueError('conflicting printed review value')
                r['value']=next(iter(values))
            else:
                native='45644';source=next(s for s in parent['sources'] if s['url'].endswith('/'+native));raw=(cache/(native+'.html')).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=source['page_sha256']:raise ValueError('wrong-reference official cache differs')
                page={**parse_page(raw),**source};new_number=page['numbered_entries'][0]['collector_number'];variant='official_coordinate_family_only_'+native
                provenance='official-printed-coordinate:'+native+':page-sha256:'+source['page_sha256']+':image-sha256:'+source['image_sha256']+':parent:'+parent['event_id']
                attrs=json.dumps(dict(family_scope_only=True,parent_printing_event=parent['event_id'],source_namespace='official-printed-coordinate',physical_finish_verified=False,listing_copy_verified=False),ensure_ascii=False,sort_keys=True)
                r['reference_exclusion']=dict(source='ptcg-database',native_id=native,set_code=code,collector_number=number)
                r['new_card']=dict(card_id=core.card_id('ja',code,new_number,variant),language='ja',set_code=code,collector_number=new_number,variant=variant,name=page['name'],rarity=None,provenance=provenance,rights_reference=source['url'],display_allowed=0,match_eligible=0,attributes_json=attrs)
                r['new_reference']=dict(source='official-printed-coordinate',native_id=native,set_code=code,collector_number=new_number,name=page['name'],rarity=None,attributes_json=attrs,provenance=provenance,rights_reference=source['url'],display_allowed=0)
                r['official_page']=page
            r['event_id']=source_corrections.event_id(r);rows.append(r)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    report=dict(schema='pokemon.source-correction-build.v1',corrections=len(rows),kinds={kind:sum(r['kind']==kind for r in rows) for kind in source_corrections.KINDS},new_family_records=sum(r['new_card'] is not None for r in rows),approved_physical_printings=0,metadata_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),scope='Derived from imported actual publisher-image reviewers; preserve seed and HTML conflicts, never blind semantic accuracy')
    output.with_suffix('.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','cache','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.db,a.cache,a.output),ensure_ascii=False,indent=2))
