# M6 secret-card rarity correction

The pinned TCGdex M6 seed labels all 37 secret-number rows, `077/076` through
`113/076`, as `Mega Hyper Rare`. The pinned PTCG reference distinguishes AR,
SR, SAR and MUR. We checked each exact set/number/name against its official
Pokémon Card page and recorded the page hash and rarity icon in
[`catalog/m6-secret-rarity-official-audit.jsonl`](catalog/m6-secret-rarity-official-audit.jsonl).

The result is 35 rarity-only corrections: 12 AR, 16 SR, 6 SAR and 1 MUR.
`098/076` and `099/076` also have source-name conflicts and retain their
existing identity exceptions and offer-matching block. The 35 corrections are
in [`catalog/m6-secret-rarity-corrections.jsonl`](catalog/m6-secret-rarity-corrections.jsonl).
The raw pinned catalog files remain unchanged.

For example, the official [M6 110/076 page](https://www.pokemon-card.com/card-search/details.php/card/50551)
shows `メガレックウザex` and a SAR icon. The revised catalog can retrieve this
printing when a question says `メガレックウザex SAR`; the question still lacks
set and number, so the resolver requests those details and does not infer a
unique priceable unit. The unrelated `30周年パックのミュウSAR` question remains
unmatched; the [official 30th-anniversary product page](https://www.30th.pokemon-card.com/product/m6a)
features Mew ex FUR, which does not justify inventing a Mew SAR identity.

Rebuild the versioned private snapshot with:

```bash
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-rarity-v1.json \
  --db catalog-index-rarity-v1.sqlite3
```

The manifest pins every input hash and expects 55,167 internal identities,
33,543 match-eligible identities and 35 rarity corrections. Snapshot files are
local and not committed. The correction table binds each row to the original
name, rarity and source provenance, a pinned second-source record, and the
official URL, page hash and rarity icon. A source-changing reimport fails.
This changes catalog metadata only; it adds no listing, transaction or current
price evidence.
