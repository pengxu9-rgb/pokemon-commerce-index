# Supported catalog, collector execution and offline commerce — 1 October 2026

This implements the first independent work in the revised [build sequence](BUILD_SEQUENCE.md). Buy&Ship's listing feed remains pending. No live source, public shopping route or order creation has been enabled.

## Delivered

| Work | Result | Remaining evidence |
|---|---|---|
| Positive metadata support | 100 SV4A targets, each bound to pinned card identity, a second-source reference, official rarity audit and official release facts | Source finish labels do not verify physical printings or seller copies; automatic live-offer approval remains zero |
| Catalog safeguards | Omitted eligibility defaults to false; missing variants cannot enable matching; migration preserves historical structural flags; changed evidence invalidates support | Existing 33,543 structural flags remain historical source decisions, not accuracy approvals |
| Release vocabulary | Official title/date overlays for SV4A, SV2A and SV8A; six set-name/code aliases used in both discovery and title matching | No observed marketplace-query recall or inferred colloquial aliases |
| Bilingual concepts | 122 reviewed alias revisions and 460 review events now built from ten hash-checked consensus bundles | Concept translation does not establish counterpart or price equivalence |
| Collector execution | Character and artist card retrieval, exact coordinates, printing neighbors, dated family checklists, separate proposed artwork leads | Bounded deterministic patterns; broader dialogue and fresh real-user acceptance remain open |
| Families | Ralts: four species, Eevee: nine, Pikachu: three, from official Pokédex evolution data | Species membership does not prove cameos, paradox ancestry, full form coverage or gameplay rules |
| Commerce rehearsal | 100 synthetic listings on the supported coordinates, a target-bound ask/landed quote/recommendation/URL preview | Zero real observations, sales or fulfillment outcomes |
| Durable worker foundation | File-backed queue, committed call reservations, expiring leases, bounded retry, atomic observation receipts, restart recovery, freshness and policy retention | Operator-owned SQLite only; no cloud worker schedule or managed market storage |

The official [Shiny Treasure ex release page](https://www.pokemon-card.com/ex/sv4a/index.html) corrects the old SV4A title and date. Release and family records retain source URLs and page hashes; catalog images are not copied. The internal snapshot still has 55,167 identities, 33,543 structurally eligible rows, 532 rarity overlays, 657 proposed artwork assertions, zero verified artwork/counterpart events and zero public-display approvals.

## Verification and interpretation

- Full regression suite: **351 tests passed**. Synthetic test identities now explicitly opt into structural eligibility instead of relying on a permissive import default. Existing expectations were preserved.
- Thirty raw authored task questions and independently computed catalog-reference IDs were frozen before executor implementation. **First run: 28/30**, retained in `tasks-initial-development-report.json`. Two promo-denominator case failures were fixed; corrected development replay: **30/30**. These tasks are authored development cases, not independent user questions or a blind accuracy estimate. Exact name/number/finish conflicts have separate regression checks.
- Commerce rehearsal: **14/14 checks passed**. Retry and quote state survive reopening the file; repeated responses do not create extra observations; conflicting snapshots roll back the batch; bundles abstain; unknown condition stays separate; missing cost components block; expiry and a newer observation invalidate a quote; retention removes observations and journal payloads. The fixture partner client uses `example.invalid`; it makes no network calls or orders.
- Worker tests additionally check daily budget visibility across connections, bounded backoff/attempt exhaustion, source revocation, response limits, future timestamps and retention resurrection. Observation immutability is enforced at the new worker boundary; old standalone imports remain separate operator tools.

Snapshots can have different file hashes across rebuilds because audit application timestamps are recorded. Input hashes, logical counts and membership are pinned by the manifest. Local and staging snapshot hashes must be reported separately.

## Reproduce

```bash
python3 -m scripts.build_catalog_snapshot --db catalog.sqlite3
python3 -m pokemon_index --db catalog.sqlite3 supported-status
python3 -m pokemon_index --db catalog.sqlite3 collector-discovery "List the Ralts family cards in Japanese and English chronologically" --limit 20
python3 -m pokemon_index --db catalog.sqlite3 collector-discovery "ミュウex シャイニートレジャーex 347/190"
python3 -m scripts.evaluate_collector_tasks --db catalog.sqlite3 --output /tmp/collector-development.json
python3 -m scripts.rehearse_supported_commerce --catalog catalog.sqlite3 --state /tmp/commerce-rehearsal-new.sqlite3 --output /tmp/commerce-rehearsal.json
python3 -m unittest discover -s tests
```

The rehearsal refuses to overwrite existing state. It clones the catalog and enables a display override only in that isolated synthetic test copy; the source catalog and staging snapshot retain zero display approvals. Do not serve the rehearsal database. The worker is a library, not an enabled production feed connector. Lease duration must exceed an adapter's bounded request time; confirmed provider limits and a managed storage design are still required.

The new manifest uses an explicit-eligibility derivative of the original JA seed; the original file and historical manifests are unchanged. To reproduce old manifest counts exactly, use their historical code commit. Earlier manifests depended on the old permissive default and are not compatible with the new import default.

## Next decisions

Freeze fresh, independently sourced collector questions and measure actual returned results before further pattern expansion. Add evidence-backed coverage for additional releases and physical finishes in response to those tasks. Prepare managed observation storage and a separate worker deployment, then run Gate 0, real listing matching and freshness checks when an authorized feed is available. Keep the original sweep-fidelity gate before liquidity or transition-price claims. No AI agreement, metadata count or fixture result closes those gates.
