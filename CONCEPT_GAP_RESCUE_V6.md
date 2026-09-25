# V6 source-backed gap rescue

The first v6 ranked search exhausted five Japanese Trainer names after five
rejected English candidates each. Independent Astra and Sol source research
found direct English candidates **in the same pinned TCGdex checkout**. The
failure was candidate recall in the illustrator/date/numeral ranker, not a
catalog absence. Their [research reports](ASTRA_CONCEPT_GAP_RESEARCH_V6.md)
and [second report](SOL_CONCEPT_GAP_RESEARCH_V6.md) retain source paths, hashes,
rule comparisons and limitations.

| Japanese name | Source-backed English candidate | Distinctive rule evidence |
| --- | --- | --- |
| ポケパッド | Poké Pad | Search for a Pokémon without a Rule Box |
| みずの塔 | Tower of Waters | Rapid Strike Pokémon retreat cost reduced by two |
| サカキのカリスマ | Giovanni's Charisma | Return opposing Active Energy, then attach own Energy |
| 霧の水晶 | Fog Crystal | Search for a Basic Psychic Pokémon or Psychic Energy |
| キャンプセット | Camping Gear | Search for any card; turn ends |

The [five editorial seed pairs](catalog/concept-review-v6-gap-rescue-seeds.jsonl)
are candidate-generation hints, not aliases. `scripts/concept_gap_rescue.py`
checked exact catalog card IDs, names, category/subtype, the pinned TCGdex
revision and each card's source hash; it also rejected pairs present in the
old [125-row queue](catalog/concept-review-v6-full-queue.jsonl). Its
[review queue](catalog/concept-review-v6-gap-rescue-queue.jsonl) freezes those
sources and the [audit](catalog/concept-review-v6-gap-rescue-audit.json) records
the scope. No Japanese or English card image is redistributed in this repo.

Astra, Sol and Vertex Gemini 3.8 Flash then independently reviewed all five
name concepts. All three approved all five. Gemini received 6 of 10 possible
card images; the [image audit](catalog/concept-review-v6-gap-rescue-gemini-audit.json)
records every missing side and response hash. Tower of Waters has flattened
energy symbols in the English source, and Giovanni's Charisma has a more
explicit condition in its English rule text. Both differences are recorded
as limits, not suppressed. The [consensus bundle](catalog/concept-review-v6-gap-rescue-triple-consensus.bundle.json)
retains all three rationales and imports five internal bilingual name aliases;
its [five candidate edges](catalog/concept-review-v6-gap-rescue-proposed-edges.jsonl)
remain `proposed`. These are AI name judgments, not physical-printing or
human-certified matches. Importing again inserted zero records.

The five approved [anchors](catalog/concept-review-v6-gap-rescue-anchors.jsonl)
produced [15 further card-specific candidates](catalog/concept-review-v6-gap-rescue-relationship-queue.jsonl).
Together with the previous 58, this initially yielded 73 candidates across
25 Japanese anchors. The first visual triage exposed one wrong-artwork choice
for なかよしポフィン. Its queue had been capped at 12 despite 27 eligible
English cards. Regenerating all 25 anchors with a cap of 40 produced the
[complete 88-pair work pool](catalog/concept-review-v6-expanded-relationship-queue.jsonl)
with [zero truncations](catalog/concept-review-v6-expanded-relationship-audit.json).

The current [priority sheet](catalog/concept-review-v6-expanded-relationship-priority.csv)
orders each anchor's candidates by distinctive rarity family, variant label,
then set-release proximity. The [current first-pass queue](catalog/concept-review-v6-expanded-first-pass-queue.jsonl)
selects one candidate per anchor. This ordering is a work queue, not a match
score. The corresponding [human review template](catalog/concept-review-v6-expanded-first-pass-template.csv)
is untouched. The [priority audit](catalog/concept-review-v6-expanded-relationship-priority-audit.json)
shows 17/25 first-pass pairs with the same variant label and no missing
release dates.

Gemini's [initial image triage](catalog/concept-review-v6-first-pass-artwork-gemini.csv)
found 11 same-artwork candidates, one different-artwork candidate, and 13
without both images. The different pair was a gold Japanese Buddy-Buddy Poffin
against a later English Ultra Rare. The expanded pool surfaced an earlier
English [Hyper Rare gold candidate](catalog/concept-review-v6-buddy-poffin-gold-triage-queue.jsonl),
which Gemini judged same artwork when both images were available. The
[updated 25-pair triage](catalog/concept-review-v6-expanded-first-pass-artwork-triage.csv)
therefore has 12 same-artwork visual leads and 13 image gaps. These are AI
visual judgments only; the source images do not verify foil, variant, exact
printing, condition or price equivalence. The [13-row image-gap list](catalog/concept-review-v6-image-evidence-gaps.csv)
identifies the missing API sides and the card IDs needing authorized images.
All 13 gaps lack a Japanese image in the TCGdex API; 11 already have an
English image, one also lacks the English image, and one English fetch failed.

The local index now has 460 concept-review events, 122 internal name aliases,
122 `proposed` source-card edges, and **zero verified physical-printing edges**.
The next quality task is authorized Japanese images for the 13 incomplete
pairs and human inspection of artwork and finish for every first-pass pair.
A true blind, human-adjudicated sample is still needed before claiming
bilingual retrieval precision or recall.
