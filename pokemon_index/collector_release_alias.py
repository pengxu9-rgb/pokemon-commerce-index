"""One reviewed English rendering of a current source-bound Japanese release.

The publisher's title is Japanese. The English query alias is an explicitly
reviewed rendering, not publisher-provided English or a generic translation.
"""
import json
from pathlib import Path

BINDINGS_PATH=Path(__file__).with_name('collector-release-name-aliases-v1.json')


def aliases(db, languages):
    payload=json.loads(BINDINGS_PATH.read_text())
    if payload.get('schema')!='pokemon.reviewed-release-name-aliases.v1':
        raise ValueError('unsupported reviewed release aliases')
    out=[]
    for binding in payload['records']:
        if binding['language'] not in languages:continue
        if (binding.get('schema')!='pokemon.reviewed-release-name-alias.v1'
                or binding.get('source_published_alias') is not False
                or binding.get('derivation')!='reviewed_english_rendering_of_exact_official_japanese_title.v1'):
            continue
        scope=(binding['language'],binding['set_code'])
        row=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',scope).fetchone()
        saved=db.execute('SELECT evidence_json FROM catalog_release_evidence WHERE language=? AND set_code=?',scope).fetchone()
        if row is None or saved is None or dict(row)!=binding['current_release']:
            continue
        if json.loads(saved[0])!=binding['release_evidence']:
            continue
        out.append(dict(alias=binding['alias'],language=binding['language'],set_code=binding['set_code'],
            derivation=binding['derivation'],source_published_alias=False,source_title=binding['source_title'],
            source_ref=binding['release_evidence']['official_url'],
            source_page_sha256=binding['release_evidence']['official_page_sha256'],
            rights_reference=binding['current_release']['rights_reference']))
    return out
