"""Compile one exact reviewed Johto pilot from authorized pinned local metadata.

The older Kanto policies stay unchanged. This policy accepts only its frozen
25 bare-name/Dex triples and exact 89-Japanese/25-English witness packet.
"""
import argparse
import ast
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from pokemon_index import catalog_locale, core, tcgdex_source, variant_dimension_hold
from pokemon_index import catalog_question_resolver_v2 as resolver
from scripts import build_pokemon_name_coverage as names
from scripts import build_pokemon_name_followup as previous
from scripts import audit_international_coverage_expansion as history
from scripts.audit_international_coverage import facts as resolution_facts
from scripts.build_international_coverage_expansion import ALIAS_FIELDS, RIGHTS, source_fields, translated_query
from scripts.pokemon_release_witness import release_path, inspect_release
from scripts.qualify_international_product_documents import REVISION, checked_source, git_tree, header_fields

PACKET_SHA = '79a243ce9e9f1115a9d82affef7ff9364f33f689ba6bb3d271c2b78f42d97085'
REVIEW_SHA = '71f3fe32841c12736ffcfbdd7eb1dfab18a4b471f5357339aafeaa2104d35c48'
BEFORE_SHA = '5289fb3167fe193257e4d58e715f9600a8f585443fdb9c61563aecd8c80f86cf'
SETS = ('PMCG1', 'PMCG3', 'S12A', 'S8B', 'SM12A', 'SM8B', 'SV8A')
COUNTS = dict(ja=89, en=25, existing=17, new=72, pairs=25, groups=52)
PENDING_SEMANTIC_REVIEW = 'Exact full-name semantic review not yet completed; source text and matching Dex do not approve a translation or printing counterpart'
JOHTO_PAIRS = frozenset((
    (206, 'ノコッチ', 'Dunsparce'), (179, 'メリープ', 'Mareep'), (180, 'モココ', 'Flaaffy'),
    (177, 'ネイティ', 'Natu'), (158, 'ワニノコ', 'Totodile'), (159, 'アリゲイツ', 'Croconaw'),
    (160, 'オーダイル', 'Feraligatr'), (163, 'ホーホー', 'Hoothoot'), (164, 'ヨルノズク', 'Noctowl'),
    (168, 'アリアドス', 'Ariados'), (178, 'ネイティオ', 'Xatu'), (196, 'エーフィ', 'Espeon'),
    (197, 'ブラッキー', 'Umbreon'), (167, 'イトマル', 'Spinarak'), (185, 'ウソッキー', 'Sudowoodo'),
    (194, 'ウパー', 'Wooper'), (195, 'ヌオー', 'Quagsire'), (215, 'ニューラ', 'Sneasel'),
    (223, 'テッポウオ', 'Remoraid'), (224, 'オクタン', 'Octillery'), (228, 'デルビル', 'Houndour'),
    (229, 'ヘルガー', 'Houndoom'), (230, 'キングドラ', 'Kingdra'), (241, 'ミルタンク', 'Miltank'),
    (243, 'ライコウ', 'Raikou'),
))
CODE_INPUTS = dict(languages='pokemon_index/languages.py', tcgdex_source='pokemon_index/tcgdex_source.py',
    source_header_parser='scripts/qualify_international_product_documents.py',
    name_literal_parser='scripts/build_pokemon_name_coverage.py', localized_release_witness='scripts/pokemon_release_witness.py')
ADDITIONS = dict(bilingual_concept_revision=25, concept_review_event=25,
                 catalog_locale_evidence=114, catalog_source_mapping=114)


def signature(raw):
    return hashlib.sha256(raw).hexdigest()


def false_claims(value):
    if any(value.get(k) is not False for k in catalog_locale.FALSE_CLAIMS):
        raise ValueError('offline metadata cannot grant printing, image, display or trading approval')


def checked_packet(packet_raw, review_raw):
    if signature(packet_raw) != PACKET_SHA or signature(review_raw) != REVIEW_SHA:
        raise ValueError('frozen pilot packet or independent semantic review differs')
    packet = json.loads(packet_raw); review = json.loads(review_raw)
    if (packet.get('schema') != 'pokemon.stage16-next-source-qualification.v1' or packet.get('applied') is not False
            or packet.get('input_database_sha256') != BEFORE_SHA or packet.get('source_pin') != REVISION
            or packet.get('rights_reference') != RIGHTS):
        raise ValueError('pilot source/database/rights scope differs')
    false_claims(packet)
    if (review.get('schema') != 'pokemon.independent-name-review.v1' or review.get('reviewer') != 'GPT-6.1 Sol high'
            or review.get('proposal_sha256') != PACKET_SHA or review.get('decision') != 'approve_all_exact_pairs'
            or type(review.get('approved_pairs')) is not int or review['approved_pairs'] != 25
            or review.get('rejected_pairs') != [] or review.get('uncertain_pairs') != []
            or review.get('approved_into_catalog') is not False or review.get('sources_fetched') is not False):
        raise ValueError('exact independent semantic approval is absent or changed')
    proposals = packet['johto_semantic_review_tranche']['proposals']
    triples = [(p['dex_id'], p['name_ja'], p['name_en']) for p in proposals]
    if (len(proposals) != 25 or set(triples) != JOHTO_PAIRS or len(set(triples)) != 25
            or len({p['name_ja'] for p in proposals}) != 25 or len({p['name_en'] for p in proposals}) != 25
            or any(type(p['dex_id']) is not int or not 152 <= p['dex_id'] <= 251 for p in proposals)):
        raise ValueError('outside the exact 25 reviewed Johto name/Dex triples')
    for proposal in proposals:
        false_claims(proposal)
        if (proposal.get('unresolved_conflicts') not in ([],[PENDING_SEMANTIC_REVIEW]) or proposal['ja']['identity']['language'] != 'ja'
                or proposal['en']['identity']['language'] != 'en'):
            raise ValueError('conflicted name proposal')
    draft = packet['next_concrete_draft']; false_claims(draft)
    existing = draft['existing_review_witnesses']; new = draft['unapproved_new_name_witnesses']; english = draft['english_witnesses']
    japanese = existing + new
    if (len(existing) != 17 or len(new) != 72 or len(english) != 25
            or any(w['identity']['language'] != 'ja' for w in japanese)
            or any(w['identity']['language'] != 'en' for w in english)
            or draft.get('japanese_records') != 89 or draft.get('english_comparison_records') != 25
            or len({w['identity']['card_id'] for w in japanese + english}) != 114
            or sorted(w['identity']['card_id'] for w in japanese) != draft['card_ids']
            or {w['identity']['set_code'] for w in japanese} != set(SETS)
            or Counter(w['identity']['set_code'] for w in japanese) != draft['by_set']
            or len({(w['identity']['set_code'], w['identity']['collector_number']) for w in japanese}) != 52
            or {w['identity']['card_id'] for w in english} != {p['en']['identity']['card_id'] for p in proposals}
            or {w['identity']['card_id'] for w in new} != {w['identity']['card_id'] for p in proposals for w in p['potential_ja_bindings']}):
        raise ValueError('exact complete-group Japanese or distinct English witness selection differs')
    if (not isinstance(packet.get('five_image_targets_excluded'),list)
            or len(packet['five_image_targets_excluded']) != 5
            or sorted(packet['five_image_targets_excluded']) != sorted(previous.EXPANDED_IMAGE_TARGETS)):
        raise ValueError('five frozen priority-image IDs differ')
    excluded = {tuple(group[k] for k in ('language','set_code','collector_number')) for group in previous.expanded_excluded_groups()}
    if any(tuple(w['identity'][k] for k in ('language','set_code','collector_number')) in excluded
           or w['identity']['set_code'] == 'SV4A' for w in japanese + english):
        raise ValueError('priority-image coordinate or conflicted raw SV4A release selected')
    return packet, proposals, existing, new, english


def johto_metadata(raw, pair):
    triple = (pair['dex_id'], pair['name_ja'], pair['name_en'])
    if triple not in JOHTO_PAIRS:
        raise ValueError('unreviewed Johto name/Dex scope')
    fields = header_fields(raw.decode('utf-8'), declaration_name='card', declaration_type='Card')
    if fields.get('category') is None or ast.literal_eval(fields['category']) != 'Pokemon':
        raise ValueError('literal Pokemon category required')
    value = fields.get('dexId', '')
    if not re.fullmatch(r'\[\s*\d+\s*,?\s*\]', value):
        raise ValueError('exact singleton Dex required; ambiguous or missing fields held')
    dex = ast.literal_eval(value)[0]
    if type(dex) is not int or dex != pair['dex_id']:
        raise ValueError('source singleton Dex differs from the exact reviewed Johto pair')
    return dict(category='Pokemon', dex_id=dex, names=names.names(fields.get('name')))


def inspect_witness(db, witness, raws, blobs, *, pair=None):
    false_claims(witness)
    identity = witness['identity']; cid = identity['card_id']; language = identity['language']
    if language not in ('ja','en') or catalog_locale.snapshot(db, cid) != identity:
        raise ValueError('frozen witness identity or language changed')
    path, sha = source_fields(identity); source = witness['source']
    if (source.get('provider') != 'tcgdex' or source.get('revision') != REVISION or source.get('native_id') != path
            or source.get('git_blob') != blobs[path] or source.get('sha256') != sha or signature(raws[path]) != sha
            or source.get('bytes') != len(raws[path]) or source.get('rights_reference') != RIGHTS
            or source.get('rights_status') != 'metadata_internal_reviewed' or source.get('retrieved_at') is not None
            or source.get('retrieval_status') != 'historical_snapshot_time_not_recorded'
            or source.get('physical_distribution_region') is not None):
        raise ValueError('frozen witness pin/hash/licence or source rights changed')
    row = db.execute('SELECT match_eligible FROM card WHERE card_id=?', (cid,)).fetchone()
    category = db.execute('SELECT category FROM card_classification WHERE card_id=?', (cid,)).fetchone()
    if (not row[0] or identity['variant'].startswith('unverified') or not category or category[0] != 'Pokemon'
            or variant_dimension_hold.held(db, cid)):
        raise ValueError('ineligible, unresolved or dimension-held witness')
    losses = tcgdex_source.variant_dimension_losses(raws[path].decode('utf-8'))
    if any(loss['legacy_variant'] == identity['variant'] for loss in losses):
        raise ValueError('source dimension is omitted from the legacy printing')
    metadata = johto_metadata(raws[path], pair) if pair else names.metadata(raws[path])
    if (metadata['dex_id'] != witness['dex_id'] or metadata['names'] != witness['localized_names']
            or metadata['names'].get(language) != identity['name']
            or pair and identity['name'] != pair['name_' + language]):
        raise ValueError('literal full-name/category/Dex witness differs')
    release_row = db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                             (language, identity['set_code'])).fetchone()
    release = dict(release_row) if release_row else None
    product = witness['release_source']; false_claims(product)
    if not release or release != witness['release_snapshot'] or product['snapshot'] != release:
        raise ValueError('current localized release witness differs')
    product_path = release_path(release, REVISION, RIGHTS)
    if (product['native_id'] != product_path or product['git_blob'] != blobs[product_path]
            or product['sha256'] != signature(raws[product_path]) or product.get('bytes') != len(raws[product_path])
            or product.get('rights_status') != 'metadata_internal_reviewed' or product.get('retrieved_at') is not None
            or product.get('retrieval_status') != 'historical_snapshot_time_not_recorded'
            or product['facts'] != inspect_release(release, raws[product_path])):
        raise ValueError('pinned localized release header/date/count differs')
    parsed = tcgdex_source.parse_card_source(raws[path].decode('utf-8'), set_id=identity['set_code'],
        official_count=release['official_card_count'], path=path, revision=REVISION, language=language,
        source_directory=PurePosixPath(path).parent.name)
    keys = ('language','set_code','collector_number','variant','name','provenance','rights_reference')
    if not any(all(card[k] == identity[k] for k in keys) for card in parsed):
        raise ValueError('source printing tuple differs from retained ID')
    return metadata, release


def review_bundle(db, proposals, raws, blobs, licence_sha, review_sha, inspected_at):
    events, concepts = [], []
    for pair in proposals:
        witnesses, urls = {}, {}
        for language in ('ja','en'):
            witness = pair[language]; metadata, release = inspect_witness(db, witness, raws, blobs, pair=pair)
            card = witness['identity']; path, sha = source_fields(card)
            if card['language'] != language:
                raise ValueError('paired semantic witness language differs')
            urls[language] = f'https://github.com/tcgdex/cards-database/blob/{REVISION}/' + quote(path, safe='/')
            witnesses[language] = dict(identity=card, dex_id=metadata['dex_id'], category='Pokemon', native_id=path,
                revision=REVISION, git_blob=blobs[path], sha256=sha, license_sha256=licence_sha, rights_reference=RIGHTS,
                rights_status='metadata_internal_reviewed', retrieved_at=None, retrieval_status='historical_snapshot_time_not_recorded',
                inspected_at=inspected_at, physical_distribution_region=None, release_snapshot=release)
        frozen = dict(category='Pokemon', name_ja=pair['name_ja'], name_en=pair['name_en'], dex_id=pair['dex_id'],
            source_ja=urls['ja'], source_en=urls['en'], rights_reference=RIGHTS,
            ja_card_id=pair['ja']['identity']['card_id'], en_card_id=pair['en']['identity']['card_id'], retrieval_only=True)
        frozen['proposal_id'] = 'pokemon-name-proposal:' + catalog_locale.digest(frozen)
        snapshot = dict(frozen=frozen, ja_provenance=pair['ja']['identity']['provenance'],
            en_provenance=pair['en']['identity']['provenance'], witnesses=witnesses,
            scope='exact independently reviewed Johto full-name metadata translation; no printing counterpart',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        proposal = {**frozen, 'ja_provenance':snapshot['ja_provenance'], 'en_provenance':snapshot['en_provenance'],
            'source_snapshot':snapshot, 'source_snapshot_sha256':names.spaced_digest(snapshot)}
        review = dict(decision='approve', review_revision=1, reviewer='ai-independent:gpt-6.1-sol-high',
            reviewed_at=inspected_at, ja_identity_checked=True, en_identity_checked=True, translation_checked=True,
            requires_card_binding=True, semantic_review_sha256=review_sha,
            semantic_reviewed_at=None, semantic_review_time_status='not_recorded_in_independent_approval_packet',
            identity_attestation_scope='existing pinned metadata tuples only; no physical-copy verification',
            evidence_note='The frozen GPT-6.1 Sol high packet approves this exact bare Johto name pair and singleton Dex. '
                'The recorded timestamp is the compiler metadata recheck; the independent semantic-review time remains unknown. '
                'No form inheritance, artwork, counterpart, physical, display or trading approval.',
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        event = dict(schema='pokemon.concept_review.v1', proposal=proposal, review=review)
        event['event_id'] = names.spaced_digest(event); events.append(event)
        cid = 'pokemon-name:' + catalog_locale.digest(dict(ja=pair['name_ja'], en=pair['name_en'], dex_id=pair['dex_id']))
        if (db.execute('SELECT 1 FROM bilingual_concept_revision WHERE concept_id=?', (cid,)).fetchone()
                or db.execute("SELECT 1 FROM bilingual_concept_revision WHERE category='Pokemon' AND (name_ja=? OR name_en=?)",
                              (pair['name_ja'],pair['name_en'])).fetchone()):
            raise ValueError('existing or colliding name concept requires explicit revision review')
        concepts.append(dict(concept_id=cid, revision=1, category='Pokemon', name_ja=pair['name_ja'], name_en=pair['name_en'],
            source_ja=urls['ja'], source_en=urls['en'], rights_reference=RIGHTS, reviewer=review['reviewer'],
            reviewed_at=inspected_at, status='approved', review_event_id=event['event_id']))
    return dict(schema='pokemon.concept_review_bundle.v1', review_events=events, concept_revisions=concepts)


def complete_groups(db, japanese):
    bound = previous.bound_ids(db); selected = {w['identity']['card_id'] for w in japanese}
    if selected & bound:
        raise ValueError('draft printing is already bound')
    for witness in japanese:
        card = witness['identity']
        siblings = db.execute('''SELECT c.card_id,c.name,cl.category FROM card c LEFT JOIN card_classification cl USING(card_id)
            WHERE c.language='ja' AND c.set_code=? AND c.collector_number=? AND c.match_eligible=1
            AND c.variant NOT LIKE 'unverified%' ''', (card['set_code'],card['collector_number']))
        if any(s['name'] != card['name'] or s['category'] != 'Pokemon' or s['card_id'] not in selected | bound for s in siblings):
            raise ValueError('ambiguous or incomplete eligible Japanese sibling group')


def checked_current_concepts(db, packet):
    audit = []
    for concept in db.execute('''WITH latest AS (SELECT *,row_number() OVER
            (PARTITION BY concept_id ORDER BY revision DESC) AS rank FROM bilingual_concept_revision)
            SELECT * FROM latest WHERE rank=1 AND status='approved' AND category='Pokemon' ORDER BY concept_id'''):
        stored = db.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',(concept['review_event_id'],)).fetchone()
        if not stored:
            raise ValueError('current exact-name review event missing')
        event = json.loads(stored[0]); frozen = event['proposal']['source_snapshot']['frozen']
        if (names.spaced_digest({k:v for k,v in event.items() if k!='event_id'}) != concept['review_event_id']
                or event['review'].get('decision') != 'approve' or event['review'].get('requires_card_binding') is not True
                or frozen.get('name_ja') != concept['name_ja'] or frozen.get('name_en') != concept['name_en']
                or type(frozen.get('dex_id')) is not int or not 1 <= frozen['dex_id'] <= 151):
            raise ValueError('retained reviewed-name policy drifted')
        audit.append(dict(concept_id=concept['concept_id'],revision=concept['revision'],name_ja=concept['name_ja'],
            name_en=concept['name_en'],review_event_id=concept['review_event_id'],dex_id=frozen['dex_id'],requires_exact_card_binding=True))
    if audit != packet['current_concept_audit'] or len(audit) != packet['current_approved_pokemon_full_name_concepts']:
        raise ValueError('current exact reviewed concept inventory differs')


def compile(db_path, repo, root, packet_path, semantic_review_path, inspected_at):
    core.parse_time(inspected_at)
    packet_raw = packet_path.read_bytes(); review_raw = semantic_review_path.read_bytes()
    packet, proposals, existing, new, english = checked_packet(packet_raw, review_raw)
    if signature(db_path.read_bytes()) != BEFORE_SHA:
        raise ValueError('immutable input database differs')
    code_root = Path(__file__).resolve().parents[1]
    inputs = {code_root/path: (code_root/path).read_bytes() for path in CODE_INPUTS.values()}
    if any(signature(inputs[code_root/path]) != packet['parsing_source_sha256'][name] for name,path in CODE_INPUTS.items()):
        raise ValueError('qualification parser checkpoint changed')
    for name, sha in packet.get('input_packet_sha256', {}).items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or not name.startswith('catalog/') or signature(path.read_bytes()) != sha:
            raise ValueError('prior qualification source packet changed')
        inputs[path] = path.read_bytes()
    licence_path = root/'catalog/TCGDEX-LICENSE'; licence = licence_path.read_bytes(); inputs[licence_path] = licence
    inventory = packet['source_inventory']
    if not 1 <= len(inventory) <= 200 or 'LICENSE' not in inventory:
        raise ValueError('bounded original source inventory required')
    for path in inventory:
        p = PurePosixPath(path)
        if (p.is_absolute() or '..' in p.parts or path != 'LICENSE' and (p.suffix != '.ts' or p.parts[0] not in ('data','data-asia'))
                or any(part.casefold() in ('pocket','digital') for part in p.parts)):
            raise ValueError('only pinned physical metadata/licence paths allowed')
    blobs = git_tree(repo, sorted(inventory), revision=REVISION)
    if set(blobs) != set(inventory):
        raise ValueError('pinned source entries missing')
    raws = {path:checked_source(repo,path,blob) for path,blob in blobs.items()}
    if (any(inventory[path] != dict(git_blob=blobs[path],sha256=signature(raw),bytes=len(raw)) for path,raw in raws.items())
            or raws['LICENSE'] != licence or signature(licence) != packet['license_sha256']):
        raise ValueError('original source bytes or reviewed metadata licence changed')
    pair_by_name = {(lang,p['name_'+lang]):p for p in proposals for lang in ('ja','en')}
    japanese = existing + new
    with closing(core.connect(db_path, readonly=True)) as original:
        original.execute('BEGIN'); complete_groups(original,japanese)
        checked_current_concepts(original,packet)
        if len(variant_dimension_hold.rows_for(original)) != packet['identity_holds_preserved'] or packet['identity_holds_preserved'] != 44:
            raise ValueError('44 historical identity holds differ')
        bound = previous.bound_ids(original)
        if any(w['identity']['card_id'] in bound for w in english):
            raise ValueError('English comparison already bound')
        if original.execute('SELECT count(*) FROM catalog_locale_evidence').fetchone()[0] != packet['current_localized_bindings']:
            raise ValueError('input locale inventory differs')
        for witness in existing:
            inspect_witness(original,witness,raws,blobs)
            alias,dex = previous.current_alias(original,witness['identity'])
            if alias != witness['name_alias'] or dex != witness['dex_id']:
                raise ValueError('current retained exact-name review differs')
            review_event = json.loads(original.execute('SELECT record_json FROM concept_review_event WHERE event_id=?',
                                    (alias['review_event_id'],)).fetchone()[0])
            retained = review_event['proposal']['source_snapshot']['witnesses']
            for language,semantic in witness['existing_semantic_witnesses'].items():
                inspect_witness(original,semantic,raws,blobs)
                if semantic['identity']['language'] != language or semantic['identity'] != retained[language]['identity']:
                    raise ValueError('retained semantic source witness differs')
        for witness in new + english:
            card = witness['identity']; pair = pair_by_name.get((card['language'],card['name']))
            if pair is None:
                raise ValueError('selected name has no exact reviewed Johto pair')
            inspect_witness(original,witness,raws,blobs,pair=pair)
        bundle = review_bundle(original,proposals,raws,blobs,signature(licence),signature(review_raw),inspected_at)
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)/'pilot.sqlite3'; shutil.copyfile(db_path,scratch)
            with closing(core.connect(scratch)) as db:
                imported = core.import_concept_review_bundle(db,bundle)
                if imported != dict(review_events=25,concept_revisions=25):
                    raise ValueError('exact review append differs')
                rows, gaps = [], []
                for witness in japanese + english:
                    card = witness['identity']; pair = pair_by_name.get((card['language'],card['name']))
                    metadata,release = inspect_witness(db,witness,raws,blobs,pair=pair)
                    if pair:
                        concept = next(c for c in bundle['concept_revisions'] if c['name_'+card['language']] == card['name'])
                        alias = {k:concept[k] for k in ALIAS_FIELDS}
                    else:
                        alias,_ = previous.current_alias(db,card)
                    query = translated_query(card,alias)
                    before = core.catalog_search_internal(original,query,set_code=card['set_code'],limit=100)
                    if card['card_id'] in {c['card_id'] for c in before['cards']}:
                        raise ValueError('selected translated-query target already retrievable')
                    path,sha = source_fields(card)
                    row = dict(schema='pokemon.catalog-locale.v1',identity=card,
                        source=dict(provider='tcgdex',language=card['language'],region='ZZ',release_id='tcgdex-product:'+card['set_code'],
                            native_id=path,source_variant=card['variant'],revision=REVISION,git_blob=blobs[path],sha256=sha,
                            license_git_blob=blobs['LICENSE'],license_sha256=signature(licence),retrieved_at=None,
                            retrieval_status='historical_snapshot_time_not_recorded',inspected_at=inspected_at,
                            physical_distribution_region=None,rights_reference=RIGHTS,rights_status='metadata_internal_reviewed'),
                        release_snapshot=release,name_aliases=[alias],character_scope=dict(dex_id=metadata['dex_id'],
                            full_name=card['name'],category='Pokemon',form_inheritance_allowed=False),confidence=1.0,
                        confidence_scope='checked pinned tuples and exact independent full-name translation only',
                        unresolved_conflicts=[],test_only=False,**{k:False for k in catalog_locale.FALSE_CLAIMS})
                    row['evidence_id'] = 'catalog-locale:'+catalog_locale.digest(row); catalog_locale.validate(db,row); rows.append(row)
                    lookup = resolver.resolve_question(db,resolution_facts(row,alias['name_en' if card['language']=='ja' else 'name_ja']))
                    if lookup['resolution']['status'] != 'not_attempted' or lookup['reason'] != 'reviewed_name_record_binding_required':
                        raise ValueError('review alone widened an unbound translated record')
                    gaps.append(dict(card_id=card['card_id'],query=query,before_contains_target=False,before_total=before['total']))
                locales = catalog_locale.import_evidence(db,rows)
                if locales != dict(inserted=114,unchanged=0,quarantined=0):
                    raise ValueError('exact locale append differs')
                for row,gap in zip(rows,gaps):
                    cid = row['identity']['card_id']; after = core.catalog_search_internal(db,gap['query'],set_code=row['identity']['set_code'],limit=100)
                    if cid not in {c['card_id'] for c in after['cards']} or catalog_locale.snapshot(db,cid) != row['identity']:
                        raise ValueError('translated retrieval failed or existing identity changed')
                    lookup = resolver.resolve_question(db,resolution_facts(row,row['name_aliases'][0]['name_en' if row['identity']['language']=='ja' else 'name_ja']))
                    if lookup['resolution']['status'] not in ('unique','multiple_candidates') or cid not in lookup['resolution']['candidate_ids']:
                        raise ValueError('bound translated resolution failed')
                    gap.update(after_contains_target=True,after_total=after['total'],resolver_after=lookup['resolution'])
                preserved = {}
                for table in history.tables(original):
                    old,after = history.records(original,table),history.records(db,table)
                    preserved[table] = (after[:len(old)] == old and len(after) == len(old)+ADDITIONS[table]) if table in ADDITIONS else after == old
                if not all(preserved.values()):
                    raise ValueError('pilot changed historical rows outside four exact append tables')
                repeat_bundle = core.import_concept_review_bundle(db,bundle); repeat_locales = catalog_locale.import_evidence(db,rows)
                if repeat_bundle != dict(review_events=0,concept_revisions=0) or repeat_locales != dict(inserted=0,unchanged=114,quarantined=0):
                    raise ValueError('idempotent reimport changed evidence')
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('scratch snapshot integrity or references failed')
    if (git_tree(repo,sorted(inventory),revision=REVISION) != blobs
            or any(checked_source(repo,path,blobs[path]) != raw for path,raw in raws.items())
            or any(path.read_bytes() != raw for path,raw in inputs.items())
            or packet_path.read_bytes() != packet_raw or semantic_review_path.read_bytes() != review_raw
            or signature(db_path.read_bytes()) != BEFORE_SHA):
        raise ValueError('source,licence,parser,review,packet or input snapshot drifted')
    selection = dict(schema='pokemon.johto-name-pilot-selection.v1',inspected_at=inspected_at,
        input_database_sha256=BEFORE_SHA,proposal_sha256=PACKET_SHA,semantic_review_sha256=REVIEW_SHA,
        source_revision=REVISION,japanese=89,english=25,japanese_existing_review_records=17,japanese_new_name_records=72,
        exact_name_pairs=25,japanese_coordinate_groups=52,by_set=dict(Counter(r['identity']['language']+':'+r['identity']['set_code'] for r in rows)),
        new_name_pairs=[dict(dex_id=d,name_ja=j,name_en=e) for d,j,e in sorted(JOHTO_PAIRS)],
        source_inventory=inventory,localized_release_source_witnesses=packet['localized_release_source_witnesses'],
        prior_semantic_hold_resolved_by=REVIEW_SHA,
        semantic_approval_scope='exact 25 bare-name/Dex pairs only; all printing/counterpart/physical/trading claims remain false',
        strict_variant_dimensions=True,excluded_image_target_ids=sorted(packet['five_image_targets_excluded']),
        excluded_image_target_groups=previous.expanded_excluded_groups(),preserved_identity_holds=44,excluded_raw_sv4a_header_conflicts=29,
        concept_reviews=imported,locale_import=locales,idempotent_reimport=dict(concepts=repeat_bundle,locales=repeat_locales),
        historical_tables_preserved=preserved,gaps=gaps,concepts_without_record_bindings_abstain=114,
        new_card_identities=0,new_counterpart_relationships=0,new_source_images=0,
        demand=packet['demand'],authorized_supply=packet['authorized_supply'],physical_distribution_region=None,
        scope='bounded exact full-name metadata retrieval; review and artwork never merge distinct printing IDs or prices',
        **{k:False for k in catalog_locale.FALSE_CLAIMS})
    return bundle,rows,selection,licence,packet_raw,review_raw


def publish_exclusive(temporary,output):
    """Atomically publish a directory while refusing even an empty destination."""
    libc = ctypes.CDLL(None,use_errno=True)
    if sys.platform == 'darwin':
        function = libc.renamex_np; function.argtypes = (ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint)
        result = function(os.fsencode(temporary),os.fsencode(output),4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
        function = libc.renameat2; function.argtypes = (ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint)
        result = function(-100,os.fsencode(temporary),-100,os.fsencode(output),1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise RuntimeError('exclusive atomic directory publication unavailable on this host')
    if result:
        code = ctypes.get_errno()
        if code in (errno.EEXIST,errno.ENOTEMPTY):
            raise FileExistsError('artifact destination appeared before exclusive publication')
        raise OSError(code,os.strerror(code),str(output))


def build(db_path,repo,root,packet_path,semantic_review_path,output,inspected_at):
    if output.exists():
        raise FileExistsError('Johto pilot artifact directory already exists')
    bundle,rows,selection,licence,packet_raw,review_raw = compile(db_path,repo,root,packet_path,semantic_review_path,inspected_at)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.pokemon-johto-pilot-',dir=output.parent))
    try:
        for name,value in [('concept-review-bundle.json',bundle),('selection.json',selection)]:
            (temporary/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        (temporary/'locales.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows))
        (temporary/'basis-qualification.json').write_bytes(packet_raw)
        (temporary/'semantic-review.json').write_bytes(review_raw)
        (temporary/'TCGDEX-LICENSE').write_bytes(licence)
        if packet_path.read_bytes() != packet_raw or semantic_review_path.read_bytes() != review_raw or signature(db_path.read_bytes()) != BEFORE_SHA:
            raise ValueError('publication inputs changed after compilation')
        packet = json.loads(packet_raw); inventory = selection['source_inventory']
        if (git_tree(repo,sorted(inventory),revision=REVISION) != {p:w['git_blob'] for p,w in inventory.items()}
                or any(signature(checked_source(repo,p,w['git_blob'])) != w['sha256'] for p,w in inventory.items())
                or (root/'catalog/TCGDEX-LICENSE').read_bytes() != licence
                or any(signature((Path(__file__).resolve().parents[1]/path).read_bytes()) != packet['parsing_source_sha256'][name] for name,path in CODE_INPUTS.items())
                or any(signature((root/path).read_bytes()) != sha for path,sha in packet.get('input_packet_sha256',{}).items())):
            raise ValueError('source,licence,parser or prior evidence changed before publication')
        publish_exclusive(temporary,output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {k:selection[k] for k in ('japanese','english','exact_name_pairs','by_set','idempotent_reimport')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('db','source-repo','qualification','semantic-review','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--inspected-at',required=True); args = parser.parse_args()
    print(json.dumps(build(args.db,args.source_repo,Path.cwd(),args.qualification,args.semantic_review,args.output,args.inspected_at)))


if __name__ == '__main__':
    main()
