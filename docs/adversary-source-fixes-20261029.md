# Adversary source fixes (29 October 2026)

The research response now projects every accumulated offer against current
source authority after all selected marketplaces finish. Revoked, disabled or
otherwise unauthorized rows are removed from the response and retained offers
and selections. A photo display downgrade strips photos from every retained
row and the final response. Source readiness, connection readiness and coverage
describe the same resulting response. Readiness checks run before the final
authority projection, which does not wait on transport locks.

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
host alias captures. It uses fake HTTPS and a loopback HTTP server while denying
external socket and DNS operations. All quote-provider dispatch lists remain
empty in these source regressions.

Focused validation:

```sh
python3 -m unittest tests.test_adversary_source_fixes tests.test_live_offer_pilot tests.test_marketplace_sources tests.test_commerce_loop tests.test_ebay_official tests.test_ebay_commerce_integration
```
