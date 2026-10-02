# Two-card catalog comparison — 2 October 2026

## Delivered behavior

Collectors can compare two Japanese/English catalog records through an internal tool or supported natural-language questions. The tool returns separately scoped numbers, source-declared version candidates, exact reviewed stock-image artwork edges and outstanding copy/market evidence.

`POST /card-comparison` accepts only `left` and `right`. Each endpoint is either `{ "card_id": "..." }` or a language, set code and collector number, optionally with a source-declared variant. The CLI command `card-comparison request.json` uses the same read-only contract. Missing release information is invalid in the structured tool.

```json
{
  "left": {"language": "ja", "set_code": "SM1M", "collector_number": "18/60"},
  "right": {"language": "en", "set_code": "SM1", "collector_number": "50/149"}
}
```

`collector-discovery` additionally recognizes exactly two fraction-number mentions with preceding Japanese/English language and release codes/names, or two explicit canonical IDs, in comparison questions. Missing releases remain `scope_confirmation_needed`. Current graph evidence can identify a reviewed candidate pair within those candidates, but never supplies the missing requested release. An explicit unknown release stays unknown. More than 32 matches on either side requires narrowing and suppresses edge retrieval from the truncated list.

Mixed artwork/price questions retain useful catalog information while price evidence stays unavailable. This interpreter does not resolve all named characters, artists, grades or physical finishes from prose; that limitation is returned in `interpretation` and `unfulfilled_constraints`. Existing supported source-label filters and single-card flows remain available separately. Unsupported prose still asks for scope clarification.

## Evidence boundaries

- Number comparisons are derived from current raw card coordinates, not a possibly stale number-context cache. Language/release namespaces stay separate. Denominators do not report print-run quantities; numbering alone establishes neither scarcity nor price trends. The historical reason a publisher assigned a number remains unestablished.
- Only the newest event for each exact pair and relationship type is returned, including rejection. Verified artwork must pass current endpoint eligibility, family and frozen identity-snapshot guards. Proposals, rejected or stale links remain separate.
- Artwork evidence covers the exact reviewed stock-image endpoints. Uncovered sibling records are listed. Approval never transfers to another source-declared version or establishes all coordinate variants.
- Physical finish, edition, copy condition, printing equivalence, price comparability, numeric price gap, automatic offer joins, purchase readiness and public display remain unapproved. There are no live offers, prices or transaction URLs.
- A comparison journey has no selectable purchase target. Pivota's existing caller returns the nested partial result and rejects nested commerce approvals. The new runtime file is included in catalog/journey revision binding, requiring reconfirmation after a policy change.

## Measurement

[Six existing source-led questions](catalog/two-card-comparison-v1/questions-frozen-v1.jsonl) and their expected exact reviewed pairs/scope boundaries were frozen before the new route was first executed. The [first replay](catalog/two-card-comparison-v1/replay-first-v1.json) meets all six expectations. Three have complete regional coordinates and three retain a missing-release confirmation. This does not establish complete answers, independent held-out user accuracy or real-listing precision.

The first focused test attempt had one environment failure: the sandbox denied a loopback listener. After network permission was granted, the full suite passed **509 Python tests**, including 13 new comparison guard tests, and **12 Node tests**, including nested comparison approval rejection. After adding an explicit denominator/print-run explanation, the 13 focused guards were rerun successfully. The [final local HTTP/caller rehearsal](catalog/two-card-comparison-v1/local-http-replay-v2.json) passes 30 checks, preserves catalog bytes and verifies six actual Node caller responses against direct replay. The first local rehearsal is retained. [Existing source regression](catalog/two-card-comparison-v1/legacy-source-regression-v1.json) also passes: 82 queries, 31 graph results, 14 exact card details and source-only family selection guards. Source-led questions and raw responses remain intact.

The [rehearsal runner](scripts/rehearse_card_comparison.py) can repeat those checks against private staging and adds two unauthenticated-denial checks. It preserves original responses and normalizes only the build application timestamp of imported proposed AI edges for semantic comparison. Evidence, review and source timestamps remain bound. A `completed` flag distinguishes an interrupted report from a completed rehearsal.

[Private staging replay](catalog/two-card-comparison-v1/private-cloud-replay-v1.json) completes **32/32 checks** on revision `pokemon-commerce-index-00031-l5p`, with 30 authenticated requests, two unauthenticated 403 denials and zero recorded transport errors. It verifies actual Node caller protocol compatibility using an authorized operator token, not Pivota's deployed service identity. [Final binding](catalog/two-card-comparison-v1/deployment-final-binding-v1.json) confirms the revision still receives all traffic and checks the canonical service URL's authenticated health and unauthenticated denial. The previous 160-request cloud suite is historical; it was not rerun in full on this revision.

Catalog and graph inputs are unchanged: **70,006 internal source-version/family records**, 45,438 coordinate groups and **23 reviewed artwork-only pairs / 634 proposals**. The 47-input catalog build manifest remains unchanged. This delivery makes existing evidence usable in comparisons; it adds no new physical identity or graph approvals.

## Next priorities

1. Expand qualified artwork evidence and test fresh comparison questions across more releases and ambiguous versions; route unknown names/grades/finishes to their existing evidence flows.
2. Prepare an internal collector pilot through a deliberately registered Pivota service identity, with caller-owned sessions and the existing revision/reconfirmation contract.
3. Once Buy&Ship supplies an authorized listing/search feed and data-use scope, calibrate real listing identities, variants and grades, measure freshness/quota, then attach offers and transaction-bound URLs. Catalog comparison alone does not open these gates.
