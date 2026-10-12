"""Literal provider release witnesses; original bytes remain the evidence."""
import ast,re
from pathlib import PurePosixPath
from pokemon_index import tcgdex_source
from scripts import build_pokemon_name_coverage as names
from scripts.qualify_international_product_documents import header_fields


def release_path(release,revision,rights):
    match=re.fullmatch(r'tcgdex:([0-9a-f]{40}):(.+\.ts)',release['provenance'])
    if not match or match[1]!=revision or release['rights_reference']!=rights:
        raise ValueError('localized release lacks existing reviewed pin/rights')
    path=PurePosixPath(match[2])
    if path.is_absolute() or '..' in path.parts or path.parts[0] not in ('data','data-asia'):
        raise ValueError('localized release source path is unsupported')
    return match[2]


def inspect_release(release,raw):
    source=raw.decode('utf-8');_,masked=tcgdex_source._lexical_source(source)
    declarations=list(re.finditer(r'\bconst\s+([A-Za-z_$][\w$]*)\s*:\s*Set\s*=\s*\{',masked))
    exports=list(re.finditer(r'\bexport\s+default\s+([A-Za-z_$][\w$]*)\b',masked))
    if len(declarations)!=1 or len(exports)!=1 or declarations[0][1]!=exports[0][1]:
        raise ValueError('single matching localized release declaration/export required')
    declaration=declarations[0];extraction=source
    if declaration[1]!='set':
        for start,end in sorted([(declaration.start(1),declaration.end(1)),(exports[0].start(1),exports[0].end(1))],reverse=True):
            extraction=extraction[:start]+'set'+extraction[end:]
    fields=header_fields(extraction);provider_id=ast.literal_eval(fields['id']);localized_names=names.names(fields['name'])
    count=fields['cardCount']
    if not count.startswith('{') or not count.endswith('}'):raise ValueError('literal localized release count required')
    count_fields=tcgdex_source._literal_properties(count[1:-1]);official_count=ast.literal_eval(count_fields['official'])
    date_field=fields['releaseDate']
    if date_field.startswith('{'):
        provider_date=names.names(date_field).get(release['language']);date_kind='localized_provider_date'
    else:provider_date=ast.literal_eval(date_field);date_kind='shared_scalar_provider_date'
    if (not isinstance(provider_id,str) or provider_id.upper()!=release['set_code']
            or localized_names.get(release['language'])!=release['name']
            or type(official_count) is not int or official_count!=release['official_card_count']
            or not provider_date or provider_date!=release['release_date']):
        raise ValueError('pinned localized release name/date/count differs')
    return dict(provider_set_id=provider_id,name=release['name'],release_date=provider_date,
        declared_official_card_count=official_count,date_kind=date_kind,
        date_scope='provider_declaration_not_region_or_initial_vs_copy_release_verified')
