# v12 Pricing Strategy Correction

Tags: #type/project #status/needs-review

Status: DRAFT
Date: 2026-06-28
Branch: v12-app-readiness-next
Supersedes: v11.x procurement-centric pricing assumptions

## Overview

This document corrects the pricing strategy direction for the SaveRoom Pokémon Card Database platform. The correction applies immediately to all v12 planning and supersedes any prior implied strategy where JustTCG or SaveRoom first-party sales were treated as the core pricing source.

## Why the strategy is being corrected

v11.x planning treated JustTCG as the preferred procurement target and assumed its USD market pricing could feed directly into UK pricing outputs. This was a pragmatic second-source comparison choice for cross-source confidence scoring, but it was never explicitly elevated to "core UK pricing source." The ambiguity needs correcting because:

1. **JustTCG is USD-only.** UK customers, UK market focus, and UK sold/completed evidence require GBP. USD evidence cannot be presented as UK sold-market value without explicit FX conversion and labelling.
2. **JustTCG is market/active-listing pricing, not sold/completed evidence.** It is analogous to TCGplayer marketPrice — useful for trends and sanity checks, but not a substitute for sold-completed market evidence.
3. **SaveRoom is building a commercial API.** The platform's pricing outputs will be consumed by scanner apps, POS systems, inventory tools, listing assistants, and external developer APIs. These consumers need a clear, regionally-anchored headline price with explicit provenance — not a blind average of mixed-region sources.
4. **The UK market is the primary commercial focus.** SaveRoom is UK-based. UK eBay sold/completed evidence in GBP is the most defensible headline market estimate for UK customers.

## External-only pricing rule

All pricing evidence must come from approved external sources. No internal SaveRoom data is used as market pricing evidence.

## SaveRoom sales exclusion rule

SaveRoom first-party sales data is excluded from market pricing until a future marketplace product exists and is explicitly modelled as a separate first-party marketplace signal.

This means:

- SaveRoom Whatnot/shop sales records are never used as market pricing evidence.
- SaveRoom sales are commercial inventory movement, not market price discovery.
- If a future marketplace product is built, its first-party sales may become a separate data source — but only then, and only when explicitly modelled as first-party marketplace evidence with clear separation from external market evidence.

## UK-first pricing USP

The core USP is UK-first external pricing intelligence anchored on UK sold/completed market evidence.

This means:

- Headline UK market estimate is always GBP.
- Primary evidence source is UK sold/completed external data (eBay UK as the canonical first source).
- Non-UK evidence is only used as fallback, sanity check, trend indicator, or thin-market support — never as the headline UK price.
- Every estimate carries explicit source breakdown, confidence, and warnings.

## Source hierarchy

| Tier | Source | Role | Currency | Region |
|------|--------|------|----------|--------|
| 1 | eBay UK sold/completed | Headline UK market estimate | GBP | UK |
| 2 | Other UK/EU external evidence | Support or challenge UK estimate | GBP/EUR | UK/EU |
| 3 | USD/global providers (JustTCG, TCGplayer) | Fallback, sanity check, trend, thin-market | USD | Global |
| 4 | Active listings | Weak evidence only | Any | Any |

Tier 1 is the headline. Tiers 2-4 support, challenge, or fill gaps — they do not replace Tier 1.

## JustTCG role after correction

JustTCG is:

- A **technically useful** external pricing source with good schema fit.
- A **stable UUID/variant mapping source** with tcgplayerId cross-referencing.
- A **USD external market/current pricing provider** useful for trend/sanity/thin-market support.
- A **fallback provider** when UK sold evidence is thin or absent.
- A **mapping source** for cross-referencing between TCGplayer and TCGdex identifiers.

JustTCG is **not**:

- The core UK pricing source.
- UK sold-market evidence.
- A replacement for eBay UK sold/completed data.
- A source whose USD output can be used as GBP without explicit FX conversion.

## Currency and region rules

1. **No currency mixing without explicit FX conversion.** A USD price must never appear in a GBP field without conversion and labelling.
2. **Converted evidence must be labelled.** Any price converted from USD to GBP must carry `fx_rate_source`, `fx_rate_timestamp`, and `original_currency` fields.
3. **USD-only JustTCG data requires explicit FX conversion before it can contribute to a GBP fallback estimate.** Converted USD evidence must be labelled as converted external evidence, not UK sold evidence.
4. **Active listings are not sold prices.** Any listing-only price must be explicitly typed as `listing` or `market_estimate`, never as `sold` or `market_value`.
5. **Every estimate must include source breakdown, confidence, and warnings.**

## Why blind averaging is forbidden

Blind averaging across sources with different currencies, regions, price types (sold vs listing vs market), and evidence quality produces a meaningless number. A USD active listing averaged with a GBP sold-completed price does not produce a "confident UK price" — it produces an unlabelled mixed-source number that cannot be defended to a commercial customer.

Instead:

- Each source tier is weighted explicitly.
- The headline price always reflects the highest-tier available evidence.
- Lower-tier evidence modifies confidence, provides sanity flags, or fills gaps — it does not blindly average into the headline.

## Future marketplace-data separation

If SaveRoom builds a marketplace product in the future, first-party marketplace sales data must be:

- Modelled as a **separate data source** with explicit `source_type: "first_party_marketplace"`.
- Kept distinct from external market evidence in storage, API responses, and aggregation logic.
- Never silently merged into external market pricing estimates.
- Clearly attributed in every API response that includes it.

## What this means for v12

v12 planning assumes:

- UK-first external pricing as the platform USP.
- eBay UK sold/completed as the primary target source (planned, not live).
- JustTCG as a supporting/fallback provider (terms approved 2026-06-29 with API resale restriction; adapter implementation unblocked for SaveRoom ecosystem apps).
- Cardmarket and TCGplayer as additional supporting/fallback providers (blocked pending access).
- No live provider adapters in v12 slice 0.
- App-readiness work proceeds using the corrected pricing summary shape, with placeholder structure for future live data.

## Links

- Related: `docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
