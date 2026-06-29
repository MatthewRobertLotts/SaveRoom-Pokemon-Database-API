# v11.2 Provider Fixture Intake

Tags: #type/project #status/needs-review

Status: DOCUMENT_ONLY
Date: 2026-06-28
Branch: v11.2-provider-access-next

## Overview

This document defines the rules for safely saving approved provider fixtures for use in unit tests. **No real provider fixtures are stored yet.**

## When Fixtures May Be Saved

Fixtures may ONLY be saved when ALL of the following are true:

1. The provider's terms of service explicitly permit caching/storing responses for development/testing
2. `POKEMON_PRICE_SOURCE_{PROVIDER}_ALLOW_FIXTURES=true` is set in the local environment
3. The data is a minimal representative sample (not a bulk dump)
4. The data does not include paid-only content beyond what terms allow

## Fixture Storage Rules

- **Path**: `tests/fixtures/pricing_sources/{provider_code}/`
- **Format**: JSON files with descriptive names
- **Sanitization**: Remove any API keys, tokens, or personal data before saving
- **Labeling**: Each fixture file must include a header comment noting:
  - Source provider
  - Date captured
  - Permission basis (e.g., "terms permit caching for development")
  - Card/set represented

## What NOT to Store

- Full catalog dumps
- Paid-only bulk data beyond terms allowance
- Real API keys or tokens
- Data from providers whose terms prohibit caching
- Graded/sold-comps data unless explicitly permitted

## Fixture Naming Convention

```
tests/fixtures/pricing_sources/justtcg/
  justtcg_charizard_vstar_gg69_2026-06-28.json
  justtcg_pikachu_promo_2026-06-28.json
```

## Current Status

**No fixtures stored yet.** JustTCG fixture storage is now approved (2026-06-29). Fixture collection is unblocked after API key is obtained and configured.

## Links

- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
- Related: `docs/V11_2_PREFLIGHT.md`
- Gate module: `pricing_sources/provider_access.py`
