"""Build bounded official release metadata from hash-checked cached pages.

The reviewed selectors identify product family names/dates. Card-page links bind
those products to an exact Japanese numbering scope; mixed denominators abstain.
"""
from __future__ import annotations
import argparse,hashlib,html,json,re,sqlite3
from pathlib import Path
from pokemon_index import supported_catalog
from scripts.audit_japanese_metadata_batch import parse_page

SELECTORS=[
 ('SI','si','スタートデッキ100','2021-12-17'),
 ('SVM','svm','スタートデッキ Generations','2024-11-22'),
 ('SVD','svd','exスタートデッキ',None),
 ('SD','sd','Vスタートデッキ',None),
 ('S3','s3','ムゲンゾーン','2020-06-05'),
 ('S2','s2','反逆クラッシュ','2020-03-06'),
 ('S3A','s3a','伝説の鼓動','2020-07-10'),
 ('S1A','s1a','VMAXライジング','2020-02-07'),
 ('S2A','s2a','爆炎ウォーカー','2020-04-24'),
 ('S1H','s1','シールド','2019-12-06'),
 ('S1W','s1','ソード','2019-12-06'),
 ('CP4','cp4','プレミアムチャンピオンパック「EX×M×BREAK」','2016-04-16'),
 ('CP6','cp6','ポケットモンスターカードゲーム 拡張パック 20th Anniversary',None),
 ('XY3','xy3','ライジングフィスト','2014-06-14'),
 ('XY4','xy4','ファントムゲート','2014-09-13'),
 ('XY2','xy2','ワイルドブレイズ','2014-03-15'),
 ('CP5','cp5','幻・伝説ドリームキラコレクション','2016-07-16'),
 ('SMP2','smp2','名探偵ピカチュウ','2019-04-26')]


def cached(cache,key):
    raw=(cache/(key+'.html')).read_bytes();receipt=json.loads((cache/(key+'.receipt.json')).read_text())
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('cached page hash mismatch')
    if not receipt['url'].startswith('https://www.pokemon-card.com/'):raise ValueError('nonofficial cached page')
    return raw.decode(),receipt


def compact(s):return re.sub(r'\s+','',html.unescape(s))


def build(db_path,cache,out):
    if out.exists():raise FileExistsError(out)
    db=sqlite3.connect('file:'+str(db_path.resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    rows=[];holds=[]
    for code,key,name,date in SELECTORS:
        try:
            scope=supported_catalog.release_scope_snapshot(db,'ja',code)
            if len(scope['denominators'])!=1:raise ValueError('multiple numbering denominators; product identity withheld')
            product,p=cached(cache,key);card,c=cached(cache,'card-'+code);parsed=parse_page(card.encode())
            entries=parsed['numbered_entries']
            refid=c['url'].rsplit('/',1)[1]
            ref=db.execute("SELECT * FROM card_reference WHERE source='ptcg-database' AND native_id=? AND set_code=?",(refid,code)).fetchone()
            if ref is None or (code,ref['collector_number']) not in [(x['set_code'],x['collector_number']) for x in entries]:raise ValueError('official card coordinate mismatch')
            product_path=re.sub(r'/index\.html$','/',p['url'].removeprefix('https://www.pokemon-card.com'))
            links=[(u,html.unescape(re.sub('<[^>]+>','',label)).strip()) for u,label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',card,re.S) if u.rstrip('/')==product_path.rstrip('/') and compact(name) in compact(re.sub('<[^>]+>','',label))]
            if not links:raise ValueError('card-page release link does not support selected name')
            if compact(name) not in compact(product):raise ValueError('product page lacks selected name')
            if date:
                y,m,d=map(int,date.split('-'))
                if not re.search(fr'{y}年\s*0?{m}月\s*0?{d}日',product):raise ValueError('official product page does not contain selected date')
            original=db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',('ja',code)).fetchone();original=dict(original) if original else None
            row=dict(schema='pokemon.catalog-release-metadata.v1',language='ja',set_code=code,name=name,release_date=date,
                date_scope='initial_product_release_not_copy_date' if date else 'unknown_or_multiple_product_dates',
                original_release=original,original_name=original['name'] if original else None,
                source_provenance=original['provenance'] if original else 'official-release:sha256:'+p['sha256'],
                official_url=p['url'],official_page_sha256=p['sha256'],verified_at=p['fetched_at'],
                evidence_locator='Reviewed product name/date selector; exact card-page coordinate and product link; dates describe initial product family, not copies',
                scope_snapshot=scope,coordinate_reference=dict(native_id=refid,collector_number=ref['collector_number'],provenance=ref['provenance'],official_url=c['url'],official_page_sha256=c['sha256'],product_href=links[0][0],product_link_text=links[0][1]),
                physical_finish_verified=False,price_comparable=False,automatic_offer_join_allowed=False,display_allowed=False)
            rows.append(row)
        except Exception as e:holds.append(dict(set_code=code,reason=str(e)))
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    vocab=[dict(language='ja',set_code=r['set_code'],alias=alias,alias_kind=kind,evidence=r) for r in rows for alias,kind in [(r['name'],'set_name'),(r['set_code'],'printed_code')]]
    out.with_name('vocabulary-v1.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in vocab))
    report=dict(schema='pokemon.release-metadata-build.v1',records=len(rows),names_added=len(rows),dated_products=sum(r['release_date'] is not None for r in rows),undated_products=sum(r['release_date'] is None for r in rows),covered_card_records=sum(r['scope_snapshot']['record_count'] for r in rows),vocabulary_records=len(vocab),holds=holds,selectors_source='manually reviewed official product and card-link scopes; not blind accuracy',metadata_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    out.with_suffix('.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['db','cache','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.db,a.cache,a.output),ensure_ascii=False,indent=2))
