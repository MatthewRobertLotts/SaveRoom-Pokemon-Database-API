"""Pure file tests for the v12.2 POS-ready fixture pack.

The fixture pack is static documentation/test data for frontend/POS mocks. These
checks intentionally do not import the FastAPI app, call providers, access the
network, or mutate project data.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "docs" / "fixtures" / "v12_2_pos"
README = FIXTURE_DIR / "README.md"
MAIN_DOC = ROOT / "docs" / "V12_2_POS_READY_FIXTURE_PACK.md"

EXPECTED_JSON_FIXTURES = {
    "card_detail_response.json",
    "inventory_item_list_filtered_response.json",
    "inventory_item_workflow_response.json",
    "listing_draft_workflow_response.json",
    "listing_draft_list_filtered_response.json",
    "local_sales_summary_response.json",
}

FORBIDDEN_MARKERS = (
    "api_key",
    "x-api-key",
    "authorization",
    "headers",
    "private_provider_payloads",
    "sanitized_candidates",
    "account_metadata",
    "raw_provider_json",
    "raw provider",
    "/home/matt",
    "/media/matt/Storage",
    "marketplace_account",
    "whatnot_listing_id",
    "ebay_listing_id",
    "shopify_product_id",
    "external_access_token",
    "refresh_token",
    "llm_prompt",
    "llm_response",
    "JustTCG raw",
    "TotalTCG raw",
    ".env",
)


def _load(name: str) -> dict:
    path = FIXTURE_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _fixture_texts() -> dict[str, str]:
    return {name: (FIXTURE_DIR / name).read_text(encoding="utf-8") for name in EXPECTED_JSON_FIXTURES}


def test_all_expected_fixture_files_exist_and_parse():
    assert README.exists()
    assert MAIN_DOC.exists()
    for name in EXPECTED_JSON_FIXTURES:
        path = FIXTURE_DIR / name
        assert path.exists(), name
        assert isinstance(_load(name), dict)


def test_card_detail_fixture_shape():
    body = _load("card_detail_response.json")
    assert set(body) == {"data", "metadata", "warnings"}
    assert body["metadata"]["api_version"] == "v1"
    assert body["metadata"]["fixture"] is True
    assert body["metadata"]["sanitized"] is True
    data = body["data"]
    assert {"card", "set", "images", "commercial", "pricing", "provider_status"} <= set(data)
    assert data["card"]["card_key"] == "en:sv03-223"
    assert data["commercial"]["sellable_skus"][0]["sku_id"] == 1001


def test_inventory_item_list_fixture_shape():
    body = _load("inventory_item_list_filtered_response.json")
    assert {"data", "pagination", "metadata"} <= set(body)
    assert isinstance(body["data"], list) and body["data"]
    assert set(body["pagination"]) == {"limit", "offset", "count", "total", "has_more"}
    item = body["data"][0]
    for key in ["item_id", "sku_id", "sku_identity", "item_condition", "location_code", "status", "images", "last_transaction"]:
        assert key in item
    assert item["item_id"].startswith("item_fixture_")
    assert body["metadata"]["filters"]["has_listing_draft"] is True


def test_inventory_item_workflow_fixture_shape():
    body = _load("inventory_item_workflow_response.json")
    assert set(body) == {"data", "metadata"}
    assert body["metadata"]["contract"] == "v12.1-inventory-item-workflow"
    data = body["data"]
    assert {"item", "listing_draft_link", "listing_draft", "active_reservation", "completed_sale", "summary"} <= set(data)
    assert data["item"]["item_id"].startswith("item_fixture_")
    assert data["summary"]["has_listing_draft"] is True
    assert data["summary"]["has_active_reservation"] is True


def test_listing_draft_workflow_fixture_shape():
    body = _load("listing_draft_workflow_response.json")
    assert set(body) == {"data", "metadata"}
    assert body["metadata"]["contract"] == "v12.1-listing-draft-workflow"
    data = body["data"]
    assert {"draft", "listing_draft_link", "inventory_item", "active_reservation", "completed_sale", "summary"} <= set(data)
    assert data["draft"]["draft_id"].startswith("ld_fixture_")
    assert data["summary"]["is_inventory_linked"] is True


def test_listing_draft_list_fixture_shape():
    body = _load("listing_draft_list_filtered_response.json")
    assert {"data", "pagination", "metadata"} <= set(body)
    assert isinstance(body["data"], list) and body["data"]
    assert set(body["pagination"]) == {"limit", "offset", "count", "total", "has_more"}
    draft = body["data"][0]
    assert draft["draft_id"].startswith("ld_fixture_")
    assert draft["platform"] == "generic"
    assert draft["inventory_item_id"].startswith("item_fixture_")


def test_local_sales_summary_fixture_shape():
    body = _load("local_sales_summary_response.json")
    assert set(body) == {"data", "metadata"}
    assert body["metadata"]["contract"] == "v12.1-local-sales-summary"
    data = body["data"]
    for key in ["currency", "sale_count", "quantity_sold", "gross_sales_total_minor", "by_platform", "by_currency", "by_status", "recent_sales"]:
        assert key in data
    sale = data["recent_sales"][0]
    assert sale["sale_id"].startswith("sale_fixture_")
    assert sale["buyer_reference"] == "fixture-buyer"
    assert sale["external_order_reference"] == "fixture-order"


def test_fixture_ids_use_safe_fixture_style_values_where_appropriate():
    combined = "\n".join(_fixture_texts().values())
    for required in ["item_fixture_001", "ld_fixture_001", "sale_fixture_001", "sku_id", "1001", "en:sv03-223", "fixture-buyer", "fixture-order"]:
        assert required in combined


def test_fixture_json_contains_no_forbidden_markers_or_raw_paths():
    for name, text in _fixture_texts().items():
        lowered = text.lower()
        for marker in FORBIDDEN_MARKERS:
            assert marker.lower() not in lowered, f"{name} contains forbidden marker {marker!r}"


def test_fixture_docs_mention_sanitized_local_only_status_and_usage():
    readme = README.read_text(encoding="utf-8").lower()
    main_doc = MAIN_DOC.read_text(encoding="utf-8").lower()
    for text in [readme, main_doc]:
        assert "sanitized" in text
        assert "frontend" in text
        assert "pos" in text
        assert "not live provider" in text or "not generated from live provider" in text
        assert "not marketplace" in text or "not connected to marketplace" in text
        assert "not a substitute" in text or "not a replacement" in text
