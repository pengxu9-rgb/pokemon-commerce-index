# Backend handoff — offline international coverage pilot

No creator frontend files changed. Build the candidate backend catalogue explicitly with `catalog-build-manifest-international-pilot-v1.json`; Dockerfile remains on the original source-binding manifest. Keep this local until a separate release decision.

`core.catalog_search_internal`, internal HTTP `/catalog-search?language=...`, and CLI `catalog-search --language ...` support an explicit language filter and exact recognized language tokens in free-text queries. Existing set codes such as EL take precedence when a free-text token also spells a language. For those ambiguous tokens or arbitrary tags, pass `language=` explicitly; additional imports do not imply language-specific natural-language routing. Localized set fields use generic `name`/`release_date`, while Japanese legacy fields remain compatible. Missing localized dates remain unknown.

The 35 Japanese and 25 English pilot records expose current reviewed translated names in internal search. Existing card IDs and references are stable. Result cards can contain `localization_evidence` with provider/native ID, hash/revision, retrieval status, region (`ZZ` = unknown), product-release scope and `current` status. Free-text results remain discovery candidates. The existing v2 resolver's global reviewed concepts, full variant/category checks and required coordinates remain unchanged; 59 unique and one ambiguous result are unchanged by this pilot. Never select a SKU from a single translated search hit alone.

All returned localization permission claims are false. Treat identity/variant questions, source conflicts and quarantined identities as clarification work. Cross-language counterparts and artwork are relationships; no artwork/name/number similarity implies identical SKU, price, stock, condition or grade. Catalogue counts are source-version/family records, not verified physical-card totals. Keep listing/asking/sold/landed-cost evidence and Buy&Ship MoR handoff separate. There is no live feed, purchase eligibility or payment activation in this patch. Pivota does not hold customer funds.

Run the shared internal-query and variant-clarification regression cases against the candidate backend when separately authorized to integrate. Do not expose images or catalogue text publicly based solely on the metadata license. The frontend session need not edit IDs or migrate saved references for this batch.

## Stage 2: optional held evidence context

The separate offline `catalog-build-manifest-international-qualification-v1.json` appends 65 held release-evidence candidates across SMH/DS/SC/LL. It does not add identities, aliases, dates, price data or permissions. Creator frontend source has not been edited.

Internal `catalog-card` returns optional `card.coverage_qualification`; internal `catalog-search` cards can carry the same field. Each entry contains `candidate_id`, `status` (`held` or `stale`), `hold_reasons`, provisional `numbering_scope`, provider source evidence, confidence separated into checked source bytes and unknown product/physical identity, and all-false permission claims. `catalog-status.coverage_qualification` contains event, distinct-subject, current-held and stale counts. Older snapshots return no card context and zero qualification counts.

Treat this optional context as evidence work status only. It cannot supply a display name/date, prove a regional printing, select a variant, enable an offer join or authorize checkout. Existing names and the resolver remain unchanged. The default Docker manifest is unchanged; these fields appear only when a separately authorized backend build includes the held queue.

## Stage 3: optional exact-coordinate publisher captions

The local 68-step `catalog-build-manifest-international-product-text-v1.json` appends four current publisher-caption events for existing SMH/DS/SC/LL Japanese anchors. Internal `catalog-card` and `catalog-search` can expose optional `publisher_product_text`, containing current/stale status, exact captions, publisher namespace/native ID/hash/retrieval time, link classification, evidence scope and all-false approval claims. `catalog-status.product_text` reports event, subject, current and stale counts. Older snapshots omit card context and return zero counts.

Internal search can match the four exact Japanese product captions to their bound coordinate families when `language=ja`; adjacent coordinates and English records do not inherit them. These are discovery candidates. Full variant/category/coordinate resolution and v2 concepts remain unchanged. A publisher `official_news_article` link is factual source context, not a verified product-release date or purchase target. Do not assign the named SMH deck caption to every SMH printing. All 65 physical-identity holds remain held.

Use these fields only for internal evidence-aware discovery when integration is separately authorized. They grant no public text/artwork display, offer association or checkout eligibility. No frontend code or default Docker build has changed.

## Stage 4: operator evidence plan

The offline `scripts.plan_international_release_evidence` command emits the fixed 65 subjects with four caption-priority flags, 61 exact card-page requests and four product-document work groups. Each group keeps exact coordinate bindings; it is not a release/SKU identity. Source declarations and checked publisher captions remain distinguishable. A related SMH family page supplies only a yearless month/day marker, so release date and physical region remain unknown.

This stage adds no runtime response fields, aliases, database tables or manifest inputs. Continue using the stage 3 backend contract above; the frontend session has no integration change to make. All 65 holds and all display and purchase restrictions remain unchanged. The saved plan is operator evidence work, with no network fallback or promotion path.

## Stage 5: qualified provider documents and held anchors

`scripts.qualify_international_product_documents` emits three verified pinned TCGdex header-fact records for DS/SC/LL and four `held_anchor_binding_unqualified` outcomes. Provider-declared names, counts and scalar dates are operator evidence only. They do not establish exact publisher-product/card bindings, Japanese initial-release dates, physical region or variant identity. SMH's exact linked news document remains absent; its yearless family-page marker cannot supply a date.

This stage changes no runtime contract, manifest or database. The frontend session should keep the stage3 contract and existing IDs; it has no new integration work. Do not present provider-header dates as card release dates, propagate captions to adjacent coordinates or infer Korean SKU coverage from header names. All65 holds and all-false display, offer and purchase claims remain in force. Buy&Ship remains the intended MoR; Pivota does not hold customer funds.

## Stage6: exact-anchor field evidence supplement

The offline `scripts.build_anchor_qualification_fields` artifact adds four source-bound illustrator/Pokédex/rarity-identifier checks for the same existing anchors. It changes no runtime response, manifest, database or frontend contract. PTCG derives from the publisher, so literal agreement is dependent evidence. LL's legacy rarity icon remains unnormalized. These records cannot supply a product date, physical variant, offer join or display permission, and cannot propagate across language, collector-number or artwork matches. Continue using stage3's contract and existing held statuses; there is no frontend integration change.
