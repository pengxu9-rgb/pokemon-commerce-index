# Buyer discovery journeys without marketplace data

The pinned private catalog now carries **657 AI-proposed `same_artwork` edges and zero verified cross-region edges**. These proposals can appear as internal artwork leads with `price_comparable=false`. They do not make two cards the same printing and cannot merge ask or sale prices. The import step rejects any row that tries to upgrade a proposal to `verified` during the catalog build.

The [journey suite](catalog/discovery-buyer-journeys.json) contains 10 hand-authored examples and 15 structured steps: language choice, Japanese set/number/finish narrowing, a named artist, Prism Star, an unverified promo, grade and budget preferences, a multi-character name, and absent search clues. The [frozen-catalog replay](catalog/discovery-buyer-journeys-audit.json) passed all 15 expected decisions. It checks the next question, candidate basis, exact target, and the boundary that no live price is claimed.

Two changes came from this probe:

- An unqualified English character name now retrieves clearly labelled Japanese **same-character leads** as well as English catalog text, so the first question can be language. `Pikachu` yields both basis types on this catalog; this is not a counterpart or same-artwork assertion.
- A verified JP↔EN counterpart, once one exists, remains discoverable after the user selects the destination set. The former retrieval condition dropped it at that step. Current production data still contains **no verified counterpart**.

Rebuild and replay against the fixed manifest, writing the report to a new path:

```
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest.json --db /tmp/pokemon-discovery-catalog.sqlite3
python3 -m scripts.evaluate_discovery_journeys \
  --db /tmp/pokemon-discovery-catalog.sqlite3 \
  --manifest catalog-build-manifest.json \
  --suite catalog/discovery-buyer-journeys.json \
  --output /tmp/pokemon-discovery-journeys.json
```

The suite is an **engineering regression**, not measured user relevance or natural-language understanding: its utterances were manually mapped to structured constraints. The next independent evidence is a small set of actual buyer questions, labelled without seeing candidate results, followed by card-specific review of proposed artwork links most often needed by those journeys. Until then, the agent should explain “same character” and “AI artwork proposal” as leads and ask for the exact set, number and finish before tracking.
