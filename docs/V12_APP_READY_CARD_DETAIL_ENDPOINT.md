# v12 App-Ready Card Detail Endpoint

Tags: #type/project #status/implemented

Status: IMPLEMENTED
Date: 2026-06-28
Branch: v12-app-readiness-next

## Endpoint

```
GET /api/v1/cards/{card_key}/detail
```

`{card_key}` follows the existing v1 canonical format: `{language_code}:{card_id}` (e.g., `en:sv03-223`). The slash alias `en/sv03-223` is also accepted.

Auth: requires a v1 API key (same as all `/api/v1/...` routes).

## What it returns

One consumer-ready payload combining:

- **card** — canonical identity (card_key, name, name_english, language_code, number, rarity, canonical_printing_id).
- **set** — set info (set_id, set_code, name, release_date).
- **images** — image manifest (primary_image_url, signed_image_url, has_local_image, missing_image, image_policy_status). No raw filesystem paths are exposed.
- **commercial** — canonical printing record, commercial variants, sellable SKUs, external references.
- **pricing** — UK-first pricing summary shell (primary_price, fallback_price, source_breakdown, evidence_summary, confidence, warnings, last_refresh).
- **provider_status** — per-provider status (uk_ebay_sold, tcgdex, justtcg, cardmarket, tcgplayer).
- **warnings** — top-level consumer warnings.
- **metadata** — contract name, generated_at timestamp, request info.

## Pricing behaviour

The pricing summary follows the corrected UK-first external pricing strategy.

- **primary_price**: always `null` until a live UK eBay sold/completed source is connected.
- **fallback_price**: populated from existing local evidence (TCGdex/legacy) when available, clearly labelled as `market_existing_local` (not UK sold evidence).
- **confidence**: `NONE` when no evidence exists, `LOW` when only fallback evidence is available.
- **warnings**: always includes a warning that UK eBay sold/completed source is not yet live.

## Provider status behaviour

| Provider | Status | Role | Live? |
|---|---|---|---|
| uk_ebay_sold | planned | primary_uk_market_evidence | no |
| tcgdex | available | existing_local_source | yes (free keyless) |
| justtcg | blocked_pending_terms | supporting_usd_fallback | no |
| cardmarket | blocked_access_closed | supporting_eu_fallback | no |
| tcgplayer | blocked_pending_access | supporting_usd_fallback | no |

No provider has `terms_confirmed: true`.

## Error responses

- `200` — card found, payload returned.
- `404` — card not found in the database.
- `400` — invalid card key format (e.g., missing language code or colon separator).
- `401` — API key required/invalid.

## Tests

`tests/test_v12_app_ready_card_detail_api.py` — 18 tests covering endpoint existence, response shape, identity fields, image safety, commercial presence, pricing shell, null primary_price, warnings, provider status, 404/400 handling, metadata, no network calls, and JSON validity.

## Implementation notes

- Read-only. No external API calls. No mutations.
- Declared BEFORE the catch-all `GET /api/v1/cards/{card_key}` route so the `/detail` suffix is not swallowed by the path converter.
- Uses existing v10 identity tables (canonical_printings, commercial_variants, sellable_skus, external_references) and v2 card detail cache.
- 18 new tests added. Full suite: 618 passed, 1 skipped.

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_API_GAP_ANALYSIS.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
- Related: `docs/API_CONTRACT_V1.md`
- Implementation: `pokemon_db_v2_fastapi.py` (function `v12_app_ready_card_detail`)
- Tests: `tests/test_v12_app_ready_card_detail_api.py`
