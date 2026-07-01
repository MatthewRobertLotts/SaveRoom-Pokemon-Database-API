# v12 Pricing Source Exposure Policy

Tags: #type/project #status/implemented

Status: IMPLEMENTED
Date: 2026-06-29
Branch: v12-app-readiness-next

## Overview

A code-enforced policy guard that ensures JustTCG-derived pricing is allowed for SaveRoom-owned apps and tools but blocked from standalone external developer API responses, public pricing feeds, and competing third-party data products. The restriction is permanent and cannot be overridden by env flags.

## Motivation

JustTCG's final clarification allows SaveRoom-owned apps and tools to use JustTCG-derived pricing through the SaveRoom backend, including paid SaveRoom products. The key restriction remains: the SaveRoom backend must not expose a public standalone pricing API, data feed, or competing data product for third-party developers to fetch JustTCG-derived pricing.

This policy enforces that restriction in code — not just documentation.

## Module

```
pricing_sources/exposure_policy.py
```

## Surfaces

| Surface | Constant | Description |
|---|---|---|
| SaveRoom Internal | `SURFACE_SAVEROOM_INTERNAL` | Admin tools, internal scripts |
| SaveRoom Customer App | `SURFACE_SAVEROOM_CUSTOMER_APP` | Customer-facing app, web tracker |
| Internal Admin | `SURFACE_INTERNAL_ADMIN` | Internal admin UI/panel |
| Customer SaveRoom App | `SURFACE_CUSTOMER_SAVEROOM_APP` | Future customer-facing SaveRoom products |
| SaveRoom-Owned Paid Apps | `SURFACE_SAVEROOM_OWNED_PAID_APPS` | Scanner, POS, inventory desktop, web tracker, listing assistant, and other paid SaveRoom-owned apps |
| External Developer API | `SURFACE_EXTERNAL_DEVELOPER_API` | Third-party developer pricing API |
| Standalone Pricing API | `SURFACE_STANDALONE_PRICING_API` | Public standalone pricing API/data feed |

## Source rules

| Source | Internal/Admin | Customer SaveRoom App | SaveRoom-Owned Paid Apps | External Dev API | Standalone Pricing API |
|---|---|---|---|---|---|
| justtcg | ✅ allowed | ✅ allowed | ✅ allowed | ❌ **blocked/redacted** | ❌ **blocked** |
| tcgdex | ✅ | ✅ | ✅ | ✅ | ✅ |
| uk_ebay_sold | ✅ | ✅ | ✅ | ✅ | ✅ |
| ebay_uk / ebay_uk_sold | ✅ | ✅ | ✅ | ✅ | ✅ |
| cardmarket | ✅ | ✅ | ✅ | ✅ | ✅ |
| tcgplayer | ✅ | ✅ | ✅ | ✅ | ✅ |
| unknown source | ✅ | ✅ | ✅ | ❌ blocked (conservative) | ❌ blocked (conservative) |

## Key functions

### `can_expose_source(source_code, surface, field_type="pricing") -> bool`

Check whether a source's data can be exposed on a given surface.

### `filter_price_payload_for_surface(payload, surface) -> dict`

Filter a pricing payload for a surface. For external developer API, removes/redacts blocked source fields and adds warnings.

### `apply_pricing_exposure_policy(payload, surface) -> dict`

Main entry point for endpoint code. Alias for `filter_price_payload_for_surface`.

### `get_source_exposure_metadata(source_code) -> dict`

Return exposure metadata for a source (useful for provider_status responses).

## Redaction behaviour

For external developer API and standalone pricing API surfaces:
- Pricing fields (price, amount, median, low, high, primary_price, fallback_price, etc.) from blocked sources are set to `null`
- `source_breakdown` items from blocked sources are removed
- Source labels are suffixed with `_redacted_for_surface`
- A warning is added: "Some pricing fields were withheld because their source is not licensed for standalone external developer API resale."

For SaveRoom internal/admin/customer/owned-app surfaces:
- No filtering — all source labels and data pass through unchanged

## Permanent restriction

```python
JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED: bool = True
```

This constant is `True` and **must remain True**. It cannot be overridden by env flags or config. If JustTCG's terms change, this requires an explicit code change + test update + docs update.

## Integration with API responses

The `apply_pricing_exposure_policy()` function is the entry point for future integration:

```python
result = apply_pricing_exposure_policy(payload, SURFACE_SAVEROOM_INTERNAL)
```

For now, all v12 endpoints default to `SURFACE_SAVEROOM_INTERNAL`. External developer API mode must be explicitly requested and tested.

## Attribution

JustTCG-derived data shown in SaveRoom apps should include:
> "Pricing data provided by JustTCG"

Allowed attribution locations include About page, Settings page, Data sources page, and footer.

## Price semantics

JustTCG price fields should be labelled as **Market Price**.

JustTCG clarified this represents a volume-weighted average of completed marketplace sales. It must not be labelled as UK sold price, UK market price, active listing price, or live listing price.

Recommended internal names: `justtcg_market_price`, `provider_market_price`, `completed_sales_market_price`.

Avoid names: `uk_sold_price`, `uk_market_price`, `active_listing_price`, `listing_price`.

## Cancellation and retention

If the JustTCG subscription is cancelled, normalized and aggregate JustTCG-derived data already stored in the SaveRoom database may remain permanently. Live updates should stop after cancellation.

## Tests

```
tests/test_v12_pricing_source_exposure_policy.py
```

22 tests covering: surface rules, JustTCG blocking, tcgdex/ebay allowances, nested redaction, warnings, label preservation, permanent restriction, env flag override prevention, missing source safety, recursive filtering, deep copy safety, exposure metadata.

## Links

- Related: docs/JUSTTCG_TERMS_AND_USAGE.md
- Related: docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md
- Related: docs/V12_JUSTTCG_FIXTURE_ADAPTER_SPIKE.md
- Related: docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md
- Related: docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md
- Module: pricing_sources/exposure_policy.py
- Tests: tests/test_v12_pricing_source_exposure_policy.py
