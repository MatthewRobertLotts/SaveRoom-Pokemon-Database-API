# v12.2 Inventory Item List Filters

Tags: #type/doc #pokemon-db #v12-2 #inventory #pos

## Overview

v12.2 milestone 1 improves the existing inventory item list endpoint so POS/frontends can find the right physical inventory item before opening workflow detail pages.

This milestone updates only the existing read-only list endpoint:

```text
GET /api/v1/inventory/items
```

No duplicate route was added. The existing response model, list item shape, pagination shape, default limit/offset behavior, and `q` search behavior are preserved.

## Body

### Endpoint path

```text
GET /api/v1/inventory/items
```

### Existing behavior preserved

Preserved behavior:

```text
limit default: 50
limit max: 200
offset default: 0
pagination shape: limit, offset, count, total, has_more
existing inventory item response shape
existing q search over notes, acquired_source, and item_id
existing status filter
existing location_code filter
```

The endpoint remains tenant-scoped through the existing API-key/membership logic.

### Filters

Supported optional query parameters after v12.2 milestone 1:

```text
sku_id: int | None
card_key: str | None
condition: str | None
status: str | None
location_code: str | None
has_listing_draft: bool | None
has_active_reservation: bool | None
has_completed_sale: bool | None
q: str | None
limit: int
offset: int
```

### Filter semantics

| Filter | Behavior |
|---|---|
| `sku_id` | Exact match against `physical_items.sku_id`. |
| `card_key` | Exact match through local SKU/card identity tables. |
| `condition` | Exact match against `physical_items.item_condition`. |
| `status` | Exact match against `physical_items.status`. |
| `location_code` | Exact match against `physical_items.location_code`. |
| `has_listing_draft=true` | Includes items with at least one `inventory_listing_draft_links` row. |
| `has_listing_draft=false` | Includes items without an `inventory_listing_draft_links` row. |
| `has_active_reservation=true` | Includes items with an active `listing_draft_inventory_reservations.status = reserved` row. |
| `has_active_reservation=false` | Includes items without an active reserved reservation. |
| `has_completed_sale=true` | Includes items with a completed `listing_draft_sales.status = completed` row. |
| `has_completed_sale=false` | Includes items without a completed local sale. |
| `q` | Existing search behavior over notes, acquired source, and item ID. |

All user-supplied filter values use bound SQL parameters.

### card_key join approach

`card_key` is implemented with a reliable local join:

```text
physical_items.sku_id
→ sellable_skus.sku_id
→ sellable_skus.printing_id
→ canonical_printings.printing_id
→ canonical_printings.canonical_card_key
```

SQL shape:

```sql
EXISTS (
  SELECT 1
  FROM sellable_skus ss
  JOIN canonical_printings cp ON cp.printing_id = ss.printing_id
  WHERE ss.sku_id = p.sku_id
    AND cp.canonical_card_key = ?
)
```

No provider API is called to resolve `card_key`.

### Workflow filter SQL approach

Workflow-state filters use fixed internal `EXISTS` / `NOT EXISTS` clauses:

```text
has_listing_draft:
  inventory_listing_draft_links.inventory_item_id = physical_items.item_id

has_active_reservation:
  listing_draft_inventory_reservations.inventory_item_id = physical_items.item_id
  AND status = 'reserved'

has_completed_sale:
  listing_draft_sales.inventory_item_id = physical_items.item_id
  AND status = 'completed'
```

If an optional workflow table is absent:

- positive workflow filters return no matches;
- negative workflow filters do not exclude rows merely because the table is absent.

### Pagination behavior

Filtered totals use the same filtered query as the returned page.

The row query remains ordered by newest physical item creation time:

```sql
ORDER BY p.created_at DESC
LIMIT ? OFFSET ?
```

`limit` and `offset` remain bound parameters.

### Relationship to inventory item workflow endpoint

This endpoint is for finding inventory items.

After a frontend finds the target item, it can call:

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

That workflow endpoint returns per-item composed state across inventory, listing draft link, draft, reservation, sale, and summary fields.

The list endpoint does not expand every inventory item into a full workflow response.

### Read-only behavior

The endpoint does not mutate:

```text
physical_items
inventory_transactions
listing_drafts
inventory_listing_draft_links
listing_draft_inventory_reservations
listing_draft_sales
```

It does not:

```text
create listing drafts
create or release reservations
complete sales
mark inventory sold
publish marketplace listings
import marketplace orders
capture payments
process refunds
create fulfilment/shipping state
```

### Provider and marketplace boundaries

The endpoint does not call:

```text
_get_justtcg_price_data()
JustTCG
TotalTCG
TCGplayer
Cardmarket
eBay
Whatnot
Shopify
LLM APIs
```

It must not expose:

```text
.env or .env.local contents
API keys
headers
account metadata
private provider payloads
raw provider JSON
sanitized candidates
raw filesystem paths
```

### Known limitations

- The endpoint does not add free-text search over card names or set names yet; `q` keeps the existing inventory-field behavior.
- The endpoint does not return a full workflow summary per row; use the item workflow endpoint for that.
- Workflow boolean filters are based on local SaveRoom workflow tables only.
- Completed sale means a local `listing_draft_sales.status = completed` row, not marketplace reconciliation.
- Active reservation means local `listing_draft_inventory_reservations.status = reserved`.

### Tests

Coverage lives in:

```text
tests/test_v12_2_inventory_item_list_filters_api.py
```

The tests cover default list behavior, pagination, existing `q` search, exact filters, `card_key` local join behavior, workflow boolean filters, composed filters, filtered pagination totals, bound-parameter safety, response shape compatibility, read-only/no domain mutation checks, no provider/network/marketplace/LLM calls, and no sensitive/provider/filesystem leakage.

## Links

- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.1 Inventory Item Workflow Endpoint](V12_1_INVENTORY_ITEM_WORKFLOW_ENDPOINT.md)
- Related: [V12.1 Post-Release State](V12_1_POST_RELEASE_STATE.md)
