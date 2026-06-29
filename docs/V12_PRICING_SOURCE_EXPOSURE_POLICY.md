# v12 Pricing Source Exposure Policy

Tags: #type/project #status/implemented

Status: IMPLEMENTED
Date: 2026-06-29
Branch: v12-app-readiness-next

## Overview

A code-enforced policy guard that ensures JustTCG-derived pricing is allowed for SaveRoom ecosystem apps but blocked from standalone external developer API responses. The restriction is permanent and cannot be overridden by env flags.

## Motivation

JustTCG's terms state: *"The integration cannot be wrapped into a secondary API that acts as a standalone pricing service or competing data product for external parties."*

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
| External Developer API | `SURFACE_EXTERNAL_DEVELOPER_API` | Third-party developer pricing API |

## Source rules

| Source | Internal | Customer App | External Dev API |
|---|---|---|---|
| justtcg | ✅ allowed | ✅ allowed | ❌ **blocked** |
| tcgdex | ✅ | ✅ | ✅ |
| uk_ebay_sold | ✅ | ✅ | ✅ |
| ebay_uk / ebay_uk_sold | ✅ | ✅ | ✅ |
| cardmarket | ✅ | ✅ | ✅ |
| tcgplayer | ✅ | ✅ | ✅ |
| unknown source | ✅ | ✅ | ❌ blocked (conservative) |

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

For external developer API surfaces:
- Pricing fields (price, amount, median, low, high, primary_price, fallback_price, etc.) from blocked sources are set to `null`
- `source_breakdown` items from blocked sources are removed
- Source labels are suffixed with `_redacted_for_surface`
- A warning is added: "Some pricing fields were withheld because their source is not licensed for standalone external developer API resale."

For SaveRoom internal/customer surfaces:
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

## Tests

```
tests/test_v12_pricing_source_exposure_policy.py
```

22 tests covering: surface rules, JustTCG blocking, tcgdex/ebay allowances, nested redaction, warnings, label preservation, permanent restriction, env flag override prevention, missing source safety, recursive filtering, deep copy safety, exposure metadata.

## Links

- Related: docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md
- Related: docs/V12_JUSTTCG_FIXTURE_ADAPTER_SPIKE.md
- Related: docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md
- Related: docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md
- Module: pricing_sources/exposure_policy.py
- Tests: tests/test_v12_pricing_source_exposure_policy.py
