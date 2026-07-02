# v12.1 Listing Draft List Filters

## Overview

v12.1 milestone 4 improves the existing listing draft list endpoint with read-only POS/frontend filters.

The goal is to let clients list local drafts by workflow-relevant state without fetching every draft and filtering locally.

This milestone does not change list item shape and does not add marketplace/provider behavior.

## Endpoint path

```text
GET /api/v1/listings/drafts
```

Existing response model remains:

```text
ListingDraftListResponseV1
```

## Existing behavior preserved

The endpoint keeps the existing defaults and response shape:

- `include_archived=true` by default;
- `limit` / `offset` pagination;
- response envelope with `data`, `pagination`, and `metadata`;
- list items remain existing listing draft objects;
- `metadata.contract` remains `v12-listing-draft`;
- archived drafts remain included unless `include_archived=false` is supplied.

This milestone only adds optional filters.

## New filters

Supported query parameters:

```text
status: str | None
platform: str | None
card_key: str | None
inventory_item_id: str | None
has_reservation: bool | None
has_sale: bool | None
```

## Filter semantics

| Filter | Behavior |
|---|---|
| `status` | Exact match against `listing_drafts.status`. |
| `platform` | Exact match against `listing_drafts.platform`. Platform is a local label only. |
| `card_key` | Exact match against `listing_drafts.card_key`. |
| `inventory_item_id` | Includes drafts with an `inventory_listing_draft_links` row for the supplied physical item ID. |
| `has_reservation=true` | Includes drafts with an active `listing_draft_inventory_reservations.status = reserved` row. |
| `has_reservation=false` | Includes drafts without an active reserved reservation. |
| `has_sale=true` | Includes drafts with a completed local `listing_draft_sales.status = completed` row. |
| `has_sale=false` | Includes drafts without a completed local sale. |

Filters compose with each other and with `include_archived`, `limit`, and `offset`.

Example:

```text
GET /api/v1/listings/drafts?status=ready&platform=generic&card_key=en:sv03-223&inventory_item_id=...&has_reservation=true&has_sale=false
```

## SQL approach

The implementation uses bound SQL parameters for user-supplied values.

Workflow-related filters use fixed internal SQL clauses:

```text
inventory_item_id:
EXISTS inventory_listing_draft_links row for draft_id and inventory_item_id

has_reservation=true:
EXISTS active reserved row for draft_id

has_reservation=false:
NOT EXISTS active reserved row for draft_id

has_sale=true:
EXISTS completed sale row for draft_id

has_sale=false:
NOT EXISTS completed sale row for draft_id
```

If an optional workflow table does not exist yet:

- positive filters (`inventory_item_id`, `has_reservation=true`, `has_sale=true`) return no matches;
- negative boolean filters (`has_reservation=false`, `has_sale=false`) do not exclude drafts merely because the table is absent.

## Pagination behavior

Pagination remains offset/limit based.

The filtered `total` uses the same SQL filters as the returned page.

Response pagination shape remains:

```json
{
  "limit": 50,
  "offset": 0,
  "count": 50,
  "total": 123,
  "has_more": true
}
```

## Relationship to workflow endpoints

This endpoint is for list pages and narrow filtered draft collections.

It does not embed full workflow summaries in every list item.

For per-draft workflow detail, call:

```text
GET /api/v1/listings/drafts/{draft_id}/workflow
```

For per-inventory-item workflow detail, call:

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

## Read-only behavior

The list endpoint is read-only for domain data. It does not:

- create or update listing drafts;
- create, release, complete, or update reservations;
- create or update sale rows;
- change physical inventory status;
- mark inventory sold;
- write marketplace IDs or account data;
- publish listings;
- import marketplace orders;
- capture payments.

## Provider and marketplace boundaries

The endpoint must never:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- perform external network calls;
- expose API keys, headers, account metadata, raw provider JSON, sanitized candidates, private provider payloads, or raw filesystem paths.

Marketplace names in `platform` are local labels only. They are not proof of marketplace account integration, order import, or listing publication.

## Known limitations

- Filters are exact-match filters, not fuzzy search.
- `has_reservation` only considers active `reserved` rows, not released/completed history.
- `has_sale` only considers local `listing_draft_sales.status = completed` rows.
- The endpoint does not compute workflow state; it only filters list rows. Use `/workflow` for composed state.
- There is still no aggregate local sales summary endpoint for totals/counts by date/platform/status/card/inventory item.

## Tests

Coverage lives in:

```text
tests/test_v12_1_listing_draft_list_filters_api.py
```

The tests cover default list behavior, `include_archived`, status/platform/card filters, inventory item link filtering, `has_reservation=true/false`, `has_sale=true/false`, composed filters, pagination with filters, response shape compatibility, read-only/no domain mutation checks, no provider/network/marketplace/LLM calls, and no sensitive/provider/filesystem leakage.
