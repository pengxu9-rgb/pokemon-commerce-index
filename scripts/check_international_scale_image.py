"""Check the entire read-only scale database inside or outside the runtime image.

Only the four already documented build-generated timestamp columns are
normalized. The expected digest must come from the independently rebuilt and
reviewed 86-input database, never from the image under test.
"""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

GENERATED = {'card_identity_exception':'applied_at', 'card_number_conflict_rule':'applied_at',
             'card_rarity_correction':'applied_at', 'card_relationship_assertion':'asserted_at'}
# Independently audited stage19 scale.sqlite3 and its equivalent rebuild.
REVIEWED_LOGICAL_SHA = 'b73076d0e7fd718c68544df3088741359949b1daed6ea97c64be059855225f7a'
REVIEWED_RUNTIME_REVISION = '17f89aeb6bc24088e36103cd9435687a831f622f06630191b8d0902fb4d4f4ad'


def quoted(value):
    return '"'+value.replace('"','""')+'"'


def logical_digest(db):
    digest=hashlib.sha256(b'pokemon.international-scale-logical.v1')
    def add(value):
        digest.update(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode());digest.update(b'\n')
    add([db.execute('PRAGMA '+p).fetchone()[0] for p in ('encoding','application_id','user_version')])
    add([list(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name')])
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for table in tables:
        columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted(table)+')')];add([table,columns])
        for row in db.execute('SELECT * FROM '+quoted(table)+' ORDER BY rowid'):
            values=list(row)
            if table in GENERATED:
                index=columns.index(GENERATED[table]);stamp=values[index]
                if not isinstance(stamp,str) or datetime.fromisoformat(stamp.replace('Z','+00:00')).tzinfo is None:
                    raise ValueError('invalid generated timestamp')
                values[index]=None
            add(values)
    return digest.hexdigest()


def check(db,expected):
    if expected is not None and not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('expected digest must be a SHA256')
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('database integrity failed')
    counts={table:db.execute('SELECT count(*) FROM '+quoted(table)).fetchone()[0] for table in
        ('card','catalog_locale_evidence','catalog_source_mapping','bilingual_concept_revision','concept_review_event','catalog_identity_quarantine','priceable_unit','listing','observation','landed_quote','verified_sale')}
    wanted=dict(card=70006,catalog_locale_evidence=6364,catalog_source_mapping=6364,bilingual_concept_revision=718,concept_review_event=1056,catalog_identity_quarantine=109,priceable_unit=0,listing=0,observation=0,landed_quote=0,verified_sale=0)
    if counts!=wanted or db.execute('SELECT count(*) FROM card WHERE display_allowed=1').fetchone()[0]:raise ValueError('scale coverage or trading boundary differs')
    languages=dict(db.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language'))
    if languages!=dict(en=1333,ja=5031):raise ValueError('localized languages differ')
    value=logical_digest(db)
    if expected is not None and value!=expected:raise ValueError('image differs from independently verified full logical snapshot')
    return dict(schema='pokemon.scale-image-check.v1',passed=True,logical_sha256=value,counts=counts,localized_languages=languages,read_only=True)


def runtime_smoke(path):
    from pokemon_index import core,collector_journey,collector_runtime,variant_dimension_hold,catalog_read_model_artifact
    from pokemon_index import catalog_question_resolver_v2 as resolver
    def exercise(db):
        results=[]
        for language in ('ja','en'):
            records=db.execute('SELECT e.record_json FROM catalog_locale_evidence e JOIN card c USING(card_id) WHERE c.language=? ORDER BY c.card_id LIMIT 2',(language,))
            for record in records:
                row=json.loads(record[0]);card=row['identity'];alias=row['name_aliases'][0];name=alias['name_en' if language=='ja' else 'name_ja']
                ids=[]
                for query in (name,unicodedata.normalize('NFD',name)):
                    answer=core.catalog_search_internal(db,query,language=language,set_code=card['set_code'],variant=card['variant'],limit=100)
                    found=sorted(c['card_id'] for c in answer['cards'])
                    if card['card_id'] not in found:raise ValueError('container translated runtime target lost')
                    ids.append(found)
                facts=dict(object_type='single_card',primary_goal='price_comparison',transaction_context='prospective_buy',seller_channel='none',identity_tokens=dict(card_names=[name],set_name=card['set_code'],collector_number=card['collector_number'],language=language,rarity=None,finish=card['variant'],grade=None),media_state='none',language_mentions=[language],platform_refs=[],merchant_ref=None,destination=None)
                resolution=resolver.resolve_question(db,facts)['resolution']
                if card['card_id'] not in resolution['candidate_ids']:raise ValueError('container exact translated resolver target lost')
                results.append(dict(target=card['card_id'],query_ids=ids,resolution=resolution))
        held=core.catalog_card_internal(db,'en:BASE1:058/102:normal')['card']
        if held['media_availability']['status']!='identity_hold' or held['variant_dimension_hold']['purchase_allowed'] is not False:raise ValueError('container identity hold lost')
        return results
    with closing(core.connect(path,readonly=True)) as db:
        revision=collector_journey.catalog_revision(db)
        if revision!=REVIEWED_RUNTIME_REVISION:raise ValueError('actual container runtime policy or data differs')
        if len(variant_dimension_hold.rows_for(db))!=44:raise ValueError('container hold inventory differs')
        native=exercise(db)
    with closing(core.connect(path,readonly=True)) as db,collector_runtime.sqlite_deadline(db,time.monotonic()+8):model=collector_runtime.CatalogReadModel(db)
    with closing(core.connect(path,readonly=True)) as db,collector_runtime.sqlite_deadline(db,time.monotonic()+8),model.request(db):accelerated=exercise(db)
    if native!=accelerated:raise ValueError('container native and accelerated runtime differ')
    native_state=catalog_read_model_artifact.model_state(model)
    with closing(core.connect(path,readonly=True)) as db,collector_runtime.sqlite_deadline(db,time.monotonic()+8):
        loaded,loaded_revision,artifact=catalog_read_model_artifact.load_packaged(db,required=True)
    if loaded_revision!=revision or catalog_read_model_artifact.model_state(loaded)!=native_state:
        raise ValueError('complete packaged model differs from independent native facts or revision')
    if len(loaded._media_ids)!=1171:
        raise ValueError('packaged model source-evidence membership differs')
    with closing(core.connect(path,readonly=True)) as db,collector_runtime.sqlite_deadline(db,time.monotonic()+8),loaded.request(db):
        packaged=exercise(db)
    if packaged!=native:raise ValueError('packaged runtime JSON differs from native responses')
    return dict(catalog_revision=revision,representative_targets=4,native_accelerated_equal=True,
                packaged_native_state_equal=True,packaged_native_json_equal=True,
                packaged_current_source_evidence_ids=1171,packaged_artifact=artifact,
                held_target_blocked=True,existing_eight_second_budget_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',type=Path,default=Path('/app/catalog.sqlite3'));parser.add_argument('--expected-logical-sha',default=REVIEWED_LOGICAL_SHA);parser.add_argument('--runtime-smoke',action='store_true');args=parser.parse_args()
    uri=args.db.resolve(strict=True).as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:report=check(db,args.expected_logical_sha)
    if args.runtime_smoke:report['actual_runtime']=runtime_smoke(args.db)
    print(json.dumps(report))


if __name__=='__main__':main()
