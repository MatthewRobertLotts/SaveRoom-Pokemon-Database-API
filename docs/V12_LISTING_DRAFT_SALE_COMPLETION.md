# v12 Listing Draft Sale Completion

## Overview

This v12 milestone adds an explicit local sale-completion workflow for inventory-linked listing drafts.

Workflow:

```text
physical inventory item
  -> inventory listing draft
  -> ready/reserved locally
  -> explicit complete-sale action
  -> local listing_draft_sales record
  -> physical inventory marked sold
  -> inventory transaction and snapshot written
```

This is local SaveRoom workflow state only. It is not marketplace publishing, marketplace fulfilment, payment capture, marketplace order import, live pricing, or LLM automation.

## Endpoint

```text
POST /api/v1/listings/drafts/{draft_id}/complete-sale
```

The endpoint requires an existing local draft, an active local reservation, and explicit confirmation:

```json
{
  "confirm_completion": true,
  "sale_price": 12.5,
  "currency": "GBP",
  "platform": "whatnot",
  "sold_at": null,
  "buyer_reference": "plain local buyer reference",
  "external_order_reference": "plain local order reference",
  "notes": "confirmed local sale"
}
```

## Request model

```text
ListingDraftCompleteSaleRequestV1
```

Fields:

```text
confirm_completion: bool
sale_price: float | null
currency: string, default GBP
platform: whatnot | ebay | shopify | generic | offline
sold_at: string | null
buyer_reference: string | null
external_order_reference: string | null
notes: string | null
```

Validation and interpretation:

- `confirm_completion` must be true.
- `sale_price` must be non-negative when supplied.
- `currency` defaults to `GBP`.
- `quantity` is taken from the active reservation, not from the request.
- `buyer_reference` and `external_order_reference` are plain local text references only.
- Marketplace credentials are not required.
- Marketplace APIs are not called.
- Marketplace order IDs are not generated. A manually supplied `external_order_reference` is stored as text only.

## Response model

```text
ListingDraftCompleteSaleResponseV1
```

Shape:

```json
{
  "data": {
    "sale": {
      "sale_id": "sale_...",
      "draft_id": "ld_...",
      "reservation_id": "ldr_...",
      "inventory_item_id": "...",
      "card_key": "en:sv03-223",
      "quantity": 1,
      "platform": "whatnot",
      "sale_price": 12.5,
      "currency": "GBP",
      "status": "completed",
      "sold_at": "...",
      "buyer_reference": "plain local buyer reference",
      "external_order_reference": "plain local order reference",
      "notes": "confirmed local sale",
      "created_at": "...",
      "updated_at": "..."
    },
    "draft": {},
    "reservation": {},
    "inventory_item": {
      "item_id": "...",
      "status_before": "owned",
      "status_after": "sold"
    }
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12-listing-draft-sale-completion",
    "generated_at": "..."
  }
}
```

## Database table

```text
listing_draft_sales
```

Fields:

```text
sale_id TEXT PRIMARY KEY
draft_id TEXT NOT NULL
reservation_id TEXT NOT NULL
inventory_item_id TEXT NOT NULL
card_key TEXT NOT NULL
quantity INTEGER NOT NULL
platform TEXT NOT NULL
sale_price REAL
currency TEXT NOT NULL
status TEXT NOT NULL
sold_at TEXT NOT NULL
buyer_reference TEXT
external_order_reference TEXT
notes TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Indexes/constraints:

```text
idx_listing_draft_sales_draft
idx_listing_draft_sales_reservation
idx_listing_draft_sales_item
idx_listing_draft_sales_completed_draft
idx_listing_draft_sales_completed_reservation
idx_listing_draft_sales_completed_item
```

The completed indexes enforce one completed sale per draft, reservation, and physical inventory item.

## Behaviour

The endpoint:

1. loads the draft;
2. requires `confirm_completion=true`;
3. rejects archived drafts;
4. requires the draft to be inventory-linked;
5. requires an active local reservation;
6. rejects inventory items whose current status is not `owned` or `consigned`;
7. creates a local `listing_draft_sales` row with `status = completed`;
8. changes the reservation from `reserved` to `completed`, with `release_reason = sale_completed`;
9. marks `physical_items.status = sold`;
10. writes a `sold` row to `inventory_transactions`;
11. writes an `inventory_snapshots` row with `current_status = sold`;
12. returns sale, draft, reservation, and inventory summary data.

Current draft status behaviour:

- `listing_drafts.status` remains compatible with the existing `draft`, `ready`, `archived` lifecycle.
- Sale completion is represented by `listing_draft_sales.status = completed`.
- A completed sale response may still show the draft as `ready`.

## Error behaviour

```text
404 listing_draft_not_found
409 sale_completion_not_confirmed
409 listing_draft_archived
409 listing_draft_not_linked_to_inventory
409 listing_draft_not_reserved
409 listing_draft_sale_already_completed
409 inventory_item_not_available
```

## Safety boundaries

This workflow does not:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- call live provider APIs;
- call marketplace APIs;
- publish listings;
- create marketplace listings;
- create marketplace order IDs;
- ask for or need API keys;
- store API keys, request headers, account metadata, raw provider payloads, private provider paths, sanitized candidates, or raw filesystem paths.

Reservation-only workflows still do not mark inventory sold and do not decrement inventory. `complete-sale` is the only listing-draft path that marks physical inventory sold/unavailable.

## Known limitations

- This is not a full sales/order system.
- It does not perform payment capture, refund handling, fulfilment, postage, marketplace reconciliation, or customer management.
- It does not publish, revise, or end marketplace listings.
- It treats the current physical inventory bridge as one sellable physical item.
- It stores external references only as manually supplied local text.

## Tests

Coverage lives in:

```text
tests/test_v12_listing_draft_sale_completion_api.py
```

The tests cover explicit confirmation, successful local completion, local sale record persistence, reservation quantity, inventory sold status, reservation completion, duplicate completion rejection, missing reservation/link/archived/unavailable cases, transaction/snapshot writing, no JustTCG/provider/marketplace/LLM calls, no network calls, and no sensitive/provider/filesystem leakage.
