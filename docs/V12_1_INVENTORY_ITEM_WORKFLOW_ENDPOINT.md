# v12.1 Inventory Item Workflow Endpoint

## Overview

v12.1 milestone 2 adds a read-only workflow summary endpoint for one physical inventory item.

It answers the POS/frontend question: what is the current workflow state for this physical inventory item?

## Endpoint path

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

Auth follows the existing inventory read convention: v1 API key when auth is required, with `read:inventory` or `cards:read` scope.

## Read-only behaviour

The endpoint only reads existing local data. It does not:

- change `physical_items.status`;
- create or update listing drafts;
- create, release, or complete reservations;
- create or update sale rows;
- create marketplace listings;
- import marketplace orders;
- capture payments;
- call providers, marketplaces, network APIs, or LLM APIs.

## Composed local tables

The response composes existing local state from:

```text
physical_items
inventory_transactions
item_images
price_snapshots
inventory_listing_draft_links
listing_drafts
listing_draft_inventory_reservations
listing_draft_sales
```

The endpoint does not introduce a new workflow state table. It derives its summary from current local inventory/listing/sale records.

## Response model

```text
InventoryItemWorkflowMetadataV1
InventoryItemWorkflowResponseV1
```

## Response shape

```json
{
  "data": {
    "item_id": "item_...",
    "current_state": "available",
    "inventory_item": {},
    "listing_draft_link": null,
    "draft": null,
    "reservation": null,
    "sale": null,
    "summary": {
      "has_listing_draft": false,
      "has_active_reservation": false,
      "has_completed_sale": false,
      "is_available_for_listing": true,
      "is_sold": false
    }
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12.1-inventory-item-workflow",
    "generated_at": "..."
  }
}
```

## `current_state` values

Allowed values:

```text
available
draft_created
ready
reserved
sold
archived
unavailable
unknown
```

Derivation order:

1. `physical_items.status = sold` or completed local sale exists → `sold`.
2. Active reservation exists → `reserved`.
3. Linked draft exists and `draft.status = ready` → `ready`.
4. Linked draft exists and `draft.status = archived` → `archived`.
5. Any other linked draft exists → `draft_created`.
6. No workflow link and physical item status is `owned` or `consigned` → `available`.
7. Other non-empty physical item status → `unavailable`.
8. Missing/unclear status → `unknown`.

This uses existing inventory status conventions rather than inventing a separate workflow state machine.

## Summary booleans

The `summary` block is frontend-friendly and intentionally redundant with the composed sections:

| Field | Meaning |
|---|---|
| `has_listing_draft` | True when the item has a latest local inventory-to-draft link and the linked draft row still exists. |
| `has_active_reservation` | True when the item has an active `reserved` reservation. |
| `has_completed_sale` | True when a completed local sale exists for this item. |
| `is_available_for_listing` | True only when derived `current_state` is `available`. |
| `is_sold` | True only when derived `current_state` is `sold`. |

## Included sections

| Section | Contents |
|---|---|
| `inventory_item` | Existing physical item detail shape: item ID, SKU identity, condition, acquisition, location, status, item images, last transaction, tenant and timestamps. |
| `listing_draft_link` | Latest `inventory_listing_draft_links` row for the item, or null. |
| `draft` | Existing listing draft response shape when linked draft exists, or null. |
| `reservation` | Active reservation when present; otherwise latest reservation if it helps explain released/completed state; otherwise null. |
| `sale` | Latest completed local sale for the item, or null. |

## Safety boundaries

The endpoint must never:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- publish listings;
- create marketplace listings;
- import marketplace orders;
- capture payments;
- mutate inventory, drafts, reservations, or sales;
- expose API keys, headers, account metadata, raw provider JSON, sanitized candidates, private provider payloads, or raw filesystem paths.

Marketplace platform strings in draft/sale rows remain local labels only. They are not proof of marketplace integration or order validation.

## Known limitations

- The endpoint reports the latest inventory-to-draft link only. It is designed for the current item workflow summary, not a full historical timeline.
- It returns active reservation first; if no active reservation exists, it returns the latest reservation for context.
- Sale summaries are local `listing_draft_sales` rows only. There is no marketplace reconciliation, fulfilment, refund, or payment state.
- Physical item photos and card reference images remain separate concepts.
- A future companion endpoint, `GET /api/v1/listings/drafts/{draft_id}/workflow`, would make draft-first pages easier.

## Tests

Coverage lives in:

```text
tests/test_v12_1_inventory_item_workflow_api.py
```

The tests cover endpoint existence, missing item 404, available/draft_created/ready/reserved/sold/archived/unavailable states, composed response sections, summary booleans, no inventory/draft/reservation/sale mutation, no provider/network/marketplace/LLM calls, and no sensitive/provider/filesystem leakage.
