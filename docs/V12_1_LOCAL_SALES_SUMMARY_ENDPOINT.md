# v12.1 Local Sales Summary Endpoint

## Overview

v12.1 milestone 5 adds a read-only local sales summary endpoint for SaveRoom workflow reporting.

The endpoint summarizes rows in `listing_draft_sales` that are created by explicit local sale completion.

It is local SaveRoom workflow data only. It is not marketplace reconciliation, payment reporting, fulfilment/shipping, live pricing evidence, or market sales evidence.

## Endpoint path

```text
GET /api/v1/sales/summary
```

## Response models

```text
LocalSalesSummaryFiltersV1
LocalSalesSummaryTotalsV1
LocalSalesSummaryPlatformRowV1
LocalSalesSummaryStatusRowV1
LocalSalesSummaryCurrencyRowV1
LocalSalesSummaryDataV1
LocalSalesSummaryMetadataV1
LocalSalesSummaryResponseV1
```

As of v12.2 milestone 4, `LocalSalesSummaryResponseV1.data` is a typed `LocalSalesSummaryDataV1` model. The runtime JSON keys are unchanged.

## Filters

Supported query parameters:

```text
date_from: str | None
date_to: str | None
platform: str | None
status: str = completed
card_key: str | None
inventory_item_id: str | None
draft_id: str | None
```

Filter semantics:

| Filter | Behavior |
|---|---|
| `date_from` | Inclusive lower bound against `listing_draft_sales.sold_at`. |
| `date_to` | Inclusive upper bound against `listing_draft_sales.sold_at`. |
| `platform` | Exact match against local sale `platform`. |
| `status` | Exact match against local sale `status`; defaults to `completed`. |
| `card_key` | Exact match against local sale `card_key`. |
| `inventory_item_id` | Exact match against local sale `inventory_item_id`. |
| `draft_id` | Exact match against local sale `draft_id`. |

All user-supplied filter values are passed as bound SQL parameters.

## Response shape

```json
{
  "data": {
    "filters": {
      "date_from": "2026-07-01T00:00:00Z",
      "date_to": "2026-07-31T23:59:59Z",
      "platform": "whatnot",
      "status": "completed",
      "card_key": null,
      "inventory_item_id": null,
      "draft_id": null
    },
    "summary": {
      "sale_count": 0,
      "quantity_total": 0,
      "gross_sales_total": 0.0,
      "average_sale_price": null,
      "min_sale_price": null,
      "max_sale_price": null,
      "currency": "GBP",
      "currency_mixed": false
    },
    "by_platform": [],
    "by_status": [],
    "by_currency": []
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12.1-local-sales-summary",
    "generated_at": "..."
  }
}
```

## Aggregation definitions

| Field | Definition |
|---|---|
| `sale_count` | Count of matching local sale rows. |
| `quantity_total` | Sum of `quantity`. |
| `gross_sales_total` | Sum of `COALESCE(sale_price, 0) * quantity`. Null sale prices contribute `0` to gross. |
| `average_sale_price` | Average of non-null `sale_price` values. |
| `min_sale_price` | Minimum non-null `sale_price`. |
| `max_sale_price` | Maximum non-null `sale_price`. |
| `currency` | `GBP` when there are no matching rows; the single matching non-null currency when all rows share one; otherwise `null`. |
| `currency_mixed` | True when more than one non-null currency appears among matching rows. |

## Grouped summaries

The endpoint returns grouped summaries:

```text
by_platform:
  platform, sale_count, quantity_total, gross_sales_total

by_status:
  status, sale_count, quantity_total, gross_sales_total

by_currency:
  currency, sale_count, quantity_total, gross_sales_total
```

Grouping is intentionally simple. No time-series charts are included in this milestone.

## Local sales vs market evidence

This endpoint summarizes SaveRoom local sale-completion records only.

It is not:

- eBay sold market evidence;
- Whatnot order import;
- Shopify order reporting;
- payment capture;
- refund reporting;
- fulfilment reporting;
- tax/accounting advice;
- UK market pricing evidence;
- JustTCG, TotalTCG, TCGplayer, Cardmarket, or other provider data.

Marketplace-like platform strings are local labels only unless a future approved milestone explicitly adds marketplace integration.

## Read-only behavior

The endpoint does not:

- create or update sale rows;
- create or update listing drafts;
- create, release, or complete reservations;
- change physical inventory status;
- mark inventory sold;
- publish listings;
- import marketplace orders;
- capture payments;
- process refunds;
- create fulfilment/shipping state.

## Provider and marketplace boundaries

The endpoint must never:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- perform external network calls;
- expose API keys, headers, account metadata, raw provider JSON, sanitized candidates, private provider payloads, or raw filesystem paths.

## Known limitations

- No time-series/date-bucket output yet.
- No profit, margin, fees, tax, accounting, refunds, fulfilment, shipping, or payment state.
- No marketplace reconciliation or order validation.
- No market-pricing evidence is included.
- `gross_sales_total` treats null sale prices as zero.
- `average_sale_price`, `min_sale_price`, and `max_sale_price` ignore null sale prices.

## Tests

Coverage lives in:

```text
tests/test_v12_1_local_sales_summary_api.py
```

The tests cover endpoint existence, empty summaries, aggregate counts/quantities/gross/average/min/max, currency behavior, platform/status/card/item/draft/date filters, grouped summaries, composed filters, bound-parameter safety, read-only/no domain mutation checks, no provider/network/marketplace/LLM calls, and no sensitive/provider/filesystem leakage.


## Links

- Related: [V12.2 OpenAPI Schema Hygiene and Sales Summary Typing](V12_2_OPENAPI_SCHEMA_HYGIENE_AND_SALES_SUMMARY_TYPING.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
