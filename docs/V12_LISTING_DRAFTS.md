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
| `POST` | `/api/v1/listings/drafts/{draft_id}/archive` | Mark a draft archived without deleting it. |

## Safety boundaries

The listing draft endpoints do not:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- publish listings;
- spend API credits;
- ask for or need API keys;
- store API keys, headers, account metadata, raw provider payloads, private provider paths, sanitized candidates, or raw filesystem paths.

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
## Status lifecycle

Allowed statuses:

```text
draft
ready
archived
```

Meaning:

- `draft` — initial local draft state after creation.
- `ready` — local draft has been reviewed/edited and is ready for a later workflow.
- `archived` — local draft is retained but marked inactive.

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
```

The tests cover draft create/read/list/update/archive, include flags, missing card/draft errors, invalid status validation, JustTCG fetch guard, no live provider calls, no USD/fallback leakage, no filesystem path leakage, and no raw provider/API-key/header/private-path/sanitized-candidate leakage.
