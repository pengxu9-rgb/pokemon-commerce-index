# PSA certificate lookup

`pokemon_index.psa_cert.PSACertClient` implements a server-side, read-only
certificate-record lookup. It does not authenticate a physical card, slab,
photograph, seller or marketplace listing. No lookup result changes catalog
approval or the offer's `certificate_verified` / `authenticity_verified` fields.

## Configuration and transport

Pass the server-only `PSA_API_TOKEN` value as `token` and explicitly enable
`allow_live=True`. Missing access returns `unavailable/access_unconfigured`;
disabled access returns `unavailable/live_disabled`. Neither makes a request.
Never put the token in a browser environment variable, a command argument,
a fixture, a screenshot or a log.

The fixed route is `GET https://api.psacard.com/publicapi/cert/GetByCertNumber/{certificate_number}`.
Input is a string containing 7–12 ASCII digits; preserve leading zeros. This
length bound is our input policy, rather than a claim about every certificate
format PSA supports. No redirects, endpoint overrides, retries, image fetches,
population queries, orders or payment operations are available.

Defaults are an eight-second timeout, a 64 KiB JSON response, ten cache misses
per rolling minute and a five-minute cache with at most 256 records. Concurrent
provider calls are serialized; contention returns a short retry message.
Comparisons happen after cache retrieval and are never shared between offers.

## Evidence and comparison

The result schema is `pokemon.psa-cert.v1`. `record_found` means the provider
returned a card record with the exact requested certificate string.
`status` is `found`, `not_found`, `invalid`, `unavailable` or `mismatch`.
Only `found` and `mismatch` include a record. A different provider certificate
number returns `unavailable/certificate_number_mismatch`, without exposing the
unrelated record.

The optional server-owned `expected` dictionary may compare `subject`,
`card_number`, `year`, `brand`, `variety` and `grade`. Do not pass a full
marketplace title as PSA's subject. A comparison reports the matched,
mismatched and missing fields separately. `matched` means only the supplied
fields match; grade alone does not establish card identity. Missing fields
produce `inconclusive`. No translation, substring or card-number fraction
matching is attempted. Complete unqualified PSA 9/10 grade labels can match
the corresponding numeric claim; qualifiers are retained.

`certificate_verified`, `authenticity_verified` and
`physical_authenticity_verified` are always false. PSA itself explains that
database numbers can be copied onto counterfeits and that PSA does not inspect
the item offered in a web listing.

HTTP 200 alone does not establish success. Negative and contradictory PSA
envelopes, malformed/oversized JSON, missing card records and unsupported
responses fail closed. Exceptions and provider diagnostic text are replaced
with fixed messages to prevent token disclosure.

## Validation and bounded live test

Run `python3 -m unittest tests.test_psa_cert -v` for offline coverage. Tests
inject transport fixtures and block socket calls. They cover documented
responses, cache expiry and isolation, request limits, redirects, owner-free
record comparison, unavailable access and error redaction.

After the operator configures access, use one operator-supplied known
certificate for one lookup and then a cached repeat. Compare expected matching
and mismatching grades using that same returned record. Do not enumerate
certificate numbers or use random real numbers as negative tests. An unavailable
provider remains an explicit result; there is no fixture fallback.

## Primary references

- [PSA API documentation](https://www.psacard.com/publicapi/documentation)
- [PSA API Swagger schema](https://api.psacard.com/publicapi/swagger.json)
- [PSA certificate verification limits](https://www.psacard.com/cert)
- [PSA grading standards](https://www.psacard.com/gradingstandards)

Documentation and schema were checked on 21 October 2026. No certificate API
request was needed to implement or run the offline tests.
