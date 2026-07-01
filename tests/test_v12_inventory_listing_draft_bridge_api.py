"""Tests for v12 local inventory-to-listing draft bridge.

The bridge converts owned local inventory items into local listing drafts only.
It must not call live providers, marketplace APIs, network endpoints, or LLMs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import create_app


client = TestClient(create_app())


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(client.app.state.db))
    conn.row_factory = sqlite3.Row
    return conn


def _first_sku_id() -> int:
    with _db() as conn:
        row = conn.execute("SELECT sku_id FROM sellable_skus ORDER BY sku_id LIMIT 1").fetchone()
    assert row is not None, "test database must include at least one sellable_skus row"
    return int(row["sku_id"])


def _create_inventory_item(*, condition: str = "Near Mint", status: str = "owned", notes: str = "v12 bridge test") -> str:
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": _first_sku_id(),
            "item_condition": condition,
            "acquired_date": "2026-07-01",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": "local test fixture",
            "location_code": "Bridge Test Shelf",
            "status": status,
            "notes": notes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item_id"]


def _create_item_without_card_key() -> str:
    item_id = str(uuid.uuid4())
    sku_id = 987654321
    with _db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sellable_skus(
                sku_id, printing_id, variant_id, language_code, condition_code, sku_key, status
            ) VALUES (?, ?, NULL, 'en', 'NM', ?, 'active')
            """,
            (sku_id, 987654321, f"missing-card-key-{item_id}"),
        )
        conn.execute(
            """
            INSERT INTO physical_items(
                item_id, sku_id, item_condition, acquired_date, acquired_price, acquired_currency,
                acquired_source, location_code, status, notes, tenant_id, created_by, created_at, updated_at
            ) VALUES (?, ?, 'Near Mint', '2026-07-01', 1.0, 'GBP', 'fixture', 'Bridge Test Shelf',
                      'owned', 'missing card key fixture', 1, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (item_id, sku_id),
        )
        conn.commit()
    return item_id


def _create_bridge_draft(item_id: str, payload: dict | None = None):
    body = {"platform": "generic"}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.post(f"/api/v1/inventory/items/{item_id}/listing-draft", json=body)
    return response, mock_fetch


def _read_draft(draft_id: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.get(f"/api/v1/listings/drafts/{draft_id}")
    return response, mock_fetch


def test_endpoint_exists_and_known_inventory_item_creates_listing_draft():
    item_id = _create_inventory_item(condition="Near Mint")

    response, mock_fetch = _create_bridge_draft(item_id, {"platform": "ebay"})

    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    body = response.json()
    assert body["metadata"]["contract"] == "v12-inventory-listing-draft-bridge"
    data = body["data"]
    assert data["draft"]["draft_id"].startswith("ld_")
    assert data["inventory_source"]["item_id"] == item_id
    assert data["inventory_source"]["linked"] is True


def test_created_draft_can_be_read_through_existing_listing_draft_endpoint():
    item_id = _create_inventory_item(condition="Excellent")
    created, _ = _create_bridge_draft(item_id, {"platform": "shopify"})
    assert created.status_code == 201, created.text
    created_data = created.json()["data"]
    draft_id = created_data["draft"]["draft_id"]

    read, mock_fetch = _read_draft(draft_id)

    assert read.status_code == 200, read.text
    mock_fetch.assert_not_called()
    read_data = read.json()["data"]
    assert read_data["draft_id"] == draft_id
    assert read_data["card_key"] == created_data["inventory_source"]["card_key"]
    assert read_data["card_key"] == created_data["draft"]["card_key"]


def test_condition_finish_and_quantity_default_from_inventory_where_available():
    item_id = _create_inventory_item(condition="Lightly Played")

    response, _ = _create_bridge_draft(item_id)

    assert response.status_code == 201, response.text
    source = response.json()["data"]["inventory_source"]
    draft = response.json()["data"]["draft"]
    assert source["quantity_requested"] == 1
    assert source["quantity_available"] == 1
    assert source["condition"] == "Lightly Played"
    assert draft["condition"] == "Lightly Played"
    assert draft["quantity"] == 1


def test_request_overrides_condition_finish_and_quantity():
    item_id = _create_inventory_item(condition="Played")

    response, _ = _create_bridge_draft(
        item_id,
        {"condition": "Near Mint", "finish": "Holo", "quantity": 1, "platform": "whatnot"},
    )

    assert response.status_code == 201, response.text
    source = response.json()["data"]["inventory_source"]
    draft = response.json()["data"]["draft"]
    assert source["condition"] == "Near Mint"
    assert source["finish"] == "Holo"
    assert source["quantity_requested"] == 1
    assert draft["condition"] == "Near Mint"
    assert draft["finish"] == "Holo"
    assert draft["quantity"] == 1
    assert draft["platform"] == "whatnot"


def test_quantity_greater_than_available_stock_is_rejected():
    item_id = _create_inventory_item(condition="Near Mint")

    response, mock_fetch = _create_bridge_draft(item_id, {"quantity": 2})

    assert response.status_code == 409, response.text
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "inventory_quantity_unavailable"


def test_missing_inventory_item_returns_404():
    response, mock_fetch = _create_bridge_draft("not-a-real-item-id")

    assert response.status_code == 404
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "item_not_found"


def test_inventory_item_without_card_key_returns_safe_conflict_not_500():
    item_id = _create_item_without_card_key()

    response, mock_fetch = _create_bridge_draft(item_id)

    assert response.status_code == 409, response.text
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "inventory_item_missing_card_key"


def test_include_images_false_persists_images_null():
    item_id = _create_inventory_item()

    response, _ = _create_bridge_draft(item_id, {"include_images": False})

    assert response.status_code == 201, response.text
    draft = response.json()["data"]["draft"]
    assert draft["images"] is None
    assert draft["assistant_payload"]["images"] is None


def test_include_pricing_false_persists_pricing_null():
    item_id = _create_inventory_item()

    response, _ = _create_bridge_draft(item_id, {"include_pricing": False})

    assert response.status_code == 201, response.text
    draft = response.json()["data"]["draft"]
    assert draft["pricing"] is None
    assert draft["assistant_payload"]["pricing"] is None
    assert "Pricing omitted because include_pricing=false." in draft["warnings"]


def test_include_commercial_false_persists_commercial_null():
    item_id = _create_inventory_item()

    response, _ = _create_bridge_draft(item_id, {"include_commercial": False})

    assert response.status_code == 201, response.text
    draft = response.json()["data"]["draft"]
    assert draft["commercial"] is None
    assert draft["assistant_payload"]["commercial"] is None


def test_no_live_provider_marketplace_llm_calls_and_provider_status_safe():
    item_id = _create_inventory_item()

    response, mock_fetch = _create_bridge_draft(item_id, {"platform": "ebay"})

    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    provider_status = response.json()["data"]["draft"]["provider_status"]
    assert provider_status["justtcg"]["status"] == "not_used_for_listing_assistant"
    assert provider_status["justtcg"]["live_enabled"] is False
    payload_text = json.dumps(response.json()).lower()
    forbidden_live_markers = [
        "published_listing_id",
        "marketplace_account",
        "whatnot_listing_id",
        "shopify_product_id",
        "llm_prompt",
        "llm_response",
    ]
    for marker in forbidden_live_markers:
        assert marker not in payload_text


def test_no_usd_or_justtcg_fallback_leaks_into_bridge_pricing():
    item_id = _create_inventory_item()

    response, _ = _create_bridge_draft(item_id, {"platform": "ebay"})

    assert response.status_code == 201, response.text
    pricing_text = json.dumps(response.json()["data"]["draft"]["pricing"]).lower()
    assert "usd" not in pricing_text
    assert "justtcg_fallback" not in pricing_text
    assert "market_price" not in pricing_text
    assert "4.99" not in pricing_text


def test_no_raw_filesystem_paths_provider_payloads_headers_private_paths_or_candidates_appear():
    item_id = _create_inventory_item()

    response, _ = _create_bridge_draft(item_id, {"platform": "shopify"})

    assert response.status_code == 201, response.text
    payload_text = json.dumps(response.json()).lower()
    forbidden = [
        "/media/",
        "/home/",
        "private_provider_payloads",
        "x-api-key",
        "authorization",
        "raw provider",
        "sanitized candidates",
        "account metadata",
    ]
    for marker in forbidden:
        assert marker not in payload_text
