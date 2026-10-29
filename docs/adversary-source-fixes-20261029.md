# Adversary source fixes (29 October 2026)

Every research, selection, manual handoff, BNS outcome and contextual certificate
response uses one final publication projection after readiness and provider
work finishes. It projects every accumulated offer against current source
authority. Revoked, disabled or
otherwise unauthorized rows are removed from the response and retained offers
and selections. A photo display downgrade strips photos from every retained
row and the final response. Source readiness, connection readiness and coverage
describe the same resulting response. Readiness checks run before the final
authority projection, which does not wait on transport locks. Revocation of a
required selection or handoff source rejects the response after pruning its
reusable records; a photo-only downgrade strips attachments. A still-matching
selection fingerprint follows only that photo projection, preserving all other
drift checks. Unrelated evidence drift cannot be accepted by this adjustment.

The publication boundary commits a detached response snapshot under the state
and source-authority locks. The HTTP layer serializes that snapshot. A later
revocation governs subsequent publications and actions; it cannot recall bytes
from an already committed response. Private capture/drift audit snapshots are
not reusable selection records and retain their existing behavior.

Quote validity is checked again at that final publication instant, after all
API and budget readiness waits. A quote that expires during a wait becomes
`manual_handoff_required` with `quote: null` and the existing `quote_expired`
refusal code/message. Source, offer and selection expiry checks still precede
this fallback. A regression exercises a real three-second native API-lock wait
within the five-second HTTP timeout, with valid-before/expired-after timestamps;
controls retain valid quotes and reject expired source/offer/selection context.

This publication check is independent of read admission: completing a read
window or request allowance preserves already captured evidence within its
original freshness bound. Readiness still reports that further reads are
unavailable. Marketplace reads, photo display and partner handoff remain
separate capabilities; none grants the others.

For the supported eBay CCG Individual Cards category `183454`, explicit
`Ungraded`/`Raw` conditions or condition ID `4000` establish a seller raw claim.
Conflicting grader, grade, certificate, title or condition evidence fails
closed. The actual `Card Condition` descriptor is retained as
`seller_condition`, so condition changes invalidate a selection and different
conditions are not collapsed into the generic `Ungraded` label. Condition ID
`4000` in unsupported or missing categories does not establish a raw claim.
Seller statements remain unverified; no physical condition assessment occurs.

Both accepted canonical SNKRDUNK hosts, `snkrdunk.com` and
`www.snkrdunk.com`, resolve to the existing `snkrdunk` authorization check.
The existing source policy, source allowlist, exact URL allowlist, robots rules,
dispatch limits and revocation still apply.

`tests/test_adversary_source_fixes.py` reproduces the prior adversary's
multi-source revocation timing, native eBay raw condition payload and canonical
host alias captures. It also reproduces native API-lock waits during selection,
manual handoff and BNS success/refusal publication, plus photo policy changes
between research, selection and handoff. It uses fake HTTPS and a loopback HTTP
server while denying external socket and DNS operations. Source-only and manual
regressions make no quote-provider dispatches; the BNS cases use the existing
in-memory fixture and have no order or payment operation.

Focused validation:

```sh
python3 -m unittest tests.test_adversary_source_fixes tests.test_live_offer_pilot tests.test_marketplace_sources tests.test_commerce_loop tests.test_commerce_psa tests.test_ebay_official tests.test_ebay_commerce_integration
```
