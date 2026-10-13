"""Verify the exact reviewed next-eight name follow-up and its inherited history."""
import argparse
import hashlib
import json
import shutil
import tempfile
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from pokemon_index import catalog_locale, catalog_question_resolver_v2 as resolver, core, variant_dimension_hold, catalog_media
from scripts import audit_international_coverage_expansion as history
from scripts import audit_variant_dimension_holds as hold_audit
from scripts.audit_international_coverage import coverage, facts
from scripts.build_international_coverage_expansion import translated_query, ALIAS_FIELDS, RIGHTS
from scripts.build_pokemon_name_coverage import spaced_digest
from scripts.build_pokemon_name_eight_followup import SETS, PAIRS as JOHTO_PAIRS, PACKET_SHA, REVIEW_SHA, BEFORE_SHA, checked_packet
JAPANESE_LIMIT, ENGLISH_COUNT = 8, 8

DIRECTORY = 'catalog/international-pokemon-eight-followup-v1'
PRIOR = 'catalog-build-manifest-international-pokemon-johto-pilot-v1.json'
MANIFEST = 'catalog-build-manifest-international-pokemon-eight-followup-v1.json'
ADDITIONS = dict(bilingual_concept_revision=8, concept_review_event=8,
                 catalog_locale_evidence=16, catalog_source_mapping=16)


def signature(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_bundle_checks(bundle, packet, proposals, inspected_at, semantic_reviewed_at):
    """Independently bind each imported event to the exact approved source pair."""
    core.parse_time(inspected_at)
    if core.parse_time(semantic_reviewed_at) > core.parse_time(inspected_at):
        raise ValueError('compiler inspection predates actual independent semantic approval')
    events = bundle['review_events']; concepts = bundle['concept_revisions']
    if (len(events) != 8 or len(concepts) != 8
            or len({e['event_id'] for e in events}) != 8
            or len({c['concept_id'] for c in concepts}) != 8):
        raise ValueError('exact unique Johto event/concept inventory differs')
    by_pair = {(p['name_ja'],p['name_en'],p['dex_id']):p for p in proposals}
    expected_concepts = {}
    for event in events:
        proposal, review = event['proposal'], event['review']
        key = (proposal['name_ja'],proposal['name_en'],proposal['dex_id'])
        if key not in by_pair or type(proposal['dex_id']) is not int:
            raise ValueError('event pair or singleton Dex lacks exact semantic approval')
        pair = by_pair[key]; sources = {}; witnesses = {}
        for language in ('ja','en'):
            witness = pair[language]; source = witness['source']
            sources[language] = 'https://github.com/tcgdex/cards-database/blob/' + source['revision'] + '/' + quote(source['native_id'],safe='/')
            witnesses[language] = dict(identity=witness['identity'],dex_id=pair['dex_id'],category='Pokemon',
                native_id=source['native_id'],revision=source['revision'],git_blob=source['git_blob'],sha256=source['sha256'],
                license_sha256=packet['license_sha256'],rights_reference=RIGHTS,rights_status='metadata_internal_reviewed',
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                physical_distribution_region=None,release_snapshot=witness['release_snapshot'])
        frozen = dict(category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],dex_id=pair['dex_id'],
            source_ja=sources['ja'],source_en=sources['en'],rights_reference=RIGHTS,
            ja_card_id=pair['ja']['identity']['card_id'],en_card_id=pair['en']['identity']['card_id'],retrieval_only=True)
        frozen['proposal_id'] = 'pokemon-name-proposal:' + catalog_locale.digest(frozen)
        snapshot = dict(frozen=frozen,ja_provenance=pair['ja']['identity']['provenance'],en_provenance=pair['en']['identity']['provenance'],
            witnesses=witnesses,scope='exact independently reviewed Johto full-name metadata translation; no printing counterpart',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        expected = {**frozen,'ja_provenance':snapshot['ja_provenance'],'en_provenance':snapshot['en_provenance'],
                    'source_snapshot':snapshot,'source_snapshot_sha256':spaced_digest(snapshot)}
        if proposal != expected:
            raise ValueError('review proposal/source witness differs from the frozen approved pair')
        expected_review = dict(decision='approve',review_revision=1,reviewer='ai-independent:gpt-6.1-sol-high',reviewed_at=inspected_at,
            ja_identity_checked=True,en_identity_checked=True,translation_checked=True,requires_card_binding=True,
            semantic_review_sha256=REVIEW_SHA,semantic_reviewed_at=semantic_reviewed_at,
            semantic_review_time_status='recorded_in_independent_approval_packet',
            identity_attestation_scope='existing pinned metadata tuples only; no physical-copy verification',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        if any(review.get(k) != v or isinstance(v,bool) and review.get(k) is not v for k,v in expected_review.items()):
            raise ValueError('review semantic approval, reviewer or no-trading scope differs')
        if event.get('schema') != 'pokemon.concept_review.v1' or event['event_id'] != spaced_digest({k:v for k,v in event.items() if k!='event_id'}):
            raise ValueError('review event hash/schema differs')
        cid = 'pokemon-name:' + catalog_locale.digest(dict(ja=pair['name_ja'],en=pair['name_en'],dex_id=pair['dex_id']))
        expected_concepts[cid] = dict(concept_id=cid,revision=1,category='Pokemon',name_ja=pair['name_ja'],name_en=pair['name_en'],
            source_ja=sources['ja'],source_en=sources['en'],rights_reference=RIGHTS,reviewer=expected_review['reviewer'],
            reviewed_at=inspected_at,status='approved',review_event_id=event['event_id'])
    if len(expected_concepts) != 8 or {c['concept_id']:c for c in concepts} != expected_concepts:
        raise ValueError('concept-to-approved-event identity differs')
    return expected_concepts


def inputs(root):
    original = json.loads((root/'catalog-build-manifest-source-binding-v1.json').read_text())
    prior = json.loads((root/PRIOR).read_text())
    manifest = json.loads((root/MANIFEST).read_text())
    expected = {**prior['expected'], 'bilingual_alias_revisions': 318, 'concept_review_events': 656}
    operations = [('import-concept-review-bundle', DIRECTORY+'/concept-review-bundle.json'),
                  ('import-catalog-locales', DIRECTORY+'/locales.jsonl')]
    if (len(original['steps']) != 65 or len(prior['steps']) != 81 or len(manifest['steps']) != 83
            or original['steps'] != prior['steps'][:65] or manifest['steps'][:81] != prior['steps']
            or manifest['expected'] != expected
            or [(s['operation'], s['path']) for s in manifest['steps'][81:]] != operations):
        raise ValueError('ordered manifest prefix, append scope or expected inventory differs')
    for step in manifest['steps']:
        path = (root/step['path']).resolve()
        if not path.is_relative_to(root.resolve()) or signature(path) != step['sha256']:
            raise ValueError('manifest input hash/path differs')
    rows = [json.loads(line) for line in (root/DIRECTORY/'locales.jsonl').read_text().splitlines()]
    bundle = json.loads((root/DIRECTORY/'concept-review-bundle.json').read_text())
    if (len(bundle['review_events']) != 8 or len(bundle['concept_revisions']) != 8
            or any(c['category'] != 'Pokemon' for c in bundle['concept_revisions'])
            or any(e['review'].get('requires_card_binding') is not True for e in bundle['review_events'])):
        raise ValueError('exact source-bound Pokemon name review scope differs')
    bounded(rows)
    packet_raw = (root/DIRECTORY/'basis-qualification.json').read_bytes()
    review_raw = (root/DIRECTORY/'semantic-review.json').read_bytes()
    packet, proposals, residual, new, english = checked_packet(packet_raw, review_raw)
    times = {r['source']['inspected_at'] for r in rows}
    if len(times) != 1 or signature(root/DIRECTORY/'TCGDEX-LICENSE') != packet['license_sha256']:
        raise ValueError('pilot inspection time or reviewed licence differs')
    reviewed = json.loads(review_raw)
    semantic_reviewed_at = reviewed['review_completed_at']
    core.parse_time(semantic_reviewed_at)
    approved_concepts = approved_bundle_checks(bundle,packet,proposals,next(iter(times)),semantic_reviewed_at)
    if residual or len(new) != 8 or len(english) != 8:
        raise ValueError('next-eight exact witness selection differs')
    witnesses = residual + new + english
    by_id = {w['identity']['card_id']: w for w in witnesses}
    if {r['identity']['card_id'] for r in rows} != set(by_id):
        raise ValueError('pilot IDs differ from the frozen reviewed witness packet')
    if {(c['name_ja'],c['name_en']) for c in bundle['concept_revisions']} != {(j,e) for d,j,e in JOHTO_PAIRS}:
        raise ValueError('new name concepts differ from the exact independent review')
    for row in rows:
        witness = by_id[row['identity']['card_id']]
        if (row['identity'] != witness['identity'] or row['character_scope']['dex_id'] != witness['dex_id']
                or row['source']['native_id'] != witness['source']['native_id']
                or row['source']['sha256'] != witness['source']['sha256']
                or row['source']['revision'] != witness['source']['revision']
                or row['unresolved_conflicts'] or row['test_only'] is not False):
            raise ValueError('pilot source or exact name/identity scope differs')
        if any(row[k] is not False for k in catalog_locale.FALSE_CLAIMS):
            raise ValueError('metadata pilot cannot grant artwork or trading claims')
        source = witness['source']; language = row['identity']['language']
        expected_source = dict(provider='tcgdex',language=language,region='ZZ',release_id='tcgdex-product:'+row['identity']['set_code'],
            native_id=source['native_id'],source_variant=row['identity']['variant'],revision=source['revision'],git_blob=source['git_blob'],
            sha256=source['sha256'],license_git_blob=packet['source_inventory']['LICENSE']['git_blob'],license_sha256=packet['license_sha256'],
            retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at=next(iter(times)),
            physical_distribution_region=None,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed')
        if row['source'] != expected_source or row['release_snapshot'] != witness['release_snapshot']:
            raise ValueError('locale source/licence/release scope differs from the frozen witness')
        aliases = row['name_aliases']
        if len(aliases) != 1:
            raise ValueError('exact current name alias scope differs')
        if witness.get('name_alias'):
            expected_alias = witness['name_alias']
        else:
            concept = next(c for c in approved_concepts.values() if c['name_'+language] == row['identity']['name'])
            expected_alias = {k:concept[k] for k in ALIAS_FIELDS}
        if aliases[0] != expected_alias:
            raise ValueError('locale alias is not tied to its exact approved event')
    return manifest, bundle, rows


def bounded(rows):
    if (Counter(r['identity']['language'] for r in rows) != {'ja': JAPANESE_LIMIT, 'en': ENGLISH_COUNT}
            or len({r['identity']['card_id'] for r in rows}) != 16
            or {r['identity']['set_code'] for r in rows if r['identity']['language'] == 'ja'} != set(SETS)):
        raise ValueError('exact reviewed Johto pilot language/set/ID scope differs')
    for row in rows:
        scope = row.get('character_scope', {})
        if (scope.get('category') != 'Pokemon' or scope.get('full_name') != row['identity']['name']
                or type(scope.get('dex_id')) is not int or not 1 <= scope['dex_id'] <= 251
                or scope.get('form_inheritance_allowed') is not False):
            raise ValueError('literal character name scope differs')


def snapshot_guard_checks(db, hold_rows):
    """Check installed SQL guards and every current held identity, not just rows."""
    hold_audit.installed(db, hold_rows)
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('snapshot integrity or foreign-key references differ')
    if variant_dimension_hold.rows_for(db) != hold_rows:
        raise ValueError('hold evidence inventory differs')
    for row in hold_rows:
        cid = row['identity']['card_id']
        flags = db.execute('SELECT match_eligible,display_allowed FROM card WHERE card_id=?',(cid,)).fetchone()
        if (not flags or tuple(flags) != (0,0) or catalog_locale.snapshot(db,cid) != row['identity']
                or variant_dimension_hold.context(db,cid)['status'] != 'held_legacy_variant_dimensions'
                or catalog_media.availability(db,cid)['status'] != 'identity_hold'):
            raise ValueError('current held identity, flags or media gate differs')
    return True


def preserved(before, after):
    if history.tables(before) != history.tables(after):
        raise ValueError('schema inventory differs')
    hold_rows = variant_dimension_hold.rows_for(before)
    if len(hold_rows) != 44:
        raise ValueError('exact inherited 44 identity holds differ')
    snapshot_guard_checks(before,hold_rows)
    snapshot_guard_checks(after,hold_rows)
    checks = {}
    for table in history.tables(before):
        old, new = history.records(before, table), history.records(after, table)
        checks[table] = (new[:len(old)] == old and len(new) == len(old)+ADDITIONS[table]
                         if table in ADDITIONS else old == new)
    if not all(checks.values()):
        raise ValueError('historical rows/columns changed: '+','.join(t for t,v in checks.items() if not v))
    return checks


def installed_bundle(db, bundle):
    fields = ('concept_id','revision','category','name_ja','name_en','source_ja','source_en',
              'rights_reference','reviewer','reviewed_at','status','review_event_id')
    for concept in bundle['concept_revisions']:
        found = db.execute('SELECT * FROM bilingual_concept_revision WHERE concept_id=? AND revision=?',
                           (concept['concept_id'], concept['revision'])).fetchone()
        if not found or tuple(found[k] for k in fields) != tuple(concept[k] for k in fields):
            raise ValueError('installed name concept differs')
    for event in bundle['review_events']:
        proposal, review = event['proposal'], event['review']
        expected = (event['event_id'], proposal['proposal_id'], review['review_revision'],
                    proposal['source_snapshot_sha256'], review['decision'], review['reviewer'],
                    review['reviewed_at'], json.dumps(event, ensure_ascii=False, sort_keys=True))
        found = db.execute('SELECT * FROM concept_review_event WHERE event_id=?', (event['event_id'],)).fetchone()
        if not found or tuple(found) != expected:
            raise ValueError('installed name review evidence differs')


def append(before_path, output, root):
    if output.exists():
        raise FileExistsError('incremental snapshot already exists')
    manifest, bundle, rows = inputs(root)
    before_sha = signature(before_path)
    if before_sha != BEFORE_SHA:
        raise ValueError('pilot requires its exact frozen prior snapshot')
    with closing(core.connect(before_path,readonly=True)) as before:
        snapshot_guard_checks(before,variant_dimension_hold.rows_for(before))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        scratch = Path(directory)/'append.sqlite3'
        shutil.copyfile(before_path, scratch)
        with closing(core.connect(scratch)) as db:
            concepts = core.import_concept_review_bundle(db, bundle)
            locales = catalog_locale.import_evidence(db, rows)
            if concepts != dict(review_events=8, concept_revisions=8) or locales != dict(inserted=16,unchanged=0,quarantined=0):
                raise ValueError('batch must append distinct name reviews and current bindings')
            installed_bundle(db, bundle); history.installed(db, rows)
        with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(scratch, readonly=True)) as after:
            preserved(before, after)
        if inputs(root) != (manifest, bundle, rows) or signature(before_path) != before_sha:
            raise ValueError('input or prior snapshot drift during append')
        with output.open('xb') as handle:
            handle.write(scratch.read_bytes())
    return dict(concepts=concepts, locales=locales)


def run(before_path, after_path, rebuilt_path, root):
    manifest, bundle, rows = inputs(root)
    paths = (before_path, after_path, rebuilt_path)
    signatures = {str(path): signature(path) for path in paths}
    if signatures[str(before_path)] != BEFORE_SHA:
        raise ValueError('audit prior snapshot differs from the exact reviewed baseline')
    with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(after_path, readonly=True)) as after, closing(core.connect(rebuilt_path, readonly=True)) as rebuilt:
        preservation = preserved(before, after)
        snapshot_guard_checks(rebuilt,variant_dimension_hold.rows_for(before))
        for db in (after, rebuilt):
            history.installed(db, rows); installed_bundle(db, bundle)
        if history.tables(after) != history.tables(rebuilt):
            raise ValueError('rebuild schema differs')
        rebuilt_checks = {}; timestamps = {}
        for table in history.tables(after):
            left, right = history.records(after, table), history.records(rebuilt, table)
            if table in history.GENERATED_COLUMNS:
                column = history.GENERATED_COLUMNS[table]
                index = [r[1] for r in after.execute('PRAGMA table_info('+table+')')].index(column)
                timestamps[table] = dict(column=column, changed=sum(a[index] != b[index] for a,b in zip(left,right)))
                left = [r[:index]+r[index+1:] for r in left]; right = [r[:index]+r[index+1:] for r in right]
            rebuilt_checks[table] = left == right
        if not all(rebuilt_checks.values()):
            raise ValueError('independent rebuild differs outside four named generated timestamp columns')
        before_counts, after_counts = coverage(before), coverage(after)
        if {k:v for k,v in before_counts.items() if k!='localized_bindings'} != {k:v for k,v in after_counts.items() if k!='localized_bindings'}:
            raise ValueError('coverage changed outside source-bound localization')
        queries = []; search_cache = {}
        for row in rows:
            card, alias = row['identity'], row['name_aliases'][0]
            query = translated_query(card, alias)
            def search(db,q,**kw):
                # Several separate variants share an identical query. Read-only
                # snapshots are hash checked at both ends; each target ID still
                # gets an individual assertion against the actual search result.
                key=(id(db),card['set_code'],q,kw.get('language'))
                if key not in search_cache:
                    search_cache[key]=core.catalog_search_internal(db,q,set_code=card['set_code'],limit=100,**kw)
                return search_cache[key]
            target = lambda result: card['card_id'] in {c['card_id'] for c in result['cards']}
            wide = ''.join(chr(ord(c)+0xfee0) if 0x21<=ord(c)<=0x7e else c for c in query)
            checks = dict(before_missing=not target(search(before,query)), after_found=target(search(after,query)),
                native_found=target(search(after,f"{card['name']} {card['language']} {card['set_code']} {card['collector_number']}")),
                unicode_found=target(search(after,unicodedata.normalize('NFD',wide))),
                wrong_language_excludes_target=not target(search(after,query,language='en' if card['language']=='ja' else 'ja')))
            if not all(checks.values()):
                raise ValueError('retrieval regression: '+card['card_id']+' '+str(checks))
            name = alias['name_en' if card['language']=='ja' else 'name_ja']
            old = resolver.resolve_question(before,facts(row,name))
            new = resolver.resolve_question(after,facts(row,name))
            # The resolver may retain multiple variants or abstain when an unbound
            # stamped sibling is in scope. No artificial unique SKU is required.
            for candidate in new['resolution']['candidate_ids']:
                found = after.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE card_id=?',(candidate,)).fetchone()
                if (not found or found['language']!=card['language'] or found['set_code']!=card['set_code']
                        or found['collector_number']!=card['collector_number'] or found['category']!='Pokemon'
                        or resolver.full_name_key(found['name'])!=resolver.full_name_key(card['name'])
                        or not catalog_locale.has_current_alias(after,candidate,new['name_aliases'])):
                    raise ValueError('resolver crossed an identity/name/binding boundary')
            if (old['resolution']['status'] != 'not_attempted' or old['resolution']['candidate_ids']
                    or new['resolution']['status'] not in {'unique','multiple_candidates'}
                    or card['card_id'] not in new['resolution']['candidate_ids']):
                raise ValueError('unexpected translated resolver miss')
            queries.append(dict(card_id=card['card_id'],language=card['language'],query=query,**checks,
                resolver_before=old['resolution'],resolver_after=new['resolution'],resolver_reason=new['reason']))
        unfiltered = []
        for row in rows[::max(1,len(rows)//10)][:10]:
            query = translated_query(row['identity'],row['name_aliases'][0]); cid = row['identity']['card_id']
            if cid not in {c['card_id'] for c in core.catalog_search_internal(after,query,limit=100)['cards']}:
                raise ValueError('unfiltered search lost target')
            unfiltered.append(dict(card_id=cid,query=query,after_found=True))
        report = dict(schema='pokemon.pokemon-eight-followup-audit.v1',before=before_counts,after=after_counts,
            manifest_inputs_before=81,manifest_inputs_after=83,original_manifest_inputs=65,preserved_ordered_prefix=True,
            manifest_sha256=signature(root/MANIFEST),database_sha256=signatures,
            new_name_concepts=8,new_localized_bindings=16,translated_gaps_closed=len(queries),
            batch_by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
            localized_bindings_by_language={r[0]:r[1] for r in after.execute('SELECT c.language,count(*) FROM catalog_locale_evidence e JOIN card c USING(card_id) GROUP BY c.language')},
            historical_tables_preserved=preservation,rebuild_tables_equal=rebuilt_checks,
            rebuild_generated_timestamp_differences=timestamps,
            rebuild_timestamp_scope='Only legacy generated asserted_at/applied_at on four named tables excluded from rebuild comparison. Incremental snapshot preserves every prior column.',
            basis_qualification_sha256=PACKET_SHA, independent_semantic_review_sha256=REVIEW_SHA,
            exact_all44_hold_guards_flags_and_contexts_verified=True, snapshot_integrity_and_foreign_keys_verified=True,
            exact_installed_evidence_and_mapping_bindings=True,queries=queries,unfiltered_queries=unfiltered,
            resolver_status_counts=dict(Counter(q['resolver_after']['status'] for q in queries)),
            resolver_hold_reasons=dict(Counter(q['resolver_reason'] for q in queries if q['resolver_after']['status']=='not_attempted')),
            source_mappings_after=after.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],
            held_candidates_after=after.execute('SELECT count(*) FROM catalog_coverage_candidate').fetchone()[0],
            quarantine_after=after.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            scope='existing-record discovery; no new card identities, counterparts, artwork, prices, physical or commerce approvals')
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)/'reimport.sqlite3'; shutil.copyfile(after_path,scratch)
        with closing(core.connect(scratch)) as db:
            old = {table:history.records(db,table) for table in history.tables(db)}
            concepts = core.import_concept_review_bundle(db,bundle); locales = catalog_locale.import_evidence(db,rows)
            if (concepts!=dict(review_events=0,concept_revisions=0) or locales!=dict(inserted=0,unchanged=16,quarantined=0)
                    or any(history.records(db,t)!=values for t,values in old.items())):
                raise ValueError('idempotent reimport changed records')
            report['idempotent_reimport'] = dict(concepts=concepts,locales=locales,all_tables_unchanged=True)
        # Reviews alone cannot expand record eligibility across the whole catalogue.
        scratch2 = Path(directory)/'concepts-only.sqlite3'; shutil.copyfile(before_path,scratch2)
        with closing(core.connect(scratch2)) as db:
            core.import_concept_review_bundle(db,bundle)
            binding_holds = 0
            for row in rows:
                card, alias = row['identity'],row['name_aliases'][0]
                name = alias['name_en' if card['language']=='ja' else 'name_ja']
                result = resolver.resolve_question(db,facts(row,name))
                if result['resolution']['status']!='not_attempted' or result['reason']!='reviewed_name_record_binding_required':
                    raise ValueError('name review expanded an unbound record')
                binding_holds += 1
            report['concepts_without_record_bindings_abstain'] = binding_holds
    if inputs(root)!=(manifest,bundle,rows) or any(signature(path)!=signatures[str(path)] for path in paths):
        raise ValueError('audited input/snapshot drift')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','rebuilt','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a = p.parse_args(); report = run(a.before,a.after,a.rebuilt,Path.cwd())
    with a.output.open('x') as handle:
        handle.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_name_concepts','new_localized_bindings','resolver_status_counts','idempotent_reimport')}))


if __name__ == '__main__':
    main()
