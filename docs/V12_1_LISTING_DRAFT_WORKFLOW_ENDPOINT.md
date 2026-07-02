# v12.1 Listing Draft Workflow Endpoint

## Overview

v12.1 milestone 3 adds a read-only workflow summary endpoint for one local listing draft.

It answers the POS/frontend question: what is the current workflow state for this listing draft?

It is the draft-first companion to:

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

## Endpoint path

```text
GET /api/v1/listings/drafts/{draft_id}/workflow
```

Auth follows the existing listing draft read convention: v1 API key when auth is required.

## Read-only behaviour

The endpoint only reads existing local data. It does not:

- change `listing_drafts.status`;
- create or update listing drafts;
- create, release, or complete reservations;
- create or update sale rows;
- change `physical_items.status`;
- mark inventory sold;
- create marketplace listings;
- import marketplace orders;
- capture payments;
- call providers, marketplaces, network APIs, or LLM APIs.

## Composed local tables

The response composes existing local state from:

```text
listing_drafts
inventory_listing_draft_links
physical_items
inventory_transactions
item_images
price_snapshots
listing_draft_inventory_reservations
listing_draft_sales
```

The endpoint does not introduce a new persistent workflow state table. It derives workflow state from current local draft, inventory, reservation, and sale records.

## Response model

```text
ListingDraftWorkflowMetadataV1
ListingDraftWorkflowResponseV1
```

## Response shape

```json
{
  "data": {
    "draft_id": "ld_...",
    "current_state": "ready",
    "draft": {},
    "listing_draft_link": null,
    "inventory_item": null,
    "reservation": null,
    "sale": null,
    "summary": {
      "is_inventory_linked": false,
      "has_active_reservation": false,
      "has_completed_sale": false,
      "is_ready": true,
      "is_archived": false,
      "is_sold": false,
      "can_reserve": false,
      "can_complete_sale": false
    }
  },
  "metadata": {
    "api_version": "v1",
    "contract": "v12.1-listing-draft-workflow",
    "generated_at": "..."
  }
}
```

## `current_state` values

Allowed values:

```text
draft
ready
reserved
sold
archived
unlinked
unavailable
unknown
```

Derivation order:

1. Completed local sale exists, or linked physical inventory status is `sold` → `sold`.
2. Draft status is `archived` → `archived`.
3. Active reservation exists → `reserved`.
4. Draft status is `ready` → `ready`.
5. Linked physical inventory status is an unavailable/lost-style local status → `unavailable`.
6. Draft status is `draft` → `draft`.
7. No inventory link exists and draft status does not already explain the state → `unlinked`.
8. Other unclear states → `unknown`.

Documented choice: a card-only draft with `listing_drafts.status = draft` returns `current_state = draft`, not `unlinked`, because the draft's own persisted status already explains the local state. `unlinked` is reserved for unlinked drafts whose draft status does not explain the state.

A linked physical item manually marked sold without a local `listing_draft_sales` row returns `sold`. That reflects existing inventory status truth but is not treated as marketplace reconciliation.

## Summary booleans

| Field | Meaning |
|---|---|
| `is_inventory_linked` | True when the latest `inventory_listing_draft_links` row exists for the draft. |
| `has_active_reservation` | True when the draft has an active `reserved` reservation. |
| `has_completed_sale` | True when a completed local `listing_draft_sales` row exists for the draft. |
| `is_ready` | True when `listing_drafts.status = ready`. |
| `is_archived` | True when `listing_drafts.status = archived`. |
| `is_sold` | True when derived `current_state = sold`. |
| `can_reserve` | True only when the draft is inventory-linked, currently in `draft` or `ready` state, has no active reservation, and has no completed sale. |
| `can_complete_sale` | True only when the draft is inventory-linked, has an active reservation, has no completed sale, and is not archived. |

The `can_*` fields are UI hints only. They do not execute marketplace actions and are not permission grants.

## Included sections

| Section | Contents |
|---|---|
| `draft` | Existing listing draft response shape. |
| `listing_draft_link` | Latest `inventory_listing_draft_links` row for the draft, or null. |
| `inventory_item` | Existing physical item detail-style shape when the draft is linked to an inventory item, or null. |
| `reservation` | Active reservation when present; otherwise latest reservation if it explains released/completed state; otherwise null. |
| `sale` | Latest completed local sale for the draft, or null. |
| `summary` | Frontend-friendly workflow booleans and safe next-action hints. |

## Relationship to inventory item workflow endpoint

`GET /api/v1/inventory/items/{item_id}/workflow` starts from a physical item and answers "what listing workflow is this item in?"

`GET /api/v1/listings/drafts/{draft_id}/workflow` starts from a draft and answers "what inventory/reservation/sale workflow is this draft in?"

Both endpoints are read-only, local-only, and compose the same existing tables from different starting IDs.

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

- The endpoint reports the latest inventory-to-draft link only. It is a current workflow summary, not a full historical timeline.
- It returns active reservation first; if no active reservation exists, it returns the latest reservation for context.
- Sale summaries are local `listing_draft_sales` rows only. There is no marketplace reconciliation, fulfilment, refund, payment, or shipment state.
- `can_reserve` and `can_complete_sale` are local UI hints, not substitute validation for mutating endpoints.
- Listing draft list filters were added in v12.1 milestone 4 for `status`, `platform`, `card_key`, `inventory_item_id`, `has_reservation`, and `has_sale`; this workflow endpoint remains the per-draft detail companion rather than changing list item shape.

## Tests

Coverage lives in:

```text
tests/test_v12_1_listing_draft_workflow_api.py
```

The tests cover endpoint existence, missing draft 404, card-only draft state, inventory-linked draft state, ready/reserved/sold/archived/unavailable states, linked sold inventory without sale context, composed response sections, summary booleans, `can_reserve`, `can_complete_sale`, no inventory/draft/reservation/sale mutation, no provider/network/marketplace/LLM calls, and no sensitive/provider/filesystem leakage. Listing-level filters are covered separately in `tests/test_v12_1_listing_draft_list_filters_api.py`.
