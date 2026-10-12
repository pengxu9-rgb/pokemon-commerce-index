"""Compile up to 65 held Japanese release candidates from authorized local bytes.

No network, new identities, artwork, prices or release overlays. The four source
scopes were selected by the existing release-gap audit, not by supplier demand.
"""
import argparse
import hashlib
import html
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from pokemon_index import core, catalog_locale, coverage_qualification as qualification
from scripts.audit_japanese_metadata_batch import parse_page

SCOPES = ('SMH', 'DS', 'SC', 'LL')


def checked_source(repo, revision, path, sha256):
    relative = Path(path)
    target = (repo / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(repo.resolve()):
        raise ValueError('source path escapes checkout')
    raw = target.read_bytes()
    blob = subprocess.check_output(['git', 'rev-parse', revision + ':' + relative.as_posix()], cwd=repo, text=True).strip()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != actual or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('selected source bytes differ from pinned revision/provenance')
    return raw


def cached_page(cache, code, identity, references):
    path = cache / ('card-' + code + '.html')
    receipt_path = path.with_suffix('.receipt.json')
    if not path.exists() and not receipt_path.exists():
        return None
    raw = path.read_bytes()
    receipt = json.loads(receipt_path.read_text())
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('cached official page hash mismatch')
    url = receipt['url']
    if not re.fullmatch(r'https://www\.pokemon-card\.com/card-search/details\.php/card/[0-9]+', url) or receipt.get('final_url', url) != url:
        raise ValueError('cached official page URL differs')
    native_id = url.rsplit('/', 1)[1]
    if not any(r['source'] == 'ptcg-database' and r['native_id'] == native_id for r in references):
        return None  # A cached sibling coordinate must never support this card.
    parsed = parse_page(raw)
    coordinate = dict(set_code=code, collector_number=identity['collector_number'])
    if parsed['name'] != identity['name'] or not any({k: e[k] for k in coordinate} == coordinate for e in parsed['numbered_entries']):
        raise ValueError('cached official name/coordinate differs')
    core.parse_time(receipt['fetched_at'])
    links = []
    for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw.decode(), re.S):
        target = urljoin(url, html.unescape(href))
        name = html.unescape(re.sub('<[^>]+>', '', label)).strip()
        if name and re.fullmatch(r'https://www\.pokemon-card\.com/(?:ex/[a-z0-9]+/(?:index\.html)?|products/[a-z0-9]+/[a-z0-9]+\.html)', target):
            links.append(dict(name=name, url=target))
    return dict(native_id=native_id, url=url, sha256=receipt['sha256'], retrieved_at=receipt['fetched_at'],
                rights_status='cached_evidence_only_no_display_grant', name=parsed['name'],
                coordinate=coordinate, product_links=links)


def select(db, repo, cache, inspected_at, limit=65, license_path=Path('catalog/PTCG-DATABASE-LICENSE')):
    core.parse_time(inspected_at)
    if type(limit) is not int or not 4 <= limit <= 65:
        raise ValueError('next batch must contain 4–65 candidates')
    repo = repo.resolve()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    license_bytes = (repo/'LICENSE').read_bytes()
    if license_bytes != license_path.read_bytes():
        raise ValueError('existing reviewed metadata license differs')
    license_sha = hashlib.sha256(license_bytes).hexdigest()
    checked_source(repo, revision, 'LICENSE', license_sha)
    rows = []
    for index, code in enumerate(SCOPES):
        wanted = limit // len(SCOPES) + (index < limit % len(SCOPES))
        cards = db.execute('''SELECT c.* FROM card c LEFT JOIN catalog_set_localized s
            ON s.language=c.language AND s.set_code=c.set_code WHERE c.language='ja' AND c.set_code=?
            AND (s.name IS NULL OR trim(s.name)='' OR s.release_date IS NULL OR trim(s.release_date)='')
            ORDER BY c.card_id''', (code,)).fetchall()
        if len(cards) < wanted:
            raise ValueError('insufficient current gap evidence in ' + code)
        for card in cards[:wanted]:
            identity = catalog_locale.snapshot(db, card['card_id'])
            match = re.fullmatch(r'ptcg-database:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})', card['provenance'])
            if not match or match[1] != revision:
                raise ValueError('candidate requires pinned baseline PTCG metadata')
            _, path, sha = match.groups()
            source = json.loads(checked_source(repo, revision, path, sha))
            if (source['set_name'] != code or source['name'] != identity['name']
                    or core.normalize_collector_number(str(source['number']) + '/' + str(source['set_total'])) != identity['collector_number']):
                raise ValueError('pinned source text differs from selected identity')
            references = qualification.references_snapshot(db, identity)
            declarations = [dict(name=s['name'], product_url=s.get('link')) for s in source.get('sources', [])]
            row = dict(schema=qualification.SCHEMA, identity=identity,
                coordinate_snapshot=qualification.coordinate_snapshot(db, identity), coordinate_references=references,
                release_snapshot=qualification.release_snapshot(db, identity),
                numbering_scope='provisional:ja:' + code, status='held', test_only=False,
                source=dict(provider='ptcg-database', native_id=path, revision=revision, sha256=sha,
                    language='ja', region='ZZ', rights_reference=identity['rights_reference'],
                    rights_status='metadata_internal_reviewed', license_sha256=license_sha,
                    retrieved_at=None, retrieval_status='historical_snapshot_time_not_recorded', inspected_at=inspected_at),
                confidence=dict(source_bytes=1.0, product_binding=None, physical_printing=None),
                source_product_declarations=declarations,
                cached_official_page=cached_page(cache, code, identity, references),
                **{k: False for k in qualification.FLAGS})
            row['hold_reasons'] = qualification.hold_reasons(row)
            row['candidate_id'] = 'coverage-candidate:' + catalog_locale.digest(row)
            qualification.validate(db, row)
            rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--source-repo', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--inspected-at', required=True)
    p.add_argument('--limit', type=int, default=65)
    args = p.parse_args()
    if args.output_dir.exists():
        raise FileExistsError('coverage queue output already exists')
    with core.connect(args.db, readonly=True) as db:
        rows = select(db, args.source_repo, args.cache, args.inspected_at, args.limit)
    args.output_dir.mkdir(parents=True)
    queue = args.output_dir/'candidates.jsonl'
    queue.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows))
    report = dict(schema='pokemon.coverage-qualification-build.v1', candidates=len(rows),
        by_scope=dict(Counter(r['identity']['set_code'] for r in rows)),
        hold_reasons=dict(Counter(reason for r in rows for reason in r['hold_reasons'])),
        cached_exact_card_pages=sum(r['cached_official_page'] is not None for r in rows),
        release_metadata_admitted=0, new_identities=0, new_images=0, new_prices=0,
        queue_sha256=hashlib.sha256(queue.read_bytes()).hexdigest(),
        selection='Existing SMH/DS/SC/LL gap audit; evenly bounded first coordinates; no measured demand claim',
        source_rights='Reviewed pinned MIT metadata only; official cached evidence has no display grant',
        scope='Held qualification records, not verified printings or product release declarations')
    (args.output_dir/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
