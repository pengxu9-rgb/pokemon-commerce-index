"""Plan evidence work for the fixed offline queue without admitting metadata.

Existing card, source and caption bindings remain exact. Grouping document
requests saves operator work; it never groups releases, variants, SKUs or prices.
No network fallback or database writes are available in this command.
"""
import argparse
import calendar
import hashlib
import json
import re
from collections import Counter
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pokemon_index import core, catalog_locale, product_text, coverage_qualification as qualification
from scripts.audit_international_product_text import verify_installed
from scripts.audit_international_coverage import coverage

SMH_URL = 'https://www.pokemon-card.com/ex/smh/index.html'
SMH_SHA = '2cff2f62bc235bd3279c9113a1ab40ea7b3dce70b505b65dd70e854e12a2c2f3'


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document_url(url):
    """Separate a fragment selector for document retrieval only, not identity."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.pokemon-card.com'
            or parsed.query or not parsed.path.startswith('/')):
        raise ValueError('evidence request is outside exact publisher namespace')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def cache_inventory(cache):
    receipts = sorted(cache.glob('*.receipt.json'))
    if not receipts or len(receipts) > 100:
        raise ValueError('authorized cache must contain 1–100 document receipts')
    documents = {}
    for path in receipts:
        stem = path.name.removesuffix('.receipt.json')
        if not re.fullmatch(r'[A-Za-z0-9-]+', stem):
            raise ValueError('unsupported cache receipt filename')
        raw_path = cache/(stem+'.html')
        if any(not p.resolve().is_relative_to(cache.resolve()) for p in (path, raw_path)):
            raise ValueError('cache path escapes authorized directory')
        receipt_raw = path.read_bytes()
        receipt = json.loads(receipt_raw)
        url = receipt['url']
        if document_url(url) != url or receipt.get('final_url', url) != url:
            raise ValueError('cache document URL or redirect differs')
        if url in documents:
            raise ValueError('multiple cache receipts for the same document')
        if digest_file(raw_path) != receipt['sha256']:
            raise ValueError('cache document bytes differ from receipt')
        core.parse_time(receipt['fetched_at'])
        documents[url] = dict(url=url, sha256=receipt['sha256'], retrieved_at=receipt['fetched_at'],
            receipt_file=path.name, receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(), document_file=raw_path.name,
            rights_status='existing_cached_evidence_no_display_grant')
    return documents


class SaleMarker(HTMLParser):
    """Read only the sale image's date marker; do not retain price/copy text."""
    def __init__(self):
        super().__init__()
        self.in_sale = False
        self.markers = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p':
            if self.in_sale:
                raise ValueError('nested sale marker')
            self.in_sale = 'sale' in attrs.get('class', '').split()
        if tag == 'img' and self.in_sale:
            alt = attrs.get('alt', '')
            marker = re.match(r'([0-9]{1,2})\.([0-9]{1,2})\[([月火水木金土日])\]\s*発売!!', alt)
            if not marker:
                raise ValueError('sale marker is missing or has an unsupported date form')
            month, day = int(marker[1]), int(marker[2])
            if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2000, month)[1]:
                raise ValueError('sale marker month/day out of range')
            self.markers.append(dict(text=marker[0], month=month, day=day, weekday=marker[3],
                year=None, release_date=None, date_scope='year_not_observed_in_sale_marker'))

    def handle_endtag(self, tag):
        if tag == 'p':
            self.in_sale = False


def smh_family_observation(cache, documents):
    document = documents.get(SMH_URL)
    if not document:
        return None
    if document['sha256'] != SMH_SHA:
        raise ValueError('SMH family document differs from pinned authorized bytes')
    raw = (cache/document['document_file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SMH_SHA:
        raise ValueError('SMH observed bytes differ from the verified cache inventory')
    parser = SaleMarker()
    parser.feed(raw.decode('utf-8')); parser.close()
    if parser.in_sale or len(parser.markers) != 1:
        raise ValueError('SMH sale marker missing, unclosed or ambiguous')
    return dict(document=document, observed_sale_marker=parser.markers[0],
        scope='related_GX_start_deck_family_document_not_exact_caption_link_target',
        release_binding_verified=False, release_date_admitted=False, physical_region=None,
        **{k:False for k in catalog_locale.FALSE_CLAIMS})


def assert_inputs_unchanged(signatures, cache, documents):
    if ({p.name for p in cache.glob('*.receipt.json')} != {d['receipt_file'] for d in documents.values()}
            or any(digest_file(path) != sha for path,sha in signatures.items())):
        raise ValueError('input changed during readiness inspection')


def assemble(db, candidates, captions, documents, inspected_at, supplemental=None):
    core.parse_time(inspected_at)
    by_id = {}
    reference_owners = {}
    for held in candidates:
        cid = qualification.validate(db, held)
        installed = db.execute('SELECT record_json FROM catalog_coverage_candidate WHERE candidate_id=?',
                               (held['candidate_id'],)).fetchone()
        if not installed or installed[0] != catalog_locale.encoded(held):
            raise ValueError('readiness needs the exact installed held evidence')
        if cid in by_id or held['identity']['language'] != 'ja':
            raise ValueError('duplicate or non-Japanese readiness subject')
        by_id[cid] = held
        for ref in held['coordinate_references']:
            key = (ref['source'], ref['native_id'])
            if key in reference_owners and reference_owners[key] != cid:
                raise ValueError('provider/native reference collides across readiness subjects')
            reference_owners[key] = cid
    verified = {}
    for caption in captions:
        cid = product_text.validate(db, caption)
        installed = db.execute('SELECT record_json FROM catalog_product_text WHERE evidence_id=?',
                               (caption['evidence_id'],)).fetchone()
        if not installed or installed[0] != catalog_locale.encoded(caption):
            raise ValueError('readiness needs the exact installed caption evidence')
        if cid not in by_id or cid in verified or caption['candidate_id'] != by_id[cid]['candidate_id']:
            raise ValueError('caption is outside or ambiguous in the fixed held queue')
        verified[cid] = caption
    needs = {}
    subjects = []

    def request(kind, url, selector, binding):
        key = catalog_locale.encoded(dict(kind=kind, document_url=url, selector=selector))
        if key not in needs:
            needs[key] = dict(request_id='evidence-need:'+catalog_locale.digest(json.loads(key)),
                kind=kind, document_url=url, selector=selector,
                cache_status='cached_needs_separate_review' if url in documents else 'not_in_authorized_cache',
                cached_document=documents.get(url), subject_bindings=[],
                scope='retrieval_work_group_only_not_release_or_SKU_identity',
                release_binding_verified=False, **{k:False for k in catalog_locale.FALSE_CLAIMS})
        needs[key]['subject_bindings'].append(binding)
        return needs[key]['request_id']

    for cid, held in sorted(by_id.items()):
        identity = held['identity']; refs = [r for r in held['coordinate_references'] if r['source'] == 'ptcg-database']
        if len(refs) != 1 or not refs[0]['native_id'].isdigit():
            raise ValueError('readiness needs one exact publisher-native coordinate reference')
        card_url = 'https://www.pokemon-card.com/card-search/details.php/card/'+refs[0]['native_id']
        page = held['cached_official_page']; cached = documents.get(card_url)
        if page is not None and (not cached or cached['sha256'] != page['sha256'] or cached['retrieved_at'] != page['retrieved_at']):
            raise ValueError('held cached card page is absent or differs from its receipt')
        binding = dict(candidate_id=held['candidate_id'], card_id=cid, language=identity['language'],
            set_code=identity['set_code'], collector_number=identity['collector_number'])
        requested = []
        if page is None:
            requested.append(request('exact_coordinate_publisher_page', card_url, None, binding))
        for declared in product_text.declared_products(held):
            link = declared['publisher_link']
            url = document_url(link) if link else None
            # A shared document can serve separate caption selectors. Exact
            # coordinate bindings remain in each work item, never propagate.
            selector = None if url else dict(language=identity['language'], provisional_set_code=identity['set_code'],
                                             declared_caption=declared['name'])
            requested.append(request('product_release_document', url, selector, dict(**binding,
                declared_caption=declared['name'], publisher_link=link,
                caption_status='publisher_caption_checked' if cid in verified else 'provider_declaration_only',
                declaration_source=held['source'])))
        subjects.append(dict(**binding, priority='exact_caption_anchor' if cid in verified else 'remaining_fixed_queue',
            source=held['source'], original_hold_reasons=held['hold_reasons'], publisher_card_url=card_url,
            caption_evidence_id=verified[cid]['evidence_id'] if cid in verified else None,
            card_page_status='checked_exact_cached_coordinate' if page else (
                'cached_needs_coordinate_review' if cached else 'not_in_authorized_cache'),
            request_ids=sorted(set(requested)), physical_distribution_region=None,
            required_physical_evidence=['finish', 'stamp_or_edition', 'distribution_region'],
            status='held', release_date=None, release_binding_verified=False,
            **{k:False for k in catalog_locale.FALSE_CLAIMS}))
    requests = sorted(needs.values(), key=lambda n:(n['kind'], n['document_url'] or '', catalog_locale.encoded(n['selector'])))
    for need in requests:
        need['subject_bindings'].sort(key=lambda b:b['card_id'])
    return dict(schema='pokemon.international-release-readiness.v1', inspected_at=inspected_at,
        scope='read_only_evidence_work_plan_no_catalogue_admission', subjects=subjects, requests=requests,
        related_unqualified_family_observation=supplemental,
        summary=dict(subjects=len(subjects), prioritized_caption_anchors=len(verified), remaining_subjects=len(subjects)-len(verified),
            by_scope=dict(Counter(r['set_code'] for r in subjects)),
            request_groups=len(requests), by_request_kind=dict(Counter(r['kind'] for r in requests)),
            new_identities=0, release_bindings_verified=0, release_dates_admitted=0,
            physical_printing_approvals=0, display_approvals=0, commerce_approvals=0),
        rights_status='existing_licensed_metadata_and_cached_evidence_internal_only',
        source_inventory=sorted(documents.values(),key=lambda d:d['url']))


def build(db_path, root, cache, inspected_at):
    signatures = {}

    def read(path):
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if path in signatures and signatures[path] != sha:
            raise ValueError('input changed during readiness inspection')
        signatures[path] = sha
        return raw

    manifest_path = root/'catalog-build-manifest-international-product-text-v1.json'
    manifest = json.loads(read(manifest_path))
    baseline = json.loads(read(root/'catalog-build-manifest-source-binding-v1.json'))
    prior = json.loads(read(root/'catalog-build-manifest-international-qualification-v1.json'))
    if (len(baseline['steps']) != 65 or len(prior['steps']) != 67 or len(manifest['steps']) != 68
            or manifest['steps'][:65] != baseline['steps'] or manifest['steps'][:67] != prior['steps']):
        raise ValueError('readiness requires the explicit preserved 68-step snapshot inputs')
    for step in manifest['steps']:
        path = root/step['path']
        if not path.resolve().is_relative_to(root.resolve()) or hashlib.sha256(read(path)).hexdigest() != step['sha256']:
            raise ValueError('hash-bound snapshot input differs')
    candidates = [json.loads(s) for s in read(root/manifest['steps'][66]['path']).splitlines()]
    captions = [json.loads(s) for s in read(root/manifest['steps'][67]['path']).splitlines()]
    documents = cache_inventory(cache)
    for document in documents.values():
        signatures[cache/document['document_file']] = document['sha256']
        signatures[cache/document['receipt_file']] = document['receipt_sha256']
    before = digest_file(db_path)
    with closing(core.connect(db_path,readonly=True)) as db:
        if len(candidates) != 65 or len(captions) != 4:
            raise ValueError('readiness must remain on the fixed 65 subjects and four caption anchors')
        verify_installed(db, captions)
        if qualification.status(db) != dict(coverage_candidate_events=65,coverage_candidate_subjects=65,
                coverage_current_held=65,coverage_stale_candidates=0,coverage_admitted_identities=0):
            raise ValueError('readiness requires the complete current installed held queue')
        report = assemble(db,candidates,captions,documents,inspected_at,smh_family_observation(cache,documents))
        report['catalogue_inventory'] = coverage(db)
    if before != digest_file(db_path):
        raise ValueError('readiness changed input database bytes')
    assert_inputs_unchanged(signatures, cache, documents)
    report['snapshot'] = dict(manifest_sha256=signatures[manifest_path],
        verified_input_hashes=68, preserved_original_inputs=65, database_sha256=before, database_bytes_unchanged=True,
        inspected_input_files=len(signatures), input_file_bytes_unchanged=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--inspected-at',required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError('readiness output already exists')
    report=build(args.db,Path.cwd(),args.cache,args.inspected_at)
    with args.output.open('x') as handle:
        handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary']))


if __name__=='__main__':
    main()
