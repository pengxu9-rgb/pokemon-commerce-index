# Evidence gates for buyer questions

Collectors ask about language alternatives, exact foil finishes, card identity and price differences before choosing an offer. These needs appear in public discussions about [Japanese versus English collecting](https://www.reddit.com/r/pkmntcgcollections/comments/rwfq17), [identifying foil patterns](https://www.reddit.com/r/PokemonTCG/comments/1vn449q/help_identifying_foiling/), [card set codes and numbers](https://www.reddit.com/r/pokemoncards/comments/1dm7qoo), and [cross-language prices](https://www.reddit.com/r/pkmntcgcollections/comments/1kkj0ab). These links informed the question categories; they are **not** a representative user sample or an accuracy test.

The new internal `buyer-question-plan` takes a **structured question type** and an optional exact `card_id`. A future language model may suggest the type, but the graph determines what can be claimed. Without an exact card it asks for language, set, number and printing. With one, it handles six types:

| Question type | Current response gate |
| --- | --- |
| `printing_variants` | Lists same-language, same-set, same-number printing candidates. The link is structural; artwork and finish are not inferred. |
| `english_or_japanese_counterpart` | Returns only verified card-specific counterpart links. AI artwork proposals remain review leads. |
| `same_artwork` | Returns verified same-artwork or counterpart links. AI proposals are explicitly separate. |
| `cross_region_price` | Requests a second exact printing, fresh authorized offers, currency and landed cost. It does not compute a price from catalog relations. |
| `condition` | Requires an authorized listing, front and back photos, and a condition review. |
| `merchant_choice` | Requires fresh offers, landed quotes and seller fulfilment evidence for a full recommendation. |

All responses set `price_comparable=false`. A reviewed relationship still does not merge two priceable units. The current fixed catalog has 657 AI artwork proposals and **zero verified cross-region links**. For example, `ja:M-P:046/M-P:normal` has an English artwork lead, but the answer is `relationship_review_needed`, not “English counterpart found.” The same-set-number query for `ja:SV2A:025/165:normal` returns Poké Ball and Master Ball variants as choices. The price question returns `market_evidence_needed`.

Run against a clean private catalog snapshot:

```bash
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest.json --db /tmp/pokemon-buyer-catalog.sqlite3
python3 -m pokemon_index.cli --db /tmp/pokemon-buyer-catalog.sqlite3 \
  buyer-question-plan same_artwork --card-id 'ja:M-P:046/M-P:normal' --target-language en
```

The same read-only route is available as `/buyer-question-plan` only when the internal catalog API is enabled behind authentication. No public card metadata display right is implied.

## Independent question evaluation still needed

This is an evidence gate, **not a natural-language classifier**. The earlier 10 journey examples were manually converted to structured constraints. To measure the agent, freeze its parser/prompt/model and collect buyer questions before seeing its output. Independently label each question's intent, whether an exact card is specified, which missing evidence must be requested, and which exact card or graph claim would be valid. Keep photo-dependent questions separate from text-only questions. Report intent accuracy, exact-card precision and recall, abstention, and unsupported price or counterpart claims. The public links above can guide coverage but must not be reported as a blind accuracy score.

The offline evaluator is ready for that frozen set. Keep `gold.jsonl` and `predictions.jsonl` separate under a private working directory. Each gold row has a stable `id`, the original `question`, two distinct reviewers with agreeing `label` objects, and an `adjudicated` copy of that label. A label has exactly `question_type`, `card_id`, and `target_language`; each latter field may be `null`. Use `question_type: "unsupported"` with both remaining fields `null` when the catalog product cannot safely route the question. A prediction row has the same `id` and three label fields; `question_type: null` is an abstention. Predictions must cover every frozen gold ID, including abstentions, so unresolved rows cannot disappear from the denominator.

```bash
python3 -m scripts.evaluate_buyer_questions \
  --db /tmp/pokemon-buyer-catalog.sqlite3 \
  --manifest catalog-build-manifest.json \
  --gold ../../work/buyer-questions/gold.jsonl \
  --predictions ../../work/buyer-questions/predictions.jsonl \
  --output ../../work/buyer-questions/report.json
```

The report separates intent agreement, exact-card agreement, joint agreement, abstentions, premature card selections, and invalid card IDs. It records hashes of the catalog and both input files. Reviewer IDs and matching labels do not prove independence; the study owner must keep predictions hidden until gold is fixed. The evaluator does not score prose answers, image recognition, offer quality or actual market prices.
