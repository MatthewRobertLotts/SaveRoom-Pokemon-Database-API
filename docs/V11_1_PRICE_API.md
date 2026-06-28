# v11.1 Price Comparison API

Tags: #type/project #status/needs-review

Status: IMPLEMENTED
Date: 2026-06-27
Branch: v11.1-market-evidence-next

## Overview

This document describes the v11.1 cross-source comparison API endpoint.

## Endpoint

### `GET /api/v1/prices/comparison/{target_type}/{target_id}`

Read-only endpoint that compares existing source evidence for a target.

**Path parameters:**
- `target_type` — `canonical_printing`, `commercial_variant`, or `sellable_sku`
- `target_id` — the target's ID

**Behavior:**
- Reads existing `v11_price_observations` rows for the target
- Computes per-source aggregate buckets (median per source/currency/listing_type/finish/condition)
- Compares source pairs using the provider-neutral comparison module
- Returns `INSUFFICIENT_EVIDENCE` when only one source exists
- Does NOT fetch from any external provider
- Does NOT invent a second source
- Does NOT imply pricing certainty

**Response shape:**
```json
{
  "data": {
    "target_type": "canonical_printing",
    "target_id": "cp-001",
    "comparisons": [
      {
        "source_a_id": "src-tcgdex",
        "source_b_id": "src-justtcg",
        "currency": "USD",
        "listing_type": "market_price",
        "finish": "normal",
        "condition": "unknown",
        "source_a_median": 100.0,
        "source_b_median": 105.0,
        "absolute_difference": 5.0,
        "percentage_difference": 0.0476,
        "agreement_band": "AGREE",
        "confidence_impact": "BOOSTED",
        "comparison_reason": "two sources agree; raised to HIGH",
        "is_comparable": true
      }
    ],
    "summary": {
      "source_count": 2,
      "comparison_count": 1,
      "highest_disagreement": "AGREE",
      "confidence_note": "Sources agree"
    }
  }
}
```

**Agreement bands:**
- `AGREE` — medians within 15%
- `MINOR_DISAGREEMENT` — medians differ by >15–35%
- `MAJOR_DISAGREEMENT` — medians differ by >35%
- `INSUFFICIENT_EVIDENCE` — fewer than two comparable sources
- `MIXED_SEMANTICS` — currency/listing/condition/finish mismatch

**Limitations:**
- Only compares evidence already stored in the database
- Becomes more useful after a real second source is approved and its observations are stored
- Does not imply pricing certainty
- Does not perform FX conversion
- Does not mix sold vs active vs guide prices

## Links

- Related: `docs/V11_1_CROSS_SOURCE_COMPARISON_MODEL.md`
- Related: `docs/V11_PRICE_API.md`
- Related: `docs/V11_MARKET_EVIDENCE_MODEL.md`
- Implementation: `pricing_sources/router.py` (`get_comparison`)
- Comparison logic: `pricing_sources/comparison.py` (`compare_target_aggregates`)
- Tests: `tests/test_v11_1_price_comparison_api.py`


## UI Panel

### Browser Comparison Panel

A minimal read-only comparison panel is available in the browser UI under the "v11 Pricing Evidence" section.

**Behavior:**
- Reuses the existing `evidenceTargetId` input (treated as `canonical_printing`)
- Calls `GET /api/v1/prices/comparison/canonical_printing/{target}`
- Does NOT fetch from any external provider
- Shows source count, comparison count, highest disagreement, and confidence note
- Renders comparison rows in a table with agreement band badges

**Conservative messaging:**
- "Only one source available — comparison is not yet possible."
- "Sources agree within the configured band."
- "Sources disagree — confidence should be treated cautiously."

**Cache bust:** `app.js?v=20260628-comparison-ui-v1`

**Until a second approved source exists:** the panel will show `INSUFFICIENT_EVIDENCE` for live data.
