"""Compile a frozen image-research expansion as append-only proposed evidence.

No AI agreement promotes a finding. Official captions are checked separately.
Omitted species remain unresolved, rather than becoming negative evidence.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,re
from contextlib import closing
from pathlib import Path
from pokemon_index import core,collector_evidence,supported_catalog
from scripts.build_collector_evidence import fetch
from scripts.public_question_sandbox import read_jsonl,sha_file


def qualified(row,queued):
    f=row.get('finding',{})
    return (row['status']=='reviewed' and f.get('identity_match')=='match'
        and f['read_name'].strip()==queued['identity']['name']
        and core.normalize_collector_number(re.sub(r'\s+','',f['read_number'])).upper()==queued['identity']['collector_number']
        and row['identity_sha256']==queued['identity_sha256'])


def key(r):
    return collector_evidence._key(r)


def pairs(r):
    return {(d['dex_id'],d['role']) for d in r.get('finding',{}).get('depictions',[])}


def build(db_path,directory):
    output=directory/'evidence-events.jsonl'
    if output.exists():raise FileExistsError(output)
    queue_path=directory/'visual-queue.jsonl';queue={r['card_id']:r for r in read_jsonl(queue_path)}
    reviewed=read_jsonl(directory/'gemini-visual-review.jsonl')
    protocol_sha=sha_file(directory/'gemini-visual-review.protocol.json')
    if len(reviewed)!=len(queue) or {r['card_id'] for r in reviewed}!=set(queue):raise ValueError('review coverage differs')
    if any(r['queue_sha256']!=sha_file(queue_path) or r.get('protocol_sha256')!=protocol_sha for r in reviewed):raise ValueError('review protocol differs')
    by_id={r['card_id']:r for r in reviewed}
    codex_file=directory/'codex-visual-audit.json';codex=json.loads(codex_file.read_text())
    if codex['protocol_sha256']!=sha_file(directory/'codex-audit-protocol.json'):raise ValueError('Codex protocol differs')
    audit_by_id={r['card_id']:r for r in codex['findings']}
    old_review=read_jsonl(Path('catalog/collector-evidence-v1/gemini-visual-review.jsonl'))
    events=[];excluded=[];comparisons=[]
    with closing(core.connect(db_path,readonly=True)) as db:
        prior={key(r):r for r in collector_evidence.records(db)}
        def append(subject,claim,value,role,status,evidence,identity_sha):
            r=dict(schema='pokemon.collector-evidence.v1',subject_kind='card',subject_id=subject,
                claim=claim,value=value,role=role,status=status,identity_sha256=identity_sha,
                evidence=evidence,actor='collector-evidence-v2',recorded_at='2026-10-01T08:00:00+00:00')
            head=prior.get(key(r));r['expected_head']=head['event_id'] if head else None
            r['event_id']='colevidence-v2:'+supported_catalog.digest(r)[:32]
            if any(key(x)==key(r) for x in events):raise ValueError('duplicate expansion finding')
            events.append(r)
        def audit_context(cid,image_sha,dex,role):
            fresh=by_id[cid];a=audit_by_id.get(cid)
            context=dict(re_enumeration='returned' if (dex,role) in pairs(fresh) and qualified(fresh,queue[cid]) else 'not_returned_or_unresolved',
                same_model_family_replication=True,ai_agreement_is_accuracy=False)
            if a:
                if a['image_sha256']!=image_sha or a['identity_match']!='match':raise ValueError('Codex image binding differs')
                context.update(codex_visual_support='identified' if (dex,role) in {(d['dex_id'],d['role']) for d in a['depictions']} else 'not_identified_or_uncertain',
                    codex_audit_sha256=sha_file(codex_file),codex_uncertainties=a['uncertainties'],human_review=False)
            return context
        for r in reviewed:
            cid=r['card_id'];q=queue[cid]
            if not qualified(r,q):
                excluded.append(dict(card_id=cid,status=r['status'],reason=r.get('validation_error','review or printed identity unresolved')));continue
            image=r['image_evidence'];page=r['official_identity']
            for d in r['finding']['depictions']:
                e=dict(kind='ai_visual',source_url=page['url'],source_page_sha256=page['page_sha256'],
                    official_card_url=page['url'],official_card_page_sha256=page['page_sha256'],
                    image_url=image['image_url'],image_sha256=image['image_sha256'],locator='illustrated scene only',
                    finding=d['name']+': '+d['detail'],review={k:r[k] for k in ['model','prompt_version','prompt_sha256','response_sha256']})
                e['review'].update(identity_match='match',uncertainties=r['finding']['uncertainties'],
                    protocol_sha256=protocol_sha,audit=audit_context(cid,image['image_sha256'],d['dex_id'],d['role']))
                append(cid,'depicted_pokemon',d['dex_id'],d['role'],'proposed',e,q['identity_sha256'])
        # Annotate old findings omitted by the new enumeration without claiming
        # absence or erasing historical evidence. Append, never rewrite v1.
        new_keys={key(r) for r in events}
        for k,old in prior.items():
            if old['evidence']['kind']!='ai_visual' or old['subject_id'] not in queue or k in new_keys:continue
            cid=old['subject_id'];e=copy.deepcopy(old['evidence'])
            e['review']['audit']=audit_context(cid,e['image_sha256'],old['value'],old['role'])
            append(cid,old['claim'],old['value'],old['role'],'proposed',e,old['identity_sha256'])
        # Operator-inspected preview bindings, frozen before compiling. Captions
        # name the scene species; exact preview numbers were read from the image.
        bindings=json.loads((directory/'official-caption-bindings.json').read_text())
        pages={}
        for b in bindings['bindings']:
            cid=b['card_id'];r=by_id[cid];q=queue[cid]
            if not qualified(r,q):raise ValueError('caption card identity lacks valid image review')
            url=b['source_url'];raw=pages.setdefault(url,fetch(url))
            text=raw.decode();region=re.search(re.escape(b['preview_asset'])+r'.*?<p[^>]*>(.*?)</p>',text,re.S)
            if region is None:raise ValueError('caption region missing')
            caption=re.sub(r'<[^>]+>','',region[1]);preview=fetch(b['preview_url'])
            if hashlib.sha256(preview).hexdigest()!=b['preview_sha256']:raise ValueError('caption preview changed')
            for d in b['depictions']:
                if d['name_ja'] not in caption:raise ValueError('caption does not name declared character')
                e=dict(kind='official_description',source_url=url,source_page_sha256=hashlib.sha256(raw).hexdigest(),
                    official_card_url=r['official_identity']['url'],official_card_page_sha256=r['official_identity']['page_sha256'],
                    image_url=r['image_evidence']['image_url'],image_sha256=r['image_evidence']['image_sha256'],
                    locator=b['preview_asset']+' and adjacent scene caption',
                    finding='Official scene caption identifies '+d['name_ja']+' in the illustrated scene.',
                    declared_character_ja=d['name_ja'],preview_url=b['preview_url'],preview_sha256=b['preview_sha256'],
                    source_binding='Operator read exact preview number/name; pinned official detail and image identity checked. Does not certify physical finish or copy.')
                append(cid,'depicted_pokemon',d['dex_id'],d['role'],'source_supported',e,q['identity_sha256'])
        for old in old_review:
            cid=old['card_id'];fresh=by_id[cid];a=audit_by_id.get(cid)
            comparisons.append(dict(card_id=cid,old_status=old['status'],fresh_status=fresh['status'],
                old_image_sha256=old.get('image_evidence',{}).get('image_sha256'),
                fresh_image_sha256=fresh.get('image_evidence',{}).get('image_sha256'),
                old_pairs=sorted(pairs(old)),fresh_pairs=sorted(pairs(fresh)),
                fresh_only_pairs=sorted(pairs(fresh)-pairs(old)),old_not_returned_pairs=sorted(pairs(old)-pairs(fresh)),
                codex_pairs=sorted((d['dex_id'],d['role']) for d in a['depictions']) if a else None,
                codex_uncertainties=a['uncertainties'] if a else None))
        before_events=db.execute('SELECT COUNT(*) FROM catalog_collector_evidence').fetchone()[0]
    # Validate the entire append chain in a disposable database before publishing.
    with closing(core.connect(':memory:')) as scratch,closing(core.connect(db_path,readonly=True)) as original:
        original.backup(scratch);collector_evidence.import_evidence(scratch,events)
        active=collector_evidence.status(scratch)
        final_events=scratch.execute('SELECT COUNT(*) FROM catalog_collector_evidence').fetchone()[0]
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in events))
    report=dict(schema='pokemon.collector-evidence-expansion-audit.v1',visual_targets=len(queue),new_targets=len(queue)-len(old_review),
        sets=sorted({q['identity']['set_code'] for q in queue.values()}),qualified_reviews=sum(qualified(r,queue[r['card_id']]) for r in reviewed),
        excluded=excluded,codex_sample=len(audit_by_id),comparisons=comparisons,
        appended_events=len(events),prior_events=before_events,total_events=final_events,active=active,
        source_supported_added=sum(r['status']=='source_supported' for r in events),events_sha256=sha_file(output),
        queue_sha256=sha_file(queue_path),protocol_sha256=protocol_sha,review_sha256=sha_file(directory/'gemini-visual-review.jsonl'),
        codex_audit_sha256=sha_file(codex_file),images_redistributed=False,
        interpretation='Purposive expansion plus deterministic AI sample audit. Gemini repeat passes share a model family; Codex is another AI with known prior official captions. No human truth set or population precision; all image-only findings remain proposed. Omission is not absence.')
    (directory/'build-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['visual_targets','new_targets','qualified_reviews','appended_events','source_supported_added','total_events','active']}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();build(a.db,a.directory)
