# v12.2 POS-Ready Fixture Pack

Tags: #type/fixtures #pokemon-db #v12-2 #pos

## Overview

This fixture pack provides stable, sanitized example JSON responses for POS and frontend mock work.

The files are hand-authored static fixtures that resemble current v12/v12.1/v12.2 app-facing response shapes. They are not generated from live provider data, are not connected to marketplace accounts, and are not order/payment records.

## Body

### Fixture files

| File | Represents | Endpoint shape |
|---|---|---|
| `card_detail_response.json` | App-ready card detail | `GET /api/v1/cards/{card_key}/detail` |
| `inventory_item_list_filtered_response.json` | Filtered inventory item list | `GET /api/v1/inventory/items` |
| `inventory_item_workflow_response.json` | Inventory-item workflow summary | `GET /api/v1/inventory/items/{item_id}/workflow` |
| `listing_draft_workflow_response.json` | Listing-draft workflow summary | `GET /api/v1/listings/drafts/{draft_id}/workflow` |
| `listing_draft_list_filtered_response.json` | Filtered listing draft list | `GET /api/v1/listings/drafts` |
| `local_sales_summary_response.json` | Local sales summary | `GET /api/v1/sales/summary` |

### Safety

These fixtures are sanitized and safe for frontend/POS mock work. They use fixture-style IDs such as `item_fixture_001`, `ld_fixture_001`, `sale_fixture_001`, `sku_id: 1001`, `card_key: en:sv03-223`, `platform: generic`, `buyer_reference: fixture-buyer`, and `external_order_reference: fixture-order`.

They are local examples only. They are not live provider data, not marketplace publication data, not imported orders, not payment data, and not fulfilment/shipping state.

### How frontend work should use them

Use these files as static mock responses for layout, component states, local demos, and visual regression fixtures. They are not a substitute for API contract tests or live endpoint verification.

## Links

- Related: [V12.2 POS Ready Fixture Pack](../../V12_2_POS_READY_FIXTURE_PACK.md)
- Related: [V12.2 Inventory Item List Filters](../../V12_2_INVENTORY_ITEM_LIST_FILTERS.md)
- Related: [API Contract v1](../../API_CONTRACT_V1.md)
