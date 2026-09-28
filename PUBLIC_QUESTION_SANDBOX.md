# Public question sandbox: AI silver-label pilot

This sandbox starts from actual public buyer and seller discussions, without waiting for a marketplace listing feed. The first frozen pilot has **24 source-backed situations** from Reddit (12), Elite Fourum (6) and Yahoo!知恵袋 (6), including 18 English and 6 Japanese questions. Nine refer to photos that were **not collected**. All stored question text is a short, source-condensed excerpt; this pilot can test intent and evidence routing, but cannot measure verbatim natural-language accuracy or image understanding.

Examples include [foil identification](https://www.reddit.com/r/PokemonTCG/comments/1vn449q/help_identifying_foiling/), [Japanese-only promo art](https://www.elitefourum.com/t/japanese-exclusive-sets-and-promos/44507), [graded Japanese card pricing](https://www.elitefourum.com/t/price-check-lugia-ex-psa-10-jpn/31021), and [auction versus fixed-price listing](https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q12330528722). These illustrate coverage, not a random or representative sample. Forum replies and any prices mentioned in old posts are never treated as current market truth.

## Frozen inputs

The frozen v1 pilot and both independent review files are archived in [`sandbox/public_questions/v1/`](sandbox/public_questions/v1/). They contain short paraphrases and source URLs, no account names, forum images, credentials, marketplace listing data or live prices. The freeze step validates unique HTTPS source posts, records hashes, separates source URLs and sampling strata from the blind question file, and uses a fixed seed to split source posts into development and holdout groups. All 24 records remain in the denominator, including out-of-scope sealed products and photo-dependent questions.

```bash
python3 -m scripts.public_question_sandbox freeze \
  --source sandbox/public_questions/v1/source_questions.jsonl \
  --out-dir ../../work/public-question-sandbox/frozen-v1
```

The frozen `blind_questions.jsonl` contains only ID, question excerpt, language, photo-availability state and source-bound question hash. `source_index.jsonl` holds links, sampling bucket and split. The source set is a **search convenience sample**. The holdout split prevents tuning on the same source post, but does not make it a market-representative test.

## Two independent AI reviews

Astra and Vertex Gemini 3.8 Flash each receive the same frozen question text and media flag. They do not see each other's output, forum replies, sampling strata or a target agent's prediction. Each returns:

- actor and primary intent;
- whether the exact card is identifiable from the text;
- the safest next action;
- evidence still needed and claims that must not be made.

The [Gemini 3.8 Flash model ID and Vertex endpoint](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-flash) are pinned in the reviewer script. It records actual model version, prompt hash, question hash and usage metadata for every call; failures remain explicit rows. No forum image or private marketplace listing is sent. The labeling prompt does not use Google Search, because this first task is to route the question **as asked**. Search grounding belongs in a separate evidence-research step, where returned sources can be inspected and cited; [Vertex supports Google Search grounding](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/grounding/grounding-with-google-search).

```bash
python3 -m scripts.vertex_public_question_review \
  --frozen-dir ../../work/public-question-sandbox/frozen-v1 \
  --checkpoint ../../work/public-question-sandbox/gemini-review-v1.jsonl \
  --project YOUR_VERTEX_PROJECT --location global
python3 -m scripts.public_question_sandbox merge \
  --frozen-dir ../../work/public-question-sandbox/frozen-v1 \
  --astra ../../work/public-question-sandbox/astra-review-v1.jsonl \
  --gemini ../../work/public-question-sandbox/gemini-review-v1.jsonl \
  --output ../../work/public-question-sandbox/silver-report-v1.json
```

The merge reports `silver_agreed`, `disputed` and `review_failed` separately, preserving every question. It measures **AI agreement**, not card identification accuracy. AI consensus cannot upgrade a card relationship to `verified`, establish a paid sale, evaluate an unseen photo, or justify a live price. Seller topics outside today's buyer question router remain visible as product gaps.

## Frozen v1 result

The archived [silver report](sandbox/public_questions/v1/silver_report.json) covers all 24 situations. Gemini returned a valid label for 23 and one explicit error. On those 23, Astra and Gemini agreed on primary intent in **20**, identity evidence state in **21**, and the first action in **14**. They agreed on all six exact fields in **2**; 21 are disputed. Required-evidence sets disagreed in 14 and forbidden-claim sets in 18. These are agreement counts, **not accuracy, safety, or coverage scores**. The photo-dependent questions cannot test visual reasoning because their images were not collected.

The largest discrepancy is in label scope. One reviewer often lists every globally unsafe claim; the other lists only claims relevant to the question. Evidence lists also mix the immediate blocker with later purchase requirements. v2 will define a first blocking action, separate blocking from optional evidence, and limit question-specific forbidden claims to relevant assertions. It will add seller context, platform policy, selling fees, cost basis and sealed-product metadata. Keep both v1 outputs intact. Since v2 design used these disagreements, the existing holdout is now a regression set; the next blind estimate must use newly found source posts.

## Next replay gate

Collect a broader, source-grouped batch of unviewed seller and buyer posts with explicit Japanese/English, price/condition, image and platform strata. Freeze source wording and dates before reviewing. Run independent v2 Astra/Gemini labels and a separate target-agent replay; score intent routing, missing-evidence questions, premature exact-card selection and unsupported claims separately. Multi-turn episodes may add simulated follow-ups, but each follow-up must disclose only a fact recorded in the original source or a clearly marked synthetic fixture. Synthetic variations never increase the count of real source questions. A person can later inspect high-impact disputes without blocking this first AI-led pilot.
