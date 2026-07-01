# v12.1 POS/Inventory App API Polish Plan

## 1. Current branch and baseline commit

Audit timestamp: `2026-07-01T20:23:41Z`

```text
Branch: v12.1-next
Baseline HEAD before this audit doc: 913499baebe00b5754f7ebc7f017bc75fe9c78ea
Baseline commit: 913499b docs: add v12 post-release planning
Remote tracking branch: origin/v12.1-next
```

This is the first Matthew-approved v12.1 milestone. It is an audit and planning milestone only. No product endpoint behaviour is changed by this document.

## 2. v12.0.0 stable release reference

```text
Stable release: v12.0.0 app readiness API foundation
Stable branch: main
Merge commit: aee25bb793676f445d2b3b8e3f9a62212a989588
Tag: v12.0.0
```

v12.0.0 includes canonical/app-ready card detail, batch app-ready detail, chart-ready price history, UK-primary pricing recommendation fields, deterministic listing assistant, local listing drafts, inventory-to-draft bridge, local reservation workflow, explicit local sale completion, local sales read/list API, JustTCG exposure policy guard, and release-candidate audit.

## 3. App-facing route inventory

| Route | Read-only or mutating | Current POS/frontend stability | Notes |
|---|---|---|---|
| `GET /api/v1/cards/{card_key}/detail` | Read-only | Stable enough for card detail page | Combines identity, set, images, commercial, pricing shell, provider status, warnings. No external calls. |
| `POST /api/v1/cards/detail/batch` | Read-only-style POST | Stable enough for batch card hydration | Uses POST for request body and up to 50 card keys. Supports partial success and include flags. |
| `GET /api/v1/prices/chart/cards/{card_key}` | Read-only | Stable for local chart display | Reads local `uk_price_history` only. Useful but not live-market proof. |
| `GET /api/v1/prices/cards/{card_key}` | Read-only | Stable for current app pricing shell | Has `data.recommendation`. UK-primary source is not live; no live provider calls. |
| `POST /api/v1/listings/assist/cards/{card_key}` | Local deterministic generation | Stable for draft prefill | Generates local listing copy/data. Does not publish or call marketplaces/LLMs. |
| `POST /api/v1/listings/drafts/cards/{card_key}` | Mutating local draft create | Stable for card-to-draft creation | Creates local draft from card key, but not tied to inventory workflow unless created via inventory bridge. |
| `GET /api/v1/listings/drafts/{draft_id}` | Read-only | Stable for one draft | Returns saved draft shape. Needs workflow context companion endpoint for frontend convenience. |
| `GET /api/v1/listings/drafts` | Read-only | Partly stable | Has pagination and `include_archived`; missing important POS filters. |
| `PATCH /api/v1/listings/drafts/{draft_id}` | Mutating local draft edit | Stable for safe local edits | Allows safe editable fields only. It can set status directly, which frontend should use carefully. |
| `POST /api/v1/listings/drafts/{draft_id}/archive` | Mutating local draft state | Stable | Local archive only, no deletion or marketplace action. |
| `POST /api/v1/inventory/items/{item_id}/listing-draft` | Mutating local draft/link create | Stable and high-value | Main inventory-to-listing bridge. Creates local draft and local link row. |
| `POST /api/v1/listings/drafts/{draft_id}/ready` | Mutating local workflow state | Stable | Marks ready and can reserve linked inventory. Does not sell inventory. |
| `POST /api/v1/listings/drafts/{draft_id}/reserve` | Mutating local reservation state | Stable | Creates/reuses one active local reservation. Prevents duplicate reservations per draft/item. |
| `POST /api/v1/listings/drafts/{draft_id}/unreserve` | Mutating local reservation state | Stable | Releases active reservation; can set draft back to `draft` or leave `ready`. |
| `GET /api/v1/listings/drafts/{draft_id}/reservation` | Read-only | Stable but narrow | Returns active reservation or null. Does not show sale/completion state. |
| `POST /api/v1/listings/drafts/{draft_id}/complete-sale` | Mutating sale/inventory state | Stable but high-risk action | Requires `confirm_completion=true` and active reservation. This is the only listing-draft path that marks inventory sold. |
| `GET /api/v1/sales/{sale_id}` | Read-only | Stable | Reads local sale row only. |
| `GET /api/v1/sales` | Read-only | Stable for sales list | Has useful filters; missing summary/aggregate endpoint. |

Related existing inventory routes are also app-relevant:

| Route | Read-only or mutating | Notes |
|---|---|---|
| `GET /api/v1/inventory/items` | Read-only | Existing list with `limit`, `offset`, `status`, `location_code`, and `q`. |
| `POST /api/v1/inventory/items` | Mutating | Existing item creation; not changed in v12.1 milestone 1. |
| `GET /api/v1/inventory/items/{item_id}` | Read-only | Existing item detail. Good base for POS item pages but lacks workflow summary. |
| `PUT /api/v1/inventory/items/{item_id}` | Mutating metadata | Existing safe metadata update; location changes intentionally rejected here. |
| `PATCH /api/v1/inventory/items/{item_id}/status` | Mutating inventory status | Existing direct status mutation. POS workflow should prefer explicit complete-sale when selling a draft-linked item. |
| `PATCH /api/v1/inventory/items/{item_id}/location` | Mutating location | Existing location transaction path. |
| `GET /api/v1/inventory/items/{item_id}/transactions` | Read-only | Existing item history/read path; likely enough to defer a separate v12.1 history endpoint. |
| `GET /api/v1/inventory/transactions` | Read-only | Existing global transaction feed. |
| `GET /api/v1/inventory/locations` | Read-only | Useful for POS/inventory filters. |
| `GET /api/v1/inventory/valuation` | Read-only | Useful admin/inventory overview; not central to POS workflow state. |
| `GET /api/v1/inventory/items/{item_id}/photos` | Read-only | Physical item photos exist separately from app-ready card image metadata. |

## 4. Stable object identifiers

Stable identifiers already present and suitable for app clients:

| Identifier | Resource | Stability notes |
|---|---|---|
| `card_key` | Localized card row | Public v1 durable key in `{language_code}:{card_id}` form, e.g. `en:sv03-223`. |
| `canonical_card_key` | Canonical printing linkage | Used internally through `canonical_printings`; inventory bridge resolves SKU to this before draft creation. |
| `canonical_printing_id` | Canonical identity | Present in app-ready detail/commercial data. Useful for dedupe and cross-source grouping. |
| `commercial_variant_id` | Commercial variant | Present in listing assistant/commercial data when resolved. Useful for SKU/finish-specific app views. |
| `sellable_sku_id` / `sku_id` | Inventory SKU | Inventory uses integer `sku_id`; listing assistant commercial payload may expose sellable SKU ID. Naming should be clarified for clients. |
| `item_id` / `inventory_item_id` | Physical inventory item | Existing inventory routes use `item_id`; v12 sale/reservation/listing-link payloads use `inventory_item_id`. This is semantically the same physical item key. |
| `draft_id` | Local listing draft | Stable local draft key, prefix `ld_...`. |
| `reservation_id` | Local draft inventory reservation | Stable local reservation key, prefix `ldr_...`. |
| `sale_id` | Local sale record | Stable local sale key, prefix `sale_...`. |
| `tenant_id` | Tenant boundary | Present on inventory responses; not central to app routing but useful for admin/debug. |

Naming finding: `item_id` and `inventory_item_id` are both used for the same physical item concept. This is acceptable for storage/history but awkward for client developers. Future response docs should explicitly state that `inventory_item_id` references `physical_items.item_id` and the inventory route path parameter `{item_id}`.

## 5. Inventory API observations

Stable enough now:

- A POS/inventory app can list inventory with basic filters using `GET /api/v1/inventory/items`.
- It can read one item via `GET /api/v1/inventory/items/{item_id}`.
- Item detail includes `sku_identity`, condition, certification fields, location, status, current value, images, last transaction, tenant, and timestamps.
- Item transactions already exist via `GET /api/v1/inventory/items/{item_id}/transactions`, reducing the urgency of a separate history endpoint.
- Location and status mutations already have dedicated transaction-aware endpoints.

Awkward/inconsistent for app clients:

- The inventory item response does not include listing workflow state: linked draft IDs, active reservation, completed sale, or whether the item is already part of a local listing workflow.
- A frontend must manually call draft list/read, reservation read, sales list, and inventory transactions to reconstruct one item's workflow state.
- The item image/photos model is separate from card app-ready image metadata; clients need clearer guidance on when to use card image fields vs physical item photos.
- `GET /api/v1/inventory/items` has general inventory filters but no workflow filters such as `has_draft`, `has_reservation`, `has_sale`, or `card_key`.

## 6. Listing draft API observations

Stable enough now:

- Drafts can be created from a card key or from a physical inventory item.
- Drafts can be read individually and listed with pagination.
- Drafts can be patched with safe local editable fields only: title, subtitle, bullets, tags, condition, finish, quantity, status, and notes.
- Drafts can be archived locally.
- Draft payloads preserve listing assistant output, pricing, images, commercial data, platform guidance, provider status, warnings, and source contract.

Awkward/inconsistent for app clients:

- `GET /api/v1/listings/drafts` currently supports `include_archived`, `limit`, and `offset` only. It lacks filters a POS/frontend would expect: `status`, `platform`, `card_key`, `inventory_item_id`, `has_reservation`, and `has_sale`.
- The individual draft read does not include its inventory link or sale state unless the client also calls `/reservation` and `/sales?draft_id=...`.
- Sale completion leaves `listing_drafts.status` as `ready`; sale state lives in `listing_draft_sales.status=completed`. This is correct for backwards compatibility but awkward for UI badges unless a workflow summary endpoint composes it.
- Response models for drafts are currently `dict[str, Any]` in Pydantic (`ListingDraftResponseV1.data`). That is flexible but less self-documenting for generated clients than named nested models.

## 7. Reservation workflow observations

Stable enough now:

- `POST /api/v1/listings/drafts/{draft_id}/ready` sets draft status to `ready` and, by default, reserves linked inventory where a link exists.
- `POST /api/v1/listings/drafts/{draft_id}/reserve` creates or reuses an active reservation.
- `POST /api/v1/listings/drafts/{draft_id}/unreserve` releases the active reservation and can reset draft status.
- `GET /api/v1/listings/drafts/{draft_id}/reservation` returns the active reservation or null.
- Active uniqueness constraints prevent duplicate reservations per draft and per inventory item.
- Reservation-only paths do not publish listings, decrement stock, or mark inventory sold.

Awkward/inconsistent for app clients:

- The reservation read endpoint only returns the active reservation. It does not expose completed/released history, so clients need sales reads or transactions to understand completed workflows.
- Reservation status supports `reserved`, `released`, and `completed`, but `GET /reservation` intentionally focuses on active reservation only. A workflow endpoint should compose active and latest completed state.
- `notes` exists on `ListingDraftReserveRequestV1` but current reservation table does not store reservation notes separately. Treat it as future-proof/request parity rather than current persisted state unless implementation changes later.

## 8. Sale completion observations

Stable enough now:

- `POST /api/v1/listings/drafts/{draft_id}/complete-sale` is explicit and guarded by `confirm_completion=true`.
- It requires an inventory-linked draft and active local reservation.
- It rejects archived drafts, missing reservation, duplicate completion, and unavailable inventory.
- It creates a local `listing_draft_sales` row, changes reservation to `completed`, marks the physical item `sold`, and writes inventory transaction/snapshot records.
- It is the only listing-draft path that marks inventory sold.

Awkward/inconsistent for app clients:

- This is a high-impact mutation and should remain separated from marketplace integration and frontend convenience shortcuts.
- Response includes `sale`, `draft`, `reservation`, and a small `inventory_item` status summary, but subsequent reads require separate sale/draft/inventory/reservation endpoints.
- The request field `external_order_reference` is plain local text only. Frontend copy must avoid implying marketplace order import or marketplace validation.

## 9. Local sales read/list observations

Stable enough now:

- `GET /api/v1/sales/{sale_id}` reads one local sale.
- `GET /api/v1/sales` lists local sales with filters: `draft_id`, `inventory_item_id`, `card_key`, `platform`, `status`, `date_from`, `date_to`, `limit`, and `offset`.
- Sales reads are read-only and do not mutate inventory, reservations, or sale rows.
- The default list status is `completed`, which is sensible for POS history.

Awkward/inconsistent for app clients:

- There is no sales summary/aggregate endpoint yet for totals, counts, date buckets, or platform breakdown.
- The list endpoint is useful for one draft/item lookup, but clients must know to call `GET /api/v1/sales?draft_id=...` or `?inventory_item_id=...` to reconstruct workflow state.
- There is no explicit profit/margin layer; acquired price exists on inventory item and sale price exists on sale, but calculations are not exposed.

## 10. Card/detail/image fields needed by POS clients

Current support:

- A POS app can find cards through existing v1 search/card routes and hydrate selected cards with `GET /api/v1/cards/{card_key}/detail`.
- It can show a card detail page from the app-ready detail endpoint.
- It can show card image status using `images.primary_image_url`, `images.signed_image_url`, `images.has_local_image`, `images.missing_image`, and `images.image_policy_status` from app-ready detail.
- It can reduce payload size via batch/detail include flags.
- It can use listing assistant output for title, description bullets, tags, image candidates, pricing, and commercial identity.

Needs clearer client guidance:

- Card app-ready images and physical inventory photos are different concepts. Card images describe reference/display art for the card; inventory photos describe the specific physical item. POS/frontend documentation should describe when to show each.
- App-ready card pricing is a local/UK-primary shell. It must not be displayed as live UK sold pricing unless real UK external evidence is present.
- JustTCG-derived pricing may be used in SaveRoom-owned apps through the backend under the exposure policy, but standalone external developer pricing/data-feed exposure remains blocked.

## 11. Response-shape consistency findings

What is consistent:

- Most v12 endpoints use a top-level `data` object plus `metadata` with `api_version`, `contract`, and `generated_at`.
- List endpoints use a project-standard `pagination` object with `limit`, `offset`, `count`, `total`, and `has_more`.
- Error paths use explicit code/message/details patterns in tests and docs.
- Local workflow payloads avoid raw provider data, raw filesystem paths, keys, headers, and marketplace account metadata.

What is awkward:

- Draft, reservation, sale-completion, and local-sale response models keep `data` as `dict[str, Any]`, which makes generated client typing weaker.
- `GET /api/v1/listings/drafts/{draft_id}/reservation` returns the same envelope as mutating reservation endpoints, even when used read-only; that is acceptable but may surprise client developers.
- Inventory item responses do not include v12 workflow sections, while v12 workflow responses include only partial inventory summaries.
- Sale completion uses `status` in two places with different meanings: draft status can remain `ready`, while sale status becomes `completed` and reservation status becomes `completed`. A composed workflow view would prevent UI ambiguity.

## 12. Missing filters or convenience reads

Highest-value missing reads/filters:

1. `GET /api/v1/inventory/items/{item_id}/workflow` — read-only composed workflow state for one physical item.
2. `GET /api/v1/listings/drafts/{draft_id}/workflow` — read-only composed workflow state for one draft.
3. `GET /api/v1/listings/drafts` filters: `status`, `platform`, `card_key`, `inventory_item_id`, `has_reservation`, `has_sale`.
4. `GET /api/v1/sales/summary` — read-only summary totals by date/platform/status/card/inventory item.
5. Dedicated inventory history alias only if the existing `GET /api/v1/inventory/items/{item_id}/transactions` is not app-friendly enough.

Current assessment: the inventory history candidate is less urgent because transaction history already exists. The workflow-summary gap is more urgent because no single endpoint currently answers "what is happening with this item/draft in the listing workflow?".

## 13. Safety boundaries

These boundaries remain active for v12.1 milestone 1 and the next implementation milestone:

- Do not run live provider calls.
- Do not spend API credits.
- Do not call `_get_justtcg_price_data()`.
- Do not call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs.
- Do not publish listings.
- Do not create marketplace listings.
- Do not import marketplace orders.
- Do not capture payments.
- Do not add marketplace auth/account flows.
- Do not expose API keys, headers, account metadata, raw provider JSON, sanitized candidates, private provider payloads, or raw filesystem paths.
- Do not connect JustTCG-derived pricing to standalone external developer pricing APIs or data feeds.
- Keep marketplace platform labels (`whatnot`, `ebay`, `shopify`, `generic`, `offline`) as local labels only unless a future approved milestone explicitly adds marketplace integration.

Important mutation boundary: `POST /api/v1/listings/drafts/{draft_id}/complete-sale` is the only listing-draft workflow route that may mark a physical inventory item sold. New v12.1 workflow-summary endpoints should be read-only.

## 14. Recommended v12.1 implementation milestones

Ranked candidates:

### 1. Recommended: inventory item workflow summary endpoint

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

Why this should be next:

- It is read-only and therefore lower risk than new mutations.
- It directly answers the hardest POS question: "what is the current workflow state for this physical item?"
- It composes already-existing local data rather than introducing marketplace/provider dependencies.
- It helps a POS/frontend decide which buttons to show: create draft, view draft, mark ready, reserve, complete sale, read sale, or show sold state.
- It avoids changing existing endpoint behaviour.

Suggested response sections:

```text
inventory_item: minimal physical item identity/status/location
card: card_key and SKU/card identity summary when available
listing_draft_link: latest linked draft or null
active_reservation: active reservation or null
latest_sale: completed sale for the item or null
workflow_state: not_listed | draft_created | ready | reserved | sold | archived_or_inactive
available_actions: safe UI action hints only, not executable marketplace actions
warnings: local-only / marketplace-not-connected warnings when relevant
metadata: api_version, contract, generated_at
```

Safety notes:

- Read-only only.
- No status changes.
- No sale creation.
- No provider/marketplace/LLM calls.
- No marketplace IDs or credentials.

### 2. Listing draft workflow summary endpoint

```text
GET /api/v1/listings/drafts/{draft_id}/workflow
```

Useful for draft-detail pages and likely a close follow-up. It should compose draft, inventory link, active/latest reservation, sale state, and allowed local next actions. It is slightly less useful as the first milestone because POS users often start from a physical item scan or inventory list rather than an existing draft ID.

### 3. Improved listing draft list filters

```text
GET /api/v1/listings/drafts?status=ready&platform=whatnot&card_key=en:sv03-223&inventory_item_id=...&has_reservation=true&has_sale=false
```

Useful once workflow summaries exist. It should be implemented with bound SQL parameters and contract tests. This is low-risk but less immediately clarifying than a one-item workflow endpoint.

### 4. Local sales summary endpoint

```text
GET /api/v1/sales/summary
```

Useful for reporting, but less foundational for POS workflow navigation. It should stay read-only and avoid profit/marketplace reconciliation until explicitly approved.

### 5. Inventory item history endpoint

```text
GET /api/v1/inventory/items/{item_id}/history
```

Lower priority because `GET /api/v1/inventory/items/{item_id}/transactions` already exists. Consider only if the existing transaction shape is too raw for app clients.

## 15. Explicit no-go items for v12.1 milestone 1

Milestone 1 is only this audit and planning document. It does not implement product endpoint changes.

Do not include in this milestone:

- No endpoint behaviour changes.
- No new database migrations.
- No new marketplace integrations.
- No live pricing/provider fetches.
- No listing publication.
- No marketplace order import.
- No payment capture.
- No inventory state changes.
- No sale creation or mutation.
- No v13 branch/versioning work.
- No commits of `.env`, `.env.local`, `private_provider_payloads/`, raw provider JSON, sanitized candidates, API keys, headers, account metadata, or the unrelated report/visual docs.

## POS/frontend questions answered

| Question | Current answer |
|---|---|
| Can a POS app find a card quickly? | Yes, through existing v1 search/card APIs, then hydrate with app-ready detail or batch detail. |
| Can it show a card detail page? | Yes. `GET /api/v1/cards/{card_key}/detail` is stable enough for this. |
| Can it show local image status? | Yes for card images via app-ready detail; physical item photos are separate inventory photo endpoints. |
| Can it create a listing draft from an inventory item? | Yes. `POST /api/v1/inventory/items/{item_id}/listing-draft`. |
| Can it mark a draft ready? | Yes. `POST /api/v1/listings/drafts/{draft_id}/ready`. |
| Can it reserve inventory? | Yes for inventory-linked drafts through `/ready` or `/reserve`. |
| Can it complete a local sale? | Yes, through explicit `POST /api/v1/listings/drafts/{draft_id}/complete-sale` with confirmation and active reservation. |
| Can it read completed sales? | Yes. `GET /api/v1/sales/{sale_id}` and `GET /api/v1/sales` with filters. |
| Can it reconstruct workflow state for one inventory item? | Yes, but awkwardly: it must combine inventory item, listing draft links/listing reads, reservation reads, sales filters, and transactions. Recommended next endpoint should compose this. |
| Can it reconstruct workflow state for one listing draft? | Yes, but awkwardly: it must combine draft read, reservation read, sales filtered by `draft_id`, and possibly inventory item read. |
| What is still awkward for a frontend? | Missing composed workflow state, weak draft list filters, mixed `item_id`/`inventory_item_id` naming, separate card-image vs physical-photo concepts, and `draft.status` not reflecting completed sale state. |
| What should be added next without marketplace integration? | Read-only `GET /api/v1/inventory/items/{item_id}/workflow` as the first implementation milestone. |

## Recommended next action

Ask Matthew to approve the first v12.1 implementation milestone:

```text
GET /api/v1/inventory/items/{item_id}/workflow
```

Scope should be read-only composition of existing local data, with fixture-backed tests and explicit no-provider/no-marketplace/no-LLM guards.
