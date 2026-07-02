"""Tests for v12.1 read-only listing draft list filters.

The list endpoint must keep the existing ListingDraftListResponseV1 shape while
adding POS/frontend filters over local draft, inventory-link, reservation, and
sale state. Filter reads must not mutate inventory, drafts, reservations, sales,
or call providers, marketplaces, network APIs, or LLMs.
"""
from __future__ import annotations

import json
import os
import sqlite3
from urllib.parse import urlencode
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


def _guarded_get(path: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.get(path)
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _guarded_post(path: str, payload: dict | None = None):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(path, json=payload or {})
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _create_card_draft(*, platform: str = "generic", include_pricing: bool = False, notes: str | None = None) -> dict:
    body: dict = {"platform": platform, "include_pricing": include_pricing}
    if notes is not None:
        body["notes"] = notes
    response = _guarded_post(f"/api/v1/listings/drafts/cards/{TEST_CARD_KEY}", body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_inventory_item(*, source_suffix: str = "list-filter") -> str:
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": _first_sku_id(),
            "item_condition": "Near Mint",
            "acquired_date": "2026-07-01",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": f"listing draft filter test fixture {source_suffix}",
            "location_code": "Draft Filter Test Shelf",
            "status": "owned",
            "notes": "v12.1 listing draft list filter test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item_id"]


def _create_inventory_draft(item_id: str, *, platform: str = "generic") -> dict:
    response = _guarded_post(
        f"/api/v1/inventory/items/{item_id}/listing-draft",
        {"platform": platform, "include_pricing": False},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _ready_draft(draft_id: str) -> None:
    response = _guarded_post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": False})
    assert response.status_code == 200, response.text


def _reserve_draft(draft_id: str) -> dict:
    response = _guarded_post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})
    assert response.status_code == 200, response.text
    return response.json()["data"]["reservation"]


def _complete_sale(draft_id: str) -> dict:
    ready = _guarded_post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})
    assert ready.status_code == 200, ready.text
    response = _guarded_post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {"confirm_completion": True, "sale_price": 12.5, "currency": "GBP", "platform": "offline"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["sale"]


def _list_drafts(**params):
    query = urlencode({k: v for k, v in params.items() if v is not None})
    suffix = f"?{query}" if query else ""
    return _guarded_get(f"/api/v1/listings/drafts{suffix}")


def _ids(response) -> set[str]:
    return {draft["draft_id"] for draft in response.json()["data"]}


def _active_reservation_exists(draft_id: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM listing_draft_inventory_reservations WHERE draft_id = ? AND status = 'reserved' LIMIT 1",
            (draft_id,),
        ).fetchone()
    return row is not None


def _completed_sale_exists(draft_id: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM listing_draft_sales WHERE draft_id = ? AND status = 'completed' LIMIT 1",
            (draft_id,),
        ).fetchone()
    return row is not None


def _table_count(table: str) -> int | None:
    with _db() as conn:
        exists = conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists or int(exists["c"]) == 0:
            return None
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def _row(table: str, key_col: str, key: str) -> dict | None:
    with _db() as conn:
        exists = conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists or int(exists["c"]) == 0:
            return None
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_col} = ?", (key,)).fetchone()
    return dict(row) if row is not None else None


def _assert_list_shape(body: dict) -> None:
    assert set(body) == {"data", "pagination", "metadata"}
    assert isinstance(body["data"], list)
    assert body["metadata"]["contract"] == "v12-listing-draft"
    pagination = body["pagination"]
    assert {"limit", "offset", "count", "total", "has_more"}.issubset(pagination)
    assert pagination["count"] == len(body["data"])
    for draft in body["data"]:
        assert "draft_id" in draft
        assert "status" in draft
        assert "platform" in draft
        assert "card_key" in draft


def _assert_no_forbidden_payload_markers(body: dict) -> None:
    text = json.dumps(body, sort_keys=True).lower()
    for marker in FORBIDDEN_RESPONSE_MARKERS:
        assert marker.lower() not in text


def test_default_list_still_returns_listing_draft_list_response_shape():
    draft = _create_card_draft(platform="generic", notes="default list filters smoke")

    response = _list_drafts(limit=25)

    assert response.status_code == 200, response.text
    body = response.json()
    _assert_list_shape(body)
    _assert_no_forbidden_payload_markers(body)
    assert draft["draft_id"] in _ids(response)


def test_include_archived_behavior_is_preserved():
    draft = _create_card_draft(platform="generic", notes="archived filter fixture")
    archived = _guarded_post(f"/api/v1/listings/drafts/{draft['draft_id']}/archive")
    assert archived.status_code == 200, archived.text

    included = _list_drafts(include_archived="true", limit=100)
    excluded = _list_drafts(include_archived="false", limit=100)

    assert included.status_code == 200, included.text
    assert excluded.status_code == 200, excluded.text
    assert draft["draft_id"] in _ids(included)
    assert draft["draft_id"] not in _ids(excluded)


def test_status_platform_and_card_key_filters_return_matching_drafts_only():
    item_id = _create_inventory_item(source_suffix="status-platform-card")
    created = _create_inventory_draft(item_id, platform="ebay")
    draft_id = created["draft"]["draft_id"]
    _ready_draft(draft_id)

    by_status = _list_drafts(status="ready", include_archived="true", limit=100)
    by_platform = _list_drafts(platform="ebay", include_archived="true", limit=100)
    by_card_key = _list_drafts(card_key=TEST_CARD_KEY, include_archived="true", limit=100)

    assert by_status.status_code == 200, by_status.text
    assert draft_id in _ids(by_status)
    assert all(draft["status"] == "ready" for draft in by_status.json()["data"])
    assert by_platform.status_code == 200, by_platform.text
    assert draft_id in _ids(by_platform)
    assert all(draft["platform"] == "ebay" for draft in by_platform.json()["data"])
    assert by_card_key.status_code == 200, by_card_key.text
    assert draft_id in _ids(by_card_key)
    assert all(draft["card_key"] == TEST_CARD_KEY for draft in by_card_key.json()["data"])


def test_inventory_item_id_filter_returns_only_linked_draft():
    item_id = _create_inventory_item(source_suffix="item-id")
    created = _create_inventory_draft(item_id, platform="generic")
    draft_id = created["draft"]["draft_id"]
    _create_card_draft(platform="generic", notes="unlinked inventory filter control")

    response = _list_drafts(inventory_item_id=item_id, include_archived="true", limit=100)

    assert response.status_code == 200, response.text
    body = response.json()
    _assert_list_shape(body)
    assert _ids(response) == {draft_id}


def test_has_reservation_true_and_false_filters_active_reserved_state():
    reserved_item_id = _create_inventory_item(source_suffix="reservation-true")
    reserved_created = _create_inventory_draft(reserved_item_id)
    reserved_draft_id = reserved_created["draft"]["draft_id"]
    _reserve_draft(reserved_draft_id)
    plain_draft = _create_card_draft(notes="no reservation control")

    true_response = _list_drafts(has_reservation="true", include_archived="true", limit=100)
    false_response = _list_drafts(has_reservation="false", include_archived="true", limit=100)

    assert true_response.status_code == 200, true_response.text
    assert reserved_draft_id in _ids(true_response)
    assert all(_active_reservation_exists(draft["draft_id"]) for draft in true_response.json()["data"])
    assert false_response.status_code == 200, false_response.text
    assert reserved_draft_id not in _ids(false_response)
    assert plain_draft["draft_id"] in _ids(false_response)
    assert all(not _active_reservation_exists(draft["draft_id"]) for draft in false_response.json()["data"])


def test_has_sale_true_and_false_filters_completed_local_sales():
    sale_item_id = _create_inventory_item(source_suffix="sale-true")
    sale_created = _create_inventory_draft(sale_item_id)
    sale_draft_id = sale_created["draft"]["draft_id"]
    sale = _complete_sale(sale_draft_id)
    plain_draft = _create_card_draft(notes="no sale control")

    true_response = _list_drafts(has_sale="true", include_archived="true", limit=100)
    false_response = _list_drafts(has_sale="false", include_archived="true", limit=100)

    assert true_response.status_code == 200, true_response.text
    assert sale["draft_id"] == sale_draft_id
    assert sale_draft_id in _ids(true_response)
    assert all(_completed_sale_exists(draft["draft_id"]) for draft in true_response.json()["data"])
    assert false_response.status_code == 200, false_response.text
    assert sale_draft_id not in _ids(false_response)
    assert plain_draft["draft_id"] in _ids(false_response)
    assert all(not _completed_sale_exists(draft["draft_id"]) for draft in false_response.json()["data"])


def test_filters_compose_together_safely():
    item_id = _create_inventory_item(source_suffix="compose")
    created = _create_inventory_draft(item_id, platform="shopify")
    draft_id = created["draft"]["draft_id"]
    _reserve_draft(draft_id)
    _create_inventory_draft(_create_inventory_item(source_suffix="compose-control"), platform="shopify")

    response = _list_drafts(
        status="draft",
        platform="shopify",
        card_key=TEST_CARD_KEY,
        inventory_item_id=item_id,
        has_reservation="true",
        has_sale="false",
        include_archived="true",
        limit=100,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [draft["draft_id"] for draft in data] == [draft_id]
    assert data[0]["status"] == "draft"
    assert data[0]["platform"] == "shopify"
    assert data[0]["card_key"] == TEST_CARD_KEY


def test_pagination_still_works_with_filters():
    draft_a = _create_card_draft(platform="whatnot", notes="pagination filter a")
    draft_b = _create_card_draft(platform="whatnot", notes="pagination filter b")

    first = _list_drafts(platform="whatnot", include_archived="true", limit=1, offset=0)
    second = _list_drafts(platform="whatnot", include_archived="true", limit=1, offset=1)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_page = first.json()["pagination"]
    second_page = second.json()["pagination"]
    assert first_page["limit"] == 1
    assert first_page["offset"] == 0
    assert first_page["count"] == 1
    assert first_page["total"] >= 2
    assert first_page["has_more"] is True
    assert second_page["limit"] == 1
    assert second_page["offset"] == 1
    assert second_page["count"] == 1
    assert {draft_a["draft_id"], draft_b["draft_id"]} & (_ids(first) | _ids(second))


def test_list_filters_are_read_only_for_domain_tables():
    item_id = _create_inventory_item(source_suffix="read-only")
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    reservation = _reserve_draft(draft_id)
    before_item = _row("physical_items", "item_id", item_id)
    before_draft = _row("listing_drafts", "draft_id", draft_id)
    before_reservation = _row("listing_draft_inventory_reservations", "reservation_id", reservation["reservation_id"])
    before_sale_count = _table_count("listing_draft_sales")

    response = _list_drafts(inventory_item_id=item_id, has_reservation="true", has_sale="false", limit=25)

    assert response.status_code == 200, response.text
    assert draft_id in _ids(response)
    assert _row("physical_items", "item_id", item_id) == before_item
    assert _row("listing_drafts", "draft_id", draft_id) == before_draft
    assert _row("listing_draft_inventory_reservations", "reservation_id", reservation["reservation_id"]) == before_reservation
    assert _table_count("listing_draft_sales") == before_sale_count


def test_filtered_response_excludes_sensitive_provider_and_filesystem_payloads():
    _create_card_draft(platform="generic", notes="sensitive marker filter check")

    response = _list_drafts(platform="generic", include_archived="true", limit=25)

    assert response.status_code == 200, response.text
    _assert_no_forbidden_payload_markers(response.json())
