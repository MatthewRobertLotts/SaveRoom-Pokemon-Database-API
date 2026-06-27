# v11 Quality Report

Tags: #type/project #status/needs-review
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

Quality assessment of v11.0 Market Evidence Foundation.

## Test Results

```text
v11 market evidence migrations:     21 passed
v11 price adapter framework:         24 passed
v11 tcgdex adapter:                   16 passed
v11 price matching confidence:       20 passed
v11 price aggregation:               20 passed
v11 price API:                       12 passed
                                   --------
Total v11 tests:                    113 passed

v10 identity (critical):             65 passed
v9.2 regression (critical):          33 passed
v8 pricing:                          passed
API contract v1:                     passed
```

## Pipeline Status

| Stage | Status | Notes |
|-------|--------|-------|
| Source adapter (TCGdex) | Working | Free, keyless, fast |
| Raw response cache | Working | Full JSON stored in v11_price_source_cache |
| Normalisation | Working | TCGPlayer + Cardmarket → observations |
| Identity matching | Working | set_code + collector_number → canonical printing |
| Confidence scoring | Working | HIGH/MEDIUM/LOW/UNUSABLE |
| Aggregation | Working | Median, low, high, count, freshness |
| API endpoints | Working | 6 endpoints, read-only + refresh |
| Admin UI | **NOT IMPLEMENTED** | Backend-only, API available |

## Known Limitations

1. **Finish ambiguity** — 90.4% of v10 variants have `finish = 'unknown'`. TCGdex provides variant-level pricing (normal/reverse/holo) but matching to v10's finish model is imperfect. Aggregates from ambiguous finish get `confidence_label = LOW`.

2. **No condition data** — TCGdex provides market-level pricing only. Cannot distinguish Mint vs Played prices.

3. **No sold prices** — TCGdex provides active listing market prices, not confirmed sold data.

4. **Single source** — v11.0 implements only TCGdex. No cross-validation between sources.

5. **No admin UI** — Backend pipeline is complete but the thin admin UI is deferred.

6. **TCGPlayer lowPrice is unreliable** — The lowest listed price can be an outlier. We store it but prefer `marketPrice` for aggregates.

## What v11.0 Does NOT Do

- Not pricing-complete (one source, no finish enrichment)
- Not scanner-ready (scanner is a separate workstream)
- Not marketplace-ready (no listing automation)
- Not POS-ready (no checkout flow)
- Not billing-ready (no payment processing)
- Not public SaaS (no developer portal)

## Links

- Related: [[V11_PREFLIGHT]]
- Related: [[V11_RELEASE]]
