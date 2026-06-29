# v12 Batch App-Ready Card Detail Endpoint

Tags: #type/project #status/implemented

Status: IMPLEMENTED
Date: 2026-06-29
Branch: v12-app-readiness-next

## Endpoint

```
POST /api/v1/cards/detail/batch
```

Auth: requires a v1 API key (same as all `/api/v1/...` routes).

## Request body

```json
{
  "card_keys": ["en:sv03-223", "en:sv09-001"],
  "include_pricing": true,
  "include_commercial": true,
  "include_images": true
}
```

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| card_keys | list[str] | yes | — | 1-50 items, each a canonical card_key |
| include_pricing | bool | no | true | When false, sets pricing to null in each item's detail |
| include_commercial | bool | no | true | When false, sets commercial to null in each item's detail |
| include_images | bool | no | true | When false, sets images to null in each item's detail |

## Response shape

```json
{
  "data": {
    "items": [
      {
        "card_key": "en:sv03-223",
        "status": "ok",
        "detail": { ... },
        "error": null
      },
      {
        "card_key": "en:missing-card",
        "status": "error",
        "detail": null,
        "error": {
          "code": "card_not_found",
          "message": "Card not found."
        }
      }
    ],
    "summary": {
      "requested": 2,
      "returned": 1,
      "errors": 1
    }
  },
  "warnings": ["UK eBay sold/completed source is not yet live. Batch results may only include fallback/local evidence."],
  "metadata": {
    "api_version": "v1",
    "contract": "v12-app-ready-card-detail-batch",
    "generated_at": "2026-06-29T12:00:00+00:00",
    "max_batch_size": 50,
    "request": {
      "count": 2,
      "include_pricing": true,
      "include_commercial": true,
      "include_images": true
    }
  }
}
```

## Partial success

The batch endpoint supports partial success. Each card key is independently resolved:

- **ok** — card found, full detail payload returned in `detail`.
- **error** — card not found or invalid key. `error.code` is one of `card_not_found`, `invalid_card_key`, or `request_error`.

Empty `card_keys` is rejected by validation (422). More than 50 `card_keys` is rejected by validation (422).

Duplicate card keys are handled predictably — each is resolved independently and returned in order.

## Include flags behaviour

The three include flags control which sections are populated in each ok item's detail:

- `include_pricing=false` → `detail.pricing` is set to `null`
- `include_commercial=false` → `detail.commercial` is set to `null`
- `include_images=false` → `detail.images` is set to `null`

This allows callers to reduce payload size when sections are not needed.

## Pricing behaviour

Pricing behaviour matches the single-card endpoint:

- **primary_price**: always `null` until a live UK eBay sold/completed source is connected.
- **fallback_price**: populated from existing local evidence when available, clearly labelled.
- Warnings explain when UK-first source is not live.

## Provider status behaviour

All provider status fields match the single-card endpoint. JustTCG is now `terms_approved_with_restriction` (2026-06-29): approved for SaveRoom ecosystem apps, must not be exposed via standalone external developer pricing API. The adapter must propagate `terms_confirmed: false` until API key is configured and env flags are set.

## Implementation notes

- Read-only. No external API calls. No mutations.
- Calls the existing `v12_app_ready_card_detail` single-card function for each item.
- Item-level errors are caught as HTTPException and returned inline.
- Route is declared BEFORE the catch-all `{card_key:path}` route to avoid path-converter swallowing.
- 22 tests added (total batch suite: 22 passed; combined with single-card: 40 passed).

## Route ordering

```
1. GET  /api/v1/cards/{card_key:path}/detail   (single card)
2. POST /api/v1/cards/detail/batch              (batch)
3. GET  /api/v1/cards/{card_key:path}           (catch-all)
```

## Links

- Related: `docs/V12_APP_READY_CARD_DETAIL_ENDPOINT.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
- Related: `docs/V12_API_GAP_ANALYSIS.md`
- Related: `docs/API_CONTRACT_V1.md`
- Implementation: `pokemon_db_v2_fastapi.py` (function `v12_app_ready_card_detail_batch`)
- Models: `pokemon_db_v5_api_models.py` (classes `AppReadyBatchRequestV1`, `AppReadyBatchResponseV1`, etc.)
- Tests: `tests/test_v12_app_ready_card_detail_batch_api.py`
