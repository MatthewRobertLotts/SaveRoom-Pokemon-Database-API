# v12 JustTCG Fixture-Only Adapter Spike

Tags: #type/project #status/implemented

Status: IMPLEMENTED (fixture-only, no live calls)
Date: 2026-06-29
Branch: v12-app-readiness-next

## Overview

A fixture-only JustTCG adapter spike that can normalize synthetic fixture payloads and is gated against making live API calls unless all access-gate env flags are configured.

## Endpoint

No new API endpoint. This is a pricing source adapter module.

## Terms status

JustTCG terms approved (2026-06-29) with restriction. All permissions confirmed:
- Commercial backend use, raw cache, normalized storage, aggregate storage, fixture storage, internal display, customer display, identifier mapping
- Soft attribution requested: "Pricing data provided by JustTCG"
- **Critical restriction:** No standalone external developer pricing API resale. SaveRoom ecosystem apps only.

## Adapter module

```
pricing_sources/justtcg.py
```

- `source_code`: "justtcg"
- `requires_access_gate()`: True
- `fetch()`: Gated — raises PermissionError unless config provides key + enabled + terms confirmed, or fixture path is set
- `normalise()`: Converts JustTCG variant data into `PriceObservationCandidate` with USD market_price semantics
- `match_observations()`: Uses tcgplayerSkuId (HIGH) or justtcg_variant_uuid (MEDIUM fallback)
- `validate_identifier_mapping()`: Validates UUID and tcgplayerSkuId presence per variant
- `capabilities()`: Documents all permissions, restrictions, and match keys

## Normalization mapping

| JustTCG field | v11 observation field |
|---|---|
| variant.uuid | source_record_id (prefixed with "justtcg:") |
| variant.price | amount |
| USD | currency (always) |
| "market_price" | listing_type / observation_type |
| variant.condition (NM/LP/MP/HP/D) | condition (normalized) |
| variant.printing | finish |
| variant.language | language |
| variant.tcgplayerSkuId | printing_label (preferred match key) |
| variant.lastUpdated | observed_at (ISO format) |

## Important semantics

- JustTCG price is **market price**, not sold/completed evidence
- Currency is **USD only** — never treated as UK GBP estimate
- Must NOT be labelled as UK sold evidence
- Must NOT be exposed through standalone external developer pricing API
- Preferred match key: `tcgplayerSkuId`
- Fallback match key: `justtcg_variant_uuid`

## Fixture

```
tests/fixtures/pricing_sources/justtcg/synthetic_pokemon_cards.json
```

- Type: synthetic_schema_shape
- Contains no real provider data
- Contains no API keys or account metadata
- Clearly labelled as synthetic in `_metadata`
- Includes two cards with multiple variants (NM Normal, NM Foil, LP Normal)

## Access gate behaviour

- Missing API key → live calls blocked
- enabled=false → live calls blocked
- terms_confirmed=false → live calls blocked
- All three required for live access
- Fixture-only mode works without any config

## External API resale protection

- `capabilities()["external_api_resale_allowed"]` is always False
- `.env.example` includes `POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_EXTERNAL_API_RESALE=false`
- This flag must remain false — architectural restriction from JustTCG terms

## Env flags

```
POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY=           # (secret, never commit)
POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED=false
POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_NORMALIZED_STORAGE=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_INTERNAL_DISPLAY=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_CUSTOMER_DISPLAY=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_EXTERNAL_API_RESALE=false
```

## Tests

```
tests/test_v12_justtcg_fixture_adapter.py
```

20 tests covering: source_code, access gate, external API resale, capabilities, fixture loading, fixture safety (no secrets/synthetic), normalization (USD, market_price, not UK sold), identifier keys (tcgplayerSkuId preferred, variant UUID fallback), display permissions, no-network source inspection, condition normalization, identifier mapping validation.

## Implementation notes

- No live HTTP calls are made by this adapter or its tests.
- The adapter module does not import `requests`, `httpx`, or `aiohttp`.
- All data flows through the existing `PriceSourceAdapter` ABC.
- UK-first pricing strategy is preserved: JustTCG is USD market fallback, not UK sold evidence.

## Links

- Related: docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md
- Related: docs/V11_2_PROVIDER_ACCESS_READINESS.md
- Related: docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md
- Related: docs/JUSTTCG_API_REFERENCE.md
- Adapter: pricing_sources/justtcg.py
- Fixture: tests/fixtures/pricing_sources/justtcg/synthetic_pokemon_cards.json
- Tests: tests/test_v12_justtcg_fixture_adapter.py
