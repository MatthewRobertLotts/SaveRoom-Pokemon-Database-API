"""Tests for v12 read-only local sales API.

Local sales reads expose rows created by the explicit local sale-completion
workflow. They must be read-only and must not call providers, marketplaces,
network APIs, or LLMs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
import datetime as dt
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


def _create_inventory_item(*, source_suffix: str = "read-api") -> str:
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": _first_sku_id(),
            "item_condition": "Near Mint",
            "acquired_date": "2026-07-01",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": f"local sales read test fixture {source_suffix}",
            "location_code": "Local Sales Read Test Shelf",
            "status": "owned",
            "notes": "v12 local sales read test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item_id"]


def _post(path: str, payload: dict | None = None):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.post(path, json=payload or {})
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _get(path: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network calls must not be made")) as mock_request:
            response = client.get(path)
    mock_fetch.assert_not_called()
    mock_request.assert_not_called()
    return response


def _create_completed_sale(
    *,
    platform: str = "generic",
    sale_price: float = 12.5,
    sold_at: str | None = None,
    external_order_reference: str = "plain-local-order-ref",
    buyer_reference: str = "plain-local-buyer-ref",
    notes: str = "confirmed local sale for read test",
) -> dict:
    if sold_at is None:
        sold_at = dt.datetime.now(dt.UTC).isoformat()
    item_id = _create_inventory_item(source_suffix=platform)
    draft_response = _post(
        f"/api/v1/inventory/items/{item_id}/listing-draft",
        {"platform": platform if platform in {"whatnot", "ebay", "shopify", "generic"} else "generic", "include_pricing": False},
    )
    assert draft_response.status_code == 201, draft_response.text
    draft_id = draft_response.json()["data"]["draft"]["draft_id"]
    ready = _post(f"/api/v1/listings/drafts/{draft_id}/ready", {"reserve_inventory": True})
    assert ready.status_code == 200, ready.text
    reservation = ready.json()["data"]["reservation"]
    complete = _post(
        f"/api/v1/listings/drafts/{draft_id}/complete-sale",
        {
            "confirm_completion": True,
            "platform": platform,
            "sale_price": sale_price,
            "currency": "GBP",
            "sold_at": sold_at,
            "buyer_reference": buyer_reference,
            "external_order_reference": external_order_reference,
            "notes": notes,
        },
    )
    assert complete.status_code == 200, complete.text
    sale = complete.json()["data"]["sale"]
    sale["_item_id"] = item_id
    sale["_draft_id"] = draft_id
    sale["_reservation_id"] = reservation["reservation_id"]
    return sale


def _db_row(table: str, key_column: str, key: str) -> dict:
    with _db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (key,)).fetchone()
    assert row is not None
    return dict(row)


def test_get_sale_by_id_returns_completed_local_sale():
    sale = _create_completed_sale(platform="whatnot", external_order_reference="manual-whatnot-text-ref")

    response = _get(f"/api/v1/sales/{sale['sale_id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["contract"] == "v12-local-sales-read"
    data = body["data"]
    assert data["sale_id"] == sale["sale_id"]
    assert data["sale_id"].startswith("sale_")
    assert data["draft_id"] == sale["draft_id"]
    assert data["reservation_id"] == sale["reservation_id"]
    assert data["inventory_item_id"] == sale["inventory_item_id"]
    assert data["card_key"] == sale["card_key"]
    assert data["quantity"] == sale["quantity"]
    assert data["platform"] == "whatnot"
    assert data["sale_price"] == 12.5
    assert data["currency"] == "GBP"
    assert data["status"] == "completed"
    assert data["buyer_reference"] == "plain-local-buyer-ref"
    assert data["external_order_reference"] == "manual-whatnot-text-ref"


def test_missing_sale_id_returns_local_sale_not_found():
    response = _get("/api/v1/sales/sale_not_real")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "local_sale_not_found"


def test_list_sales_defaults_to_completed_sales():
    sale = _create_completed_sale(platform="offline", external_order_reference="list-default-ref")

    response = _get("/api/v1/sales")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["contract"] == "v12-local-sales-read"
    assert body["pagination"]["limit"] == 50
    assert body["pagination"]["offset"] == 0
    assert body["pagination"]["count"] == len(body["data"])
    assert body["pagination"]["total"] >= 1
    assert "has_more" in body["pagination"]
    assert sale["sale_id"] in {row["sale_id"] for row in body["data"]}
    assert {row["status"] for row in body["data"]} == {"completed"}


def test_list_sales_supports_draft_id_filter():
    sale = _create_completed_sale(platform="generic", external_order_reference="draft-filter-ref")

    response = _get(f"/api/v1/sales?draft_id={sale['draft_id']}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [row["sale_id"] for row in data] == [sale["sale_id"]]


def test_list_sales_supports_inventory_item_id_filter():
    sale = _create_completed_sale(platform="generic", external_order_reference="item-filter-ref")

    response = _get(f"/api/v1/sales?inventory_item_id={sale['inventory_item_id']}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [row["inventory_item_id"] for row in data] == [sale["inventory_item_id"]]


def test_list_sales_supports_card_key_filter():
    sale = _create_completed_sale(platform="generic", external_order_reference="card-filter-ref")

    response = _get(f"/api/v1/sales?card_key={sale['card_key']}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert sale["sale_id"] in {row["sale_id"] for row in data}
    assert {row["card_key"] for row in data} == {sale["card_key"]}


def test_list_sales_supports_platform_filter():
    sale = _create_completed_sale(platform="ebay", external_order_reference="platform-filter-ref")

    response = _get("/api/v1/sales?platform=ebay")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert sale["sale_id"] in {row["sale_id"] for row in data}
    assert {row["platform"] for row in data} == {"ebay"}


def test_list_sales_supports_status_filter():
    sale = _create_completed_sale(platform="generic", external_order_reference="status-filter-ref")
    with _db() as conn:
        conn.execute("UPDATE listing_draft_sales SET status = 'local_review' WHERE sale_id = ?", (sale["sale_id"],))
        conn.commit()

    completed = _get(f"/api/v1/sales?draft_id={sale['draft_id']}")
    review = _get(f"/api/v1/sales?status=local_review&draft_id={sale['draft_id']}")

    assert completed.status_code == 200, completed.text
    assert completed.json()["data"] == []
    assert review.status_code == 200, review.text
    assert [row["sale_id"] for row in review.json()["data"]] == [sale["sale_id"]]
    assert review.json()["data"][0]["status"] == "local_review"


def test_list_sales_supports_sold_at_date_range_filter():
    early = _create_completed_sale(platform="generic", sold_at="2026-07-02T10:00:00Z", external_order_reference="early-date-ref")
    late = _create_completed_sale(platform="generic", sold_at="2026-08-02T10:00:00Z", external_order_reference="late-date-ref")

    response = _get("/api/v1/sales?date_from=2026-08-01T00:00:00Z&date_to=2026-08-31T23:59:59Z")

    assert response.status_code == 200, response.text
    sale_ids = {row["sale_id"] for row in response.json()["data"]}
    assert late["sale_id"] in sale_ids
    assert early["sale_id"] not in sale_ids


def test_list_sales_supports_limit_offset_and_project_pagination_style():
    first = _create_completed_sale(platform="generic", sold_at="2026-09-01T10:00:00Z", external_order_reference="pagination-first-ref")
    second = _create_completed_sale(platform="generic", sold_at="2026-09-02T10:00:00Z", external_order_reference="pagination-second-ref")
    marker_status = f"local_page_{uuid.uuid4().hex}"
    with _db() as conn:
        conn.execute(
            "UPDATE listing_draft_sales SET status = ? WHERE sale_id IN (?, ?)",
            (marker_status, first["sale_id"], second["sale_id"]),
        )
        conn.commit()

    page = _get(
        f"/api/v1/sales?status={marker_status}"
        "&date_from=2026-09-01T00:00:00Z&date_to=2026-09-30T23:59:59Z&limit=1&offset=1"
    )

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["pagination"] == {
        "limit": 1,
        "offset": 1,
        "count": 1,
        "total": 2,
        "has_more": False,
    }
    assert [row["sale_id"] for row in body["data"]] == [first["sale_id"]]
    assert second["sale_id"] not in {row["sale_id"] for row in body["data"]}


def test_read_list_endpoints_do_not_mutate_inventory_sales_or_reservations():
    sale = _create_completed_sale(platform="offline", external_order_reference="mutation-check-ref")
    before_item = _db_row("physical_items", "item_id", sale["inventory_item_id"])
    before_sale = _db_row("listing_draft_sales", "sale_id", sale["sale_id"])
    before_reservation = _db_row("listing_draft_inventory_reservations", "reservation_id", sale["reservation_id"])

    one = _get(f"/api/v1/sales/{sale['sale_id']}")
    many = _get(f"/api/v1/sales?draft_id={sale['draft_id']}")

    assert one.status_code == 200, one.text
    assert many.status_code == 200, many.text
    assert _db_row("physical_items", "item_id", sale["inventory_item_id"]) == before_item
    assert _db_row("listing_draft_sales", "sale_id", sale["sale_id"]) == before_sale
    assert _db_row("listing_draft_inventory_reservations", "reservation_id", sale["reservation_id"]) == before_reservation


def test_read_list_responses_have_no_sensitive_raw_provider_path_marketplace_or_llm_leakage():
    sale = _create_completed_sale(platform="shopify", external_order_reference="manual-shopify-text-ref")

    responses = [
        _get(f"/api/v1/sales/{sale['sale_id']}"),
        _get(f"/api/v1/sales?draft_id={sale['draft_id']}"),
    ]

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
        "marketplace account",
        "published_listing_id",
        "whatnot_listing_id",
        "shopify_product_id",
        "generated marketplace listing",
        "llm_prompt",
        "llm_response",
        "justtcg_fallback",
        "totaltcg_live_call",
        "tcgplayer_live_call",
        "cardmarket_live_call",
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        text = json.dumps(response.json()).lower()
        assert "manual-shopify-text-ref" in text
        for marker in forbidden:
            assert marker not in text, marker
