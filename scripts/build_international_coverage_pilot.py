"""Select bounded existing printing retrieval gaps; offline, no new identities."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from pokemon_index import core, catalog_locale

SETS = ('SV4A', 'SV2A', 'SV8', 'S12A')
ALIAS_FIELDS = ('concept_id', 'revision', 'name_ja', 'name_en', 'category', 'review_event_id')


def select(db, source_repo, inspected_at):
    concepts = db.execute('''WITH ranked AS (SELECT *, row_number() OVER
        (PARTITION BY concept_id ORDER BY revision DESC) AS rank FROM bilingual_concept_revision)
        SELECT * FROM ranked WHERE rank=1 AND status='approved' ORDER BY concept_id''').fetchall()
    aliases = {c['name_ja']: c for c in concepts}
    japanese = []
    for code in SETS:
        japanese.extend((c, aliases[c['name']]) for c in db.execute('''SELECT c.* FROM card c
            JOIN card_classification cl USING(card_id) WHERE language='ja' AND set_code=?
            AND match_eligible=1 ORDER BY card_id''', (code,))
            if c['name'] in aliases)
    japanese = japanese[:100]
    used = {a['name_en']: a for _, a in japanese}
    english = [(c, used[c['name']]) for c in db.execute('''SELECT c.* FROM card c
        JOIN card_classification cl USING(card_id) WHERE language='en' AND match_eligible=1
        ORDER BY card_id''') if c['name'] in used][:25]
    if len(english) != 25 or len({c['set_code'] for c, _ in japanese}) not in range(3, 6):
        raise ValueError('pilot comparison/set bounds not met')
    rows = []
    for card, alias in japanese + english:
        match = re.fullmatch(r'tcgdex:([0-9a-f]{40}):(.+):sha256:([0-9a-f]{64})', card['provenance'])
        if not match:
            raise ValueError('pilot requires pinned TCGdex provenance')
        revision, path, sha = match.groups()
        source = (source_repo / path).resolve()
        if not source.is_relative_to(source_repo.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            raise ValueError('pinned source bytes differ')
        # The copied repository license is the existing internal metadata review;
        # it grants no artwork, public display or marketplace data permission.
        if (source_repo / 'LICENSE').read_bytes() != Path('catalog/TCGDEX-LICENSE').read_bytes():
            raise ValueError('pinned metadata license differs')
        release = db.execute('SELECT * FROM catalog_set_localized WHERE language=? AND set_code=?',
                             (card['language'], card['set_code'])).fetchone()
        # ZZ explicitly preserves the unknown English print/distribution region.
        region = 'JP' if card['language'] == 'ja' else 'ZZ'
        row = dict(schema='pokemon.catalog-locale.v1', identity=catalog_locale.snapshot(db, card['card_id']),
            source=dict(provider='tcgdex', language=card['language'], region=region,
                release_id='tcgdex-product:' + card['set_code'], native_id=path, source_variant=card['variant'],
                revision=revision, sha256=sha, retrieved_at=None,
                retrieval_status='historical_snapshot_time_not_recorded', inspected_at=inspected_at,
                rights_reference=card['rights_reference'], rights_status='metadata_internal_reviewed'),
            release_snapshot=dict(release), name_aliases=[{k: alias[k] for k in ALIAS_FIELDS}],
            confidence=1.0, confidence_scope='exact pinned bytes and current reviewed text only',
            unresolved_conflicts=[], test_only=False, **{k: False for k in catalog_locale.FALSE_CLAIMS})
        row['evidence_id'] = 'catalog-locale:' + catalog_locale.digest(row)
        rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--source-repo', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--inspected-at', required=True)
    args = p.parse_args()
    core.parse_time(args.inspected_at)
    with core.connect(args.db, readonly=True) as db:
        rows = select(db, args.source_repo, args.inspected_at)
    with args.output.open('x') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    print(json.dumps({'japanese': sum(r['identity']['language'] == 'ja' for r in rows),
                      'english': sum(r['identity']['language'] == 'en' for r in rows), 'new_card_rows': 0}))


if __name__ == '__main__':
    main()
