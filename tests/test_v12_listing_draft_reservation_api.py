"""Tests for v12 local listing draft readiness and inventory reservations.

Reservations are local-only workflow state. They must not publish listings,
call providers/marketplaces/LLMs, mark inventory sold, or decrement stock.
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
            "acquired_source": "local reservation test fixture",
            "location_code": "Reservation Test Shelf",
            "status": status,
            "notes": "v12 reservation test",
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
        response = client.post(path, json=payload or {})
    mock_fetch.assert_not_called()
    return response


def _get(path: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.get(path)
    mock_fetch.assert_not_called()
    return response


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


def test_ready_marks_non_inventory_draft_ready_without_reservation():
    draft = _create_card_draft()

    response = _post(f"/api/v1/listings/drafts/{draft['draft_id']}/ready", {"reserve_inventory": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["contract"] == "v12-listing-draft-reservation"
    assert body["data"]["draft"]["status"] == "ready"
    assert body["data"]["reservation"] is None


def test_ready_reserves_linked_inventory_draft():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["draft"]["status"] == "ready"
    reservation = data["reservation"]
    assert reservation["reservation_id"].startswith("ldr_")
    assert reservation["draft_id"] == draft_id
    assert reservation["inventory_item_id"] == item_id
    assert reservation["card_key"] == created["inventory_source"]["card_key"]
    assert reservation["quantity"] == 1
    assert reservation["status"] == "reserved"
    assert reservation["released_at"] is None
    assert reservation["release_reason"] is None


def test_reserve_creates_active_reservation_for_inventory_linked_draft():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {"quantity": 1})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["draft"]["draft_id"] == draft_id
    assert data["draft"]["status"] == "draft"
    assert data["reservation"]["status"] == "reserved"
    assert data["reservation"]["quantity"] == 1


def test_reserve_rejects_draft_with_no_inventory_link():
    draft = _create_card_draft()

    response = _post(f"/api/v1/listings/drafts/{draft['draft_id']}/reserve", {})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_draft_not_linked_to_inventory"


def test_duplicate_active_reservation_for_same_inventory_item_returns_409():
    item_id = _create_inventory_item()
    first = _create_inventory_draft(item_id)
    second = _create_inventory_draft(item_id)
    first_draft_id = first["draft"]["draft_id"]
    second_draft_id = second["draft"]["draft_id"]
    assert _post(f"/api/v1/listings/drafts/{first_draft_id}/reserve", {}).status_code == 200

    response = _post(f"/api/v1/listings/drafts/{second_draft_id}/reserve", {})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "inventory_already_reserved"
    assert _active_reservation_count(item_id=item_id) == 1


def test_duplicate_active_reservation_for_same_draft_returns_existing_without_duplicate_rows():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    first = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})
    assert first.status_code == 200, first.text

    second = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})

    assert second.status_code == 200, second.text
    assert second.json()["data"]["reservation"]["reservation_id"] == first.json()["data"]["reservation"]["reservation_id"]
    assert _active_reservation_count(draft_id=draft_id) == 1
    assert _active_reservation_count(item_id=item_id) == 1


def test_unreserve_releases_active_reservation():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    assert _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {}).status_code == 200

    response = _post(f"/api/v1/listings/drafts/{draft_id}/unreserve", {"release_reason": "test release"})

    assert response.status_code == 200, response.text
    reservation = response.json()["data"]["reservation"]
    assert reservation["status"] == "released"
    assert reservation["released_at"] is not None
    assert reservation["release_reason"] == "test release"
    assert _active_reservation_count(draft_id=draft_id) == 0
    assert _active_reservation_count(item_id=item_id) == 0


def test_unreserve_can_set_draft_status_back_to_draft():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    assert _post(f"/api/v1/listings/drafts/{draft_id}/ready", {}).status_code == 200

    response = _post(f"/api/v1/listings/drafts/{draft_id}/unreserve", {"set_status": "draft"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["draft"]["status"] == "draft"
    assert response.json()["data"]["reservation"]["status"] == "released"


def test_reservation_returns_active_reservation():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    reserved = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})
    assert reserved.status_code == 200, reserved.text

    response = _get(f"/api/v1/listings/drafts/{draft_id}/reservation")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["reservation"]["reservation_id"] == reserved.json()["data"]["reservation"]["reservation_id"]


def test_reservation_returns_null_when_no_active_reservation_exists():
    draft = _create_card_draft()

    response = _get(f"/api/v1/listings/drafts/{draft['draft_id']}/reservation")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["reservation"] is None


def test_missing_draft_returns_404_for_reservation_workflow():
    for method, path in [
        ("post", "/api/v1/listings/drafts/ld_not_real/ready"),
        ("post", "/api/v1/listings/drafts/ld_not_real/reserve"),
        ("post", "/api/v1/listings/drafts/ld_not_real/unreserve"),
        ("get", "/api/v1/listings/drafts/ld_not_real/reservation"),
    ]:
        response = _post(path, {}) if method == "post" else _get(path)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["error"]["code"] == "listing_draft_not_found"


def test_archived_draft_cannot_be_reserved():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    archive = _post(f"/api/v1/listings/drafts/{draft_id}/archive")
    assert archive.status_code == 200, archive.text

    response = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_draft_archived"
    assert _active_reservation_count(draft_id=draft_id) == 0


def test_reservation_does_not_mark_physical_item_sold_or_decrement_inventory():
    item_id = _create_inventory_item(status="owned")
    before = _inventory_item(item_id)
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {})

    assert response.status_code == 200, response.text
    after = _inventory_item(item_id)
    assert before["status"] == "owned"
    assert after["status"] == "owned"
    assert after["item_id"] == item_id
    assert response.json()["data"]["reservation"]["quantity"] == 1


def test_reservation_no_live_provider_marketplace_llm_calls_and_provider_status_safe():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id, {"include_pricing": False})
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})

    assert response.status_code == 200, response.text
    body = response.json()
    provider_status = body["data"]["draft"]["provider_status"]
    assert provider_status["justtcg"]["status"] == "not_used_for_listing_assistant"
    assert provider_status["justtcg"]["live_enabled"] is False
    assert body["data"]["draft"]["pricing"] is None


def test_reservation_response_has_no_sensitive_or_live_provider_leakage():
    item_id = _create_inventory_item()
    created = _create_inventory_draft(item_id, {"include_pricing": False})
    draft_id = created["draft"]["draft_id"]

    response = _post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})

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
        "published_listing_id",
        "marketplace_account",
        "whatnot_listing_id",
        "shopify_product_id",
        "llm_prompt",
        "llm_response",
        "justtcg_fallback",
        "usd",
    ]
    for marker in forbidden:
        assert marker not in text, marker
