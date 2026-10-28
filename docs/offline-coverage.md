# Offline card, image and offer coverage

These standard-library reporting commands operate on explicitly supplied local
files. They make no source, image, certificate or cloud requests; do not modify
catalog or offer data; and create no source access, display, order or payment
authorization. They do not change a service's startup flags or release pins.
No private catalog, operator records, credentials or generated reports are
packaged with the code. All test fixtures are synthetic.

## Reports

- `pokemon_index.image_coverage` reconciles exported primary-image decisions with
  detailed historical media-copy receipts and emits an image work queue.
- `pokemon_index.cohort_coverage` checks a chosen exact-printing cohort against a
  pinned catalog, hash-bound selection evidence and exported image decisions.
- `pokemon_index.offer_coverage` measures supplied listing and photo evidence.
  Multiple native listings and sellers on the same platform remain separate.

The catalog's newer native primary-image reader is deliberately not imported
from an arbitrary runtime path. The first two commands consume a reviewed,
digest-pinned export instead. They validate the export's population, exact card
identity and provenance against the local catalog, but **do not independently
re-run or attest its producer's decisions**. Every report states that limit.
Obtain the export from the reviewed catalog reader; a JSON file or its hash does
not establish authorization or accuracy by itself.

## Primary-decision export contract

The export is UTF-8 JSON (maximum 128 MiB) with schema
`pokemon.catalog-primary-decisions.v1`:

```json
{
  "schema": "pokemon.catalog-primary-decisions.v1",
  "database_sha256": "<64 lowercase hexadecimal characters>",
  "catalog_records": 1,
  "producer": {
    "name": "reviewed-catalog-reader-version",
    "reader_code_sha256": "<64 lowercase hexadecimal characters>"
  },
  "rows": [{
    "card_id": "<exact catalog ID>",
    "identity": {"language": "ja", "set_code": "S", "collector_number": "1", "variant": "holo", "name": "Example"},
    "catalog_provenance_sha256": "<SHA-256 of the exact catalog provenance string>",
    "primary_image": {
      "status": "missing", "basis": null, "event_id": null,
      "current_endpoint": false, "image_sha256": null,
      "source_ref": null, "reason": "no_primary_image_recorded"
    },
    "source_scan": {
      "status": "missing_source_scan_evidence", "evidence_basis": null,
      "source_scan_event_id": null, "current_endpoint": false,
      "image_sha256": null, "inspection_tier": null
    }
  }]
}
```

There must be exactly one row for every catalog record. Current primaries need
an explicit supported basis, event ID, image digest and current endpoint.
Current source scans also need their source-scan event, basis and digest.
Duplicate JSON keys, contradictory current states, duplicate IDs and changed
identity/provenance are rejected. `producer` is provenance supplied with the
export, not a cryptographic attestation. Treat real exports as private data.

## Image-copy reconciliation

Supply both detailed copy receipts: the CSV with successful source-generation
and destination rows, and JSONL records with source/destination generations,
object name and size. A summary with schema `pot.beta-media-copy.v1` must match
their exact source/destination bucket, generation/create-only flags, object and
byte counts, and contain no errors or unexpected destination objects. Bucket
names and namespace are explicit operator arguments; none are hardcoded.

```sh
python -m pokemon_index.image_coverage \
  --database /path/catalog.sqlite3 \
  --snapshot /path/primary-decisions.json \
  --expected-snapshot-sha256 "$COVERAGE_SNAPSHOT_SHA" \
  --source-bucket source-bucket --destination-bucket destination-bucket \
  --namespace selected-copy-namespace \
  --copy-csv /path/copy.csv --copy-generations /path/generations.jsonl \
  --copy-verification /path/copy-summary.json --output /tmp/image-report
```

`image-inventory.json` and `image-work-queue.jsonl` describe supplied decisions
joined to historical copy evidence. They do not prove that bytes still exist,
that the browser can decode/load them, that image rights were granted, or that
an image depicts a seller's copy. Blobs not selected by a current primary may
still belong to held/stale records; they are not a deletion queue.

## Focused cohort

A cohort has schema `pot.focused-card-cohort.v1`, `id`, `basis` and `entries`.
Each entry contains exact `card_id`, `identity` (the five fields above),
`catalog_provenance_sha256`, and nonempty `selection_evidence`. Each evidence
record supplies a workspace-relative `path`, `sha256`, `json_pointer`, and
`expected_value`. Evidence paths must remain inside the selected workspace.
Evidence bytes are hashed and parsed together. Keep real usage evidence out of
source control.

```sh
python -m pokemon_index.cohort_coverage \
  --database /path/catalog.sqlite3 --expected-database-sha256 "$COVERAGE_CATALOG_SHA" \
  --snapshot /path/primary-decisions.json --expected-snapshot-sha256 "$COVERAGE_SNAPSHOT_SHA" \
  --cohort /path/cohort.json --workspace /path/private-review \
  --output /tmp/cohort-report.json
```

Optional `--next-wave` accepts retained JSONL identity samples. Their provisional
selection, unresolved marketplace-alias and photo-review states must remain
unchanged. The report never interprets a cohort as popular inventory, a trusted
physical-card match, or readiness to buy.

## Offer and actual-copy photo evidence

With no inventory, counts remain `null` (not measured). An explicitly supplied
empty array reports zero. This distinction is separate from whether a
marketplace has listings.

```sh
python -m pokemon_index.offer_coverage --now 2026-10-29T00:00:00Z
```

Add `--input /path/observations.json` for retained normalized listing observations
and optional `--photo-audits /path/photo-audits.json` for local operator audits.
`--synthetic` diagnoses fixtures without counting them as real inventory.
Malformed, stale, sold, synthetic and conflicting observations cannot form a
real-current comparison group. The report enforces its own freshness bound
(300 seconds by default, explicitly configurable from 1 to 900 seconds); a
far-future producer expiry cannot make old inventory current. Complete equal printing, grade, condition,
quantity and currency claims form **seller-claim groups only**, never approved
catalog matches. Grade grouping is deliberately limited to the reviewed rollout
pairs PSA 9 and PSA 10 and explicit raw form; other grade claims require review.
Missing API/crawl provenance or identity evidence from a different capture also
prevents grouping. Prices are native-currency item asks; fees, shipping, tax, FX
and later final quotes are outside this report.

Photo audits contain exactly `source`, `native_id`, `listing_url`,
`offer_observed_at`, `photo_url`, `evidence_ref`, `observed_at`, `sha256`,
`rights_reference`, `expires_at`, `view`, `depiction`, and `authorized`.
They are local operator attestations, not authenticated grants. Actual-copy
counts require an exact listing/capture binding, `depiction=actual_copy`,
`authorized=true`, a digest, a rights reference and explicit view. Unknown or
contradictory fields and conflicting audits fail closed; front/back evidence
requires distinct image hashes. URLs alone do not count as reviewed copy photos.
Photo completeness counts may include stale or sold observations; current-active
listing counts and current seller-claim groups remain separate metrics.
Neither a certificate number nor any report grants physical authentication.

## Verification

```sh
python -m unittest tests.test_image_coverage tests.test_cohort_coverage tests.test_offer_coverage -v
```

The offline CI job also runs these tests. They cover the actual local CLIs,
snapshot checksum/population/provenance binding, ambiguous/contradictory
decisions, receipt reconciliation, missing versus empty inventory, multiple
sellers, capture integrity, grade/currency separation and revoked photo audits.
Provider activation, current-byte delivery and a signed-in deployed flow remain
separate integration checks.
