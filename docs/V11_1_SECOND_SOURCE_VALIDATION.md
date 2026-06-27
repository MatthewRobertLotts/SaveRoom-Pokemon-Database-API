# v11.1 Second-Source Validation — Market Evidence Next

Tags: #type/project #status/needs-review

Status: VALIDATED_WITH_ACCESS_BLOCKERS
Date: 2026-06-27
Branch: v11.1-market-evidence-next
Commit: 97f7bde

## Overview

This document validates candidate second sources for v11.1 Second-Source Comparison & Cross-Source Confidence. No signup, spend, secret storage, paid-credit usage, aggressive scraping, or adapter implementation was performed.

## Validation Rules Applied

- Do not sign up for anything.
- Do not spend money.
- Do not use paid API credits.
- Do not store secrets.
- Do not scrape aggressively.
- Do not build an adapter yet.
- Do not fake source access.
- If a key-required source is not safely usable now, mark it blocked/pending access.

Credential presence was checked only as yes/no in the current shell. Values were not read or stored. Because several sources may consume paid quota per call, authenticated source calls were not made during this validation.

## Summary Decision

Recommended option: **D. Do source-access procurement first**.

Reason: no candidate was proven to satisfy all required criteria at once: accessible now, legally/cache-safe enough, distinct enough from TCGdex, useful for confidence, and matchable to v10 identity without major schema rewrite.

## Candidate 1 — JustTCG

| Criterion | Validation |
|---|---|
| Reachable now? | Public docs reachable. Unauthenticated API probe to `https://api.justtcg.com/v1/games` returned HTTP 401 with `API key is required`. |
| API key required? | Yes. Docs require `x-api-key`; SDK reads `JUSTTCG_API_KEY`. |
| Free or paid? | Public site says free tier/no credit card for evaluation, but docs also say sign up and subscribe to a plan. Plan/credit behavior must be confirmed before use. |
| Terms/caching risk? | Unknown from quick docs. Must confirm commercial use, cache retention, and whether storing raw payloads is allowed. |
| Pricing type | Market/pricing API; public copy emphasizes real-time pricing, condition-specific pricing, variants, historical data. Not validated as sold-comps. |
| Condition-specific? | Yes per public product pages/blog copy. |
| Finish-specific? | Yes/likely; public copy says printing/variant tracking and condition/printing parameters. |
| Currency | Not fully validated. Likely source-dependent; needs authenticated response samples. |
| Region | Multi-TCG/global service; Pokémon supported. Region/provider detail needs authenticated samples. |
| Rate limits? | Not validated without account/plan. Public examples include `api_calls_used`/`api_calls_remaining`. |
| Data shape | REST JSON. Example shape includes cards with `id`, `name`, `game`, `set`, `number`, `rarity`, `tcgplayerId`, `details`, `variants`, and `meta.api_calls_remaining`. |
| Identity matching viability with v10 | Potentially good if Pokémon responses expose set and collector number consistently; strongest if TCGplayer IDs align with existing v10 external refs. Needs sample payloads. |
| Development risk | Medium. Adapter shape likely fits existing framework, but auth, pagination, limits, and exact Pokémon payload shape are unverified. |
| Commercial risk | Medium until plan, terms, and caching are confirmed. |
| Recommendation | Strong candidate after access/terms procurement. Do not proceed until an approved key/plan is confirmed and sample payloads can be captured without paid-credit risk. |

Evidence:

- `https://justtcg.com/docs` — base URL, auth header, API key requirement.
- `https://justtcg.com` — public claims for condition-specific prices, variants, bulk lookup, free evaluation tier.
- Local probe: HTTP 401 without key.

## Candidate 2 — Cardmarket Direct API

| Criterion | Validation |
|---|---|
| Reachable now? | Public docs reachable. Unauthenticated priceguide probe returned HTTP 403. |
| API key required? | Yes. Official docs require authentication. |
| Free or paid? | API access is restricted; public help page says Cardmarket is currently not accepting API access applications. |
| Terms/caching risk? | High until access terms are reviewed. Credentials can act on account/stock; sharing restrictions are explicit. Priceguide endpoint is restricted. |
| Pricing type | Price guide fields include average sell price, low, trend, low EX+, AVG1/7/30, foil sell/low/trend/AVG1/7/30. |
| Condition-specific? | Partial. `Low Price Ex+` exists; full condition-specific ladders not evident from priceguide fields. |
| Finish-specific? | Yes for non-foil/foil buckets in priceguide fields. |
| Currency | EUR. |
| Region | Europe/Cardmarket. |
| Rate limits? | Priceguide file updated daily; docs warn 429 if requested more frequently. |
| Data shape | Base64-encoded gzipped CSV via API response; fields keyed by `idProduct`. |
| Identity matching viability with v10 | Potentially good only if `idProduct` or set/collector mapping exists in v10 external refs. Otherwise needs product-ID mapping work. |
| Development risk | Medium/high. OAuth/signing + restricted endpoint + product-ID mapping. |
| Commercial risk | High until access, permissions, and caching rights are confirmed. |
| Recommendation | Do not build now. Procurement/permission first. If approved, implement as a daily guide-price source, not a general live query adapter. |

Evidence:

- `https://help.cardmarket.com/en/cardmarket-api` — official access notice: applications currently not accepted; credential sharing warning.
- `https://api.cardmarket.com/ws/documentation/API_2.0:PriceGuide` — priceguide endpoint, restricted access, daily update, 429 warning, CSV fields.
- Local probe: HTTP 403 without auth.

## Candidate 3 — eBay Sold/Completed Source

| Criterion | Validation |
|---|---|
| Reachable now? | Official Browse API docs reachable; unauthenticated API probe returned HTTP 403/error page. Third-party sold-comps docs/providers reachable. |
| API key required? | Yes. Official Browse requires OAuth bearer token. RapidAPI/Apify sold-comps providers require provider keys/subscription. |
| Free or paid? | Official developer access may be free but requires app credentials/OAuth; sold-comps providers are paid or quota-based. Apify example pricing: from $4/1,000 results. RapidAPI provider requires a RapidAPI key/plan. |
| Terms/caching risk? | High. Official API is active listing search, not clearly sold-comps. Third-party sold-comps are scraping/provider products; terms and caching must be reviewed. |
| Pricing type | Sold/completed for third-party sold-comps providers; active listing for official Browse API search. |
| Condition-specific? | Sold providers include condition/condition ID. Official Browse supports condition filters and item condition fields. |
| Finish-specific? | Not structured for Pokémon finishes; finish usually inferred from title/aspects, so noisy. |
| Currency | Marketplace-specific: USD, GBP, EUR, CAD, AUD, etc. |
| Region | Marketplace-specific; eBay US/UK/EU/etc. |
| Rate limits? | Provider-specific. Official Browse has OAuth and API limits; third-party providers have plan/result limits. |
| Data shape | Sold-comps APIs return title, URL/item ID, sale price, currency, condition, buying format, sold date, shipping, seller/category fields, and aggregate stats. |
| Identity matching viability with v10 | Low/medium. Keyword/title matching can use card name, set, collector number, and category, but false positives are likely. Needs a title parser/review layer before aggregate confidence. |
| Development risk | High for v11.1 first adapter because identity matching and noise filtering are harder than structured set/number APIs. |
| Commercial risk | High due paid-provider/scraping/caching uncertainty. |
| Recommendation | Valuable later for sold-comps validation, especially graded/slab market evidence, but not first v11.1 adapter unless source-access and caching terms are approved and matching is scoped to small reviewed samples. |

Evidence:

- `https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search` — official Browse search requires OAuth bearer token and returns item summaries; default is fixed-price active listings.
- `https://github.com/colindaniels/eBay-sold-items-documentation` — RapidAPI completed-items provider shape and site IDs.
- `https://apify.com/caffein.dev/ebay-sold-listings` — paid sold-listings actor, sold-only claims, output fields.
- Local probe: official Browse API returned HTTP 403 without auth.

## Candidate 4 — PokéWallet API

| Criterion | Validation |
|---|---|
| Reachable now? | Yes for public endpoints. `https://api.pokewallet.io/health` returned HTTP 200 healthy; root metadata returned HTTP 200. Authenticated data endpoints were not called. |
| API key required? | Yes for search/cards/sets and most useful data endpoints. |
| Free or paid? | Free plan advertised at 100/hour and 1,000/day; paid Pro at higher limits. Requires account/key. |
| Terms/caching risk? | Unknown. Must confirm commercial backend use and raw-payload cache permission. |
| Pricing type | Real-time pricing from TCGPlayer and CardMarket per docs; Pro endpoints may include historical/statistical data. |
| Condition-specific? | Public docs describe variant models more than condition ladders; must validate with payload samples. |
| Finish-specific? | Yes/partial: TCGPlayer subtype names and CardMarket normal/holo variant types. |
| Currency | USD/EUR likely via TCGPlayer/CardMarket. |
| Region | North America and Europe via underlying providers; CardMarket-only records include Japanese/European promos per docs. |
| Rate limits? | Free: 100/hour, 1,000/day; response headers document remaining limits. |
| Data shape | REST JSON. IDs are `pk_` hashes for TCG/TCGPlayer cards and bare hashes for CardMarket-only cards. Search/card endpoints require key. |
| Identity matching viability with v10 | Medium. It may expose source-specific IDs and set/card fields, but custom hashed IDs require mapping. Useful if set code/number and source IDs are returned consistently. |
| Development risk | Medium. Structured API, but identity mapping and source independence from TCGdex need validation. |
| Commercial risk | Medium until terms and caching are confirmed. |
| Recommendation | Backup structured candidate after JustTCG, if access terms are clearer and sample payloads match v10 identity well. |

Evidence:

- `https://pokewallet.io/api-docs` — auth, free rate limits, ID formats, pricing providers, variant models.
- Local probe: `/health` HTTP 200 and root metadata HTTP 200; useful endpoints require key.

## Candidate 5 — CardMarket API / Pokemon API via RapidAPI

| Criterion | Validation |
|---|---|
| Reachable now? | Public landing pages reachable. Authenticated API not called. |
| API key required? | Yes, via RapidAPI. |
| Free or paid? | Public copy says “Try Free — 100 Requests/Day”; plan and credit use need confirmation. |
| Terms/caching risk? | Unknown/high until RapidAPI terms and provider terms are reviewed. It appears to aggregate Cardmarket, TCGPlayer, and eBay graded sold data. |
| Pricing type | Market/guide estimates, country-specific Cardmarket prices, TCGPlayer prices, graded eBay sold medians. |
| Condition-specific? | Some country-specific near-mint fields in examples; full condition support unclear. |
| Finish-specific? | Not fully validated. |
| Currency | EUR and USD in examples. |
| Region | EU/US, plus country-specific DE/FR/ES/IT. |
| Rate limits? | Plan-specific. Public free tier says 100/day. |
| Data shape | REST JSON with card, expansion, prices, graded, eBay, TCGPlayer, artist/image fields in examples. |
| Identity matching viability with v10 | Medium if set code/card number fields are stable; custom provider IDs need mapping. |
| Development risk | Medium, but source may overlap heavily with TCGdex and may add a provider dependency rather than independent evidence. |
| Commercial risk | Medium/high until terms are reviewed. |
| Recommendation | Not first choice. Treat as procurement candidate only if JustTCG/PokéWallet are unsuitable. |

Evidence:

- `https://www.cardmarket-api.com` — public feature and sample response summary.

## Candidate 6 — TCGplayer Direct API

| Criterion | Validation |
|---|---|
| Reachable now? | Public help/docs reachable through web search; authenticated API not probed. |
| API key required? | Yes. Current shell indicates a TCGplayer key variable exists, but it was not used. |
| Free or paid? | Requires TCGplayer API/partner access; terms must be confirmed. |
| Terms/caching risk? | Medium/high. TCGplayer pricing data is commercially licensed; cache/redistribution terms need explicit review. |
| Pricing type | Market price, low/mid/high/direct-style fields depending endpoint/product. |
| Condition-specific? | TCGplayer SKU/product model may support condition/printing details; not validated here. |
| Finish-specific? | Yes through product/SKU variant model where mapped. |
| Currency | USD. |
| Region | North America/TCGplayer. |
| Rate limits? | Not validated. |
| Data shape | REST API; exact modern payload not validated in this preflight. |
| Identity matching viability with v10 | Potentially high if v10 external references include TCGplayer product/SKU IDs; otherwise requires mapping. |
| Development risk | Medium. Good structured source, but likely overlaps with TCGdex's TCGPlayer market feed. |
| Commercial risk | Medium/high until API terms and cache rights are confirmed. |
| Recommendation | Consider only after confirming rights; less distinct from current TCGdex evidence than a genuinely independent sold-comps source. |

Evidence:

- Public TCGplayer help indicates API/partner access for pricing data.
- No authenticated calls made.

## Decision Rule Applied

Pick a second source only if it is:

1. accessible now;
2. legally/cache-safe enough;
3. distinct from TCGdex;
4. useful for confidence;
5. matchable to v10 identity without major schema rewrite.

No candidate cleared all five gates during this validation.

## Recommended Implementation Path

**D. Do source-access procurement first.**

Procurement checklist:

1. Pick one structured source to evaluate first, preferably JustTCG.
2. Confirm account/plan may be used for backend development without paid-credit surprises.
3. Confirm commercial use and cache/retention rights for raw payloads and normalized observations.
4. Capture 10-20 approved sample payloads for cards with known v10 canonical printings, including normal, holo, reverse-holo, modern, vintage, promo, and Japanese cases.
5. Confirm fields for set identity, collector number, language, finish/printing, condition, currency, timestamp, marketplace, and source record ID.
6. Only then build a source-neutral adapter and cross-source confidence tests.

## Next Exact Implementation Step

Do not build an adapter yet. The next implementation-enabling step is an access/terms checkpoint: choose JustTCG as the first procurement target, verify permitted API use/caching and quota/credit behavior, then collect approved fixture payloads for a fixture-only adapter spike.

## Links

- Related: `docs/V11_1_PREFLIGHT.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Related: `docs/V11_MARKET_EVIDENCE_MODEL.md`
- Related: `docs/V11_SOURCE_VALIDATION.md`
- JustTCG docs: https://justtcg.com/docs
- Cardmarket API help: https://help.cardmarket.com/en/cardmarket-api
- Cardmarket priceguide docs: https://api.cardmarket.com/ws/documentation/API_2.0:PriceGuide
- eBay Browse API search docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
- PokéWallet docs: https://pokewallet.io/api-docs
- TCGdex markets docs: https://tcgdex.dev/markets-prices
