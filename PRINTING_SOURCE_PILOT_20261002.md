# Printed source evidence pilot — 2 October 2026

## Delivered scope

The pilot contains 23 append-only evidence events: 14 source observations and nine holds. Fourteen exact official card images were directly inspected by the implementation agent and the root agent. The second reviewer saw the first findings before inspection; these are two actual source inspections, not a blinded or population accuracy measurement. The separate root report binds its readings to the full-image SHA-256 receipts.

| Evidence | Count | Result |
|---|---:|---|
| Printed artist credits | 10 coordinate events | Two source inspections agree. Six seed credits differ from the printed credit; four official HTML labels differ from the printed image. |
| Professor subtitle and stamp | 2 coordinate events | 021/SV-P prints オーリム博士; 022/SV-P prints フトゥー博士. Both images print EVENT ORGANIZER. |
| Wrong numbered source reference | 1 held coordinate event, 2 images | Target 153/SV-P includes reference45644, which visibly prints154/SV-P. Distinct artwork and a シールド戦 stamp are visible on both images. The incorrect reference remains recorded and held. |
| Missing Japanese references | 8 held coordinate events | SV-P037–044 have no pinned exact official reference in the frozen queue. No reading is invented or substituted from another region. |
| Manufacturer mirror declarations | 2 release events | SV8A declares premium mirror treatment; SV2A declares Poké Ball pattern mirror treatment. These do not enumerate every affected number or assign source variants. |

The ten printed credits are: M6 110/076 Kazuki Minami; M-P046/M-P 5ban Graphics; M-P131/M-P and132/M-P YOSHIROTTEN; M-P134/M-P HACCAN; M-P137/M-P AKIRA EGAWA; SV11W088/086, SV-P111/SV-P and SV8012/106 0313; SV-P198/SV-P Kariya. The leading zero is visibly printed in all three 0313 cases.

Images and raw HTML remain in the local research cache, outside the cloud catalog. The catalog stores factual readings, official locators, page/image hashes and review bindings. These facts do not approve image redistribution.

## Runtime contract and boundaries

`pokemon_index/printing_evidence.py` provides `import_evidence`, `context`, `supported_artist` and `status`. Imports bind a complete current coordinate membership/reference snapshot, exact publisher source pages/images, reading digests, distinct review actors and consecutive revisions. Identity/reference changes stale the overlay. A source image whose native asset ID differs from its referenced page is rejected. A wrong printed coordinate requires an explicit hold.

`supported_artist` returns a separately evidenced credit only with two exact-image reading bindings, current identity and same-valued artist readings covering every current coordinate reference. Single reviews, partial reference coverage, conflicting values, holds and stale identities return no supported credit. This is an overlay fact; the seed is preserved. Discovery facets for the ten earlier conflicts remain excluded pending a separately scoped immutable correction.

Release declarations are bound to the Japanese release namespace and official product page. They cannot specify an individual card finish. Publisher stamps/subtitles are stock-asset observations; actual seller photographs, stamp/finish identity, physical condition, authenticity and grading remain unverified. Family copy blockers remain in force. All physical-finish, actual-copy, price-comparability, public-display, exact-alias and automatic-offer permissions remain false. No verified relation pair or market observation is added.

## Frozen collector diagnostic

Twenty source-led authored questions were frozen before their first execution. The initial replay used the existing pre-ledger database with the already integrated collector runtime; it is not a pre-implementation baseline. It yielded five abstention checks and zero of15 newly expected source-fact cases. The ledger replay exposes the expected fact on the first returned page in15/15 cases and passes the five abstention checks. Both runs return zero prices or live offers.

These are first-page evidence visibility and abstention diagnostics. They do not measure useful complete answers, physical printing precision, independent held-out performance, population accuracy or marketplace matching. Exact initial outputs, runtime/database hashes, source/expectation locks and the chronology note are retained. Expectations were not changed between replays.

Artifacts: `catalog/printing-source-pilot-v1/evidence-v1.jsonl`, `summary-v1.json`, `root-visual-review-v1.json`, `questions-frozen-v1.jsonl`, `questions-lock-v1.json`, `initial-development-results-v1.json`, `baseline-provenance-v1.json` and `ledger-development-results-v1.json`.

## Reproduce

```sh
python3 -m scripts.build_printing_source_pilot \
  --db /tmp/pokemon-coordinate-family-v1.sqlite3 \
  --page-cache ../../work/japanese-evidence-next-v1-cache \
  --image-cache ../../work/printing-pilot-v1-cache \
  --root-review catalog/printing-source-pilot-v1/root-visual-review-v1.json \
  --output /tmp/new-printing-source-pilot

python3 -m scripts.rehearse_printing_source_tasks \
  --db /tmp/pokemon-printing-pilot-v1.sqlite3 \
  --cohort catalog/printing-source-pilot-v1 \
  --output /tmp/new-printing-source-replay.json

python3 -m unittest tests.test_printing_evidence -q
```

The builder records fresh event times/IDs and therefore does not promise byte-identical output. Rebuilding checks exact cached hashes, publisher page-to-image membership and the separate source review. Existing frozen events are imported without modification. The pilot database is a separate operator-owned copy of the baseline, with the23 events imported; production snapshot membership is determined by the root's ordered manifest.

Next: source-backed immutable credit correction if retrieval needs the ten credits, explicit printed subtype alias review for the two professors, and a scoped correction of153's wrong reference. A specific physical-finish pilot needs stronger per-card manufacturer evidence or actual controlled copy photographs. Generic product declarations and a flat stock image cannot establish every exact printing.
