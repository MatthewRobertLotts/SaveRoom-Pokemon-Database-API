"""Tests for the v12 deterministic listing assistant endpoint.

The listing assistant uses the local UK-primary pricing recommendation layer only.
It must not call live providers, marketplace APIs, network endpoints, or LLMs.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import create_app


client = TestClient(create_app())
TEST_CARD_KEY = "en:sv03-223"


def _post_listing(card_key: str = TEST_CARD_KEY, payload: dict | None = None):
    body = {"platform": "generic"}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.post(f"/api/v1/listings/assist/cards/{card_key}", json=body)
    return response, mock_fetch


def test_listing_assistant_endpoint_exists_and_known_card_returns_200():
    response, mock_fetch = _post_listing()

    assert response.status_code == 200
    mock_fetch.assert_not_called()
    body = response.json()
    assert body["metadata"]["contract"] == "v12-listing-assistant"
    assert body["data"]["metadata"]["contract"] == "v12-listing-assistant"


def test_listing_assistant_missing_card_returns_404():
    response, mock_fetch = _post_listing("en:not-a-real-card")

    assert response.status_code == 404
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "card_not_found"


def test_listing_response_has_card_listing_and_metadata_sections():
    response, _ = _post_listing()

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data).issuperset({"card", "listing", "metadata", "platform_guidance", "provider_status"})
    assert data["card"]["card_key"] == TEST_CARD_KEY
    assert data["card"]["name"]
    assert data["listing"]["title"]
    assert data["metadata"]["api_version"] == "v1"


def test_title_is_non_empty_and_contains_card_name():
    response, _ = _post_listing(payload={"platform": "ebay", "title_style": "seo"})

    assert response.status_code == 200
    data = response.json()["data"]
    title = data["listing"]["title"]
    assert title
    assert data["card"]["name"] in title


def test_description_bullets_are_deterministic_from_known_fields():
    payload = {"condition": "Near Mint", "finish": "Holo", "quantity": 2}
    first, _ = _post_listing(payload=payload)
    second, _ = _post_listing(payload=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_bullets = first.json()["data"]["listing"]["description_bullets"]
    second_bullets = second.json()["data"]["listing"]["description_bullets"]
    assert first_bullets == second_bullets
    assert any(b == "Condition: Near Mint" for b in first_bullets)
    assert any(b == "Finish: Holo" for b in first_bullets)
    assert any(b == "Quantity: 2" for b in first_bullets)


def test_include_images_false_returns_images_null():
    response, _ = _post_listing(payload={"include_images": False})

    assert response.status_code == 200
    assert response.json()["data"]["images"] is None


def test_include_pricing_false_returns_pricing_null():
    response, _ = _post_listing(payload={"include_pricing": False})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pricing"] is None
    assert "Pricing omitted because include_pricing=false." in data["warnings"]


def test_include_commercial_false_returns_commercial_null():
    response, _ = _post_listing(payload={"include_commercial": False})

    assert response.status_code == 200
    assert response.json()["data"]["commercial"] is None


def test_platform_supports_whatnot_ebay_shopify_and_generic():
    expected_limits = {"whatnot": 80, "ebay": 80, "shopify": 120, "generic": 120}
    for platform, title_limit in expected_limits.items():
        response, _ = _post_listing(payload={"platform": platform})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["platform_guidance"]["platform"] == platform
        assert data["platform_guidance"]["title_limit"] == title_limit
        assert data["listing"]["title"]


def test_condition_is_only_included_when_supplied():
    no_condition, _ = _post_listing()
    with_condition, _ = _post_listing(payload={"condition": "Excellent"})

    assert no_condition.status_code == 200
    assert with_condition.status_code == 200
    no_listing = no_condition.json()["data"]["listing"]
    yes_listing = with_condition.json()["data"]["listing"]
    assert no_listing["condition_note"] is None
    assert not any(b.startswith("Condition:") for b in no_listing["description_bullets"])
    assert yes_listing["condition_note"] == "Excellent"
    assert "Condition: Excellent" in yes_listing["description_bullets"]


def test_pricing_uses_recommendation_not_raw_provider_data():
    listing_response, _ = _post_listing()
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", return_value=None):
        price_response = client.get(f"/api/v1/prices/cards/{TEST_CARD_KEY}")

    assert listing_response.status_code == 200
    assert price_response.status_code == 200
    listing_pricing = listing_response.json()["data"]["pricing"]
    recommendation = price_response.json()["data"]["recommendation"]
    assert listing_pricing["suggested_price"] == recommendation["recommended_listing_price"]["amount"]
    assert listing_pricing["based_on_recommendation"]["primary_uk_price"] == recommendation["primary_uk_price"]
    assert listing_pricing["source_summary"]["calculation_method"] == recommendation["calculation_method"]


def test_get_justtcg_price_data_is_not_called_and_no_live_provider_call_is_made():
    response, mock_fetch = _post_listing(payload={"platform": "whatnot"})

    assert response.status_code == 200
    mock_fetch.assert_not_called()
    provider_status = response.json()["data"]["provider_status"]
    assert provider_status["justtcg"]["status"] == "not_used_for_listing_assistant"
    assert provider_status["justtcg"]["live_enabled"] is False


def test_no_usd_or_justtcg_fallback_price_leaks_into_listing_pricing():
    response, _ = _post_listing(payload={"platform": "ebay"})

    assert response.status_code == 200
    pricing_text = json.dumps(response.json()["data"]["pricing"]).lower()
    assert "usd" not in pricing_text
    assert "justtcg_fallback" not in pricing_text
    assert "market_price" not in pricing_text
    assert "4.99" not in pricing_text


def test_output_does_not_include_raw_filesystem_paths_or_private_payload_markers():
    response, _ = _post_listing()

    assert response.status_code == 200
    payload_text = json.dumps(response.json())
    assert "/media/" not in payload_text
    assert "/home/" not in payload_text
    assert "private_provider_payloads" not in payload_text
    assert "x-api-key" not in payload_text.lower()
    assert "authorization" not in payload_text.lower()
    assert "raw provider" not in payload_text.lower()
    assert "sanitized candidates" not in payload_text.lower()


def test_request_validation_rejects_invalid_platform_strategy_title_style_and_quantity():
    invalid_payloads = [
        {"platform": "bad"},
        {"pricing_strategy": "aggressive"},
        {"title_style": "hype"},
        {"quantity": 0},
    ]
    for payload in invalid_payloads:
        response, mock_fetch = _post_listing(payload=payload)
        assert response.status_code == 422
        mock_fetch.assert_not_called()
