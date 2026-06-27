# V10 Identity API

## Endpoints

All endpoints are under `/api/v1/identity` and are **read-only** in v10.

### `GET /api/v1/identity/health`

Returns aggregate counts and last build run info.

Response:

```json
{
  "canonical_printings": 23456,
  "card_links": 46000,
  "commercial_variants": 47000,
  "sellable_skus": 47000,
  "external_references": 92000,
  "build_runs": 1,
  "last_build_run": {
    "build_run_id": "br-...",
    "started_at": "2026-06-27T...",
    "status": "completed",
    "algorithm_version": "1.0.0",
    "canonical_printings_created": 23456,
    "commercial_variants_created": 47000,
    "sellable_skus_created": 47000,
    "notes": "..."
  },
  "high_confidence": 23456,
  "medium_confidence": 0,
  "low_confidence": 0,
  "unknown_finish": 12000
}
```

### `GET /api/v1/identity/canonical-printings`

List canonical printings with filters.

Query params: `q`, `core_set_id`, `set_id`, `collector_number`, `language` (alias `language_code`), `confidence_label`, `limit` (default 50, max 500), `offset`.

Response: `{"data": [...], "meta": {"limit": 50, "offset": 0, "count": N}}`

### `GET /api/v1/identity/canonical-printings/{canonical_printing_id}`

Detail with linked cards and commercial variants.

### `GET /api/v1/identity/cards/{card_key}`

Card-to-identity lookup. Returns `mapped: false` with warnings if unmapped (does not 404).

### `GET /api/v1/identity/sellable-skus`

List SKUs with filters: `q`, `item_class`, `language` (alias `language_code`), `status`, `limit`, `offset`.

### `GET /api/v1/identity/sellable-skus/{sellable_sku_id}`

SKU detail.

### `GET /api/v1/identity/external-references`

List external references with filters: `entity_type`, `entity_id`, `source_name`, `source_identifier`, `confidence_label`, `limit`, `offset`.

## Response Envelope

All list endpoints use `{"data": [...], "meta": {...}}`. Detail endpoints use `{"data": {...}}`.

## Authentication

Follows the existing `require_v1_api_key` pattern. In local dev mode (no `POKEMON_DB_REQUIRE_API_KEY` set), auth is disabled.

## Rate Limits

No dedicated rate limits on identity endpoints in v10. These share the global quota middleware.
