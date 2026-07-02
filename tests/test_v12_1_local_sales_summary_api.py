"""Tests for v12.1 read-only local sales summary endpoint.

The endpoint summarizes local listing_draft_sales rows created by explicit local
sale completion. It must not mutate inventory, drafts, reservations, sales, or
call providers, marketplaces, network APIs, or LLMs.
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


def _create_inventory_item(*, source_suffix: str) -> str:
    response = client.post(
        "/api/v1/inventory/items",
        json={
            "sku_id": _first_sku_id(),
            "item_condition": "Near Mint",
            "acquired_date": "2026-07-01",
            "acquired_price": 12.34,
            "acquired_currency": "GBP",
            "acquired_source": f"local sales summary test fixture {source_suffix}",
            "location_code": "Local Sales Summary Test Shelf",
            "status": "owned",
            "notes": "v12.1 local sales summary test",
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
    marker_status: str,
    platform: str = "generic",
    sale_price: float | None = 12.5,
    quantity: int = 1,
    currency: str = "GBP",
    sold_at: str = "2026-07-02T10:00:00Z",
) -> dict:
    item_id = _create_inventory_item(source_suffix=marker_status)
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
            "sale_price": sale_price if sale_price is not None else 0,
            "currency": currency,
            "sold_at": sold_at,
            "buyer_reference": f"buyer-{marker_status}",
            "external_order_reference": f"order-{marker_status}",
            "notes": "confirmed local sale for summary test",
        },
    )
    assert complete.status_code == 200, complete.text
    sale = complete.json()["data"]["sale"]
    with _db() as conn:
        conn.execute(
            """
            UPDATE listing_draft_sales
            SET status = ?, sale_price = ?, quantity = ?, currency = ?, sold_at = ?
            WHERE sale_id = ?
            """,
            (marker_status, sale_price, quantity, currency, sold_at, sale["sale_id"]),
        )
        conn.commit()
    sale.update(
        {
            "status": marker_status,
            "sale_price": sale_price,
            "quantity": quantity,
            "currency": currency,
            "sold_at": sold_at,
            "_item_id": item_id,
            "_draft_id": draft_id,
            "_reservation_id": reservation["reservation_id"],
        }
    )
    return sale


def _summary(**params):
    query = urlencode({key: value for key, value in params.items() if value is not None})
    suffix = f"?{query}" if query else ""
    return _get(f"/api/v1/sales/summary{suffix}")


def _db_row(table: str, key_column: str, key: str) -> dict:
    with _db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key_column} = ?", (key,)).fetchone()
    assert row is not None
    return dict(row)


def _table_count(table: str) -> int:
    with _db() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def _assert_no_forbidden_payload_markers(body: dict) -> None:
    text = json.dumps(body, sort_keys=True).lower()
    for marker in FORBIDDEN_RESPONSE_MARKERS:
        assert marker not in text, marker


def _assert_sales_summary_shape(body: dict) -> None:
    assert set(body) == {"data", "metadata"}
    assert body["metadata"]["contract"] == "v12.1-local-sales-summary"
    data = body["data"]
    assert set(data) == {"filters", "summary", "by_platform", "by_status", "by_currency"}
    assert set(data["filters"]) == {
        "date_from",
        "date_to",
        "platform",
        "status",
        "card_key",
        "inventory_item_id",
        "draft_id",
    }
    assert set(data["summary"]) == {
        "sale_count",
        "quantity_total",
        "gross_sales_total",
        "average_sale_price",
        "min_sale_price",
        "max_sale_price",
        "currency",
        "currency_mixed",
    }
    assert isinstance(data["by_platform"], list)
    assert isinstance(data["by_status"], list)
    assert isinstance(data["by_currency"], list)


def test_sales_summary_endpoint_exists_and_empty_summary_is_safe():
    marker = f"summary_empty_{uuid.uuid4().hex}"

    response = _summary(status=marker)

    assert response.status_code == 200, response.text
    body = response.json()
    _assert_sales_summary_shape(body)
    assert body["metadata"]["contract"] == "v12.1-local-sales-summary"
    data = body["data"]
    assert data["filters"] == {
        "date_from": None,
        "date_to": None,
        "platform": None,
        "status": marker,
        "card_key": None,
        "inventory_item_id": None,
        "draft_id": None,
    }
    assert data["summary"] == {
        "sale_count": 0,
        "quantity_total": 0,
        "gross_sales_total": 0.0,
        "average_sale_price": None,
        "min_sale_price": None,
        "max_sale_price": None,
        "currency": "GBP",
        "currency_mixed": False,
    }
    assert data["by_platform"] == []
    assert data["by_status"] == []
    assert data["by_currency"] == []


def test_sales_summary_aggregates_counts_quantities_prices_and_groups():
    marker = f"summary_agg_{uuid.uuid4().hex}"
    sale_a = _create_completed_sale(marker_status=marker, platform="whatnot", sale_price=10.0, quantity=2, currency="GBP")
    sale_b = _create_completed_sale(marker_status=marker, platform="whatnot", sale_price=20.0, quantity=3, currency="GBP")
    sale_c = _create_completed_sale(marker_status=marker, platform="ebay", sale_price=None, quantity=4, currency="GBP")

    response = _summary(status=marker)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["summary"] == {
        "sale_count": 3,
        "quantity_total": 9,
        "gross_sales_total": 80.0,
        "average_sale_price": 15.0,
        "min_sale_price": 10.0,
        "max_sale_price": 20.0,
        "currency": "GBP",
        "currency_mixed": False,
    }
    by_platform = {row["platform"]: row for row in data["by_platform"]}
    assert by_platform["whatnot"] == {"platform": "whatnot", "sale_count": 2, "quantity_total": 5, "gross_sales_total": 80.0}
    assert by_platform["ebay"] == {"platform": "ebay", "sale_count": 1, "quantity_total": 4, "gross_sales_total": 0.0}
    assert data["by_status"] == [{"status": marker, "sale_count": 3, "quantity_total": 9, "gross_sales_total": 80.0}]
    assert data["by_currency"] == [{"currency": "GBP", "sale_count": 3, "quantity_total": 9, "gross_sales_total": 80.0}]
    assert {sale_a["sale_id"], sale_b["sale_id"], sale_c["sale_id"]}


def test_sales_summary_currency_mixed_when_multiple_currencies_match():
    marker = f"summary_currency_{uuid.uuid4().hex}"
    _create_completed_sale(marker_status=marker, platform="generic", sale_price=10.0, quantity=1, currency="GBP")
    _create_completed_sale(marker_status=marker, platform="generic", sale_price=12.0, quantity=1, currency="EUR")

    response = _summary(status=marker)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["summary"]["currency"] is None
    assert data["summary"]["currency_mixed"] is True
    by_currency = {row["currency"]: row for row in data["by_currency"]}
    assert set(by_currency) == {"EUR", "GBP"}
    assert by_currency["GBP"]["gross_sales_total"] == 10.0
    assert by_currency["EUR"]["gross_sales_total"] == 12.0


def test_sales_summary_filters_platform_card_item_draft_and_date_range():
    marker = f"summary_filters_{uuid.uuid4().hex}"
    early = _create_completed_sale(
        marker_status=marker,
        platform="shopify",
        sale_price=5.0,
        quantity=1,
        sold_at="2026-07-01T10:00:00Z",
    )
    late = _create_completed_sale(
        marker_status=marker,
        platform="whatnot",
        sale_price=7.0,
        quantity=2,
        sold_at="2026-08-01T10:00:00Z",
    )

    by_platform = _summary(status=marker, platform="whatnot")
    by_card = _summary(status=marker, card_key=late["card_key"])
    by_item = _summary(status=marker, inventory_item_id=late["inventory_item_id"])
    by_draft = _summary(status=marker, draft_id=late["draft_id"])
    by_date = _summary(status=marker, date_from="2026-08-01T00:00:00Z", date_to="2026-08-31T23:59:59Z")

    for response in [by_platform, by_card, by_item, by_draft, by_date]:
        assert response.status_code == 200, response.text
    assert by_platform.json()["data"]["summary"]["sale_count"] == 1
    assert by_platform.json()["data"]["summary"]["gross_sales_total"] == 14.0
    assert by_card.json()["data"]["summary"]["sale_count"] >= 2  # card_key is shared by fixtures
    assert by_item.json()["data"]["summary"]["sale_count"] == 1
    assert by_draft.json()["data"]["summary"]["sale_count"] == 1
    assert by_date.json()["data"]["summary"]["sale_count"] == 1
    assert by_date.json()["data"]["summary"]["gross_sales_total"] == 14.0
    assert early["sale_id"] != late["sale_id"]


def test_sales_summary_defaults_to_completed_status_and_status_filter_is_exact():
    completed = _create_completed_sale(marker_status="completed", platform="offline", sale_price=11.0, quantity=1)
    marker = f"summary_status_{uuid.uuid4().hex}"
    review = _create_completed_sale(marker_status=marker, platform="offline", sale_price=13.0, quantity=1)

    default = _summary(draft_id=completed["draft_id"])
    explicit = _summary(status=marker, draft_id=review["draft_id"])
    missing_default = _summary(draft_id=review["draft_id"])

    assert default.status_code == 200, default.text
    assert default.json()["data"]["filters"]["status"] == "completed"
    assert default.json()["data"]["summary"]["sale_count"] == 1
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["data"]["summary"]["sale_count"] == 1
    assert missing_default.status_code == 200, missing_default.text
    assert missing_default.json()["data"]["summary"]["sale_count"] == 0


def test_sales_summary_uses_bound_parameters_for_sql_like_input():
    marker = f"summary_sql_{uuid.uuid4().hex}"
    _create_completed_sale(marker_status=marker, platform="generic", sale_price=9.0, quantity=1)

    response = _summary(status=marker, platform="generic' OR 1=1 --")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["sale_count"] == 0


def test_sales_summary_is_read_only_for_domain_tables():
    marker = f"summary_readonly_{uuid.uuid4().hex}"
    sale = _create_completed_sale(marker_status=marker, platform="offline", sale_price=8.0, quantity=2)
    before_item = _db_row("physical_items", "item_id", sale["inventory_item_id"])
    before_draft = _db_row("listing_drafts", "draft_id", sale["draft_id"])
    before_reservation = _db_row("listing_draft_inventory_reservations", "reservation_id", sale["reservation_id"])
    before_sale = _db_row("listing_draft_sales", "sale_id", sale["sale_id"])
    before_sale_count = _table_count("listing_draft_sales")

    response = _summary(status=marker, draft_id=sale["draft_id"])

    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["sale_count"] == 1
    assert _db_row("physical_items", "item_id", sale["inventory_item_id"]) == before_item
    assert _db_row("listing_drafts", "draft_id", sale["draft_id"]) == before_draft
    assert _db_row("listing_draft_inventory_reservations", "reservation_id", sale["reservation_id"]) == before_reservation
    assert _db_row("listing_draft_sales", "sale_id", sale["sale_id"]) == before_sale
    assert _table_count("listing_draft_sales") == before_sale_count


def test_sales_summary_response_excludes_sensitive_provider_filesystem_and_marketplace_payloads():
    marker = f"summary_safe_{uuid.uuid4().hex}"
    _create_completed_sale(marker_status=marker, platform="shopify", sale_price=6.0, quantity=1)

    response = _summary(status=marker)

    assert response.status_code == 200, response.text
    _assert_no_forbidden_payload_markers(response.json())
