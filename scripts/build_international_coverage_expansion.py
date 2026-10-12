"""Compile one bounded offline retrieval batch against existing printing IDs.

No new identities, translations, artwork, dates, relationships or permissions.
Only the existing reviewed TCGdex pin and current reviewed concept ledger apply.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pokemon_index import catalog_locale, core, tcgdex_source
from scripts.build_international_coverage_pilot import ALIAS_FIELDS
from scripts.qualify_international_product_documents import REVISION, checked_source, git_tree

SETS = ('SV8A', 'S8B', 'SM12A', 'SM6B', 'SM8B')
EN_PREFIXES = ('SM', 'SWSH', 'SV')
MAX_JAPANESE = 100
ENGLISH_COMPARISONS = 25
MAX_EXPANDED_JAPANESE = 300
MAX_EXPANDED_ENGLISH = 75
MAX_EXPANDED_SETS = 64
RIGHTS = f'https://github.com/tcgdex/cards-database/blob/{REVISION}/LICENSE'


@dataclass(frozen=True)
class RetrievalScope:
    """Explicit operator batch decision; never infer scope from row counts."""
    name: str
    sets: tuple[str, ...]
    japanese_records: int
    english_records: int = ENGLISH_COMPARISONS
    expanded_batch: bool = False

    def __post_init__(self):
        if type(self.expanded_batch) is not bool:
            raise ValueError('invalid bounded retrieval scope')
        japanese_limit = MAX_EXPANDED_JAPANESE if self.expanded_batch else MAX_JAPANESE
        set_limit = MAX_EXPANDED_SETS if self.expanded_batch else 19
        if (not isinstance(self.name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', self.name)
                or not isinstance(self.sets, tuple) or not 3 <= len(self.sets) <= set_limit
                or any(not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]*', code) for code in self.sets)
                or len(set(self.sets)) != len(self.sets)
                or type(self.japanese_records) is not int or not 1 <= self.japanese_records <= japanese_limit
                or type(self.english_records) is not int
                or (not 1 <= self.english_records <= MAX_EXPANDED_ENGLISH if self.expanded_batch else self.english_records != ENGLISH_COMPARISONS)):
            raise ValueError('invalid bounded retrieval scope')


def translated_query(card, alias):
    name = alias['name_en' if card['language'] == 'ja' else 'name_ja']
    return f"{name} {card['language']} {card['set_code']} {card['collector_number']}"


def pairs(db, *, scope=None):
    """Find disjoint name/category matches; ambiguous concepts abort, never guess."""
    if scope is not None and not isinstance(scope, RetrievalScope):
        raise ValueError('explicit scope must be a validated RetrievalScope')
    if scope is not None and scope.expanded_batch:
        raise ValueError('expanded batches require the frozen exact-name follow-up compiler')
    allowed_sets = scope.sets if scope is not None else SETS
    concepts = db.execute('''WITH latest AS (SELECT *, row_number() OVER
        (PARTITION BY concept_id ORDER BY revision DESC) AS rank FROM bilingual_concept_revision)
        SELECT * FROM latest WHERE rank=1 AND status='approved' ORDER BY concept_id''').fetchall()
    indexes = {language: defaultdict(list) for language in ('ja', 'en')}
    for concept in concepts:
        for language in indexes:
            indexes[language][(concept['name_' + language], concept['category'])].append(concept)
    bound = {r[0] for r in db.execute('''SELECT card_id FROM catalog_locale_evidence
        UNION SELECT card_id FROM catalog_source_mapping''')}
    candidates = {'ja': [], 'en': []}
    for card in db.execute('''SELECT c.*, cl.category FROM card c JOIN card_classification cl
        USING(card_id) WHERE match_eligible=1 AND language IN ('ja','en') ORDER BY card_id'''):
        language = card['language']
        if card['card_id'] in bound or card['variant'].startswith('unverified'):
            continue
        if language == 'ja' and card['set_code'] not in allowed_sets:
            continue
        if language == 'en' and not card['set_code'].startswith(EN_PREFIXES):
            continue
        aliases = indexes[language].get((card['name'], card['category']), [])
        if len(aliases) > 1:
            raise ValueError('ambiguous current reviewed name/category: ' + card['card_id'])
        if aliases:
            candidates[language].append((card, aliases[0]))
    japanese = candidates['ja']
    # Exceeding the scope requires another explicit batch decision; do not silently
    # truncate a set or select a broader catalogue because it has more rows.
    if not 1 <= len(japanese) <= MAX_JAPANESE:
        raise ValueError('bounded Japanese printing/set scope not met')
    if scope is None and not 3 <= len({c['set_code'] for c, _ in japanese}) <= 5:
        raise ValueError('bounded Japanese printing/set scope not met')
    if scope is not None and (len(japanese) != scope.japanese_records
            or {c['set_code'] for c, _ in japanese} != set(scope.sets)):
        raise ValueError('explicit Japanese printing/set scope not met')
    used = {a['concept_id'] for _, a in japanese}
    english_pool = [(c, a) for c, a in candidates['en'] if a['concept_id'] in used]
    # Prefer different reviewed concepts for comparison; then distinct remaining
    # variants if needed. These are comparison records, never counterpart edges.
    english = []; seen = set()
    for pair in english_pool:
        if pair[1]['concept_id'] not in seen:
            english.append(pair); seen.add(pair[1]['concept_id'])
    selected = {c['card_id'] for c, _ in english}
    english.extend(pair for pair in english_pool if pair[0]['card_id'] not in selected)
    english = english[:ENGLISH_COMPARISONS]
    if len(english) != ENGLISH_COMPARISONS:
        raise ValueError('25 distinct English comparison records required')
    return japanese + english


def source_fields(card):
    match = re.fullmatch(r'tcgdex:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})', card['provenance'])
    if not match or match[1] != REVISION or card['rights_reference'] != RIGHTS:
        raise ValueError('existing reviewed physical TCGdex pin/rights required')
    path = PurePosixPath(match[2])
    if (path.is_absolute() or '..' in path.parts or path.suffix != '.ts'
            or path.parts[0] not in ('data', 'data-asia')
            or any(part.casefold() in ('pocket', 'digital') for part in path.parts)):
        raise ValueError('physical card source path required; Pocket/digital excluded')
    return str(path), match[3]


def compile_rows(db, repo, root, inspected_at, *, scope=None):
    core.parse_time(inspected_at)
    selected = pairs(db, scope=scope)
    sources = {source_fields(card)[0]: source_fields(card)[1] for card, _ in selected}
    # Include the licence in the same pinned tree check; no lazy fetch/network.
    blobs = git_tree(repo, ['LICENSE', *sorted(sources)], revision=REVISION)
    if set(blobs) != {'LICENSE', *sources}:
        raise ValueError('selected source or licence absent from pinned tree')
    raw_sources = {path: checked_source(repo, path, blob) for path, blob in blobs.items()}
    license_bytes = (root / 'catalog/TCGDEX-LICENSE').read_bytes()
    if raw_sources['LICENSE'] != license_bytes:
        raise ValueError('pinned licence differs from existing metadata review')
    for path, sha in sources.items():
        if hashlib.sha256(raw_sources[path]).hexdigest() != sha:
            raise ValueError('source hash differs from baseline provenance')
    rows = []; gaps = []
    for card, alias in selected:
        path, sha = source_fields(card)
        release = db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                             (card['language'], card['set_code'])).fetchone()
        if not release or not release['name'] or not release['official_card_count']:
            raise ValueError('localized source release name/count missing')
        raw = raw_sources[path].decode('utf-8')
        parsed = tcgdex_source.parse_card_source(raw, set_id=card['set_code'],
            official_count=release['official_card_count'], path=path, revision=REVISION,
            language=card['language'], source_directory=PurePosixPath(path).parent.name)
        fields = ('language', 'set_code', 'collector_number', 'variant', 'name', 'provenance', 'rights_reference')
        if not any(all(item[k] == card[k] for k in fields) for item in parsed):
            raise ValueError('source printing tuple differs from existing ID: ' + card['card_id'])
        classification = tcgdex_source.parse_card_classification(raw)
        if not classification or classification[0] != alias['category']:
            raise ValueError('source category differs from reviewed concept')
        query = translated_query(card, alias)
        # Set filter keeps the measurement exact and inexpensive. Language and
        # number are still tested by the ordinary internal search implementation.
        result = core.catalog_search_internal(db, query, set_code=card['set_code'], limit=100)
        if card['card_id'] in {r['card_id'] for r in result['cards']}:
            raise ValueError('record already retrievable by translated query')
        body = dict(schema='pokemon.catalog-locale.v1', identity=catalog_locale.snapshot(db, card['card_id']),
            source=dict(provider='tcgdex', language=card['language'], region='ZZ',
                release_id='tcgdex-product:' + card['set_code'], native_id=path, source_variant=card['variant'],
                revision=REVISION, git_blob=blobs[path], sha256=sha,
                license_git_blob=blobs['LICENSE'], license_sha256=hashlib.sha256(license_bytes).hexdigest(),
                retrieved_at=None, retrieval_status='historical_snapshot_time_not_recorded',
                inspected_at=inspected_at, rights_reference=RIGHTS, rights_status='metadata_internal_reviewed',
                physical_distribution_region=None),
            release_snapshot=dict(release), name_aliases=[{k: alias[k] for k in ALIAS_FIELDS}],
            confidence=1.0, confidence_scope='pinned bytes, existing printing tuple and current reviewed text only',
            unresolved_conflicts=[], test_only=False, **{k: False for k in catalog_locale.FALSE_CLAIMS})
        body['evidence_id'] = 'catalog-locale:' + catalog_locale.digest(body)
        catalog_locale.validate(db, body)
        rows.append(body)
        gaps.append(dict(card_id=card['card_id'], query=query, before_total=result['total'], before_contains_target=False))
    if len({r['identity']['card_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate printing in bounded batch')
    inventory = {path: dict(git_blob=blobs[path], sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
                 for path, raw in sorted(raw_sources.items())}
    # Repeat every source and licence check after the search measurements.
    if git_tree(repo, sorted(blobs), revision=REVISION) != blobs or any(checked_source(repo, path, blobs[path]) != raw
                                                   for path, raw in raw_sources.items()):
        raise ValueError('pinned inputs changed during compilation')
    if (root / 'catalog/TCGDEX-LICENSE').read_bytes() != license_bytes:
        raise ValueError('reviewed licence changed during compilation')
    selection = dict(schema='pokemon.international-coverage-selection.v1', inspected_at=inspected_at,
        by_set=dict(Counter(r['identity']['language'] + ':' + r['identity']['set_code'] for r in rows)),
        japanese=sum(r['identity']['language'] == 'ja' for r in rows), english=ENGLISH_COMPARISONS,
        new_card_rows=0, source_inventory=inventory, gaps=gaps,
        selection_reason='Five fixed Japanese physical set scopes with measured exact-ID translated-query gaps and existing reviewed names. English comparisons span distinct concepts where available; no counterpart assertions.',
        demand='Japan-to-US discovery use case; no measured set-level demand',
        authorized_supply='Metadata only; live Buy&Ship offer availability unmeasured',
        physical_distribution_region=None, historical_retrieval_time=None)
    if scope is not None:
        selection['batch_scope'] = dict(name=scope.name, sets=list(scope.sets), japanese_records=scope.japanese_records,
                                       english_records=ENGLISH_COMPARISONS)
        selection['selection_reason'] = (f'Explicit bounded batch {scope.name}: all current reviewed-name exact-ID gaps in '
            f'{len(scope.sets)} fixed Japanese physical set scopes. '
            'English comparisons span distinct concepts where available; no counterpart assertions.')
    return rows, selection, license_bytes


def build(db_path, repo, root, output, inspected_at, *, scope=None):
    if output.exists():
        raise FileExistsError('expansion artifact directory already exists')
    signature = hashlib.sha256(db_path.read_bytes()).hexdigest()
    with closing(core.connect(db_path, readonly=True)) as db:
        db.execute('BEGIN')
        kwargs = {} if scope is None else {'scope': scope}
        rows, selection, license_bytes = compile_rows(db, repo, root, inspected_at, **kwargs)
    if hashlib.sha256(db_path.read_bytes()).hexdigest() != signature:
        raise ValueError('input snapshot changed during compilation')
    selection['input_database_sha256'] = signature
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.coverage-expansion-', dir=output.parent))
    try:
        (temporary / 'locales.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows))
        (temporary / 'selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n')
        (temporary / 'TCGDEX-LICENSE').write_bytes(license_bytes)
        if output.exists():
            raise FileExistsError('expansion artifact directory appeared during compilation')
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {k: selection[k] for k in ('japanese', 'english', 'new_card_rows', 'by_set')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--source-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inspected-at', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.source_repo, Path.cwd(), args.output, args.inspected_at)))


if __name__ == '__main__':
    main()
