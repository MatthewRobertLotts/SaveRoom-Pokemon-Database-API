"""v12.2 OpenAPI schema hygiene tests.

These tests exercise local FastAPI schema generation only. They do not call
provider, marketplace, network, or LLM APIs.
"""
from __future__ import annotations

from unittest.mock import patch

from pokemon_db_v2_fastapi import create_app

EXPECTED_PATHS = {
    "/api/v1/cards/{card_key}/detail",
    "/api/v1/cards/detail/batch",
    "/api/v1/inventory/items",
    "/api/v1/inventory/items/{item_id}",
    "/api/v1/inventory/items/{item_id}/workflow",
    "/api/v1/listings/drafts",
    "/api/v1/listings/drafts/{draft_id}",
    "/api/v1/listings/drafts/{draft_id}/workflow",
    "/api/v1/sales",
    "/api/v1/sales/{sale_id}",
    "/api/v1/sales/summary",
}


def _openapi_schema() -> dict:
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("provider calls are forbidden")) as mock_provider:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network calls are forbidden")) as mock_request:
            app = create_app()
            schema = app.openapi()
    mock_provider.assert_not_called()
    mock_request.assert_not_called()
    return schema


def test_openapi_builds_without_monkeypatching_delivery_policy_update():
    schema = _openapi_schema()

    assert schema.get("openapi")
    assert len(schema.get("paths", {})) >= len(EXPECTED_PATHS)
    assert "DeliveryPolicyUpdate" in schema.get("components", {}).get("schemas", {})


def test_expected_v12_paths_exist_in_openapi():
    schema = _openapi_schema()
    paths = set(schema.get("paths", {}))

    assert EXPECTED_PATHS <= paths
    assert "get" in schema["paths"]["/api/v1/sales/summary"]


def test_local_sales_summary_uses_typed_component_schemas():
    schema = _openapi_schema()
    components = schema.get("components", {}).get("schemas", {})

    for name in [
        "LocalSalesSummaryResponseV1",
        "LocalSalesSummaryDataV1",
        "LocalSalesSummaryFiltersV1",
        "LocalSalesSummaryTotalsV1",
        "LocalSalesSummaryPlatformRowV1",
        "LocalSalesSummaryStatusRowV1",
        "LocalSalesSummaryCurrencyRowV1",
    ]:
        assert name in components

    response = components["LocalSalesSummaryResponseV1"]
    data_schema = response["properties"]["data"]
    assert data_schema == {"$ref": "#/components/schemas/LocalSalesSummaryDataV1"}

    data_props = components["LocalSalesSummaryDataV1"]["properties"]
    assert data_props["filters"] == {"$ref": "#/components/schemas/LocalSalesSummaryFiltersV1"}
    assert data_props["summary"] == {"$ref": "#/components/schemas/LocalSalesSummaryTotalsV1"}
    assert data_props["by_platform"]["items"] == {"$ref": "#/components/schemas/LocalSalesSummaryPlatformRowV1"}
    assert data_props["by_status"]["items"] == {"$ref": "#/components/schemas/LocalSalesSummaryStatusRowV1"}
    assert data_props["by_currency"]["items"] == {"$ref": "#/components/schemas/LocalSalesSummaryCurrencyRowV1"}


def test_operation_ids_are_unique():
    schema = _openapi_schema()
    operation_ids = []
    for methods in schema.get("paths", {}).values():
        for meta in methods.values():
            if isinstance(meta, dict) and meta.get("operationId"):
                operation_ids.append(meta["operationId"])

    duplicates = sorted({op for op in operation_ids if operation_ids.count(op) > 1})
    assert duplicates == []
