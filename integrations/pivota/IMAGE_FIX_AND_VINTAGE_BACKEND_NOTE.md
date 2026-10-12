# Local backend handoff — holds, scan filtering and vintage retrieval

Use branch `codex/international-coverage-20261011`, base `f499b46f7f0898c5c0478c53fef960d435f1765f`. The final staged tree and artifact hashes are in `outputs/image-fix-backend-handoff.json` in the international-coverage chat workspace. This session supplies a local patch and read-only candidate; the separate frontend owner handles adapter/UI validation and any separately authorized private staging work.

Explicit candidate manifest: `catalog-build-manifest-international-pokemon-vintage-v1.json`, SHA256 `edac857fe29dd854ee86ee2eb95f61873aaaa14b5cd4707baf9ad8355a04bc7e`,78 ordered inputs. Original65 and all prior stages remain unchanged. Dockerfile still uses `catalog-build-manifest-source-binding-v1.json`; changing the default build/runtime source is a separate integration action.

```sh
python3 scripts/build_catalog_snapshot.py --manifest catalog-build-manifest-international-pokemon-vintage-v1.json --db ../vintage-new.sqlite3
python3 -m pokemon_index.cli --db ../vintage-new.sqlite3 serve --host 127.0.0.1 --port 18790 --internal-catalog-api
```

The existing integration server is `http://127.0.0.1:18789`, bound to the delivered `../vintage.sqlite3` SHA256 `0f030b433fb5a285d3c9bd7acc15cd73a3ff09bbf10bf9767e49346d85cccfe6`. It is read-only and imports nothing. One local19-request proof observed a2.772329s maximum request, including broad journey replay. Cloud adapter/build latency and live asset delivery remain unverified here.

## Read contract

Card rows returned by `/catalog-card`, `/catalog-search`, `/collector-discovery`, collector journey recommendations and comparison side records include `media_availability` with schema `pokemon.catalog-media-availability.v1`. Fields: `status`, `evidence_basis`, `reason`, `with_source_scans_eligible`, `source_scan_event_id`, `warnings`, `inspection_tier`, `current_endpoint`, `source_ref`, `image_sha256`, `live_fetch_verified`, `display_allowed`, `physical_printing_verified`.

Statuses are `current_source_scan_evidence`, `missing_source_scan_evidence`, `stale_source_scan_evidence`, `held_source_scan_evidence`, `identity_hold`. Only current exact evidence qualifies for the filter. Approval/live-fetch flags stay false. `source_ref` is the archived evidence reference; it need not be a displayable direct asset URL. Retain its source namespace, hash and evidence event. The browser/media bridge must apply its own authorized URL, rights and fetch rules without substituting another language, number, variant or asset extension.

Prefer current `source_image_facts` if present. A stale primary is a hard failure; it does not fall through. Only where no primary exists may current exact agreed `number_evidence` qualify. Number `reading_hold`, stale endpoint or source coordinate conflict must fail closed, including against a legacy backend response with no optional `media_availability`. Current primary warnings remain advisory and must be surfaced according to the bridge's review policy. Number-only observation is not physical variant verification; preserve observed numerator/denominator text separately from provisional catalog coordinates.

`GET /catalog-search` and `/collector-discovery` accept `with_source_scans=true|false` with exact lowercase values; default false. Filtering happens before total/offset/limit. Both expose `with_source_scans` at the top level. Catalogue search exposes `total_before_source_scan_filter` at the top level; collector discovery exposes it at `coverage.total_before_source_scan_filter`. All existing language/set/number/variant constraints remain authoritative. Empty filtered exact queries must remain empty, without sibling fallback.

Generic journey/recommendation ranking now uses `explicit_axes_then_liked_axes_then_source_scan_tiebreak_then_coordinate_round_robin.v2`; the Node collector client accepts v1/v2 and rejects unknown policies. The scan tie-break applies only after stronger relevance and is disabled for hard coordinate/variant/ID scopes. No preferences are applied to market data and no prices are introduced.

`GET /catalog-status` adds `variant_dimension_holds` and `source_scan_coverage` (`pokemon.source-scan-coverage.v1`). Final partition:70,006 rows =1,171 current +68,791 missing +44 identity holds; stale and held scan counts0. Current basis1,141 primary image-fact subjects +30 number-only subjects. The historical `printings` count is internal catalogue rows, not verified physical cards.

## Holds and targets

All44 size-loss IDs retain their exact raw source identity. `variant_dimension_hold` uses schema `pokemon.variant-dimension-context.v1` and exposes legacy ID/variant, source-declared size, immutable event/hash/pin, hold reason and status, `dimension_complete_identity=false`, `canonical_replacement_card_id=null`, `replacement_relationships=[]`, with all approval claims false. Source drift reports `stale_hold_source_changed` and keeps the hold active. Hold import installs an indexed quarantine ledger plus retention triggers. No ID migration or standard-size fallback occurs.

For exact `en:BASE1:058/102:normal`, show the source-declaredjumbo hold. Its existing unlimited and shadowless-first-edition IDs remain distinct exact lookups. Direct `/units` and `/offers` for the heldnormal ID returnHTTP400 with `card has an unresolved variant-dimension hold`. Backend unit creation, manual/prebound matching, observation/quote/sale imports and market readers also reject held identities. New source-image/number evidence imports reject held IDs until a separately reviewed dimension-complete identity migration exists.

The exact Japanese priority targets PMCG5 036normal, PMCG1 035normal/no-rarity and PMCG2 024normal have missing compatible imported scan evidence. Their existing IDs remain queryable. Existing authorized cached provider documents are not sufficient to bind images. Do not convert missing state into a physical-card absence claim, a matched sibling image, or guessed metadata. New acquisition/review remains the authorized owner's responsibility; this session uses existing sources only.

The first five broad `help me find some pikachu cards` IDs are:

1. `en:HGSSP:HGSS03/000025:holo`
2. `en:ME02.5:057/217:holo`
3. `en:SMP:SM04/0248:normal`
4. `en:SV02:063/193:holo`
5. `en:SV04.5:018/091:normal`

Each has current primary source evidence, archived exact asset reference/hash and no warnings. The first3 have two-image-model screening; the last2 have OCR/image-model screening. Advisory evidence does not grant live delivery, display, physical printing or transaction authority. English filtered searchtotal6 and full-pool Pikachu/Dex25 filteredtotal16 have been exercised against the local server.

## Dataset and rollback

Stage14 adds100JA bindings across PMCG1/PMCG2/PMCG3/E3/E5 and25EN comparisons, yielding1,907 total bindings(1,682JA/225EN). All source records and historical references stay present. Full840-test run:838 pass/2 existing skips;19new and16Node tests pass. Independent GPT-6.1 Sol high review rechecked adversarial holds/media behavior and source/snapshot reproducibility. The handoff receipt includes test logs, operator proof and patch composition/reversal proof.

Local rollback uses untouched `../classic.sqlite3` with the76-input classic manifest and the reverse-checked stage14incremental patch in a disposable checkout. Do not overwrite shared changes or delete evidence in place. Full code/data rollback restores nine known ambiguous historical flags, so retain the hold issue record and avoid market use. No deployment or cloud-permission/expiry/default-traffic changes were made here. No live ingestion, purchases or payments are enabled. Buy&Ship remains intended MoR; Pivota holds no customer funds.
