# v11 Price API

Tags: #type/project #status/needs-review

Status: IMPLEMENTED
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

This document describes the v11 market evidence API endpoints. All endpoints are under `/api/v1/prices` and follow the existing v1 API envelope style.

## Endpoints

### GET `/api/v1/prices/sources`

List all registered pricing sources.

**Response:**
```json
{
  "data": [
    {
      "source_id": "src-tcgdex",
      "source_code": "tcgdex",
      "source_name": "TCGdex Market API",
      "source_url": "https://api.tcgdex.net",
      "base_currency": "USD",
      "is_enabled": 1
    }
  ]
}
```

### GET `/api/v1/prices/sources/{source_code}/health`

Get health status for a specific source.

**Response:**
```json
{
  "data": {
    "source_code": "tcgdex",
    "status": "healthy",
    "response_ms": 52.3,
    "last_success_at": "2026-06-27T13:41:27Z"
  }
}
```

### GET `/api/v1/prices/observations`

List v11 price observations with filtering.

**Query parameters:**
- `source_code` — filter by source
- `canonical_printing_id` — filter by matched canonical printing
- `commercial_variant_id` — filter by matched commercial variant
- `currency` — filter by currency (USD, EUR)
- `listing_type` — filter by listing type
- `confidence` — filter by match confidence
- `limit` (default 50, max 200)
- `offset` (default 0)

**Response:**
```json
{
  "data": [...],
  "pagination": {"limit": 50, "offset": 0, "count": 10, "total": 100}
}
```

### GET `/api/v1/prices/observations/{observation_id}`

Get a single observation by ID, including its identity matches.

**Response:**
```json
{
  "data": {
    "observation_id": 1,
    "source_id": "src-tcgdex",
    "currency": "USD",
    "amount": 0.11,
    "finish": "normal",
    "match_confidence": "HIGH",
    "matches": [
      {
        "target_type": "canonical_printing",
        "target_id": "cp-001",
        "match_confidence": "HIGH",
        "match_method": "set_code+collector_number"
      }
    ]
  }
}
```

### GET `/api/v1/prices/aggregate/{target_type}/{target_id}`

Get aggregate valuation for a target.

**Path parameters:**
- `target_type` — `canonical_printing`, `commercial_variant`, or `sellable_sku`
- `target_id` — the target's ID

**Query parameters:**
- `currency` — filter by currency

**Response:**
```json
{
  "data": [
    {
      "target_type": "canonical_printing",
      "target_id": "cp-001",
      "currency": "USD",
      "listing_type": "market_price",
      "finish": "normal",
      "median_price": 0.11,
      "low_price": 0.04,
      "high_price": 0.37,
      "observation_count": 3,
      "source_count": 1,
      "confidence_label": "MEDIUM",
      "confidence_reason": "single source"
    }
  ]
}
```

### POST `/api/v1/prices/refresh/{target_type}/{target_id}`

Trigger a manual evidence refresh for a target.

**Path parameters:**
- `target_type` — `canonical_printing`, `commercial_variant`, or `sellable_sku`
- `target_id` — the target's ID (format: `cp-{set_code}-{collector_number}`)

**Response:**
```json
{
  "data": {
    "run_id": 42,
    "status": "completed",
    "observations_created": 5,
    "cache_rows_created": 2
  }
}
```

## Error Handling

All errors follow the standard v1 error envelope:

```json
{
  "error": {
    "code": "card_not_found",
    "message": "Card not found",
    "details": {"card_key": "en:missing"}
  }
}
```

## Links

- Related: [[V11_PRICE_ADAPTERS]]
- Related: [[API_CONTRACT_V1]]
- Related: [[V11_MARKET_EVIDENCE_MODEL]]
