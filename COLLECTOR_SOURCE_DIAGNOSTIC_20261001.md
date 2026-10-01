# Source-backed collector diagnostic — 1 October 2026

## Result

Thirty newly discovered candidates were frozen before changes to discovery. Sixteen passed original-post inspection and Codex/Gemini source-faithfulness review. Twelve inaccessible or insufficiently inspected sources and two invented requests from collection-sharing posts remain excluded. All 30 decisions and first outputs are retained.

The qualified cohort initially produced **2/16** useful scoped outcomes. After fixes, its development replay produces **16/16**, consisting of **eight catalog partials and eight explicit evidence blockers**. Complete collector answers established: **zero**. The original authored suite remains **30/30**; the full regression suite passes **360 tests**.

This is a purposively selected diagnostic. The researcher knew the implementation and supplied source context to Gemini; Gemini did not independently fetch the pages or perform multimodal verification. Corrected replay is development evidence, not blind accuracy or a representative user success rate. The planned 30-qualified-question acceptance measurement remains open.

## Changes driven by failures

- Recognize credited multiword artist names without requiring the word “artist,” and recognize Japanese `イラストレーター`. A generic English verb such as “take” does not select the artist take.
- Return artist catalog candidates for an edition-inclusive checklist, recording unresolved edition, regional and physical-version coverage. Graded-copy requests still require copy evidence.
- Preserve owned-collection constraints. A catalog list can help start a checklist; it cannot say which cards the collector owns or is missing without their inventory.
- Keep a single-species chronological checklist separate from an explicitly requested evolution family. This prevents a Pikachu checklist from silently adding Raichu.
- Require an actual release name/code alongside a printed number: `151/165` alone cannot imply the release named `151`.
- Resolve numberless, language-scoped release requests such as Japanese 151. Return source-declared variant and rarity summaries across the release. Do not turn a question about both ball variants into a Master Ball-only list or claim every physical variant is covered.
- Route depicted-character/cameo questions to artwork evidence, regional exclusivity to release/artwork coverage, and custom-card inventories to product-scope clarification. Missing catalog links do not establish exclusivity.
- Recognize price indifference without dropping an actual separate “cheapest” request.
- Deduplicate sources by stable platform post ID across URL slugs and host aliases, including against all 11 prior public-question cohorts.

The scoped results cover 227 Japanese/English Yuka Morii records, 80 Mew records, 327 Pikachu records and 516 Japanese SV2A source-variant records. These are existing internal catalog rows, **not new identities or exhaustive physical-card counts**. Results remain internal, source-declared and ineligible for automatic live-offer association.

## Evidence

Files are in [sandbox/collector_questions/v1](sandbox/collector_questions/v1/):

- `source_questions.jsonl`, `source_evidence.jsonl`, `collection_lock.json`: frozen wording, context, reference expectations, initial runtime and catalog hashes.
- `codex_preflight.jsonl`, `gemini_preflight.jsonl`, `source_gate_all_priors/report.json`: reviewer attribution, model response/prompt hashes, usage and source exclusions.
- `initial-codex-qualified-report.json`: first unchanged-runtime result. Its 16 IDs exactly equal the later dual-qualified source set.
- `development-report.json`: intermediate 15/16 run, including a multi-variant artist filtering failure; corrected reports retain its resolution.
- `coordinate-safe-replay-report.json`: final 16/16 replay on a new manifest build. The six discovery identity/facet/release/family tables have the same semantic fingerprint as the frozen baseline, despite different SQLite file hashes.
- [Cloud verification](cloud-deployment-20261001-collector-v3.json): private staging revision, image digest, source hashes and complete pagination checks against the local replay. No feed, market storage or orders are enabled.

Reproduction (use fresh output paths):

```bash
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-discovery-v1.json --db /tmp/collector-catalog.sqlite3
python3 -m scripts.evaluate_collector_sources --db /tmp/collector-catalog.sqlite3 --directory sandbox/collector_questions/v1 --eligible sandbox/collector_questions/v1/source_gate_all_priors/eligible_source_questions.jsonl --output /tmp/collector-replay.json
python3 -m unittest discover -s tests -q
```

## Next sequence

1. Collect a separate fresh cohort with at least 30 fully inspected, source-qualified questions. Increase task diversity and Japanese coverage; this cohort has 14 English and only two Japanese qualified questions, with several related artist requests. Freeze expectations before another runtime change and report useful partials, blockers and complete answers separately.
2. Prioritize source-bound artwork-character evidence and version coverage from the observed collector requests. AI can inspect permitted reference images and propose annotations; confident labels still need independent audit. Do not promote text-only user assertions about cameos into verified graph edges. Start with explicit species/trainer appearances and release/variant evidence rather than broad exclusivity claims.
3. Add actual inventory input/diff support so the agent can answer “what am I missing?” against a stated language/version scope. Current output asks for inventory but does not parse or persist it.
4. Keep Buy&Ship's feed, real listing matching, physical-copy/condition evidence and fresh quotes as separate gates. The transaction URL API remains distinct from catalog/search access.
