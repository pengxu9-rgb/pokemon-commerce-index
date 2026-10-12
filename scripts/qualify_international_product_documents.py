"""Qualify three pinned provider documents and four bounded anchor outcomes.

Provider header facts are not publisher-product or cross-provider card bindings.
This offline compiler has no database-write, network or promotion path.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

from pokemon_index import catalog_locale, tcgdex_source
from pokemon_index.languages import normalize_language
from scripts import plan_international_release_evidence as readiness

REVISION='a211f11f3ba57d56c65c5ac33be35b77d3280757'
PATHS={'DS':'data-asia/BW/DS.ts','SC':'data-asia/BW/SC.ts','LL':'data-asia/L/LL.ts'}
ANCHORS={'SMH':'35030','DS':'27836','SC':'28616','LL':'26001'}


def git_tree(repo,paths,*,revision=REVISION):
    # A partial clone must never turn an offline pin check into a network call.
    # Reject any additional remote; origin is overridden only for this process.
    if not re.fullmatch(r'[0-9a-f]{40}',revision):raise ValueError('full pinned revision required')
    remotes=subprocess.check_output(['git','remote'],cwd=repo,text=True).splitlines()
    if any(remote!='origin' for remote in remotes):
        raise ValueError('offline pin check supports only the existing origin remote')
    command=['git','-c','remote.origin.url=/dev/null','-c','remote.origin.promisor=false','-c','core.quotepath=false',
             'ls-tree','-r',revision,'--',*paths]
    output=subprocess.check_output(command,cwd=repo,text=True,
        env={**os.environ,'GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0'})
    entries={}
    for line in output.splitlines():
        meta,path=line.split('\t',1);mode,kind,blob=meta.split()
        if mode!='100644' or kind!='blob' or path in entries:
            raise ValueError('unsupported or duplicate pinned source entry')
        entries[path]=blob
    return entries


def checked_source(repo,path,blob):
    target=repo/path
    if not target.resolve().is_relative_to(repo.resolve()):
        raise ValueError('pinned source path escapes checkout')
    raw=target.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=blob:
        raise ValueError('source bytes differ from pinned Git blob')
    return raw


def string_map(body):
    if body is None:
        raise ValueError('localized source field is missing')
    pattern=re.compile(r'\s*([a-z][a-z0-9-]*)\s*:\s*'+tcgdex_source.LITERAL+r'\s*(?:,|$)')
    fields={};offset=0
    while body[offset:].strip():
        match=pattern.match(body,offset)
        if not match:
            raise ValueError('unsupported localized source syntax')
        language=normalize_language(match[1]);value=ast.literal_eval(match[2])
        if language in fields or not isinstance(value,str) or not value.strip():
            raise ValueError('duplicate or empty localized source field')
        fields[language]=value;offset=match.end()
    if not fields:
        raise ValueError('localized source field is empty')
    return fields


def header_fields(source, *, declaration_name='set', declaration_type='Set'):
    # Discover the exported top-level declaration outside comments and strings.
    # Retain literal bytes only in the separate extraction copy. Never execute TS.
    if (declaration_name,declaration_type) not in {('set','Set'),('card','Card')}:
        raise ValueError('unsupported metadata object declaration')
    clean=list(source);masked=list(source);offset=0
    while offset<len(source):
        start=offset;comment=False
        if source.startswith('//',offset):
            newline=source.find('\n',offset);offset=len(source) if newline<0 else newline;comment=True
        elif source.startswith('/*',offset):
            end=source.find('*/',offset+2)
            if end<0:raise ValueError('unclosed TypeScript comment')
            offset=end+2;comment=True
        elif source[offset] in ('\"',"'",'`'):
            quote=source[offset];offset+=1
            while offset<len(source):
                if source[offset]=='\\':offset+=2
                elif source[offset]==quote:offset+=1;break
                elif source[offset]=='\n' and quote!='`':raise ValueError('unclosed TypeScript string')
                else:offset+=1
            else:raise ValueError('unclosed TypeScript string')
        else:offset+=1;continue
        for index in range(start,min(offset,len(source))):
            if source[index]!='\n':
                masked[index]=' '
                if comment:clean[index]=' '
    source=''.join(clean);masked=''.join(masked)
    pattern=r'\bconst\s+'+declaration_name+r'\s*:\s*'+declaration_type+r'\s*=\s*\{'
    roots={m.start():m for m in re.finditer(pattern,masked)};top_roots=[];stack=[]
    for index,char in enumerate(masked):
        if index in roots and not stack:top_roots.append(roots[index])
        if char in '{[(':stack.append(char)
        elif char in '}])':
            if not stack or stack.pop()!={'}':'{',']':'[',')':'('}[char]:
                raise ValueError('unbalanced TypeScript source')
    if stack:raise ValueError('unclosed TypeScript source')
    if len(top_roots)!=1:raise ValueError('single top-level set object declaration required')
    root=top_roots[0]
    body=tcgdex_source._balanced(source,root.end()-1,'{','}')
    tail=masked[root.end()+len(body)+1:]
    if not re.fullmatch(r'\s*;?\s*export\s+default\s+'+declaration_name+r'\s*;?\s*',tail):
        raise ValueError('supported top-level default set export required')
    fields={};start=0;offset=0;stack=[]
    while offset<=len(body):
        if offset==len(body) or (body[offset]==',' and not stack):
            part=body[start:offset].strip();start=offset+1
            if part:
                match=re.fullmatch(r'([A-Za-z_$][\w$]*)\s*:\s*([\s\S]+)',part)
                if not match or match[1] in fields:
                    raise ValueError('unsupported or duplicate top-level set property')
                fields[match[1]]=match[2].strip()
            offset+=1;continue
        if body[offset] in ('\"',"'",'`'):
            quote=body[offset];offset+=1
            while offset<len(body):
                if body[offset]=='\\':offset+=2
                elif body[offset]==quote:offset+=1;break
                else:offset+=1
            else:raise ValueError('unclosed set property string')
            continue
        char=body[offset]
        if char in '{[(':stack.append(char)
        elif char in '}])':
            if not stack or stack.pop()!={'}':'{',']':'[',')':'('}[char]:
                raise ValueError('unbalanced set property')
        offset+=1
    if stack:raise ValueError('unclosed set property')
    return fields


def parse_header(raw):
    fields=header_fields(raw.decode('utf-8'))
    def literal(key):
        value=fields.get(key)
        if value is None:return None
        if not re.fullmatch(tcgdex_source.LITERAL,value):
            raise ValueError('unsupported source literal for '+key)
        return ast.literal_eval(value)
    def object_body(key):
        value=fields.get(key)
        if value is None:return None
        if not value.startswith('{') or not value.endswith('}'):
            raise ValueError('unsupported source object for '+key)
        body=tcgdex_source._balanced(value,0,'{','}')
        if len(body)+2!=len(value):raise ValueError('unsupported source object suffix')
        return body
    set_id=literal('id')
    names=string_map(object_body('name'))
    count=object_body('cardCount')
    official=re.fullmatch(r'\s*official\s*:\s*([1-9][0-9]*)\s*,?\s*',count or '')
    if not set_id or not official:
        raise ValueError('set header lacks a supported ID or official count')
    date_field=fields.get('releaseDate')
    if date_field is None:
        declaration=dict(kind='provider_date_not_declared');values=[]
    elif date_field.startswith('{'):
        localized=object_body('releaseDate')
        dates=string_map(localized)
        if set(dates)-set(names):
            raise ValueError('date language lacks a declared name')
        declaration=dict(kind='localized_provider_dates',values=dates)
        values=dates.values()
    else:
        scalar=literal('releaseDate')
        declaration=dict(kind='shared_scalar_provider_date',value=scalar)
        values=[] if scalar is None else [scalar]
    for value in values:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
            raise ValueError('provider date must be a complete ISO date')
        date.fromisoformat(value)
    return dict(provider_set_id=set_id,localized_names=names,declared_official_card_count=int(official[1]),
        declared_date=declaration,date_scope='provider_declaration_not_region_or_initial_vs_copy_release_verified')


def document_record(path,blob,raw,license_blob,license_raw,inspected_at):
    facts=parse_header(raw)
    row=dict(schema='pokemon.qualified-provider-product-document.v1',provider='tcgdex',native_id=path,
        revision=REVISION,git_blob_id=blob,sha256=hashlib.sha256(raw).hexdigest(),
        source_entity_scope='provider_set_header_only_not_card_or_SKU',facts=facts,
        retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
        qualification='pinned_bytes_license_and_literal_declarations_verified',
        rights=dict(status='reviewed_source_metadata_only_no_display_grant',license='MIT',
            license_git_blob_id=license_blob,license_sha256=hashlib.sha256(license_raw).hexdigest(),
            rights_reference=f'https://github.com/tcgdex/cards-database/blob/{REVISION}/LICENSE'),
        confidence=dict(source_bytes=1.0,literal_declaration_extraction=1.0,semantic_accuracy=None,
            anchor_binding=None,physical_printing=None,localized_initial_release_date=None),
        physical_distribution_region=None,release_binding_verified=False,test_only=False,
        **{k:False for k in catalog_locale.FALSE_CLAIMS})
    row['document_id']='provider-product-document:'+catalog_locale.digest(row)
    return row


def qualify_anchors(plan,documents):
    headers={d['facts']['provider_set_id']:d for d in documents}
    if len(headers)!=len(documents) or set(headers)!=set(PATHS):
        raise ValueError('fixed provider product documents missing or duplicated')
    anchors=[r for r in plan['subjects'] if r['priority']=='exact_caption_anchor']
    if len(anchors)!=4 or {r['set_code'] for r in anchors}!=set(ANCHORS):
        raise ValueError('exact four caption anchors required')
    requests={r['request_id']:r for r in plan['requests']}
    if len(requests)!=len(plan['requests']):raise ValueError('duplicate document request')
    results=[]
    for subject in sorted(anchors,key=lambda r:r['set_code']):
        code=subject['set_code'];header=headers.get(code)
        if (subject['language']!='ja' or subject['card_id']!=f"ja:{code}:{subject['collector_number']}:unverified"
                or subject['collector_number']!={'SMH':'001/131','DS':'001/020','SC':'001/020','LL':'001/040'}[code]):
            raise ValueError('anchor coordinate differs from fixed held scope')
        if (subject['status']!='held' or subject['release_date'] is not None
                or subject['physical_distribution_region'] is not None or subject['release_binding_verified'] is not False
                or any(subject.get(k) is not False for k in catalog_locale.FALSE_CLAIMS)):
            raise ValueError('anchor must retain all held and unknown claims')
        if subject['publisher_card_url']!='https://www.pokemon-card.com/card-search/details.php/card/'+ANCHORS[code]:
            raise ValueError('anchor native reference differs')
        links=[r for key in subject['request_ids'] for r in [requests[key]] if r['kind']=='product_release_document']
        if len(links)!=1:
            raise ValueError('anchor product document request missing or ambiguous')
        request=links[0]
        binding=[b for b in request['subject_bindings'] if b['card_id']==subject['card_id'] and b['candidate_id']==subject['candidate_id']]
        if len(binding)!=1 or binding[0]['caption_status']!='publisher_caption_checked':
            raise ValueError('anchor caption is not exactly checked')
        if any(binding[0][k]!=subject[k] for k in ('language','set_code','collector_number')):
            raise ValueError('caption binding coordinate differs')
        row=dict(schema='pokemon.anchor-product-document-qualification.v1',
            card_id=subject['card_id'],candidate_id=subject['candidate_id'],language=subject['language'],
            set_code=code,collector_number=subject['collector_number'],caption_evidence_id=subject['caption_evidence_id'],
            inspected_at=plan['inspected_at'],status='held_anchor_binding_unqualified',
            anchor_source=subject['source'],original_hold_reasons=subject['original_hold_reasons'],
            declared_caption=binding[0]['declared_caption'],
            exact_publisher_document=dict(requested_url=request['document_url'],caption_link=binding[0]['publisher_link'],
                cache_status=request['cache_status'],qualified=False),
            qualified_provider_document_id=header['document_id'] if header else None,
            candidate_relation='provider_set_header_lead_no_verified_cross_provider_card_binding' if header else None,
            unresolved_conflicts=(['exact_publisher_product_document_not_qualified',
                'no_pinned_provider_card_entries_or_cross_provider_anchor_bridge',
                'provider_date_region_and_initial_release_scope_unspecified'] if header else [
                'exact_news_target_not_in_authorized_cache' if request['cache_status']=='not_in_authorized_cache'
                    else 'exact_news_target_cached_but_not_qualified',
                'related_family_page_is_not_exact_caption_target','sale_marker_year_not_observed'])+[
                    'physical_variant_not_verified','physical_distribution_region_unknown'],
            release_date=None,physical_distribution_region=None,release_binding_verified=False,
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        row['qualification_id']='anchor-document-qualification:'+catalog_locale.digest(row)
        results.append(row)
    return results


def build(db_path,root,cache,repo,inspected_at):
    # Recompute the current installed readiness instead of trusting a saved plan.
    plan=readiness.build(db_path,root,cache,inspected_at)
    pin=git_tree(repo,['LICENSE',*PATHS.values()])
    if set(pin)!={'LICENSE',*PATHS.values()}:
        raise ValueError('required pinned headers/license absent from local Git tree')
    license_raw=checked_source(repo,'LICENSE',pin['LICENSE'])
    reviewed=(root/'catalog/TCGDEX-LICENSE').read_bytes()
    if license_raw!=reviewed:
        raise ValueError('metadata license differs from existing reviewed bytes')
    if git_tree(repo,[p.removesuffix('.ts')+'/' for p in PATHS.values()]):
        raise ValueError('provider card entries now exist; header-only qualification must be reviewed')
    snapshots={path:checked_source(repo,path,pin[path]) for path in PATHS.values()}
    documents=[document_record(path,pin[path],raw,pin['LICENSE'],license_raw,inspected_at) for path,raw in sorted(snapshots.items())]
    if {d['facts']['provider_set_id'] for d in documents}!=set(PATHS):
        raise ValueError('pinned document set IDs differ from fixed scope')
    outcomes=qualify_anchors(plan,documents)
    if (any(checked_source(repo,path,pin[path])!=raw for path,raw in snapshots.items())
            or checked_source(repo,'LICENSE',pin['LICENSE'])!=license_raw
            or (root/'catalog/TCGDEX-LICENSE').read_bytes()!=reviewed
            or readiness.build(db_path,root,cache,inspected_at)!=plan):
        raise ValueError('qualification inputs changed during inspection')
    report=dict(schema='pokemon.product-document-qualification-build.v1',snapshot=plan['snapshot'],
        provider_revision=REVISION,verified_provider_documents=len(documents),anchor_outcomes=len(outcomes),
        qualified_exact_publisher_product_documents=0,qualified_cross_provider_anchor_bindings=0,
        new_identities=0,new_card_release_dates=0,new_search_aliases=0,new_permissions=0,
        provider_card_entries_for_selected_headers=0,source_database_bytes_unchanged=True,
        catalogue_inventory=plan['catalogue_inventory'],related_family_observation=plan['related_unqualified_family_observation'],
        qualification_scope='three_provider_header_declarations_verified_four_anchor_bindings_still_held')
    return documents,outcomes,report,snapshots,license_raw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--source-repo',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--inspected-at',required=True);args=p.parse_args()
    if args.output_dir.exists():raise FileExistsError('qualification output already exists')
    documents,outcomes,report,snapshots,license_raw=build(args.db,Path.cwd(),args.cache,args.source_repo,args.inspected_at)
    args.output_dir.mkdir(parents=True);source_dir=args.output_dir/'source-snapshots';source_dir.mkdir()
    for path,raw in snapshots.items():(source_dir/Path(path).name).write_bytes(raw)
    (source_dir/'LICENSE').write_bytes(license_raw)
    for name,rows in [('provider-documents.jsonl',documents),('anchor-outcomes.jsonl',outcomes)]:
        (args.output_dir/name).write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    report['file_hashes']={str(path.relative_to(args.output_dir)):readiness.digest_file(path) for path in sorted(args.output_dir.rglob('*')) if path.is_file()}
    (args.output_dir/'coverage-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('verified_provider_documents','anchor_outcomes','qualified_exact_publisher_product_documents','qualified_cross_provider_anchor_bindings','new_identities')}))


if __name__=='__main__':main()
