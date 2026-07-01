# v12 Chart-Ready Price History Plan

Tags: #type/project #status/active

Status: ACTIVE
Date: 2026-06-29
Branch: v12-app-readiness-next

## Overview

Plan for Slice 3 of v12: a chart-ready local price history endpoint that returns time-bucketed series data suitable for rendering price charts in the web tracker, inventory views, and future listing assistant.

## Endpoint path

```
GET /api/v1/prices/chart/cards/{card_key:path}
```

Uses `{card_key:path}` to be consistent with all other v1 card endpoints. The `chart` qualifier distinguishes this from the existing raw `GET /api/v1/prices/history/cards/{card_key:path}`.

## Identifier types supported

`{card_key}` follows the existing v1 canonical format: `{language_code}:{card_id}` (e.g., `en:sv03-223`).

## Data source

Reads from `uk_price_history` table only. No live provider calls. No JustTCG calls. No eBay API calls. No FX conversion.

Existing columns used:
- `card_id`, `language_code` — card identification
- `sold_date` — date for time bucketing
- `price_gbp` — price in GBP
- `source` — source label (ebay_uk, ebay_uk_sold)
- `bucket` — evidence bucket (raw, graded, bundle, noise)
- `condition_normalized` — normalized condition
- `is_recommended_input` — quality filter flag
- `confidence_score` — per-evidence confidence

## Response shape

```json
{
  "data": {
    "card_key": "en:sv03-223",
    "series": [
      {
        "source": "ebay_uk_sold",
        "currency": "GBP",
        "price_type": "market_existing_local",
        "region": "UK",
        "points": [
          {
            "date": "2026-04-15",
            "median": 2.50,
            "low": 1.80,
            "high": 3.20,
            "evidence_count": 8,
            "confidence": "LOW"
          }
        ]
      }
    ],
    "summary": {
      "has_uk_sold_evidence": false,
      "has_fallback_evidence": true,
      "primary_source_live": false,
      "point_count": 1
    }
  },
  "warnings": [
    "UK eBay sold/completed source is not yet live.",
    "Chart uses existing local fallback evidence only."
  ],
  "metadata": {
    "api_version": "v1",
    "contract": "v12-chart-ready-price-history",
    "generated_at": "2026-06-29T12:00:00+00:00",
    "request": {}
  }
}
```

## Date bucket model

- **Default bucket: daily** by `sold_date`.
- Optional query param `bucket_size` with values `day` | `week` | `month`.
- Daily: one point per distinct `sold_date`.
- Weekly: ISO week number grouping (date = Monday of that week).
- Monthly: YYYY-MM grouping (date = first of month).
- Each point contains: `date`, `median`, `low` (10th percentile), `high` (90th percentile), `evidence_count`, `confidence`.
- Only points with evidence_count > 0 are returned.

## Series model

- One series per distinct `source` value in the evidence for that card.
- Each series has: `source`, `currency` (always GBP), `price_type` (market_existing_local), `region` (UK or null), `points`.
- Only recommended input evidence is included by default (`is_recommended_input = 1`).
- Optional query param `include_non_recommended=true` to include all evidence.

## Provider/source labels

- `ebay_uk_sold` → source label, region "UK"
- `ebay_uk` → source label, region "UK"
- No JustTCG in chart data.
- No Cardmarket/TCGplayer in chart data.

## Confidence trend

Each point's `confidence` is derived from `evidence_count`:
- `evidence_count >= 10` → "MEDIUM"
- `evidence_count >= 3` → "LOW"
- `evidence_count < 3` → "VERY_LOW"

This is a pragmatic heuristic since per-evidence `confidence_score` is not always populated.

## Warnings

Always includes:
1. "UK eBay sold/completed source is not yet live." — because no live adapter is connected.
2. "Chart uses existing local fallback evidence only." — clarifying data origin.

If no evidence exists for a card, an additional warning: "No price evidence available for this card."

## Limitations

- No live provider calls.
- No real-time data. Data reflects what was imported into `uk_price_history`.
- No FX conversion. All prices in GBP.
- No confidence score aggregation from per-evidence scores (uses evidence count heuristic).
- Date range limited to what exists in the table.
- UK-first strategy: `has_uk_sold_evidence` will be false until a live UK eBay sold/completed adapter is connected and importing.

## No-live-provider rule

This endpoint makes zero external API calls. It reads only from the local SQLite `uk_price_history` table.

## UK-first strategy alignment

- `has_uk_sold_evidence` is true only if `source = 'ebay_uk_sold'` rows exist.
- `primary_source_live` is always false (no live adapter).
- Fallback evidence (`ebay_uk`) is shown in series but clearly labelled.
- Warnings explicitly state UK-first source is not live.

## Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| bucket_size | str | day | Time bucket: day, week, month |
| source | str | null | Filter to one source (e.g. ebay_uk_sold) |
| include_non_recommended | bool | false | Include non-recommended evidence |
| limit | int | 365 | Max points per series (1-365) |

## Pydantic models (new)

- `ChartReadyPointV1` — date, median, low, high, evidence_count, confidence
- `ChartReadySeriesV1` — source, currency, price_type, region, points
- `ChartReadySummaryV1` — has_uk_sold_evidence, has_fallback_evidence, primary_source_live, point_count
- `ChartReadyPriceHistoryResponseV1` — data, warnings, metadata
- `ChartReadyPriceHistoryDataV1` — card_key, series, summary

## Implementation approach

- Read-only route inside `create_app()`, after the existing price endpoints.
- SQL aggregation query groups by sold_date (or week/month), source.
- Percentile calculation: sort prices per bucket, pick 10th/50th/90th.
- No refactoring of existing endpoints.
- Route declared before any catch-all paths.

## Links

- Related: docs/V12_IMPLEMENTATION_PLAN.md
- Related: docs/V12_API_GAP_ANALYSIS.md
- Related: docs/API_CONTRACT_V1.md
- Related: docs/V12_APP_READY_CARD_DETAIL_ENDPOINT.md
- Tests: tests/test_v12_chart_ready_price_history_api.py
