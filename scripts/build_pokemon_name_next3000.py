"""Compile the next bounded existing-concept metadata binding batch offline.

This compiler does not approve names, physical printings, images or commerce.
The historical scale compiler and its frozen release remain unchanged.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path, PurePosixPath

from pokemon_index import catalog_locale, core, variant_dimension_hold, collector_runtime
from scripts import build_pokemon_name_scale as strict
from scripts import build_pokemon_name_coverage as names
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts
from scripts.audit_pokemon_name_eight_followup import snapshot_guard_checks
from scripts.build_international_coverage_expansion import ALIAS_FIELDS, RIGHTS, translated_query
from pokemon_index import catalog_question_resolver_v2 as resolver

DIRECTORY = 'catalog/international-pokemon-next3000-v1'
PRIOR = 'catalog-build-manifest-international-pokemon-scale-v1.json'
MANIFEST = 'catalog-build-manifest-international-pokemon-next3000-v1.json'
BEFORE_SHA = 'f5a983ce5e9f8b09d67e23ab447bcac82830a6a2862bd16eafa39a64291a3c3a'
# These are filled only after the independent record-binding review completes.
PACKET_SHA = '9d44b2280faae20f060f76c94d271808375d724fecd64dde8ac7e2321e42ce45'
REVIEW_SHA = '0416402b2b8cd0147474f45972511e35180e83146522d696450f75df5f7f2cd4'
SELECTED_IDS_SHA = '6c121b06e3d2baccc0b3596bef82f4358730afbb10cf27e54f0844d873156c9f'
PRIOR_QUALIFICATION_SHA = '6b12a294f8b464106b2a2a660a895e0193f63a1f754215c1c5df7697fffa2491'
require = strict.require
signature = strict.signature
claims = strict.claims
false_claims = strict.false_claims
coordinate = strict.coordinate


def checked_packet(raw, review_raw):
    require(PACKET_SHA and REVIEW_SHA and signature(raw) == PACKET_SHA
            and signature(review_raw) == REVIEW_SHA, 'exact fresh qualification and independent record review required')
    packet, review = json.loads(raw), json.loads(review_raw)
    require(packet.get('schema') == 'pokemon.stage24-next3000-source-qualification.v1'
            and packet.get('applied') is False and packet.get('input_database_sha256') == BEFORE_SHA
            and packet.get('source_pin') == strict.REVISION and packet.get('rights_reference') == RIGHTS,
            'current snapshot/source/rights qualification differs')
    false_claims(packet)
    rows = packet['english_witnesses']
    ids = [w['identity']['card_id'] for w in rows]
    require(len(rows) == len(set(ids)) == 3000 and sorted(ids) == packet['selected_card_ids']
            and catalog_locale.digest(sorted(ids)) == SELECTED_IDS_SHA,
            'exact distinct selected 3000 IDs differ')
    require(packet['selection_counts'] == dict(ja=0, en=3000, total=3000, newpairs=0, existing_ja=0, new_ja=0, existing_en=3000, new_en=0)
            and all(packet.get(k) == [] for k in ('existing_review_witnesses', 'new_name_witnesses', 'new_name_proposals')),
            'this batch may only bind existing English identities to existing reviews')
    require(len({coordinate(w['identity']) for w in rows}) == 1503
            and len({w['identity']['set_code'] for w in rows}) == 48,
            'complete group and release inventory differs')
    require(packet.get('semantic_pending_resolution_count') == 534
            and packet.get('semantic_pending_resolution_original_packet_sha256') == PRIOR_QUALIFICATION_SHA
            and packet.get('semantic_pending_resolution_semantic_authority_sha256') == strict.REVIEW_SHA,
            'exact historical pending-note reconciliation lineage differs')
    references = {r['name_alias']['concept_id']: r for r in packet['existing_semantic_reviews']}
    resolved = 0
    for w in rows:
        c = w['identity']; false_claims(w)
        require(c['language'] == 'en' and core.card_id(c['language'], c['set_code'], c['collector_number'], c['variant']) == c['card_id']
                and w.get('name_alias') and w.get('unresolved_conflicts') == [] and w.get('unresolved_source_conflicts', []) == [],
                'conflicted identity or current exact alias absent')
        require(coordinate(c) not in {coordinate(x) for x in strict.previous.expanded_excluded_groups()}
                and c['set_code'] != 'SV4A', 'priority or raw-header identity conflict selected')
        if 'semantic_pending_resolution' in w:
            lineage = w['semantic_pending_resolution']; false_claims(lineage)
            ref = references[w['name_alias']['concept_id']]
            require(lineage.get('original_unresolved_conflicts') == [strict.PENDING_SEMANTIC_REVIEW]
                    and lineage.get('original_qualification_sha256') == PRIOR_QUALIFICATION_SHA
                    and lineage.get('current_name_alias') == w['name_alias']
                    and lineage.get('current_event_record_sha256') == ref['event_record_sha256']
                    and lineage.get('current_event_canonical_sha256') == ref['event_canonical_sha256']
                    and lineage.get('current_source_snapshot_sha256') == ref['source_snapshot_sha256']
                    and lineage.get('current_semantic_review_sha256') == strict.REVIEW_SHA,
                    'pending semantic note lacks exact current existing approval')
            require(core.parse_time(packet['inspected_at']) <= core.parse_time(lineage['resolved_at'])
                    <= core.parse_time(packet['inspection_completed_at']), 'pending resolution time is outside actual inspection')
            resolved += 1
    require(resolved == 534, 'every exact prior pending note must retain its resolution lineage')
    require(review.get('schema') == 'pokemon.independent-next3000-record-review.v1'
            and review.get('reviewer') == 'GPT-6.1 Sol high' and review.get('proposal_sha256') == PACKET_SHA
            and review.get('decision') == 'approve_all_exact_record_bindings'
            and review.get('approved_record_bindings') == 3000
            and review.get('selected_card_ids_sha256') == SELECTED_IDS_SHA
            and review.get('rejected_card_ids') == [] and review.get('uncertain_card_ids') == []
            and review.get('approved_into_catalog') is False and review.get('sources_fetched') is False,
            'fresh independent exact record-binding approval differs')
    false_claims(review)
    require(review.get('review_completed_at_status') == 'attested_by_UTC_clock_after_independent_review',
            'independently attested review time required')
    core.parse_time(review['review_completed_at'])
    require(review.get('historical_retrieved_at') is None, 'review time is not source retrieval time')
    return packet, rows


def current_concepts(db, packet):
    """Read exact current approvals, retaining the original event IDs and names."""
    audit, events, aliases = [], {}, {}
    for c in db.execute("""WITH latest AS(SELECT *,row_number() OVER(PARTITION BY concept_id ORDER BY revision DESC) rank
        FROM bilingual_concept_revision) SELECT * FROM latest WHERE rank=1 AND status='approved' AND category='Pokemon' ORDER BY concept_id"""):
        alias = {k: c[k] for k in ALIAS_FIELDS}; catalog_locale.approved_alias(db, alias)
        stored = db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?', (c['review_event_id'],)).fetchone()
        require(stored, 'current exact-name event missing')
        event = json.loads(stored[0]); proposal = event['proposal']; frozen = proposal['source_snapshot']['frozen']
        dex = frozen.get('dex_id')
        require(event.get('event_id') == c['review_event_id'] == names.spaced_digest({k: v for k, v in event.items() if k != 'event_id'})
                and proposal['source_snapshot_sha256'] == names.spaced_digest(proposal['source_snapshot'])
                and event['review'].get('decision') == 'approve' and event['review'].get('requires_card_binding') is True
                and frozen.get('category') == 'Pokemon' and type(dex) is int and 1 <= dex <= 1025
                and all(frozen.get(k) == alias[k] for k in ('name_ja', 'name_en')),
                'retained current exact full-name review changed')
        false_claims(event['review']); false_claims(proposal['source_snapshot'])
        item = dict(concept_id=c['concept_id'], revision=c['revision'], name_ja=c['name_ja'], name_en=c['name_en'],
                    review_event_id=c['review_event_id'], dex_id=dex, requires_exact_card_binding=True)
        audit.append(item); events[c['concept_id']] = event; aliases[c['concept_id']] = (alias, dex)
    require(len(audit) == packet.get('current_approved_pokemon_full_name_concepts') == 596
            and len(packet['current_concept_audit']) == 596, 'current 596 full-name inventory differs')
    for actual, declared in zip(audit, packet['current_concept_audit']):
        require(all(declared.get(k) == v for k, v in actual.items()), 'current exact concept inventory differs')
        if 'review_record_sha256' in declared:
            require(declared['review_record_sha256'] == signature(catalog_locale.encoded(events[actual['concept_id']]).encode()),
                    'current exact semantic event bytes differ')
    return audit, events, aliases


def complete_groups(db, witnesses, bound):
    selected = {w['identity']['card_id'] for w in witnesses}
    grouped = defaultdict(list)
    for row in db.execute("""SELECT c.*,cl.category FROM card c LEFT JOIN card_classification cl USING(card_id)
        WHERE c.language='en' AND c.match_eligible=1 AND c.variant NOT LIKE 'unverified%'"""):
        grouped[coordinate(row)].append(row)
    for w in witnesses:
        c = w['identity']; siblings = grouped[coordinate(c)]
        require(siblings and all(r['name'] == c['name'] and r['category'] == 'Pokemon'
                and not variant_dimension_hold.held(db, r['card_id']) and r['card_id'] in selected | bound for r in siblings),
                'incomplete, held or ambiguous whole eligible English coordinate group')


def compiler_inputs():
    inputs = strict.compiler_inputs()
    root = Path(__file__).resolve().parents[1]
    for p in (Path(__file__).resolve(), root / 'scripts/audit_pokemon_name_eight_followup.py'):
        inputs[p] = p.read_bytes()
    return inputs


def grouped_resolutions(db, rows):
    """Reuse read-only request facts within each bounded release, then discard."""
    @collector_runtime.catalog_request
    def batch(connection, selected):
        return {r['identity']['card_id']: resolver.resolve_question(connection, facts(r, r['name_aliases'][0]['name_ja']))
                for r in selected}
    groups = defaultdict(list)
    for row in rows:
        groups[row['identity']['set_code']].append(row)
    answers = {}
    for selected in groups.values():
        answers.update(batch(db, selected))
    return answers


def compile(db_path, repo, root, packet_path, review_path, inspected_at):
    core.parse_time(inspected_at)
    raw, review_raw = packet_path.read_bytes(), review_path.read_bytes()
    packet, witnesses = checked_packet(raw, review_raw)
    reviewed_at = json.loads(review_raw)['review_completed_at']
    require(core.parse_time(reviewed_at) <= core.parse_time(inspected_at), 'compiler inspection predates record approval')
    require(signature(db_path.read_bytes()) == BEFORE_SHA, 'immutable current snapshot differs')
    inputs = compiler_inputs(); code_root = Path(__file__).resolve().parents[1]
    require(all(signature(inputs[code_root / p]) == packet['parsing_source_sha256'][k]
                for k, p in strict.CODE_INPUTS.items()), 'qualification parser checkpoint differs')
    inventory = packet['source_inventory']
    require(1 <= len(inventory) <= 10000 and 'LICENSE' in inventory, 'bounded existing pinned inventory required')
    for name in inventory:
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and (name == 'LICENSE' or p.suffix == '.ts' and p.parts[0] in ('data', 'data-asia'))
                and not any(x.casefold() in ('pocket', 'digital') for x in p.parts), 'physical metadata path required')
    blobs = strict.tree_chunks(repo, inventory)
    require(set(blobs) == set(inventory), 'pinned inventory paths absent')
    raws = {p: strict.checked_source(repo, p, b) for p, b in blobs.items()}
    licence = (root / 'catalog/TCGDEX-LICENSE').read_bytes()
    require(raws['LICENSE'] == licence and signature(licence) == packet['license_sha256'], 'reviewed metadata licence differs')
    for p, b in raws.items():
        expected = dict(provider='tcgdex', native_id=p, revision=strict.REVISION, git_blob=blobs[p], sha256=signature(b), bytes=len(b),
                        rights_reference=RIGHTS, rights_status='metadata_internal_reviewed', license_sha256=signature(licence),
                        retrieved_at=None, retrieval_status='historical_snapshot_time_not_recorded', physical_distribution_region=None, available=True)
        require(all(inventory[p].get(k) == v for k, v in expected.items()), 'source inventory bytes/pin/licence/rights changed')
    with closing(core.connect(db_path, readonly=True)) as before:
        before.execute('BEGIN')
        audit, events, aliases = current_concepts(before, packet)
        bound = strict.previous.bound_ids(before)
        require(len(bound) == packet.get('current_localized_bindings') == 6364
                and catalog_locale.digest(sorted(bound)) == packet['current_bound_card_ids_sha256']
                and before.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0] == 6364
                and before.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0] == packet.get('current_source_mappings') == 6364,
                'current binding and provider mapping inventory differs')
        keys = list(catalog_locale.SOURCE_FIELDS)
        mappings = [dict(r) for r in before.execute('SELECT * FROM catalog_source_mapping ORDER BY ' + ','.join(keys))]
        require(packet.get('current_mapping_digest_order') == keys
                and catalog_locale.digest(mappings) == packet.get('current_source_mapping_rows_sha256'),
                'exact current provider-namespaced mapping rows differ')
        require(not bound & set(packet['selected_card_ids']), 'selected printing already bound')
        complete_groups(before, witnesses, bound)
        holds = variant_dimension_hold.rows_for(before)
        require(len(holds) == packet.get('identity_holds_preserved') == 44, 'identity hold inventory differs')
        snapshot_guard_checks(before, holds)
        used, cache = {}, {}
        rows = []
        for w in witnesses:
            c = w['identity']; alias = w['name_alias']
            require(alias.get('concept_id') in aliases, 'selected alias is not currently approved')
            checked, dex = aliases[alias['concept_id']]
            require(alias == checked and c['name'] == alias['name_en'] and w['dex_id'] == dex, 'current exact full-name/Dex scope differs')
            strict.inspect_witness(before, w, raws, blobs, dict(**alias, dex_id=dex), cache)
            used[alias['concept_id']] = (alias, dex)
            path, digest = strict.source_fields(c)
            row = dict(schema='pokemon.catalog-locale.v1', identity=c,
                source=dict(provider='tcgdex', language='en', region='ZZ', release_id='tcgdex-product:' + c['set_code'],
                    native_id=path, source_variant=c['variant'], revision=strict.REVISION, git_blob=blobs[path], sha256=digest,
                    license_git_blob=blobs['LICENSE'], license_sha256=signature(licence), retrieved_at=None,
                    retrieval_status='historical_snapshot_time_not_recorded', inspected_at=inspected_at, physical_distribution_region=None,
                    rights_reference=RIGHTS, rights_status='metadata_internal_reviewed'),
                release_snapshot=w['release_snapshot'], name_aliases=[alias],
                character_scope=dict(dex_id=dex, full_name=c['name'], category='Pokemon', form_inheritance_allowed=False), confidence=1.0,
                confidence_scope='checked pinned source tuples and exact independently reviewed full-name translation only',
                unresolved_conflicts=[], test_only=False, **claims())
            row['evidence_id'] = 'catalog-locale:' + catalog_locale.digest(row); rows.append(row)
        require(len(used) == 448, 'exact used current concept inventory differs')
        for cid, (alias, dex) in used.items():
            strict.inspect_existing_semantics(before, alias, dex, events[cid], raws, blobs)
        refs = packet['existing_semantic_reviews']
        require(len(refs) == len(used) and {x['name_alias']['concept_id'] for x in refs} == set(used), 'semantic reference inventory differs')
        for ref in refs:
            cid = ref['name_alias']['concept_id']; event = events[cid]
            stored_raw = before.execute('SELECT record_json FROM concept_review_event WHERE event_id=?', (ref['name_alias']['review_event_id'],)).fetchone()[0]
            require(ref['name_alias'] == used[cid][0] and ref['event_record_sha256'] == signature(stored_raw.encode())
                    and ref['event_canonical_sha256'] == signature(catalog_locale.encoded(event).encode())
                    and ref['source_snapshot_sha256'] == event['proposal']['source_snapshot_sha256'], 'retained semantic reference hash differs')
        before.commit()
        old_search = strict.grouped_search(before, rows)
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / 'next3000.sqlite3'; shutil.copyfile(db_path, scratch)
            with closing(core.connect(scratch)) as db:
                gaps = []
                before_answers = grouped_resolutions(db, rows)
                for row in rows:
                    cid = row['identity']['card_id']; alias = row['name_aliases'][0]
                    prior = old_search[strict.search_key(row)]
                    require(cid not in prior['card_ids'], 'selected translated target already retrievable')
                    catalog_locale.validate(db, row)
                    require(not catalog_locale.has_current_alias(db, cid, [alias]), 'printing is already bound')
                    answer = before_answers[cid]
                    require(answer['resolution']['status'] == 'not_attempted' and answer['reason'] == 'reviewed_name_record_binding_required',
                            'existing concept unexpectedly widens an unbound printing')
                    gaps.append(dict(card_id=cid, query=translated_query(row['identity'], alias), before_contains_target=False,
                                     before_total=prior['total']))
                imported = catalog_locale.import_evidence(db, rows)
                require(imported == dict(inserted=3000, unchanged=0, quarantined=0), 'exact locale append differs')
                after_search = strict.grouped_search(db, rows)
                after_answers = grouped_resolutions(db, rows)
                for row, gap in zip(rows, gaps):
                    cid = row['identity']['card_id']
                    require(cid in after_search[strict.search_key(row)]['card_ids'] and catalog_locale.snapshot(db, cid) == row['identity'],
                            'translated target lost or existing ID changed')
                    answer = after_answers[cid]
                    require(answer['resolution']['status'] in ('unique', 'multiple_candidates') and cid in answer['resolution']['candidate_ids'],
                            'translated resolution lost its precise printing')
                    gap.update(after_contains_target=True, resolver_after=answer['resolution'])
                preserved = {}
                require(history.tables(before) == history.tables(db), 'historical table inventory differs')
                for table in history.tables(before):
                    old, new = history.records(before, table), history.records(db, table)
                    preserved[table] = (new[:len(old)] == old and len(new) == len(old) + 3000) if table in ('catalog_locale_evidence', 'catalog_source_mapping') else old == new
                require(all(preserved.values()), 'historical rows changed outside exact locale/mapping appends')
                require(list(before.execute('SELECT * FROM sqlite_master ORDER BY type,name')) == list(db.execute('SELECT * FROM sqlite_master ORDER BY type,name')),
                        'SQL schema changed')
                snapshot_guard_checks(db, holds)
                before_repeat = {t: history.records(db, t) for t in history.tables(db)}
                repeat = catalog_locale.import_evidence(db, rows)
                require(repeat == dict(inserted=0, unchanged=3000, quarantined=0), 'idempotent reimport differs')
                require(all(history.records(db, t) == b for t, b in before_repeat.items()), 'reimport changed rows')
                require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall(), 'snapshot integrity failed')
    require(strict.tree_chunks(repo, inventory) == blobs and all(strict.checked_source(repo, p, blobs[p]) == b for p, b in raws.items()), 'pinned cache changed')
    require(all(p.read_bytes() == b for p, b in inputs.items()) and packet_path.read_bytes() == raw and review_path.read_bytes() == review_raw
            and signature(db_path.read_bytes()) == BEFORE_SHA, 'compiler/parser/packet/review/database changed')
    selection = dict(schema='pokemon.next3000-selection.v1', inspected_at=inspected_at, input_database_sha256=BEFORE_SHA,
        qualification_sha256=PACKET_SHA, record_binding_review_sha256=REVIEW_SHA, record_binding_reviewed_at=reviewed_at,
        selected_card_ids=packet['selected_card_ids'], selected_card_ids_sha256=SELECTED_IDS_SHA,
        english=3000, japanese=0, coordinate_groups=1503, release_scopes=48, existing_concepts_used=448, new_name_concepts=0,
        by_set=dict(Counter(r['identity']['set_code'] for r in rows)), source_inventory=inventory,
        compilation_source_sha256={str(p.relative_to(code_root)): signature(b) for p, b in inputs.items()},
        locale_import=imported, idempotent_reimport=repeat, historical_tables_preserved=preserved, historical_schema_unchanged=True,
        concepts_without_record_bindings_abstain=3000, gaps=gaps, strict_variant_dimensions=True, preserved_identity_holds=44,
        excluded_image_target_ids=sorted(strict.previous.EXPANDED_IMAGE_TARGETS), new_card_identities=0,
        new_counterpart_relationships=0, new_source_images=0, new_prices=0, physical_distribution_region=None,
        demand=packet['demand'], authorized_supply=packet['authorized_supply'], **claims())
    return rows, selection, licence, raw, review_raw


def build(db_path, repo, root, packet_path, review_path, output, inspected_at):
    require(not output.exists(), 'output already exists; historical evidence must not be overwritten')
    rows, selection, licence, raw, review_raw = compile(db_path, repo, root, packet_path, review_path, inspected_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        d = Path(directory)
        (d / 'locales.jsonl').write_text(''.join(catalog_locale.encoded(r) + '\n' for r in rows))
        (d / 'selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n')
        (d / 'basis-qualification.json').write_bytes(raw)
        (d / 'record-binding-review.json').write_bytes(review_raw)
        (d / 'TCGDEX-LICENSE').write_bytes(licence)
        require(packet_path.read_bytes() == raw and review_path.read_bytes() == review_raw
                and signature(db_path.read_bytes()) == BEFORE_SHA, 'publication qualification/review/database changed')
        require({str(p.relative_to(Path(__file__).resolve().parents[1])): signature(b) for p, b in compiler_inputs().items()}
                == selection['compilation_source_sha256'], 'compiler dependencies changed before publication')
        inventory = selection['source_inventory']; blobs = strict.tree_chunks(repo, inventory)
        require(blobs == {p: v['git_blob'] for p, v in inventory.items()}
                and all(signature(strict.checked_source(repo, p, b)) == inventory[p]['sha256'] for p, b in blobs.items())
                and (root / 'catalog/TCGDEX-LICENSE').read_bytes() == licence, 'source/licence changed before publication')
        strict.publish_exclusive(d, output)
    return dict(inserted_bindings=len(rows), new_concepts=0, qualification_sha256=PACKET_SHA, record_review_sha256=REVIEW_SHA)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('db', 'repo', 'root', 'qualification', 'review', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--inspected-at', required=True)
    a = p.parse_args()
    print(json.dumps(build(a.db, a.repo, a.root, a.qualification, a.review, a.output, a.inspected_at)))


if __name__ == '__main__':
    main()
