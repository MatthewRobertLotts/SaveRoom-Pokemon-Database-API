# v11.1 Preflight — Second-Source Comparison & Cross-Source Confidence

Tags: #type/project #status/needs-review

Status: PREFLIGHT_COMPLETE
Date: 2026-06-27
Branch: v11.1-market-evidence-next
Commit: 97f7bde

## Overview

v11.1 should extend the v11.0 Market Evidence Foundation toward second-source comparison and cross-source confidence. This preflight confirms the branch, release baseline, image fallback patch state, existing pricing evidence architecture, candidate sources, risks, and the recommended implementation sequence before any adapter work begins.

## Current Repository State

- Current branch: `v11.1-market-evidence-next`.
- Current commit: `97f7bde ui: repair browser card image loading fallbacks`.
- Working tree at preflight start: clean.
- `v11.0.0` tag is on `384426c Merge v11 market evidence foundation`.
- `HEAD` is two commits after `v11.0.0`:
  - `8a85438 fix: prioritize card_key gateway path for image display`
  - `97f7bde ui: repair browser card image loading fallbacks`

## v11.0.0 Release State

v11.0.0 is complete, merged, tagged, and pushed. It delivered the Market Evidence Foundation on top of v10 canonical commercial identity:

- v10 canonical printings, commercial variants, and sellable SKUs remain the identity backbone.
- v11 added seven `v11_` market evidence tables via migrations v66-v72.
- v11 added a pricing source adapter framework under `pricing_sources/`.
- v11 added a TCGdex source adapter.
- v11 added matching, aggregation, cache, source health, refresh-run, API, and minimal admin UI surfaces.
- v11 is explicitly not pricing-complete: it is one-source, market-evidence-backed indicative valuation.

## Image Fallback Patch State

Image loading was repaired on this branch before this preflight.

- Relevant commit: `97f7bde ui: repair browser card image loading fallbacks`.
- Prior commit in same branch: `8a85438 fix: prioritize card_key gateway path for image display`.
- The fix is treated as done unless verification shows a regression.
- v11.1 should not modify image loading as part of second-source validation.

## Existing v11 Pricing Evidence Architecture

Current pipeline:

```text
pricing source adapter
  -> v11_price_source_cache
  -> v11_price_observations
  -> v11_price_observation_matches
  -> v11_price_aggregates
  -> /api/v1/prices/*
  -> browser admin evidence panel
```

Core framework file: `pricing_sources/base.py`.

Adapter contract:

- `source_code`
- `source_name`
- `capabilities()`
- `health_check()`
- `build_queries()`
- `fetch()`
- `normalise()`
- `match_observations()`

Important existing model choices:

- Sold, active listing, guide, market estimate, and sealed product evidence are separated by `listing_type`.
- Original currency is stored; v11.0 does not perform FX conversion.
- Raw payloads are cached for traceability.
- Aggregates penalize single-source evidence, thin observations, stale observations, unknown finish, and mixed currencies.
- Exact SKU confidence requires a high-confidence identity match and non-unknown finish.

## Existing TCGdex Source

TCGdex is the current first source.

- Source code: `tcgdex`.
- API: `https://api.tcgdex.net`.
- Authentication: none.
- Cost: free/keyless.
- Marketplaces exposed: TCGPlayer and Cardmarket.
- Currency: USD for TCGPlayer, EUR for Cardmarket.
- Pricing type: market/active-listing estimates, not raw individual sold comps.
- Finish awareness: normal, reverse-holo, holo where provider data has variants.
- Condition specificity: no.
- Existing adapter: `pricing_sources/tcgdex.py`.

## Existing v11 API and UI

Existing API routes under `/api/v1/prices`:

- `GET /api/v1/prices/sources`
- `GET /api/v1/prices/sources/{source_code}/health`
- `GET /api/v1/prices/observations`
- `GET /api/v1/prices/observations/{observation_id}`
- `GET /api/v1/prices/aggregate/{target_type}/{target_id}`
- `POST /api/v1/prices/refresh/{target_type}/{target_id}`

Existing UI:

- Minimal v11 evidence/admin panel inside the browser UI.
- Source health check button.
- Target evidence lookup.
- Aggregate display.
- Observation table.
- Manual refresh trigger.

No broad UI changes are part of this preflight.

## v11.1 Goal

```text
Second-Source Comparison & Cross-Source Confidence
```

The feature is not “add JustTCG”. The feature is to compare one or more independent evidence streams against the existing TCGdex-backed observations and turn agreement/disagreement into a safer confidence signal.

## Candidate Second Sources

Validation details are in `docs/V11_1_SECOND_SOURCE_VALIDATION.md`.

Shortlist:

1. JustTCG
2. Cardmarket direct API
3. eBay sold/completed source
4. PokéWallet API
5. CardMarket API / Pokemon API via RapidAPI
6. TCGplayer direct API

## Primary Risks

- Credential availability does not equal permitted use; terms, plan, caching, and paid-credit implications must be confirmed before adapter development.
- Sources that repackage TCGPlayer/Cardmarket may be useful for data-shape and condition detail, but may not be independent enough for true cross-source confidence.
- Sold-comps sources are useful but title/noise matching risk is much higher than structured set+number APIs.
- Cardmarket direct API access is restricted and applications are currently not generally accepted.
- eBay official Browse API is active-listing oriented; sold/completed data likely requires another product, partner access, or third-party providers.
- Existing v10 identity can match structured set/code/number data well, but keyword/title sold comps may require a separate evidence-review workflow to avoid false matches.
- Finish remains a major quality limiter; second-source comparison should not silently promote unknown-finish evidence to exact SKU pricing.

## Recommended Implementation Sequence

1. Complete source-access procurement before adapter implementation.
   - Confirm which keys/accounts may be used for development.
   - Confirm whether calls consume paid credits.
   - Confirm caching/retention terms in writing or source documentation.
2. Prefer a structured, set/number-capable source for the first v11.1 adapter.
   - First procurement target: JustTCG if its plan permits backend caching and commercial use.
   - Backup structured target: PokéWallet or another API with explicit free/commercial terms.
3. Implement a source-neutral comparison layer before source-specific UI expansion.
   - Do not hardcode “JustTCG comparison” into API/UI names.
   - Add source-pair agreement metrics at aggregate level.
4. Add one adapter behind an explicit disabled-by-default source registry row until credentials and terms are confirmed.
5. Add focused tests:
   - adapter capabilities/normalisation tests with fixtures only;
   - source registry and disabled-source behavior;
   - aggregate confidence improvement/penalty when two sources agree/disagree;
   - no mixing sold vs active vs guide buckets;
   - no SKU-exact confidence when finish is unknown.
6. Only after backend comparison works, add minimal admin evidence display for cross-source agreement/disagreement.

## Decision

Do source-access procurement first. No candidate was validated as both accessible now and safe to implement immediately without using credentials, spending credits, or making terms/caching assumptions.

## Links

- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Related: `docs/V11_MARKET_EVIDENCE_MODEL.md`
- Related: `docs/V11_PRICE_API.md`
- Related: `docs/V11_SOURCE_VALIDATION.md`
