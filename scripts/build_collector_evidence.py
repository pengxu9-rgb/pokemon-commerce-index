"""Compile the scoped collector evidence packet; never promote AI findings."""
from __future__ import annotations
import argparse,hashlib,json,re,urllib.request
from pathlib import Path
from contextlib import closing
from pokemon_index import core,supported_catalog
from scripts.public_question_sandbox import read_jsonl,sha_file

def fetch(url):
    with urllib.request.urlopen(url,timeout=25) as r:
        if r.geturl()!=url:raise ValueError('official asset redirected')
        b=r.read(2000001)
    if len(b)>2000000:raise ValueError('oversized official evidence')
    return b

def event(subject,claim,value,role,status,evidence,identity_sha):
    row=dict(schema='pokemon.collector-evidence.v1',subject_kind='card' if claim=='depicted_pokemon' else 'release',
        subject_id=subject,claim=claim,value=value,role=role,status=status,identity_sha256=identity_sha,
        evidence=evidence,actor='collector-evidence-v1',recorded_at='2026-10-01T00:00:00+00:00',expected_head=None)
    row['event_id']='colevidence-v1:'+supported_catalog.digest(row)[:32]
    return row

def build(db_path,directory):
    output=directory/'evidence-events.jsonl'
    if output.exists():raise FileExistsError(output)
    queue={r['card_id']:r for r in read_jsonl(directory/'visual-queue.jsonl')}
    reviewed=read_jsonl(directory/'gemini-visual-review.jsonl')
    if {r['card_id'] for r in reviewed}!=set(queue) or len(reviewed)!=len(queue):raise ValueError('review coverage differs')
    by_id={r['card_id']:r for r in reviewed};events=[];excluded=[]
    for r in reviewed:
        if r['queue_sha256']!=sha_file(directory/'visual-queue.jsonl'):raise ValueError('review queue changed')
        q=queue[r['card_id']];f=r.get('finding',{})
        if (r['status']!='reviewed' or f.get('identity_match')!='match'
                or f['read_name'].strip()!=q['identity']['name']
                or core.normalize_collector_number(re.sub(r'\s+','',f['read_number'])).upper()!=q['identity']['collector_number']):
            excluded.append(dict(card_id=r['card_id'],status=r['status'],reason='review or printed identity unresolved'));continue
        image=r['image_evidence'];page=r['official_identity']
        for d in f['depictions']:
            e=dict(kind='ai_visual',source_url=page['url'],source_page_sha256=page['page_sha256'],
                official_card_url=page['url'],official_card_page_sha256=page['page_sha256'],
                image_url=image['image_url'],image_sha256=image['image_sha256'],locator='illustrated scene only',
                finding=d['name']+': '+d['detail'],review={k:r[k] for k in ['model','prompt_version','prompt_sha256','response_sha256']})
            e['review'].update(identity_match='match',uncertainties=f['uncertainties'])
            events.append(event(r['card_id'],'depicted_pokemon',d['dex_id'],d['role'],'proposed',e,q['identity_sha256']))
    url='https://www.pokemon-card.com/ex/sv2a/index.html'
    page=fetch(url);page_sha=hashlib.sha256(page).hexdigest();text=page.decode()
    # Bound captions to two exact preview assets, not to every card of the species.
    descriptions=[('ja:SV2A:173/165:holo','ar-card-1.png',[ (25,'ピカチュウ','subject'),(58,'ガーディ','cameo'),(39,'プリン','cameo'),(94,'ゲンガー','cameo'),(12,'バタフリー','cameo')]),
                  ('ja:SV2A:180/165:holo','ar-card-3.png',[(138,'オムナイト','subject'),(140,'カブト','cameo'),(139,'オムスター','cameo')])]
    for cid,asset,depictions in descriptions:
        region=re.search(re.escape(asset)+r'.*?<p>(.*?)</p>',text,re.S)
        if region is None:raise ValueError('official description missing')
        image_url=url.rsplit('/',1)[0]+'/assets/images/'+asset
        image_sha=hashlib.sha256(fetch(image_url)).hexdigest()
        record=by_id[cid]['official_identity']
        for dex,name,role in depictions:
            # Subject name appears in the heading, cameo names in the caption.
            if role=='cameo' and name not in region[1]:raise ValueError('caption does not support character')
            e=dict(kind='official_description',source_url=url,source_page_sha256=page_sha,
                image_url=image_url,image_sha256=image_sha,official_card_url=record['url'],
                official_card_page_sha256=record['page_sha256'],locator='AR section preview '+asset+' and adjacent caption',
                finding='The official illustration heading/caption names '+name+' in this scene.',
                declared_character_ja=name,source_binding='Release preview number/name and exact card detail identity checked; does not bind foil or a physical copy.')
            events.append(event(cid,'depicted_pokemon',dex,role,'source_supported',e,queue[cid]['identity_sha256']))
    if 'モンスターボール柄の特殊な加工' not in text:raise ValueError('release finish declaration missing')
    with closing(core.connect(db_path,readonly=True)) as db:
        from pokemon_index.collector_evidence import identity
        e=dict(kind='official_release_text',source_url=url,source_page_sha256=page_sha,
            locator='anchor-mirror section',finding='The release page declares a Poké Ball patterned mirror treatment. It does not enumerate every eligible card or all finishes.')
        events.append(event('ja:SV2A','finish_exists','reverse_pokeball','release_declaration','source_supported',e,
            supported_catalog.digest(identity(db,'release','ja:SV2A'))))
    events.sort(key=lambda r:r['event_id'])
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    official={(r['subject_id'],r['value']) for r in events if r['status']=='source_supported' and r['claim']=='depicted_pokemon'}
    model={(r['subject_id'],r['value']) for r in events if r['status']=='proposed'}
    audit=dict(visual_targets=len(queue),model_reviews_completed=sum(r['status']=='reviewed' for r in reviewed),
        excluded=excluded,source_supported=sum(r['status']=='source_supported' for r in events),
        proposed=sum(r['status']=='proposed' for r in events),
        official_named_depictions_not_returned_by_model=[dict(card_id=cid,dex_id=dex) for cid,dex in sorted(official-model)],
        events_sha256=sha_file(output),queue_sha256=sha_file(directory/'visual-queue.jsonl'),
        review_sha256=sha_file(directory/'gemini-visual-review.jsonl'),images_redistributed=False,
        interpretation='Source declarations and proposed visual findings; purposive non-blind diagnostic, not depiction precision, physical printing verification or graph-pair promotion.')
    (directory/'build-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:audit[k] for k in ['visual_targets','model_reviews_completed','source_supported','proposed']}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();build(a.db,a.directory)
