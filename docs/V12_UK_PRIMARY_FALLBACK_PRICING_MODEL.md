# v12 UK-Primary Fallback Pricing Model

Tags: #type/project #status/needs-review

Status: IMPLEMENTED PURE LOGIC + PRICES ENDPOINT LOCAL-UK WIRING
Date: 2026-06-30
Branch: v12-app-readiness-next
Target release: v12.0.0

## Terminology

Use **v12 milestones**, not “v12 slices”. Earlier references to “slices” meant small implementation chunks inside the larger v12.0.0 app-readiness release. They are not separate versions.

## Purpose

This document defines the pricing recommendation foundation for v12. The first implementation added deterministic calculation logic only. The current v12 milestone wires that pure model into `GET /api/v1/prices/cards/{card_key:path}` using existing local UK/GBP evidence only: no DB migrations, no live provider calls, no new provider fetching, no environment reads for recommendation calculation, and no API credits.

The model exists so listing assistant, scanner, POS, inventory, and API consumers can use a safe UK-primary pricing recommendation instead of blindly mixing UK sold evidence with foreign/global reference prices.

## Source hierarchy

| Tier | Source class | Currency basis | Role |
|---:|---|---|---|
| 1 | UK eBay sold/completed evidence | GBP | Primary UK market value |
| 2 | Other UK marketplace sold evidence | GBP | Later UK support source |
| 3 | Cardmarket/EU evidence | Converted to GBP and UK-adjusted | EU fallback/reference |
| 4 | TotalTCG / JustTCG / TCGplayer USD/global market prices | Converted to GBP and UK-adjusted | Global fallback/reference |
| 5 | Active listings | Reference only | Weak sanity/reference, never primary sold value |

## Truth rules

The system must never:

- label TotalTCG / JustTCG / TCGplayer as UK sold evidence;
- treat USD/global market price as real UK sold price;
- overwrite strong UK sold evidence with fallback data;
- blindly average all sources together;
- expose restricted provider-derived pricing through external developer API responses.

`primary_uk_price` is pure UK sold/completed evidence only. Fallback/reference providers may influence `general_market_estimate` and `recommended_listing_price`, but they must not populate or overwrite `primary_uk_price`.

## Provider classification

TotalTCG and JustTCG are treated as separate providers, not aliases. They may share the provider family:

```text
provider_family = global_market_reference
```

They remain separate because terms, API shape, coverage, reliability, identity matching, and exposure policy can differ.

Current classification:

| Provider | Family | Default tier | UK sold evidence? | Notes |
|---|---|---:|---|---|
| `ebay_uk` / `uk_ebay_sold` | `uk_sold_completed` | 1 | Yes | Primary UK evidence |
| `cardmarket` | `eu_market_reference` | 3 | No | Converted to GBP and UK-adjusted |
| `totaltcg` | `global_market_reference` | 4 | No | Separate provider from JustTCG |
| `justtcg` | `global_market_reference` | 4 | No | SaveRoom ecosystem apps only; no standalone external developer pricing API resale |
| `tcgplayer` | `global_market_reference` | 4 | No | USD/global reference |
| unknown/active listing sources | `unknown_reference` | 5 | No | Reference only |

## UK adjustment multiplier

Fallback/global prices are first converted to GBP, then UK-adjusted.

Formula:

```text
uk_adjustment_multiplier = UK sold median GBP / foreign converted median GBP
uk_adjusted_fallback = converted_price_gbp × uk_adjustment_multiplier
```

Example:

```text
Foreign market price: $20
FX converted: £15.80
Comparable UK sold median: £18.64
Multiplier: 18.64 / 15.80 = 1.18
UK-adjusted fallback: £15.80 × 1.18 = £18.64
```

Multiplier preference order:

1. `exact_card`
2. `set`
3. `era_block`
4. `rarity`
5. `language`
6. `provider_global`
7. `default_conservative`

Every fallback calculation records:

```text
adjustment_multiplier
adjustment_multiplier_level
adjustment_multiplier_sample_size
adjustment_basis
```

Default conservative multiplier is `1.00` unless a stronger learned multiplier is supplied.

## Evidence strength

Initial v12 milestone bands:

| UK sold/completed count | Strength |
|---:|---|
| 10+ | `strong` |
| 5–9 | `medium` |
| 1–4 | `thin` |
| 0 | `none` |

Freshness is accepted by the pure function signature for future use but does not alter the first milestone bands yet.

## Blend rules

| UK evidence strength | Blend |
|---|---|
| Strong UK | 100% UK, 0% fallback |
| Medium UK | 80% UK, 20% adjusted fallback |
| Thin UK | 60% UK, 40% adjusted fallback |
| No UK | 0% UK, 100% adjusted fallback, confidence low/very low |

Important distinction:

```text
primary_uk_price = pure UK evidence only
general_market_estimate = source-aware blend
recommended_listing_price = strategy-adjusted marketplace recommendation
```

## Listing strategy

`recommended_listing_price` supports deterministic strategy adjustment:

| Strategy | Behaviour |
|---|---:|
| `conservative` | `general_market_estimate × 0.90` |
| `balanced` | `general_market_estimate × 1.00` |
| `premium` | `general_market_estimate × 1.10` |

Values are rounded to two decimal places. The calculation method records the blend and strategy.

## Confidence rules

Initial labels:

| Situation | Confidence |
|---|---|
| Strong UK sold/completed evidence | `high` |
| Medium UK sold/completed evidence | `medium` |
| Thin UK sold/completed evidence | `low` |
| No UK evidence with learned UK-adjusted fallback | `low` |
| No UK evidence with default conservative fallback | `very_low` |
| No usable evidence | `none` |

Warnings explicitly state when fallback/global data influenced the recommendation and when a source is not UK sold evidence.

## Output shape

The pure recommendation object is designed to serialize with fields:

```text
currency
region_basis
primary_uk_price
uk_adjusted_fallback_price
general_market_estimate
recommended_listing_price
source_breakdown
evidence_count
uk_evidence_strength
confidence
confidence_score
confidence_reasons
warnings
calculation_method
adjustment_multiplier
adjustment_multiplier_level
adjustment_multiplier_sample_size
adjustment_basis
provider_status_summary
```

## Prices endpoint wiring milestone

`GET /api/v1/prices/cards/{card_key:path}` now includes a `data.recommendation` section. This milestone uses only the existing local GBP price summary fields:

```text
raw_median
recommended_raw_count
evidence_count
raw_min
raw_max
latest_fetched_at
source
currency
```

Mapping:

```text
primary_uk_price.amount = raw_median when recommended/local UK evidence exists
primary_uk_price.currency = GBP
primary_uk_price.evidence_count = recommended_raw_count, falling back to evidence_count only when raw_median exists
primary_uk_price.source_type = local_uk_evidence
general_market_estimate = primary_uk_price for this local-only milestone
recommended_listing_price = balanced general_market_estimate
uk_adjusted_fallback_price = null
adjustment_multiplier fields = null
```

JustTCG provider status may remain visible as metadata, but JustTCG USD pricing is not used in the recommendation. `_get_justtcg_price_data()` is not called by the recommendation builder. Fallback provider blending remains a future v12 milestone.
## How listing assistant should consume this later

The listing assistant should not implement its own pricing model. It should consume:

```text
recommended_listing_price
confidence
warnings
source_breakdown
region_basis
calculation_method
```

Application guidance:

| Consumer | Field to prefer |
|---|---|
| Scanner app | `general_market_estimate` with confidence/warnings |
| POS system | `recommended_listing_price` with confidence warning |
| Inventory desktop app | `primary_uk_price`, `general_market_estimate`, and source breakdown |
| Listing assistant | `recommended_listing_price` and warnings |
| External developer API | only fields allowed by source exposure policy; restricted provider-derived pricing must be redacted |

## Implementation boundary

Implemented module:

```text
pricing_sources/uk_pricing_model.py
```

Implemented tests:

```text
tests/test_v12_uk_pricing_model.py
tests/test_v12_prices_endpoint_recommendation_model.py
```

This milestone wires the model into the prices endpoint using local UK evidence only. It does not add DB migrations and does not call live providers for recommendation calculation.

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
