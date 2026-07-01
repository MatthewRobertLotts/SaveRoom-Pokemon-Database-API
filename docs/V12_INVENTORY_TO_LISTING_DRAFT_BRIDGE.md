# v12 Inventory-to-Listing Draft Bridge

## Overview

This v12 milestone adds a local bridge from owned physical inventory items to local listing drafts.

It connects:

```text
owned physical_items row
  -> sellable_skus
  -> canonical_printings.canonical_card_key
  -> deterministic listing assistant output
  -> local listing_drafts record
  -> optional local listing_draft_inventory_reservations row when marked ready/reserved
```

This is local inventory-to-draft creation only.

It is not marketplace publishing.

It is not eBay, Whatnot, Shopify, TCGplayer, Cardmarket, JustTCG, TotalTCG, or LLM integration.

It does not need API keys and does not spend API credits.

## Endpoint

```text
POST /api/v1/inventory/items/{item_id}/listing-draft
```

The endpoint uses the existing physical inventory item identity because current inventory APIs are rooted at:

```text
/api/v1/inventory/items/{item_id}
```

## Request model

```text
InventoryListingDraftCreateRequestV1
```

Shape:

```json
{
  "platform": "generic",
  "quantity": null,
  "condition": null,
  "finish": null,
  "include_images": true,
  "include_pricing": true,
  "include_commercial": true,
  "pricing_strategy": "balanced",
  "title_style": "marketplace",
  "notes": null
}
```

Supported platform values:

```text
whatnot
ebay
shopify
generic
```

Supported pricing strategies:

```text
conservative
balanced
premium
```

Supported title styles:

```text
compact
seo
marketplace
```

## Response model

```text
InventoryListingDraftResponseV1
```

Shape:

```json
{
  "data": {
    "draft": {},
    "inventory_source": {
      "item_id": "...",
      "card_key": "en:sv03-223",
      "quantity_requested": 1,
      "quantity_available": 1,
      "condition": "Near Mint",
      "finish": "Holo",
      "linked": true
    }
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12-inventory-listing-draft-bridge",
    "generated_at": "..."
  }
}
```

`data.draft` is the same local listing draft shape returned by the existing listing draft read endpoint.

## Quantity, condition, and finish rules

- Request `condition`, `finish`, and `quantity` override inventory-derived defaults when supplied.
- Omitted `condition` defaults from `physical_items.item_condition`, falling back to SKU condition code when needed.
- Omitted `finish` defaults from the linked commercial variant when available.
- Omitted `quantity` defaults to `1` for a physical inventory item.
- A physical item has available quantity `1` when status is `owned` or `consigned`.
- A physical item has available quantity `0` when status is no longer sellable, such as `sold` or `lost`.
- A request quantity greater than available quantity returns `409 inventory_quantity_unavailable`.
- An inventory item whose SKU cannot resolve `canonical_printings.canonical_card_key` returns `409 inventory_item_missing_card_key`, not 500.

## DB objects

Existing source tables:

```text
physical_items
sellable_skus
canonical_printings
commercial_variants
```

Existing target table:

```text
listing_drafts
```

New local bridge table:

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

The link table stores only local identifiers and metadata needed to trace which inventory item created which local draft.

It stores no marketplace IDs, account IDs, provider payloads, headers, API keys, or raw filesystem paths.

## Local reservation follow-up

Inventory-linked drafts can now be marked ready and locally reserved with:

```text
POST /api/v1/listings/drafts/{draft_id}/ready
POST /api/v1/listings/drafts/{draft_id}/reserve
POST /api/v1/listings/drafts/{draft_id}/unreserve
GET  /api/v1/listings/drafts/{draft_id}/reservation
```

Reservation table:

```text
listing_draft_inventory_reservations
```

Local reservation rules:

- `/ready` sets `listing_drafts.status = ready` and reserves linked inventory when `reserve_inventory=true`.
- `/reserve` creates/reuses one active local `reserved` row for the linked draft.
- Only one active reservation is allowed per draft.
- Only one active reservation is allowed per inventory item.
- A second draft attempting to reserve the same inventory item receives `409 inventory_already_reserved`.
- `/unreserve` releases the active reservation and can optionally set the draft status back to `draft`.
- Reservations are local workflow state only.
- Reservations do not mark the physical item sold and do not decrement inventory automatically.

## Safety boundaries

The bridge does not:

- call `_get_justtcg_price_data()`;
- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs;
- call the listing assistant endpoint over HTTP;
- publish listings;
- mark physical inventory sold;
- decrement stock automatically;
- spend API credits;
- ask for or need API keys;
- store API keys, request headers, account metadata, raw provider payloads, private provider paths, sanitized candidates, or raw filesystem paths.

The bridge calls the deterministic listing assistant function internally and then persists the output with the same local draft helper used by the card-key draft endpoint.

## Include flags

The bridge forwards include flags to the deterministic listing assistant logic:

- `include_images=false` persists `images = null` and `assistant_payload.images = null`.
- `include_pricing=false` persists `pricing = null` and `assistant_payload.pricing = null`.
- `include_commercial=false` persists `commercial = null` and `assistant_payload.commercial = null`.

## Known limitations

- This does not publish to any marketplace.
- This creates local reservations only after a draft is explicitly marked ready or reserved.
- This does not decrement or sell inventory.
- This does not create external marketplace IDs.
- This does not create marketplace account/auth flows.
- Physical item quantity is currently treated as one sellable item; bulk SKU inventory can be added in a later v12 milestone if a stable quantity table is introduced.
- Live provider pricing remains out of scope for this bridge.
