"""Tests for v12 explicit local listing draft sale completion.

Sale completion is the first local-only workflow that may mark physical
inventory sold. It must require explicit confirmation, require an active local
reservation, create a local sale record, and avoid provider, marketplace, and
LLM calls.
"""
from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import create_app


client = TestClient(create_app())
TEST_CARD_KEY = "en:sv03-223"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(client.app.state.db))
    conn.row_factory = sqlite3.Row
    return conn


def _first_sku_id() -> int:
    with _db() as conn:
        row = conn.execute("SELECT sku_id FROM sellable_skus ORDER BY sku_id LIMIT 1").fetchone()
    assert row is not None, "test database must include at least one sellable_skus row"
    return int(row["sku_id"])


def _create_inventory_item(*, condition: str = "Near Mint", status: str = "owned") -> str:
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": _first_sku_id(),
            "item_condition": condition,
            "acquired_date": "2026-07-01",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": "local sale completion test fixture",
            "location_code": "Sale Completion Test Shelf",
            "status": status,
            "notes": "v12 sale completion test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item_id"]


def _create_inventory_draft(item_id: str, payload: dict | None = None) -> dict:
    body = {"platform": "generic", "include_pricing": False}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.post(f"/api/v1/inventory/items/{item_id}/listing-draft", json=body)
    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    return response.json()["data"]


def _create_card_draft(payload: dict | None = None) -> dict:
    body = {"platform": "generic", "include_pricing": False}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.post(f"/api/v1/listings/drafts/cards/{TEST_CARD_KEY}", json=body)
    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    return response.json()["data"]


def _post(path: str, payload: dict | None = None):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(path, json=payload or {})
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _get(path: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.get(path)
    mock_fetch.assert_not_called()
    return response


def _ready_and_reserved_draft(*, item_status: str = "owned", quantity: int = 1) -> tuple[str, str, dict]:
    item_id = _create_inventory_item(status=item_status)
    created = _create_inventory_draft(item_id, {"quantity": quantity})
    draft_id = created["draft"]["draft_id"]
    ready = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})
    assert ready.status_code == 200, ready.text
    assert ready.json()["data"]["reservation"]["status"] == "reserved"
    return item_id, draft_id, ready.json()["data"]["reservation"]


def _inventory_item(item_id: str) -> dict:
    response = client.get(f"/api/v1/inventory/items/{item_id}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _active_reservation_count(*, draft_id: str | None = None, item_id: str | None = None) -> int:
    where = ["status = 'reserved'"]
    params: list[str] = []
    if draft_id is not None:
        where.append("draft_id = ?")
        params.append(draft_id)
    if item_id is not None:
        where.append("inventory_item_id = ?")
        params.append(item_id)
    with _db() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM listing_draft_inventory_reservations WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
    return int(row["c"])


def _sale_row(sale_id: str) -> sqlite3.Row:
    with _db() as conn:
        row = conn.execute("SELECT * FROM listing_draft_sales WHERE sale_id = ?", (sale_id,)).fetchone()
    assert row is not None
    return row


def test_endpoint_exists_and_requires_explicit_confirmation():
    _, draft_id, _ = _ready_and_reserved_draft()

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": False})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "sale_completion_not_confirmed"


def test_inventory_linked_ready_reserved_draft_can_be_completed():
    item_id, draft_id, reservation = _ready_and_reserved_draft()
    before = _inventory_item(item_id)

    response = _post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {
            "confirm_completion": True,
            "sale_price": 12.5,
            "currency": "GBP",
            "platform": "whatnot",
            "buyer_reference": "buyer-local-ref",
            "external_order_reference": "manual-order-ref",
            "notes": "confirmed local sale",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["contract"] == "v12-listing-draft-sale-completion"
    sale = body["data"]["sale"]
    assert sale["sale_id"].startswith("sale_")
    assert sale["draft_id"] == draft_id
    assert sale["reservation_id"] == reservation["reservation_id"]
    assert sale["inventory_item_id"] == item_id
    assert sale["card_key"] == reservation["card_key"]
    assert sale["quantity"] == reservation["quantity"] == 1
    assert sale["platform"] == "whatnot"
    assert sale["sale_price"] == 12.5
    assert sale["currency"] == "GBP"
    assert sale["status"] == "completed"
    assert sale["buyer_reference"] == "buyer-local-ref"
    assert sale["external_order_reference"] == "manual-order-ref"
    assert body["data"]["draft"]["status"] == "ready"
    assert body["data"]["reservation"]["status"] == "completed"
    assert body["data"]["reservation"]["released_at"] is not None
    assert body["data"]["reservation"]["release_reason"] == "sale_completed"
    assert body["data"]["inventory_item"] == {
        "item_id": item_id,
        "status_before": before["status"],
        "status_after": "sold",
    }


def test_sale_record_is_persisted_with_reservation_quantity_and_references():
    item_id, draft_id, reservation = _ready_and_reserved_draft(quantity=1)

    response = _post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {
            "confirm_completion": True,
            "sale_price": 9.99,
            "currency": "GBP",
            "platform": "offline",
            "external_order_reference": "plain-local-text-only",
        },
    )

    assert response.status_code == 200, response.text
    sale = response.json()["data"]["sale"]
    stored = _sale_row(sale["sale_id"])
    assert stored["draft_id"] == draft_id
    assert stored["reservation_id"] == reservation["reservation_id"]
    assert stored["inventory_item_id"] == item_id
    assert stored["card_key"] == reservation["card_key"]
    assert stored["quantity"] == reservation["quantity"]
    assert stored["platform"] == "offline"
    assert stored["sale_price"] == 9.99
    assert stored["currency"] == "GBP"
    assert stored["external_order_reference"] == "plain-local-text-only"


def test_physical_inventory_becomes_sold_only_after_complete_sale_and_snapshot_is_written():
    item_id, draft_id, _ = _ready_and_reserved_draft()
    assert _inventory_item(item_id)["status"] == "owned"

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 200, response.text
    assert _inventory_item(item_id)["status"] == "sold"
    with _db() as conn:
        txn = conn.execute(
            "SELECT * FROM inventory_transactions WHERE item_id = ? AND transaction_type = 'sold' ORDER BY transaction_id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        snapshot = conn.execute(
            "SELECT * FROM inventory_snapshots WHERE item_id = ? ORDER BY snapshot_id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    assert txn is not None
    assert txn["to_status"] == "sold"
    assert snapshot is not None
    assert snapshot["current_status"] == "sold"


def test_reservation_no_longer_remains_active_after_sale_completion():
    item_id, draft_id, _ = _ready_and_reserved_draft()
    assert _active_reservation_count(draft_id=draft_id, item_id=item_id) == 1

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 200, response.text
    assert _active_reservation_count(draft_id=draft_id, item_id=item_id) == 0
    reservation_read = _get(f"/api/v1/listings/drafts/{draft_id}/reservation")
    assert reservation_read.status_code == 200
    assert reservation_read.json()["data"]["reservation"] is None


def test_duplicate_complete_sale_is_rejected():
    _, draft_id, _ = _ready_and_reserved_draft()
    first = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})
    assert first.status_code == 200, first.text

    second = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "listing_draft_sale_already_completed"


def test_draft_without_reservation_is_rejected():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_draft_not_reserved"
    assert _inventory_item(item_id)["status"] == "owned"


def test_card_only_draft_without_inventory_link_is_rejected():
    draft = _create_card_draft()

    response = _post(f"/api/v1/listings/drafts/{draft['draft_id']}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_draft_not_linked_to_inventory"


def test_archived_draft_is_rejected():
    item_id, draft_id, _ = _ready_and_reserved_draft()
    archive = _post(f"/api/v1/listings/drafts/{draft_id}/archive")
    assert archive.status_code == 200, archive.text

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_draft_archived"
    assert _inventory_item(item_id)["status"] == "owned"


def test_inventory_item_already_sold_or_unavailable_is_rejected():
    item_id, draft_id, _ = _ready_and_reserved_draft()
    with _db() as conn:
        conn.execute("UPDATE physical_items SET status = 'sold' WHERE item_id = ?", (item_id,))
        conn.commit()

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "inventory_item_not_available"


def test_sale_completion_no_live_provider_marketplace_network_or_llm_calls():
    _, draft_id, _ = _ready_and_reserved_draft()

    response = _post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {"confirm_completion": True, "platform": "ebay", "external_order_reference": "manual-ebay-text-ref"},
    )

    assert response.status_code == 200, response.text
    text = json.dumps(response.json()).lower()
    forbidden = [
        "justtcg_fallback",
        "totaltcg_live_call",
        "tcgplayer_live_call",
        "cardmarket_live_call",
        "whatnot_listing_id",
        "shopify_product_id",
        "published_listing_id",
        "marketplace_account",
        "llm_prompt",
        "llm_response",
    ]
    for marker in forbidden:
        assert marker not in text, marker
    assert "manual-ebay-text-ref" in text


def test_sale_completion_response_has_no_sensitive_or_raw_payload_leakage():
    _, draft_id, _ = _ready_and_reserved_draft()

    response = _post(f"/api/v1/listings/drafts/{draft_id}/complete-sale", {"confirm_completion": True})

    assert response.status_code == 200, response.text
    text = json.dumps(response.json()).lower()
    forbidden = [
        "/media/",
        "/home/",
        "private_provider_payloads",
        "x-api-key",
        "authorization",
        "raw provider",
        "sanitized candidates",
        "account metadata",
        "headers",
        "api key",
        "marketplace_account",
        "published_listing_id",
        "whatnot_listing_id",
        "shopify_product_id",
        "llm_prompt",
        "llm_response",
    ]
    for marker in forbidden:
        assert marker not in text, marker


def test_missing_draft_returns_404():
    response = _post("/api/v1/listings/drafts/ld_not_real/complete-sale", {"confirm_completion": True})

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "listing_draft_not_found"
