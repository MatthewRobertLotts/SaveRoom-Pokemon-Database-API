"""Tests for v12.2 read-only inventory item list filters.

The inventory list endpoint helps POS/frontends find the right physical item
before opening workflow detail pages. These filters must remain read-only and
must not call providers, marketplaces, network APIs, or LLMs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from urllib.parse import urlencode
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import create_app

client = TestClient(create_app())

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
    "marketplace_account",
    "llm_prompt",
    "llm_response",
)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(client.app.state.db))
    conn.row_factory = sqlite3.Row
    return conn


def _sku_with_card_keys(limit: int = 2) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT s.sku_id, cp.canonical_card_key
            FROM sellable_skus s
            JOIN canonical_printings cp ON cp.printing_id = s.printing_id
            WHERE cp.canonical_card_key IS NOT NULL
            GROUP BY cp.canonical_card_key
            ORDER BY s.sku_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    assert len(rows) >= limit, "test database must include sellable SKUs with canonical card keys"
    return [dict(row) for row in rows]


def _first_sku_id() -> int:
    return int(_sku_with_card_keys(1)[0]["sku_id"])


def _create_inventory_item(
    *,
    sku_id: int | None = None,
    condition: str = "Near Mint",
    status: str = "owned",
    location_code: str | None = None,
    marker: str | None = None,
) -> dict:
    marker = marker or f"inventory-filter-{uuid.uuid4().hex}"
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": sku_id or _first_sku_id(),
            "item_condition": condition,
            "acquired_date": "2026-07-02",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": f"v12.2 inventory list filter fixture {marker}",
            "location_code": location_code or f"Filter Shelf {marker}",
            "status": status,
            "notes": f"v12.2 inventory list filter note {marker}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


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


def _list_items(**params):
    query = urlencode({key: value for key, value in params.items() if value is not None})
    suffix = f"?{query}" if query else ""
    return _guarded_get(f"/api/v1/inventory/items{suffix}")


def _create_inventory_draft(item_id: str) -> dict:
    response = _guarded_post(
        f"/api/v1/inventory/items/{item_id}/listing-draft",
        {"platform": "generic", "include_pricing": False},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _reserve_item(item_id: str) -> tuple[dict, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    response = _guarded_post(f"/api/v1/listings/drafts/{draft_id}/reserve", {})
    assert response.status_code == 200, response.text
    return created, response.json()["data"]["reservation"]


def _complete_sale(item_id: str) -> tuple[dict, dict]:
    created = _create_inventory_draft(item_id)
    draft_id = created["draft"]["draft_id"]
    ready = _guarded_post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})
    assert ready.status_code == 200, ready.text
    sale = _guarded_post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {"confirm_completion": True, "sale_price": 12.5, "currency": "GBP", "platform": "offline"},
    )
    assert sale.status_code == 200, sale.text
    return created, sale.json()["data"]["sale"]


def _row(table: str, key_column: str, key: str) -> dict:
    with _db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (key,)).fetchone()
    assert row is not None
    return dict(row)


def _count(table: str, where: str = "1=1", params: tuple = ()) -> int:
    with _db() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params).fetchone()
    return int(row["c"])


def _link_for_item(item_id: str) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM inventory_listing_draft_links WHERE inventory_item_id = ? ORDER BY created_at DESC LIMIT 1", (item_id,)).fetchone()
    assert row is not None
    return dict(row)


def _assert_response_shape(body: dict) -> None:
    assert set(body) == {"data", "pagination"}
    assert isinstance(body["data"], list)
    assert set(body["pagination"]) == {"limit", "offset", "count", "total", "has_more"}
    if body["data"]:
        row = body["data"][0]
        for key in ["item_id", "sku_id", "sku_identity", "item_condition", "location_code", "status", "images", "last_transaction"]:
            assert key in row


def test_inventory_list_defaults_pagination_and_q_search_still_work():
    marker = f"q-{uuid.uuid4().hex}"
    item = _create_inventory_item(marker=marker, location_code=f"Q Shelf {marker}")

    default_response = _list_items(limit=25)
    q_response = _list_items(q=marker, limit=25)
    page_response = _list_items(q=marker, limit=1, offset=0)

    assert default_response.status_code == 200, default_response.text
    assert q_response.status_code == 200, q_response.text
    assert page_response.status_code == 200, page_response.text
    _assert_response_shape(default_response.json())
    _assert_response_shape(q_response.json())
    assert item["item_id"] in {row["item_id"] for row in q_response.json()["data"]}
    assert page_response.json()["pagination"]["limit"] == 1
    assert page_response.json()["pagination"]["offset"] == 0
    assert page_response.json()["pagination"]["count"] <= 1
    assert page_response.json()["pagination"]["total"] >= 1


def test_exact_item_filters_status_location_sku_condition_and_card_key():
    sku_rows = _sku_with_card_keys(2)
    marker = f"exact-{uuid.uuid4().hex}"
    item = _create_inventory_item(
        sku_id=sku_rows[0]["sku_id"],
        condition="Lightly Played",
        status=f"filter_status_{marker}",
        location_code=f"Filter Location {marker}",
        marker=marker,
    )
    other = _create_inventory_item(sku_id=sku_rows[1]["sku_id"], marker=f"other-{marker}")

    checks = [
        _list_items(status=item["status"], limit=50),
        _list_items(location_code=item["location_code"], limit=50),
        _list_items(sku_id=item["sku_id"], status=item["status"], limit=50),
        _list_items(condition="Lightly Played", status=item["status"], limit=50),
        _list_items(card_key=sku_rows[0]["canonical_card_key"], status=item["status"], limit=50),
    ]
    for response in checks:
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert [row["item_id"] for row in data] == [item["item_id"]]
    miss = _list_items(card_key=sku_rows[1]["canonical_card_key"], status=item["status"], limit=50)
    assert miss.status_code == 200, miss.text
    assert miss.json()["data"] == []
    assert other["item_id"] != item["item_id"]


def test_workflow_boolean_filters_true_and_false():
    plain = _create_inventory_item(marker=f"plain-{uuid.uuid4().hex}")
    linked = _create_inventory_item(marker=f"linked-{uuid.uuid4().hex}")
    reserved = _create_inventory_item(marker=f"reserved-{uuid.uuid4().hex}")
    sold = _create_inventory_item(marker=f"sold-{uuid.uuid4().hex}")
    linked_draft = _create_inventory_draft(linked["item_id"])
    reserved_created, reservation = _reserve_item(reserved["item_id"])
    sold_created, sale = _complete_sale(sold["item_id"])

    linked_true = _list_items(has_listing_draft="true", limit=100)
    linked_false = _list_items(has_listing_draft="false", limit=100)
    reservation_true = _list_items(has_active_reservation="true", limit=100)
    reservation_false = _list_items(has_active_reservation="false", limit=100)
    sale_true = _list_items(has_completed_sale="true", limit=100)
    sale_false = _list_items(has_completed_sale="false", limit=100)

    for response in [linked_true, linked_false, reservation_true, reservation_false, sale_true, sale_false]:
        assert response.status_code == 200, response.text

    assert linked["item_id"] in {row["item_id"] for row in linked_true.json()["data"]}
    assert plain["item_id"] not in {row["item_id"] for row in linked_true.json()["data"]}
    assert plain["item_id"] in {row["item_id"] for row in linked_false.json()["data"]}
    assert linked["item_id"] not in {row["item_id"] for row in linked_false.json()["data"]}

    assert reserved["item_id"] in {row["item_id"] for row in reservation_true.json()["data"]}
    assert plain["item_id"] not in {row["item_id"] for row in reservation_true.json()["data"]}
    assert plain["item_id"] in {row["item_id"] for row in reservation_false.json()["data"]}
    assert reserved["item_id"] not in {row["item_id"] for row in reservation_false.json()["data"]}

    assert sold["item_id"] in {row["item_id"] for row in sale_true.json()["data"]}
    assert plain["item_id"] not in {row["item_id"] for row in sale_true.json()["data"]}
    assert plain["item_id"] in {row["item_id"] for row in sale_false.json()["data"]}
    assert sold["item_id"] not in {row["item_id"] for row in sale_false.json()["data"]}
    assert linked_draft["draft"]["draft_id"]
    assert reserved_created["draft"]["draft_id"] and reservation["reservation_id"]
    assert sold_created["draft"]["draft_id"] and sale["sale_id"]


def test_filters_compose_and_pagination_uses_filtered_total():
    marker = f"compose-{uuid.uuid4().hex}"
    first = _create_inventory_item(condition="Excellent", location_code=f"Compose {marker}", marker=f"first-{marker}")
    second = _create_inventory_item(condition="Excellent", location_code=f"Compose {marker}", marker=f"second-{marker}")
    first_created = _create_inventory_draft(first["item_id"])
    second_created = _create_inventory_draft(second["item_id"])

    response = _list_items(
        location_code=f"Compose {marker}",
        condition="Excellent",
        has_listing_draft="true",
        has_completed_sale="false",
        limit=1,
        offset=1,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"] == {"limit": 1, "offset": 1, "count": 1, "total": 2, "has_more": False}
    returned = {row["item_id"] for row in body["data"]}
    assert returned <= {first["item_id"], second["item_id"]}
    assert first_created["draft"]["draft_id"] and second_created["draft"]["draft_id"]


def test_inventory_list_filters_use_bound_parameters_for_sql_like_input():
    marker = f"sql-{uuid.uuid4().hex}"
    item = _create_inventory_item(location_code=f"SQL Safe {marker}", marker=marker)

    response = _list_items(location_code=f"SQL Safe {marker}' OR 1=1 --", limit=50)

    assert response.status_code == 200, response.text
    assert item["item_id"] not in {row["item_id"] for row in response.json()["data"]}
    assert response.json()["pagination"]["total"] == 0


def test_inventory_list_filters_are_read_only_for_domain_tables():
    item = _create_inventory_item(marker=f"readonly-{uuid.uuid4().hex}")
    created, reservation = _reserve_item(item["item_id"])
    draft_id = created["draft"]["draft_id"]
    link = _link_for_item(item["item_id"])
    before_item = _row("physical_items", "item_id", item["item_id"])
    before_tx_count = _count("inventory_transactions", "item_id = ?", (item["item_id"],))
    before_draft = _row("listing_drafts", "draft_id", draft_id)
    before_link = _row("inventory_listing_draft_links", "id", link["id"])
    before_reservation = _row("listing_draft_inventory_reservations", "reservation_id", reservation["reservation_id"])
    before_sale_count = _count("listing_draft_sales")

    response = _list_items(inventory_item_id=None, has_listing_draft="true", has_active_reservation="true", limit=25)

    assert response.status_code == 200, response.text
    assert item["item_id"] in {row["item_id"] for row in response.json()["data"]}
    assert _row("physical_items", "item_id", item["item_id"]) == before_item
    assert _count("inventory_transactions", "item_id = ?", (item["item_id"],)) == before_tx_count
    assert _row("listing_drafts", "draft_id", draft_id) == before_draft
    assert _row("inventory_listing_draft_links", "id", link["id"]) == before_link
    assert _row("listing_draft_inventory_reservations", "reservation_id", reservation["reservation_id"]) == before_reservation
    assert _count("listing_draft_sales") == before_sale_count


def test_inventory_list_filter_response_has_no_sensitive_provider_filesystem_or_marketplace_leakage():
    marker = f"safe-{uuid.uuid4().hex}"
    item = _create_inventory_item(marker=marker)

    response = _list_items(q=marker, limit=25)

    assert response.status_code == 200, response.text
    text = json.dumps(response.json()).lower()
    assert item["item_id"] in text
    for marker_text in FORBIDDEN_RESPONSE_MARKERS:
        assert marker_text.lower() not in text, marker_text
