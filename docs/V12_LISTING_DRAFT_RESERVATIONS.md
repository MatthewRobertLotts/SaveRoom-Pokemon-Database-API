# v12 Listing Draft Inventory Reservations

## Overview

This v12 milestone adds a local draft readiness and inventory reservation workflow.

It supports:

```text
listing draft created from inventory
  -> mark draft ready
  -> reserve linked inventory locally
  -> prevent duplicate reservation
  -> allow unreserve / return to draft
```

This is local SaveRoom workflow state only.

It is not marketplace publishing.

It is not stock decrement after sale.

It is not eBay, Whatnot, Shopify, JustTCG, TotalTCG, TCGplayer, Cardmarket, or LLM integration.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/listings/drafts/{draft_id}/ready` | Mark a draft ready and reserve linked inventory when available/requested. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/reserve` | Reserve linked local inventory without changing draft status. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/unreserve` | Release the active local reservation. |
| `GET` | `/api/v1/listings/drafts/{draft_id}/reservation` | Return the active reservation for a draft, or null. |

## Request models

```text
ListingDraftReadyRequestV1
ListingDraftReserveRequestV1
ListingDraftUnreserveRequestV1
```

### ListingDraftReadyRequestV1

```json
{
  "reserve_inventory": true,
  "notes": null
}
```

### ListingDraftReserveRequestV1

```json
{
  "quantity": null,
  "notes": null
}
```

### ListingDraftUnreserveRequestV1

```json
{
  "release_reason": null,
  "set_status": "draft"
}
```

`set_status` may be `draft`, `ready`, or null.

## Response model

```text
ListingDraftReservationResponseV1
```

Response shape:

```json
{
  "data": {
    "draft": {},
    "reservation": {
      "reservation_id": "ldr_...",
      "draft_id": "ld_...",
      "inventory_item_id": "...",
      "card_key": "en:sv03-223",
      "quantity": 1,
      "status": "reserved",
      "created_at": "...",
      "updated_at": "...",
      "released_at": null,
      "release_reason": null
    }
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12-listing-draft-reservation",
    "generated_at": "..."
  }
}
```

When no reservation exists, `data.reservation` is null.

## Database table

```text
listing_draft_inventory_reservations
```

Fields:

```text
reservation_id TEXT PRIMARY KEY
draft_id TEXT NOT NULL
inventory_item_id TEXT NOT NULL
card_key TEXT NOT NULL
quantity INTEGER NOT NULL
status TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
released_at TEXT
release_reason TEXT
```

Indexes/constraints:

```text
idx_listing_draft_reservations_draft
idx_listing_draft_reservations_item
idx_listing_draft_reservations_active_draft
idx_listing_draft_reservations_active_item
```

The active indexes enforce one active `reserved` row per draft and one active `reserved` row per inventory item.

## Status lifecycle

Draft statuses:

```text
draft
ready
archived
```

Reservation statuses:

```text
reserved
released
```

Workflow rules:

- `/ready` sets `listing_drafts.status = ready`.
- `/ready` reserves linked inventory when the draft was created from the inventory bridge and `reserve_inventory=true`.
- `/ready` on a non-inventory draft marks the draft ready and returns `reservation: null`.
- `/reserve` creates/reuses an active local reservation for an inventory-linked draft.
- `/reserve` returns `409 listing_draft_not_linked_to_inventory` for card-only drafts.
- `/reserve` returns `409 inventory_already_reserved` when another draft already reserves the same inventory item.
- Duplicate reserve calls for the same draft return the existing reservation and do not create duplicate active rows.
- `/unreserve` changes the active reservation to `released`, sets `released_at`, and stores optional `release_reason`.
- `/unreserve` can set the draft back to `draft` when requested.
- Archived drafts cannot be reserved.

## Safety boundaries

The reservation workflow does not:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- publish listings;
- create marketplace listing IDs;
- ask for or need API keys;
- mark `physical_items.status` as sold;
- decrement inventory automatically;
- store API keys, headers, account metadata, raw provider payloads, private provider paths, sanitized candidates, or raw filesystem paths.

## Known limitations

- Reservation is local workflow state only.
- Reservation does not represent a marketplace listing, sale, order, or fulfilment event.
- Reservation quantity is bounded by the local inventory-to-draft link quantity.
- Physical item quantity is currently treated as one sellable item by the inventory bridge.
- Sale completion, stock decrement, fulfilment, marketplace publication, and marketplace account integration remain later v12 work if needed.

## Tests

Coverage lives in:

```text
tests/test_v12_listing_draft_reservation_api.py
```

The tests cover ready/reserve/unreserve/reservation endpoints, inventory-linked and non-inventory drafts, duplicate reservation prevention, archived draft rejection, no inventory sale/decrement side effects, no JustTCG/live provider/marketplace/LLM calls, and no sensitive/provider/filesystem leakage.
