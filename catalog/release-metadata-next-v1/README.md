# Official Japanese release metadata batch — 2 October 2026

This batch fills missing product-family names for 18 Japanese catalog scopes, covering 2,043 existing source records. Fifteen initial product release dates are declared; SVD, SD and CP6 stay undated because the available page has multiple product dates or the date is represented without a qualified text declaration. These are product dates, never exact copy, edition or reprint dates.

The importer binds each record to the full current card/provenance scope digest, a specific official card coordinate/reference, and that card page's link to the official product page. Cache receipts and raw HTML hashes are checked during deterministic rebuilding. Multiple positive numbering denominators abstain; SI's eight sentinel unnumbered energy records are counted separately. This does not establish accuracy of all cards in each product family.

Only official Japanese names and exact same-scope code spellings are added as vocabulary. No inferred SMP/SM-P, language or cross-region alias merges are approved. Display, physical finish, price comparability and automatic offer permissions remain false. All existing card identities, variant labels and eligibility remain unchanged; the original 100 supported metadata targets stay current.

The pinned TCGdex source has an XY3 date disagreement and a CP5 title disagreement. Official product declarations used in this batch differ. The mixed-denominator XY scope is held instead of inheriting the TCGdex THE BEST OF XY header. SMH, DS, SC and LL need a stronger card-to-product binding because the sampled official card pages do not link to a product.

## Reproduce

From the repository root, with the existing source cache:

```sh
python3 -m scripts.build_release_metadata_batch \
  --db /tmp/pokemon-coordinate-family-v1.sqlite3 \
  --cache ../../work/release-metadata-next-v1-cache \
  --output /tmp/new-release-metadata-v1/metadata-v1.jsonl
python3 -m unittest tests.test_release_metadata_next -q
```

Manifest order: `import-release-metadata` on `metadata-v1.jsonl`, then `import-catalog-vocabulary` on `vocabulary-v1.jsonl`. The new function is `supported_catalog.import_release_metadata`; it uses existing tables and rejects stale scope/reference/product-link evidence, conflicting overlays and permission widening. Raw pages/cache receipts remain local research material and are excluded from the cloud image.

Measured Japanese name gaps: 9,788 → 7,745 records. Date gaps: 9,788 → 8,114. Sets with either gap: 215 → 200. Source parity and engineering tests do not measure independent semantic accuracy or real marketplace matching precision.
