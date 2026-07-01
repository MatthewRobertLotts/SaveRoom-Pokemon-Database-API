# v12 UK-First External Pricing Plan

Tags: #type/project #status/needs-review

Status: DRAFT — proposed v12 shape, not implemented yet
Date: 2026-06-28
Branch: v12-app-readiness-next
Supersedes: v11.x JustTCG-centric procurement assumptions

## Overview

This document defines the concrete pricing hierarchy, estimate outputs, and rules for the UK-first external pricing strategy. It is a planning document — no live provider calls are made.

## Pricing source hierarchy

### Tier 1 — eBay UK sold/completed, GBP, external evidence

Headline UK market estimate when enough clean evidence exists.

- Source: eBay UK sold/completed listings (external, not SaveRoom data).
- Currency: GBP.
- Region: UK.
- Price type: sold/completed.
- Use: headline `uk_market_estimate_gbp`.
- Status: **planned, not live.** Requires approved access to eBay sold/completed data (via provider or official API).

### Tier 2 — other UK/EU external evidence

Supports or challenges the UK estimate.

- Sources: Cardmarket (EUR/GBP), UK-based TCG marketplaces, other UK/EU sold-completed providers.
- Currency: GBP or EUR (with explicit FX conversion if EUR).
- Region: UK/EU.
- Price type: sold/completed or verified market transactions.
- Use: corroboration, confidence adjustment, cross-validation.
- Status: **planned, not live.** Cardmarket direct API not currently accepting applications.

### Tier 3 — USD/global providers (JustTCG, TCGplayer)

Fallback, sanity check, trend and thin-market support only.

- Sources: JustTCG (USD), TCGplayer (USD), other approved global providers.
- Currency: USD — requires explicit FX conversion before contributing to GBP estimates.
- Region: global/US.
- Price type: market price / active listing / guide price (not sold).
- Use: fallback estimate, trend direction, thin-market coverage, identifier mapping.
- Status: **JustTCG terms approved (2026-06-29) with restriction.** All permissions confirmed (cache/fixtures/storage/display). **Critical restriction:** JustTCG-derived pricing must NOT be exposed via standalone external developer API. SaveRoom ecosystem apps only. Live adapter unblocked after API key + env flags.

### Tier 4 — active listings

Weak evidence only. Never treated as sold-market value.

- Sources: any provider exposing active listing data.
- Currency: as reported, with conversion.
- Region: as reported.
- Price type: `listing` only.
- Use: sanity check, market availability signal.
- Status: **explicitly typed, never merged into sold/market value.**

## Required estimate outputs

Every pricing response from the v12 API must include:

| Field | Type | Description |
|---|---|---|
| `uk_market_estimate_gbp` | decimal \| null | Headline UK market estimate in GBP (Tier 1) |
| `fallback_estimate_gbp` | decimal \| null | Best fallback estimate when Tier 1 unavailable (Tier 2-3, converted) |
| `global_market_estimate` | object \| null | Best global estimate with source and currency |
| `source_breakdown` | array | Per-source contribution with tier, currency, price_type, timestamp |
| `confidence` | enum | HIGH / MEDIUM / LOW / NONE based on evidence quality and tier |
| `warnings` | array | Human-readable warnings (currency conversion, listing-only, thin evidence) |
| `evidence_count` | integer | Number of evidence records behind this estimate |
| `price_type` | string | `sold` / `market` / `listing` / `guide` / `unknown` |
| `currency` | string | ISO 4217 (GBP, USD, EUR) |
| `region` | string | ISO region or market identifier |
| `fx_rate_source` | string \| null | Source of FX rate used (e.g., "ecb", "xe.com", "fixed") |
| `fx_rate_timestamp` | string \| null | ISO timestamp of FX rate |
| `last_updated` | string | ISO timestamp of estimate computation |

## Rules

1. **No SaveRoom sales data.** First-party sales are never used as market pricing evidence.
2. **No blind averaging.** Sources are weighted by tier and evidence quality, not averaged.
3. **No currency mixing without explicit FX conversion.** USD must be explicitly converted to GBP before appearing in a GBP field.
4. **No USD price treated as UK sold value.** USD evidence is always labelled as converted external evidence.
5. **No active listing treated as sold price.** Listings are typed as `listing` and used only as weak evidence.
6. **Every estimate must include source breakdown, confidence and warnings.**
7. **Tier 1 is the headline.** When Tier 1 evidence exists, it drives the primary estimate. Lower tiers modify confidence and provide sanity.
8. **When Tier 1 is absent, the fallback is explicitly labelled.** A GBP estimate derived from USD evidence must carry conversion metadata and a warning.

## Example API response (proposed v12 shape)

```json
{
  "card_id": "cp-501e65fd75e0",
  "uk_market_estimate_gbp": 2.50,
  "fallback_estimate_gbp": 2.30,
  "global_market_estimate": {
    "amount": 3.10,
    "currency": "USD",
    "source": "justtcg",
    "price_type": "market"
  },
  "source_breakdown": [
    {
      "tier": 1,
      "source": "ebay_uk",
      "currency": "GBP",
      "price_type": "sold",
      "evidence_count": 8,
      "median": "2026-06-25T10:00:00Z",
      "median_gbp": 2.50,
      "low_gbp": 1.80,
      "high_gbp": 3.20
    },
    {
      "tier": 3,
      "source": "justtcg",
      "currency": "USD",
      "price_type": "market",
      "amount": 3.10,
      "converted_gbp": 2.46,
      "fx_rate": 0.7935,
      "fx_rate_source": "ecb",
      "fx_rate_timestamp": "2026-06-28T00:00:00Z"
    }
  ],
  "confidence": "MEDIUM",
  "warnings": [
    "Primary estimate based on 8 eBay UK sold-completed records."
  ],
  "evidence_count": 9,
  "price_type": "sold",
  "currency": "GBP",
  "region": "UK",
  "fx_rate_source": null,
  "fx_rate_timestamp": null,
  "last_updated": "2026-06-28T12:00:00Z"
}
```

This is a **proposed v12 shape** — not implemented yet. Field names may change during implementation.

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
