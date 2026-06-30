"""Tests for v12 UK-primary pricing recommendation fields on prices endpoint.

The endpoint recommendation wiring uses local GBP evidence only in this
milestone. No live provider calls, network calls, DB migrations, raw provider
payloads, or API credits are required.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

# Ensure auth is NOT required for endpoint contract tests.
os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import build_v1_price_recommendation, create_app


client = TestClient(create_app())
TEST_CARD_KEY = "en:sv03-223"


def _get_prices_with_no_live_provider_call():
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", return_value=None) as mock_fetch:
        response = client.get(f"/api/v1/prices/cards/{TEST_CARD_KEY}")
    return response, mock_fetch


def test_prices_endpoint_returns_200_for_known_card_and_existing_fields_remain():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    body = response.json()
    assert body["card_key"] == TEST_CARD_KEY
    data = body["data"]
    for field in (
        "currency",
        "evidence_count",
        "recommended_raw_count",
        "raw_median",
        "raw_min",
        "raw_max",
        "graded_count",
        "bundle_count",
        "noise_count",
        "latest_fetched_at",
        "source",
        "by_condition",
        "with_postage",
    ):
        assert field in data


def test_prices_endpoint_adds_recommendation_section():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    recommendation = response.json()["data"]["recommendation"]
    assert recommendation["currency"] == "GBP"
    assert recommendation["region_basis"] in {"uk_primary", "uk_primary_thin_or_medium", "no_pricing_evidence"}
    assert "primary_uk_price" in recommendation
    assert "general_market_estimate" in recommendation
    assert "recommended_listing_price" in recommendation
    assert isinstance(recommendation["source_breakdown"], list)
    assert isinstance(recommendation["confidence_reasons"], list)
    assert isinstance(recommendation["warnings"], list)
    assert recommendation["calculation_method"].startswith("local_uk_only")


def test_recommendation_primary_price_uses_local_uk_gbp_evidence_only():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    data = response.json()["data"]
    recommendation = data["recommendation"]
    primary = recommendation["primary_uk_price"]

    assert primary is not None
    assert primary["amount"] == data["raw_median"]
    assert primary["currency"] == "GBP"
    assert primary["evidence_count"] == data["recommended_raw_count"]
    assert primary["source_type"] == "local_uk_evidence"
    assert primary["price_type"] == "sold_completed"


def test_recommendation_general_and_listing_price_are_balanced_local_values():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    recommendation = response.json()["data"]["recommendation"]
    primary = recommendation["primary_uk_price"]
    general = recommendation["general_market_estimate"]
    listing = recommendation["recommended_listing_price"]

    assert general["amount"] == primary["amount"]
    assert listing["amount"] == general["amount"]
    assert listing["strategy"] == "balanced"


def test_recommendation_does_not_contain_justtcg_usd_market_price():
    mock_justtcg_price = {
        "source_code": "justtcg",
        "currency": "USD",
        "amount": 4.99,
        "observation_type": "market_price",
        "listing_type": "market_price",
        "attribution": "Pricing data provided by JustTCG",
    }
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", return_value=mock_justtcg_price):
        response = client.get(f"/api/v1/prices/cards/{TEST_CARD_KEY}")

    assert response.status_code == 200
    recommendation = response.json()["data"]["recommendation"]
    recommendation_text = json.dumps(recommendation).lower()
    assert "4.99" not in recommendation_text
    assert "justtcg_fallback" not in recommendation_text
    assert "market_price" not in recommendation_text
    assert recommendation["primary_uk_price"]["currency"] == "GBP"
    assert recommendation["general_market_estimate"]["currency"] == "GBP"
    assert recommendation["recommended_listing_price"]["currency"] == "GBP"


def test_recommendation_builder_does_not_call_justtcg_fetch_helper():
    summary = {
        "currency": "GBP",
        "evidence_count": 12,
        "recommended_raw_count": 12,
        "raw_median": 18.64,
        "raw_min": 12.0,
        "raw_max": 24.0,
        "latest_fetched_at": "2026-06-30T00:00:00Z",
        "source": "ebay_uk_sold",
    }
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("should not be called")) as mock_fetch:
        recommendation = build_v1_price_recommendation(summary, {"justtcg": {"status": "enabled"}})

    mock_fetch.assert_not_called()
    assert recommendation["primary_uk_price"]["amount"] == 18.64
    assert recommendation["uk_adjusted_fallback_price"] is None
    assert recommendation["adjustment_multiplier"] is None


def test_no_fallback_provider_can_populate_primary_uk_price():
    summary = {
        "currency": "GBP",
        "evidence_count": 0,
        "recommended_raw_count": 0,
        "raw_median": None,
        "source": None,
    }

    recommendation = build_v1_price_recommendation(summary, {"justtcg": {"status": "enabled"}})

    assert recommendation["primary_uk_price"] is None
    assert recommendation["general_market_estimate"] is None
    assert recommendation["recommended_listing_price"] is None
    assert recommendation["uk_adjusted_fallback_price"] is None


def test_endpoint_test_path_makes_no_live_provider_call():
    response, mock_fetch = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    # Existing endpoint integration still invokes the JustTCG helper; this test
    # replaces it with a mock so no live provider/API call can occur.
    mock_fetch.assert_called_once()
    assert "recommendation" in response.json()["data"]


def test_recommendation_confidence_warnings_and_source_breakdown_present():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    recommendation = response.json()["data"]["recommendation"]
    assert recommendation["confidence"] in {"high", "medium", "low", "very_low", "none"}
    assert isinstance(recommendation["confidence_score"], float)
    assert isinstance(recommendation["warnings"], list)
    assert recommendation["source_breakdown"]
    first_source = recommendation["source_breakdown"][0]
    assert first_source["tier"] == 1
    assert first_source["can_be_uk_sold_evidence"] is True


def test_recommendation_contains_no_raw_provider_payloads_or_filesystem_paths():
    response, _ = _get_prices_with_no_live_provider_call()

    assert response.status_code == 200
    recommendation_text = json.dumps(response.json()["data"]["recommendation"])
    assert "private_provider_payloads" not in recommendation_text
    assert "/media/" not in recommendation_text
    assert "/home/" not in recommendation_text
    assert "x-api-key" not in recommendation_text.lower()
    assert "authorization" not in recommendation_text.lower()
