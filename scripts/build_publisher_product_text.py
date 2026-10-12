"""Verify four bounded product captions from existing cached publisher pages.

No network fallback, artwork, marketplace link, date or whole-set inference.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from pokemon_index import core, catalog_locale, product_text
from scripts.audit_japanese_metadata_batch import parse_page
ANCHORS = (('SMH', '35030'), ('DS', '27836'), ('SC', '28616'), ('LL', '26001'))


class CaptionParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.div_depth = 0
        self.popup_depth = None
        self.popup_count = 0
        self.item = None
        self.anchor = None
        self.products = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'div':
            self.div_depth += 1
            if 'PopupSub' in classes:
                self.popup_count += 1
                if self.popup_depth is not None:
                    raise ValueError('nested product popup')
                self.popup_depth = self.div_depth
        if tag == 'li' and self.item is not None:
            raise ValueError('nested product declaration')
        if self.popup_depth is not None and tag == 'li' and 'List_item' in classes:
            self.item = dict(text=[], links=[])
        if self.item is not None and tag == 'a':
            if self.anchor is not None:
                raise ValueError('nested product anchor')
            if not attrs.get('href'):
                raise ValueError('product anchor missing href')
            self.anchor = dict(url=urljoin(self.base_url, attrs['href']), text=[])

    def handle_data(self, data):
        if self.item is not None:
            self.item['text'].append(data)
            if self.anchor is not None:
                self.anchor['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.item is not None:
            if self.anchor is None:
                raise ValueError('unbalanced product anchor')
            self.item['links'].append(self.anchor)
            self.anchor = None
        if tag == 'li' and self.item is not None:
            if self.anchor is not None:
                raise ValueError('unclosed product anchor')
            name = ''.join(self.item['text']).strip()
            if name.startswith('ポケモンカードゲーム'):
                if len(self.item['links']) > 1:
                    raise ValueError('multiple links on one product caption')
                anchor = self.item['links'][0] if self.item['links'] else None
                compact = lambda value: re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
                if anchor and compact(''.join(anchor['text'])) != compact(name):
                    raise ValueError('product anchor label differs from full caption')
                link = anchor['url'] if anchor else None
                self.products.append(dict(name=name, publisher_link=link, link_kind=product_text.link_kind(link)))
            self.item = None
        if tag == 'div':
            if self.div_depth == self.popup_depth:
                if self.item is not None:
                    raise ValueError('unclosed product declaration')
                self.popup_depth = None
            self.div_depth -= 1


def extract(raw, url):
    parser = CaptionParser(url)
    parser.feed(raw.decode('utf-8')); parser.close()
    if parser.popup_count != 1 or parser.popup_depth is not None or parser.item is not None or parser.anchor is not None:
        raise ValueError('missing, duplicate or unclosed product popup')
    if not 1 <= len(parser.products) <= 10 or len({p['name'] for p in parser.products}) != len(parser.products):
        raise ValueError('missing, duplicate or ambiguous product captions')
    return parser.products


def select(db, cache, inspected_at):
    core.parse_time(inspected_at)
    # Fixed stage-2 cached anchors; never expand to uninspected neighbors.
    selected = []
    for code, native in ANCHORS:
        candidates = [json.loads(r[0]) for r in db.execute('SELECT record_json FROM catalog_coverage_candidate')]
        candidates = [r for r in candidates if r['identity']['set_code'] == code and r['cached_official_page']
                      and r['cached_official_page']['native_id'] == native]
        if len(candidates) != 1:
            raise ValueError('fixed cached anchor missing or ambiguous')
        held = candidates[0]
        page = held['cached_official_page']
        raw = (cache/('card-'+code+'.html')).read_bytes()
        receipt = json.loads((cache/('card-'+code+'.receipt.json')).read_text())
        if (receipt['url'] != page['url'] or receipt.get('final_url', receipt['url']) != page['url']
                or receipt['sha256'] != page['sha256'] or receipt['fetched_at'] != page['retrieved_at']
                or hashlib.sha256(raw).hexdigest() != page['sha256']):
            raise ValueError('publisher cached bytes/receipt differ from held anchor')
        parsed = parse_page(raw)
        if parsed['name'] != held['identity']['name'] or page['coordinate'] not in [
                {k:e[k] for k in ('set_code','collector_number')} for e in parsed['numbered_entries']]:
            raise ValueError('publisher page coordinate/title differs')
        products = extract(raw, page['url'])
        if products != product_text.declared_products(held):
            raise ValueError('publisher captions disagree with pinned coordinate declarations')
        publisher = dict(provider='pokemon-card-publisher', native_id=native, language='ja', url=page['url'],
            sha256=page['sha256'], revision='sha256:'+page['sha256'], retrieved_at=page['retrieved_at'],
            rights_status='existing_cached_factual_text_internal_only', metadata_license_grant=None,
            physical_distribution_region=None)
        row = dict(schema=product_text.SCHEMA, candidate_id=held['candidate_id'], card_id=held['identity']['card_id'],
            publisher=publisher, products=products, confidence=dict(source_text_correspondence=1.0,
                product_release_identity=None, physical_variant=None), scope=product_text.SCOPE,
            inspected_at=inspected_at, test_only=False, **{k: False for k in product_text.FLAGS})
        row['evidence_id'] = 'product-text:' + catalog_locale.digest(row)
        product_text.validate(db, row)
        selected.append(row)
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True); p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--inspected-at',required=True)
    args=p.parse_args()
    with core.connect(args.db,readonly=True) as db:
        rows=select(db,args.cache,args.inspected_at)
    with args.output.open('x') as handle:
        handle.write(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    print(json.dumps(dict(product_text_records=len(rows), new_identities=0, release_bindings_verified=0,
        official_news_links=sum(p['link_kind']=='official_news_article' for r in rows for p in r['products']),
        unlinked_captions=sum(p['link_kind']=='unlinked_text' for r in rows for p in r['products']))))


if __name__ == '__main__':
    main()
