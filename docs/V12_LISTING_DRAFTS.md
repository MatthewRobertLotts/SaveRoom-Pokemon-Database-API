# v12 Listing Drafts

## Overview

This v12 milestone adds local listing draft persistence for deterministic listing assistant output.

It lets SaveRoom generate listing-ready data and store it as a local draft record:

```text
POST /api/v1/listings/drafts/cards/{card_key:path}
POST /api/v1/inventory/items/{item_id}/listing-draft
```

This is local app/API persistence only.

It is not marketplace publishing.

It is not eBay, Whatnot, Shopify, JustTCG, TotalTCG, TCGplayer, Cardmarket, or LLM integration.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/listings/drafts/cards/{card_key:path}` | Generate listing assistant output locally and save a draft. |
| `POST` | `/api/v1/inventory/items/{item_id}/listing-draft` | Create a local draft from an owned physical inventory item. |
| `GET` | `/api/v1/listings/drafts/{draft_id}` | Return a saved local draft. |
| `GET` | `/api/v1/listings/drafts` | List recent local drafts. |
| `PATCH` | `/api/v1/listings/drafts/{draft_id}` | Update safe editable draft fields locally. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/ready` | Mark a local draft ready and reserve linked inventory when requested/available. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/reserve` | Reserve linked local inventory without publishing or decrementing stock. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/unreserve` | Release an active local inventory reservation. |
| `GET` | `/api/v1/listings/drafts/{draft_id}/reservation` | Return the active local reservation for a draft, or null. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/complete-sale` | Explicitly complete a local sale for a ready/reserved inventory-linked draft. |
| `POST` | `/api/v1/listings/drafts/{draft_id}/archive` | Mark a draft archived without deleting it. |

## Safety boundaries

The listing draft endpoints do not:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- publish listings;
- spend API credits;
- ask for or need API keys;
- store API keys, headers, account metadata, raw provider payloads, private provider paths, sanitized candidates, or raw filesystem paths.

Reservation-only draft endpoints do not mark inventory sold or decrement stock. The only listing-draft workflow that may mark a physical item sold is the explicit `POST /api/v1/listings/drafts/{draft_id}/complete-sale` path, which requires `confirm_completion=true` and an active local reservation.

Draft creation calls the listing assistant logic internally as a Python function. It does not call the listing assistant endpoint over HTTP.

## Database table

Table:

```text
listing_drafts
```

Fields:

```text
draft_id TEXT PRIMARY KEY
card_key TEXT NOT NULL
language_code TEXT
card_id TEXT
platform TEXT NOT NULL
status TEXT NOT NULL DEFAULT 'draft'
title TEXT
subtitle TEXT
description_json TEXT
tags_json TEXT
condition TEXT
finish TEXT
quantity INTEGER NOT NULL DEFAULT 1
pricing_json TEXT
images_json TEXT
commercial_json TEXT
platform_guidance_json TEXT
provider_status_json TEXT
warnings_json TEXT
assistant_payload_json TEXT NOT NULL
source_assistant_contract TEXT NOT NULL
notes TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
archived_at TEXT
```

Indexes:

```text
idx_listing_drafts_card_key
idx_listing_drafts_status_updated
```

The table is created idempotently by the API when draft endpoints are used.

## Inventory draft bridge table

The inventory-to-listing draft bridge records local links in:

```text
inventory_listing_draft_links
```

Fields:

```text
id TEXT PRIMARY KEY
inventory_item_id TEXT NOT NULL
draft_id TEXT NOT NULL
card_key TEXT NOT NULL
quantity INTEGER NOT NULL
created_at TEXT NOT NULL
```

This table contains only local identifiers. It does not store marketplace IDs, external account IDs, provider payloads, API keys, headers, or raw filesystem paths.

## Inventory reservation table

The local readiness workflow can reserve an inventory-linked draft in:

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

The reservation table is local-only. It does not store marketplace IDs, external account IDs, provider payloads, API keys, headers, or raw filesystem paths.

## Sale completion table

Explicit local sale completion records are stored in:

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

The table stores local sale workflow state and plain local reference text only. It does not store marketplace credentials, account IDs, provider payloads, API keys, headers, raw filesystem paths, or publishing IDs generated by marketplace APIs.
## Status lifecycle

Allowed statuses:

```text
draft
ready
archived
```

Meaning:

- `draft` — initial local draft state after creation.
- `ready` — local draft has been reviewed/edited and is ready for a later workflow; inventory-linked drafts may also have a local active reservation.
- `archived` — local draft is retained but marked inactive.

Sale completion currently does not add a new `listing_drafts.status` value. A completed sale is represented by `listing_draft_sales.status = completed`; the draft may remain `ready` for backwards-compatible reads.

Archiving sets:

```text
status = archived
archived_at = current UTC timestamp
updated_at = current UTC timestamp
```

Archived drafts remain readable and appear in list results by default. Use:

```text
GET /api/v1/listings/drafts?include_archived=false
```

to filter them out of active-only views.

## Create request

Model:

```text
ListingDraftCreateRequestV1
```

It reuses listing assistant request fields:

```json
{
  "platform": "generic",
  "condition": null,
  "finish": null,
  "quantity": 1,
  "include_images": true,
  "include_pricing": true,
  "include_commercial": true,
  "pricing_strategy": "balanced",
  "title_style": "marketplace",
  "notes": null
}
```

Validation:

- `quantity >= 1`
- `platform` is one of `whatnot`, `ebay`, `shopify`, `generic`
- `pricing_strategy` is one of `conservative`, `balanced`, `premium`
- `title_style` is one of `compact`, `seo`, `marketplace`

## Update request

Model:

```text
ListingDraftUpdateRequestV1
```

Safe editable fields only:

```json
{
  "title": "Updated title",
  "subtitle": "Updated subtitle",
  "description_bullets": ["Card name: Charizard ex"],
  "tags": ["pokemon-card", "updated"],
  "condition": "Near Mint",
  "finish": "Holo",
  "quantity": 1,
  "status": "ready",
  "notes": "Local-only note"
}
```

Validation:

- `quantity >= 1`
- `status` is one of `draft`, `ready`, `archived`

The update endpoint does not allow provider data, account metadata, raw payloads, API keys, headers, or marketplace publishing fields.

## Readiness and inventory reservation workflow

This v12 milestone adds local readiness/reservation endpoints:

```text
POST /api/v1/listings/drafts/{draft_id}/ready
POST /api/v1/listings/drafts/{draft_id}/reserve
POST /api/v1/listings/drafts/{draft_id}/unreserve
GET  /api/v1/listings/drafts/{draft_id}/reservation
```

Request models:

```text
ListingDraftReadyRequestV1
ListingDraftReserveRequestV1
ListingDraftUnreserveRequestV1
```

Response model:

```text
ListingDraftReservationResponseV1
```

Rules:

- `/ready` sets `listing_drafts.status = ready`.
- `/ready` reserves linked inventory when `reserve_inventory=true` and a local inventory link exists.
- `/ready` on a non-inventory draft marks it ready and returns `reservation: null`.
- `/reserve` requires an `inventory_listing_draft_links` row and returns `409 listing_draft_not_linked_to_inventory` when none exists.
- Only one active `reserved` row is allowed per `draft_id`.
- Only one active `reserved` row is allowed per `inventory_item_id`.
- Duplicate reserve calls for the same draft return the existing reservation and do not create duplicate active rows.
- Duplicate reservation attempts for the same inventory item from a different draft return `409 inventory_already_reserved`.
- `/unreserve` marks the active reservation `released`, records `released_at`, and stores optional `release_reason`.
- `/unreserve` can set the draft back to `draft` when `set_status="draft"` is supplied.
- Archived drafts cannot be reserved.
- Reservations do not mark `physical_items.status` as sold and do not decrement inventory automatically.

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

## Response shape

Model:

```text
ListingDraftResponseV1
```

Shape:

```json
{
  "data": {
    "draft_id": "ld_...",
    "card_key": "en:sv03-223",
    "language_code": "en",
    "card_id": "sv03-223",
    "platform": "ebay",
    "status": "draft",
    "listing": {
      "title": "Charizard ex 223 Obsidian Flames Pokémon Card",
      "subtitle": "Obsidian Flames 223 Special Illustration Rare",
      "description_bullets": [],
      "condition_note": "Near Mint",
      "tags": [],
      "notes": null
    },
    "pricing": {},
    "images": {},
    "commercial": {},
    "platform_guidance": {},
    "provider_status": {},
    "warnings": [],
    "assistant_payload": {},
    "source_assistant_contract": "v12-listing-assistant",
    "condition": "Near Mint",
    "finish": null,
    "quantity": 1,
    "created_at": "...",
    "updated_at": "...",
    "archived_at": null
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12-listing-draft",
    "generated_at": "..."
  }
}
```

List responses use:

```text
ListingDraftListResponseV1
```

with standard `pagination` metadata.

## Include flags

Draft creation preserves listing assistant include flag behavior:

```text
include_images=false -> images null and assistant_payload.images null
include_pricing=false -> pricing null and assistant_payload.pricing null
include_commercial=false -> commercial null and assistant_payload.commercial null
```

## Pricing behavior

Draft creation stores the listing assistant's recommendation-based pricing output as-is.

It does not use raw JustTCG fallback data, USD/global prices, or marketplace prices.

The stored `source_assistant_contract` is:

```text
v12-listing-assistant
```

## Tests

Coverage lives in:

```text
tests/test_v12_listing_drafts_api.py
tests/test_v12_listing_draft_reservation_api.py
```

The tests cover draft create/read/list/update/archive, local readiness/reservation/unreserve workflow, duplicate active reservation prevention, no inventory sale/decrement side effects, include flags, missing card/draft errors, invalid status validation, JustTCG fetch guard, no live provider calls, no USD/fallback leakage, no filesystem path leakage, and no raw provider/API-key/header/private-path/sanitized-candidate leakage.
