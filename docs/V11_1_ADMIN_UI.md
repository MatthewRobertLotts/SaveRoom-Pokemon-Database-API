# v11.1 Admin UI — Source Comparison Panel

Tags: #type/project #status/needs-review

Status: IMPLEMENTED
Date: 2026-06-27
Branch: v11.1-market-evidence-next

## Overview

A minimal read-only comparison panel has been added to the browser admin UI, under the existing "v11 Pricing Evidence" section.

## Location

- `pokemon_db_v2_browser_ui/index.html` — DOM structure
- `pokemon_db_v2_browser_ui/app.js` — comparison logic
- `pokemon_db_v2_browser_ui/styles.css` — badge styling

## Behavior

1. User enters a target ID in the existing `evidenceTargetId` input
2. User clicks "Compare sources"
3. UI calls `GET /api/v1/prices/comparison/canonical_printing/{target}`
4. UI renders summary (source count, comparison count, highest disagreement, confidence note)
5. UI renders comparison rows if sources are comparable

## Conservative Messaging

The UI intentionally avoids pricing certainty language:
- "Only one source available — comparison is not yet possible."
- "No comparison data available. Only one source exists or no evidence is stored."
- "Read-only cross-source comparison using stored evidence. Does not fetch providers."

## Limitations

- Does NOT fetch from any external provider
- Does NOT imply price certainty
- Only compares evidence already stored in the database
- Shows `INSUFFICIENT_EVIDENCE` until a second approved source exists
- Treats all targets as `canonical_printing` (no variant/SKU resolution yet)

## Until Second Source Is Approved

Real cross-source value still requires approved second-source access (JustTCG, PokéWallet, etc.). Until then, the comparison panel will mostly show `INSUFFICIENT_EVIDENCE` for live data.

## Links

- Related: `docs/V11_1_PRICE_API.md`
- Related: `docs/V11_1_CROSS_SOURCE_COMPARISON_MODEL.md`
- Endpoint: `pricing_sources/router.py` (`get_comparison`)
- Logic: `pricing_sources/comparison.py` (`compare_target_aggregates`)
- Tests: `tests/test_v11_1_comparison_ui_smoke.py`
