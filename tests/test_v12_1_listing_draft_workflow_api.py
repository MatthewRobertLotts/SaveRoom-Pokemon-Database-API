"""Tests for v12.1 read-only listing draft workflow summary endpoint.

The endpoint composes existing local draft/inventory/reservation/sale state for
POS/frontends. It must not mutate inventory, drafts, reservations, sales, or call
providers, marketplaces, network APIs, or LLMs.
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

FORBIDDEN_RESPONSE_MARKERS = (
    "api_key",
    "authorization",
    "headers",
    "private_provider_payloads",
    "sanitized_candidates",
    "account_metadata",
    "raw_provider_json",
    "/media/matt/Storage",
    "/home/matt",
)


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
            "acquired_source": "local draft workflow test fixture",
            "location_code": "Draft Workflow Test Shelf",
            "status": status,
            "notes": "v12.1 draft workflow test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item_id"]


def _create_card_draft(payload: dict | None = None) -> dict:
    body = {"platform": "generic", "include_pricing": False}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(f"/api/v1/listings/drafts/cards/{TEST_CARD_KEY}", json=body)
    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response.json()["data"]


def _create_inventory_draft(item_id: str, payload: dict | None = None) -> dict:
    body = {"platform": "generic", "include_pricing": False}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(f"/api/v1/inventory/items/{item_id}/listing-draft", json=body)
    assert response.status_code == 201, response.text
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response.json()["data"]


def _post(path: str, payload: dict | None = None):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(path, json=payload or {})
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _get_workflow(draft_id: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.get(f"/api/v1/listings/drafts/{draft_id}/workflow")
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _ready_inventory_draft(item_id: str) -> tuple[str, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    response = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": False})
    assert response.status_code == 200, response.text
    return draft_id, response.json()["data"]


def _reserve_inventory_draft(item_id: str) -> tuple[str, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    response = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})
    assert response.status_code == 200, response.text
    return draft_id, response.json()["data"]["reservation"]


def _complete_sale(item_id: str) -> tuple[str, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    ready = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})
    assert ready.status_code == 200, ready.text
    sale = _post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {"confirm_completion": True, "sale_price": 12.5, "currency": "GBP", "platform": "offline"},
    )
    assert sale.status_code == 200, sale.text
    return draft_id, sale.json()["data"]["sale"]


def _archive_inventory_draft(item_id: str) -> tuple[str, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    response = _post(f"/api/v1/listings/drafts/{draft_id}/archive")
    assert response.status_code == 200, response.text
    return draft_id, response.json()["data"]


def _row(table: str, key_col: str, key: str) -> dict | None:
    with _db() as conn:
        exists = conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists or int(exists["c"]) == 0:
            return None
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_col} = ?", (key,)).fetchone()
    return dict(row) if row is not None else None


def _table_count(table: str) -> int | None:
    with _db() as conn:
        exists = conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists or int(exists["c"]) == 0:
            return None
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def _assert_no_forbidden_payload_markers(body: dict) -> None:
    text = json.dumps(body, sort_keys=True).lower()
    for marker in FORBIDDEN_RESPONSE_MARKERS:
        assert marker.lower() not in text


def test_endpoint_exists_and_card_only_draft_returns_draft_state_not_inventory_linked():
    draft = _create_card_draft()
    draft_id = draft["draft_id"]

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["contract"] == "v12.1-listing-draft-workflow"
    data = body["data"]
    assert data["draft_id"] == draft_id
    assert data["current_state"] == "draft"
    assert data["draft"]["draft_id"] == draft_id
    assert data["listing_draft_link"] is None
    assert data["inventory_item"] is None
    assert data["reservation"] is None
    assert data["sale"] is None
    assert data["summary"] == {
        "is_inventory_linked": False,
        "has_active_reservation": False,
        "has_completed_sale": False,
        "is_ready": False,
        "is_archived": False,
        "is_sold": False,
        "can_reserve": False,
        "can_complete_sale": False,
    }


def test_missing_draft_returns_404_listing_draft_not_found():
    response = _get_workflow("not-a-real-draft-id")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "listing_draft_not_found"


def test_inventory_linked_plain_draft_includes_link_and_inventory_item_and_can_reserve():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "draft"
    assert data["draft"]["draft_id"] == draft_id
    assert data["listing_draft_link"]["draft_id"] == draft_id
    assert data["listing_draft_link"]["inventory_item_id"] == item_id
    assert data["inventory_item"]["item_id"] == item_id
    assert data["reservation"] is None
    assert data["sale"] is None
    assert data["summary"]["is_inventory_linked"] is True
    assert data["summary"]["can_reserve"] is True
    assert data["summary"]["can_complete_sale"] is False


def test_ready_draft_returns_ready_state_and_can_reserve_if_inventory_linked():
    item_id = _create_inventory_item()
    draft_id, _ = _ready_inventory_draft(item_id)

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "ready"
    assert data["draft"]["status"] == "ready"
    assert data["summary"]["is_ready"] is True
    assert data["summary"]["can_reserve"] is True
    assert data["summary"]["can_complete_sale"] is False


def test_active_reservation_returns_reserved_state_and_can_complete_sale():
    item_id = _create_inventory_item()
    draft_id, reservation = _reserve_inventory_draft(item_id)

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "reserved"
    assert data["reservation"]["reservation_id"] == reservation["reservation_id"]
    assert data["reservation"]["status"] == "reserved"
    assert data["summary"]["has_active_reservation"] is True
    assert data["summary"]["can_reserve"] is False
    assert data["summary"]["can_complete_sale"] is True


def test_completed_sale_returns_sold_state_with_sale_and_completed_reservation():
    item_id = _create_inventory_item()
    draft_id, sale = _complete_sale(item_id)

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "sold"
    assert data["inventory_item"]["status"] == "sold"
    assert data["reservation"]["status"] == "completed"
    assert data["sale"]["sale_id"] == sale["sale_id"]
    assert data["summary"]["has_completed_sale"] is True
    assert data["summary"]["is_sold"] is True
    assert data["summary"]["can_reserve"] is False
    assert data["summary"]["can_complete_sale"] is False


def test_archived_draft_returns_archived_when_no_sale_exists():
    item_id = _create_inventory_item()
    draft_id, archived = _archive_inventory_draft(item_id)

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "archived"
    assert data["draft"]["status"] == archived["status"] == "archived"
    assert data["sale"] is None
    assert data["summary"]["is_archived"] is True
    assert data["summary"]["can_reserve"] is False
    assert data["summary"]["can_complete_sale"] is False


def test_sold_linked_inventory_item_without_sale_context_returns_sold():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    with _db() as conn:
        conn.execute("UPDATE physical_items SET status = 'sold' WHERE item_id = ?", (item_id,))
        conn.commit()

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "sold"
    assert data["inventory_item"]["status"] == "sold"
    assert data["sale"] is None
    assert data["summary"]["is_sold"] is True
    assert data["summary"]["can_reserve"] is False


def test_unavailable_linked_inventory_item_returns_unavailable():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    with _db() as conn:
        conn.execute("UPDATE physical_items SET status = 'lost' WHERE item_id = ?", (item_id,))
        conn.commit()

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_state"] == "unavailable"
    assert data["inventory_item"]["status"] == "lost"
    assert data["summary"]["is_sold"] is False
    assert data["summary"]["can_reserve"] is False
    assert data["summary"]["can_complete_sale"] is False


def test_workflow_read_does_not_mutate_inventory_drafts_reservations_or_sales():
    item_id = _create_inventory_item()
    draft_id, sale = _complete_sale(item_id)
    reservation_id = sale["reservation_id"]
    before_item = _row("physical_items", "item_id", item_id)
    before_draft = _row("listing_drafts", "draft_id", draft_id)
    before_reservation = _row("listing_draft_inventory_reservations", "reservation_id", reservation_id)
    before_sale = _row("listing_draft_sales", "sale_id", sale["sale_id"])
    before_counts = {
        table: _table_count(table)
        for table in (
            "physical_items",
            "listing_drafts",
            "listing_draft_inventory_reservations",
            "listing_draft_sales",
        )
    }

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    assert _row("physical_items", "item_id", item_id) == before_item
    assert _row("listing_drafts", "draft_id", draft_id) == before_draft
    assert _row("listing_draft_inventory_reservations", "reservation_id", reservation_id) == before_reservation
    assert _row("listing_draft_sales", "sale_id", sale["sale_id"]) == before_sale
    assert before_counts == {
        table: _table_count(table)
        for table in (
            "physical_items",
            "listing_drafts",
            "listing_draft_inventory_reservations",
            "listing_draft_sales",
        )
    }


def test_workflow_response_excludes_provider_marketplace_llm_and_sensitive_payloads():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _get_workflow(draft_id)

    assert response.status_code == 200, response.text
    _assert_no_forbidden_payload_markers(response.json())


def test_existing_listing_draft_read_still_works_for_same_draft():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    workflow = _get_workflow(draft_id)
    detail = client.get(f"/api/v1/listings/drafts/{draft_id}")

    assert workflow.status_code == 200, workflow.text
    assert detail.status_code == 200, detail.text
    assert workflow.json()["data"]["draft"]["draft_id"] == detail.json()["data"]["draft_id"]
