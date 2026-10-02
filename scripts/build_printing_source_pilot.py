"""Materialize reviewed publisher-image readings; never infer physical finishes.

The readings below were visually inspected, not extracted from image filenames.
Rebuilding verifies local image/page receipt hashes and the separate root review.
Images and raw HTML stay in the operator's cache, outside the deployable catalog.
"""
import argparse,json,hashlib,re
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from pokemon_index import core,printing_evidence,supported_catalog

ARTISTS={'48481':'5ban Graphics','50551':'Kazuki Minami','50555':'YOSHIROTTEN',
 '50556':'YOSHIROTTEN','50485':'HACCAN','50488':'AKIRA EGAWA','48000':'0313',
 '44406':'0313','49610':'Kariya','46352':'0313'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def build(db_path,page_cache,image_cache,root_review,output):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    reviewed=json.loads(root_review.read_text());root={r['native_id']:r for r in reviewed['rows']}
    if not reviewed['independent_visual_inspection_performed'] or reviewed['blinded']:raise ValueError('separate actual non-blinded inspection required')
    now=datetime.now(timezone.utc).isoformat();events=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        def source(n):
            page=json.loads((page_cache/(n+'.receipt.json')).read_text());image=json.loads((image_cache/(n+'.receipt.json')).read_text())
            if sha(page_cache/(n+'.html'))!=page['page_sha256'] or sha(image_cache/(n+'.jpg'))!=image['sha256']:raise ValueError('cached source hash differs')
            if image['url']!=root[n]['source']['url'] or image['sha256']!=root[n]['source']['sha256']:raise ValueError('second reviewer saw different image')
            if root[n]['uncertain'] or image['url'].replace('https://www.pokemon-card.com','') not in (page_cache/(n+'.html')).read_text():raise ValueError('image is not declared by exact publisher page or visual reading uncertain')
            return dict(url=page['url'],page_sha256=page['page_sha256'],fetched_at=page['fetched_at'],image_url=image['url'],image_sha256=image['sha256'])
        def coordinate(n):
            rows=db.execute('SELECT set_code,collector_number FROM card_reference WHERE native_id=? ORDER BY set_code,collector_number',(n,)).fetchall()
            # A wrongly assigned reference is retained as a held finding, not remapped.
            return 'ja:'+':'.join(rows[0])
        def reading(claim,value,src,code,number,locator):
            return dict(claim=claim,value=value,source_url=src['url'],locator=locator,
                coordinate=dict(language='ja',set_code=code,collector_number=number),scope='publisher_asset_only')
        def event(kind,subject,sources,observations,status='source_observed',hold=None):
            reviews=[]
            for actor,time in [('codex-printing-pilot-agent',now),(reviewed['reviewer'],reviewed['reviewed_at'])] if kind=='coordinate' and sources else [('codex-printing-pilot-agent',now)] if kind=='release' else []:
                reviews.append(dict(actor=actor,method='direct_image_reading' if kind=='coordinate' else 'official_release_text',reviewed_at=time,
                    source_image_sha256s=sorted(s['image_sha256'] for s in sources if s['image_sha256']),observations_sha256=supported_catalog.digest(observations)))
            row=dict(schema='pokemon.printing-source-evidence.v1',revision=1,subject_kind=kind,subject_id=subject,
                identity_sha256=supported_catalog.digest(printing_evidence.identity(db,kind,subject)),status=status,hold_reason=hold,sources=sources,
                observations=observations,reviewers=reviews,recorded_at=now,**{k:False for k in printing_evidence.FALSE_CLAIMS})
            row['event_id']=printing_evidence.event_id(row);events.append(row)
        for n,value in ARTISTS.items():
            s=source(n);subject=coordinate(n);_,code,number=subject.split(':')
            if root[n]['printed_artist']!=value or root[n]['printed_number']!=number:raise ValueError('artist visual reviews disagree')
            event('coordinate',subject,[s],[reading('printed_artist',value,s,code,number,'bottom-left Illus. credit in exact publisher image')])
        for n,number,qualifier in [('43125','021/SV-P','オーリム博士'),('43126','022/SV-P','フトゥー博士')]:
            s=source(n)
            if root[n]['printed_number']!=number or root[n]['printed_qualifier']!=qualifier or root[n]['printed_stamp']!='EVENT ORGANIZER':raise ValueError('qualifier visual reviews disagree')
            event('coordinate','ja:SV-P:'+number,[s],[reading('printed_qualifier',qualifier,s,'SV-P',number,'top-right printed subtitle; generic main title remains 博士の研究'),
                reading('printed_stamp','EVENT ORGANIZER',s,'SV-P',number,'lower-right gold publisher stamp')])
        sources=[source(n) for n in ['45643','45644']];observations=[]
        for n,s,number in zip(['45643','45644'],sources,['153/SV-P','154/SV-P']):
            if root[n]['printed_number']!=number or root[n]['printed_stamp']!='シールド戦':raise ValueError('mismatch visual reviews disagree')
            observations.extend([reading('printed_number',number,s,'SV-P',number,'bottom-left printed collector number'),
                reading('printed_stamp','シールド戦',s,'SV-P',number,'lower-right printed publisher tournament stamp')])
        event('coordinate','ja:SV-P:153/SV-P',sources,observations,'evidence_hold',
            'Reference 45644 visibly prints 154/SV-P, not target 153/SV-P. Retain wrong source reference; no automatic remapping.')
        for number in range(37,45):
            event('coordinate',f'ja:SV-P:{number:03}/SV-P',[],[],'evidence_hold',
                'Frozen source queue has no exact Japanese official reference. No printed-image reading; no substitute from another region.')
        for code,value,locator in [('SV8A','premium_mirror','mirror-section heading and descriptive image alt text'),
                ('SV2A','pokeball_pattern_mirror','mirror section text; release-level declaration only')]:
            receipt=json.loads((image_cache/(code.lower()+'.page-receipt.json')).read_text())
            raw=(image_cache/(code.lower()+'.html')).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=receipt['page_sha256']:raise ValueError('release page receipt differs')
            needles=['豪華プレミアムミラー仕様','特殊な加工'] if code=='SV8A' else ['モンスターボール柄の特殊な加工','豪華ミラー仕様']
            if any(x not in raw.decode() for x in needles):raise ValueError('manufacturer declaration absent')
            s=dict(**receipt,image_url=None,image_sha256=None)
            event('release','ja:'+code,[s],[dict(claim='manufacturer_finish_declaration',value=value,source_url=s['url'],locator=locator,coordinate=None,scope='release_only')])
    path=output/'evidence-v1.jsonl';path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    (output/'root-visual-review-v1.json').write_text(root_review.read_text())
    summary=dict(schema='pokemon.printing-source-pilot-summary.v1',events=len(events),source_observed=sum(r['status']=='source_observed' for r in events),
        evidence_holds=sum(r['status']=='evidence_hold' for r in events),printed_artist_readings=10,qualified_name_readings=2,
        publisher_stamp_readings=4,wrong_number_references=1,manufacturer_release_declarations=2,distinct_images_reviewed=14,
        two_distinct_source_inspections=True,blind_review=False,independent_population_accuracy_measurement=False,
        physical_printing_approvals=0,actual_seller_copy_approvals=0,evidence_sha256=sha(path),root_review_sha256=sha(root_review),
        interpretation='13 publisher-image events have two actual inspections. Two release-level declarations have one text inspection. Eight absent-reference holds have no image review. All physical/copy/offer permissions remain false.')
    (output/'summary-v1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['db','page-cache','image-cache','root-review','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.db,a.page_cache,a.image_cache,a.root_review,a.output),indent=2))
