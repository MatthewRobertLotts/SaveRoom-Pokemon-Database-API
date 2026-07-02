# v12.2 POS-Ready Fixture Pack

Tags: #type/doc #pokemon-db #v12-2 #pos #fixtures

## Overview

v12.2 milestone 2 adds a stable, sanitized fixture pack for future POS/frontend/mock integration.

The fixture pack is documentation/test data only. It does not add or change API endpoint behavior, does not call live providers, and does not connect to marketplace accounts.

## Body

### Purpose

The pack gives frontend and POS work a safe set of static response examples for layout, local mocks, component fixtures, and visual/regression checks.

It is intentionally:

```text
read-only
local-only
sanitized
stable for frontend mockups
safe to commit
not generated from live provider calls
not connected to marketplace accounts
not a new product feature endpoint
```

### Fixture list

| Fixture | Endpoint / flow represented |
|---|---|
| `docs/fixtures/v12_2_pos/card_detail_response.json` | `GET /api/v1/cards/{card_key}/detail` |
| `docs/fixtures/v12_2_pos/inventory_item_list_filtered_response.json` | `GET /api/v1/inventory/items` with POS filters |
| `docs/fixtures/v12_2_pos/inventory_item_workflow_response.json` | `GET /api/v1/inventory/items/{item_id}/workflow` |
| `docs/fixtures/v12_2_pos/listing_draft_workflow_response.json` | `GET /api/v1/listings/drafts/{draft_id}/workflow` |
| `docs/fixtures/v12_2_pos/listing_draft_list_filtered_response.json` | `GET /api/v1/listings/drafts` with filters |
| `docs/fixtures/v12_2_pos/local_sales_summary_response.json` | `GET /api/v1/sales/summary` |
| `docs/fixtures/v12_2_pos/README.md` | Fixture usage guide |

### Sanitization rules

The fixtures use fixture-style local IDs and fake local references:

```text
item_fixture_001
ld_fixture_001
sale_fixture_001
sku_id: 1001
card_key: en:sv03-223
platform: generic
buyer_reference: fixture-buyer
external_order_reference: fixture-order
```

They may include public/non-sensitive card identity fields needed for UI realism, but they avoid private or account-specific values.

### Forbidden fields and markers

The fixture JSON files must not contain:

```text
API keys
auth tokens
private provider payload paths
raw provider JSON
sanitized candidates
account metadata
real marketplace account IDs
real external order IDs
real buyer names
real emails
real addresses
raw filesystem paths
/home/matt
/media/matt/Storage
.env values
Whatnot/eBay/Shopify listing IDs
LLM prompts
LLM responses
```

### Relationship to v12.1 workflow endpoints

The workflow fixtures mirror the read-only v12.1 workflow endpoints:

```text
GET /api/v1/inventory/items/{item_id}/workflow
GET /api/v1/listings/drafts/{draft_id}/workflow
```

They demonstrate linked local draft/reservation/sale state without creating or mutating any real workflow rows.

### Relationship to v12.2 inventory item list filters

The inventory list fixture demonstrates the v12.2 milestone 1 search/filter surface:

```text
sku_id
card_key
condition
status
location_code
has_listing_draft
has_active_reservation
has_completed_sale
```

### Known limitations

- Fixtures are static examples, not generated contract snapshots.
- Fixtures are not a replacement for `pytest` contract/API tests.
- Prices are illustrative fixture values, not market evidence.
- Completed sale records are local SaveRoom workflow examples, not marketplace reconciliation.
- Image URLs use `example.invalid` and are not intended to load real assets.

### Future frontend integration notes

Frontend/POS work can load these files directly for mock API adapters, Storybook-like component states, local visual checks, and design conversations. Keep future fixture additions synthetic and review them with the same forbidden-marker tests before committing.

## Links

- Related: [Fixture README](fixtures/v12_2_pos/README.md)
- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.2 Inventory Item List Filters](V12_2_INVENTORY_ITEM_LIST_FILTERS.md)
- Related: [V12.1 Inventory Item Workflow Endpoint](V12_1_INVENTORY_ITEM_WORKFLOW_ENDPOINT.md)
- Related: [V12.1 Listing Draft Workflow Endpoint](V12_1_LISTING_DRAFT_WORKFLOW_ENDPOINT.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
