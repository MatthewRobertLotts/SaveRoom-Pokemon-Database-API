"""Tests for v12 local listing draft persistence.

Draft persistence stores deterministic listing assistant output locally only.
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


def _create_draft(card_key: str = TEST_CARD_KEY, payload: dict | None = None):
    body = {"platform": "generic"}
    if payload:
        body.update(payload)
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.post(f"/api/v1/listings/drafts/cards/{card_key}", json=body)
    return response, mock_fetch


def _read_draft(draft_id: str):
    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        response = client.get(f"/api/v1/listings/drafts/{draft_id}")
    return response, mock_fetch


def test_create_draft_for_known_card_returns_201_and_has_draft_id():
    response, mock_fetch = _create_draft(payload={"platform": "ebay", "condition": "Near Mint"})

    assert response.status_code == 201
    mock_fetch.assert_not_called()
    body = response.json()
    assert body["metadata"]["contract"] == "v12-listing-draft"
    data = body["data"]
    assert data["draft_id"].startswith("ld_")
    assert data["card_key"] == TEST_CARD_KEY
    assert data["platform"] == "ebay"
    assert data["status"] == "draft"


def test_created_draft_stores_listing_assistant_output():
    response, _ = _create_draft(payload={"platform": "whatnot", "condition": "Excellent", "finish": "Holo", "quantity": 2})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["assistant_payload"]["metadata"]["contract"] == "v12-listing-assistant"
    assert data["assistant_payload"]["listing"]["title"] == data["listing"]["title"]
    assert data["listing"]["condition_note"] == "Excellent"
    assert "Finish: Holo" in data["listing"]["description_bullets"]
    assert data["quantity"] == 2
    assert data["pricing"] == data["assistant_payload"]["pricing"]


def test_read_draft_by_id_returns_same_draft():
    created, _ = _create_draft(payload={"platform": "shopify", "condition": "Near Mint"})
    assert created.status_code == 201
    created_data = created.json()["data"]

    read, mock_fetch = _read_draft(created_data["draft_id"])

    assert read.status_code == 200
    mock_fetch.assert_not_called()
    read_data = read.json()["data"]
    assert read_data["draft_id"] == created_data["draft_id"]
    assert read_data["listing"] == created_data["listing"]
    assert read_data["platform"] == "shopify"


def test_list_drafts_returns_created_draft():
    created, _ = _create_draft(payload={"platform": "generic", "notes": "list test"})
    assert created.status_code == 201
    draft_id = created.json()["data"]["draft_id"]

    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        listed = client.get("/api/v1/listings/drafts?limit=25")

    assert listed.status_code == 200
    mock_fetch.assert_not_called()
    ids = {draft["draft_id"] for draft in listed.json()["data"]}
    assert draft_id in ids
    assert listed.json()["metadata"]["contract"] == "v12-listing-draft"


def test_create_missing_card_returns_404():
    response, mock_fetch = _create_draft("en:not-a-real-card")

    assert response.status_code == 404
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "card_not_found"


def test_missing_draft_returns_404():
    response, mock_fetch = _read_draft("ld_not_real")

    assert response.status_code == 404
    mock_fetch.assert_not_called()
    assert response.json()["error"]["code"] == "listing_draft_not_found"


def test_patch_updates_safe_editable_fields():
    created, _ = _create_draft(payload={"platform": "ebay"})
    assert created.status_code == 201
    draft_id = created.json()["data"]["draft_id"]
    payload = {
        "title": "Updated deterministic title",
        "subtitle": "Updated subtitle",
        "description_bullets": ["Card name: Charizard ex", "Quantity: 4"],
        "tags": ["pokemon-card", "updated"],
        "condition": "Near Mint",
        "finish": "Reverse Holo",
        "quantity": 4,
        "status": "ready",
        "notes": "local draft note",
    }

    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        patched = client.patch(f"/api/v1/listings/drafts/{draft_id}", json=payload)

    assert patched.status_code == 200
    mock_fetch.assert_not_called()
    data = patched.json()["data"]
    assert data["listing"]["title"] == "Updated deterministic title"
    assert data["listing"]["subtitle"] == "Updated subtitle"
    assert data["listing"]["description_bullets"] == payload["description_bullets"]
    assert data["listing"]["tags"] == payload["tags"]
    assert data["condition"] == "Near Mint"
    assert data["finish"] == "Reverse Holo"
    assert data["quantity"] == 4
    assert data["status"] == "ready"
    assert data["listing"]["notes"] == "local draft note"


def test_patch_rejects_invalid_status():
    created, _ = _create_draft()
    assert created.status_code == 201
    draft_id = created.json()["data"]["draft_id"]

    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        patched = client.patch(f"/api/v1/listings/drafts/{draft_id}", json={"status": "published"})

    assert patched.status_code == 422
    mock_fetch.assert_not_called()


def test_archive_endpoint_marks_draft_archived():
    created, _ = _create_draft(payload={"platform": "whatnot"})
    assert created.status_code == 201
    draft_id = created.json()["data"]["draft_id"]

    with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", side_effect=AssertionError("JustTCG fetch must not be called")) as mock_fetch:
        archived = client.post(f"/api/v1/listings/drafts/{draft_id}/archive")

    assert archived.status_code == 200
    mock_fetch.assert_not_called()
    data = archived.json()["data"]
    assert data["status"] == "archived"
    assert data["archived_at"] is not None
    assert data["updated_at"] == data["archived_at"]


def test_archived_drafts_do_not_disappear_unless_explicitly_filtered():
    created, _ = _create_draft(payload={"platform": "generic"})
    assert created.status_code == 201
    draft_id = created.json()["data"]["draft_id"]
    archive = client.post(f"/api/v1/listings/drafts/{draft_id}/archive")
    assert archive.status_code == 200

    listed = client.get("/api/v1/listings/drafts?include_archived=true&limit=50")
    assert listed.status_code == 200
    assert draft_id in {draft["draft_id"] for draft in listed.json()["data"]}

    filtered = client.get("/api/v1/listings/drafts?include_archived=false&limit=50")
    assert filtered.status_code == 200
    assert draft_id not in {draft["draft_id"] for draft in filtered.json()["data"]}


def test_include_images_false_stores_images_null():
    response, _ = _create_draft(payload={"include_images": False})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["images"] is None
    assert data["assistant_payload"]["images"] is None


def test_include_pricing_false_stores_pricing_null():
    response, _ = _create_draft(payload={"include_pricing": False})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["pricing"] is None
    assert data["assistant_payload"]["pricing"] is None
    assert "Pricing omitted because include_pricing=false." in data["warnings"]


def test_include_commercial_false_stores_commercial_null():
    response, _ = _create_draft(payload={"include_commercial": False})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["commercial"] is None
    assert data["assistant_payload"]["commercial"] is None


def test_no_live_provider_calls_and_provider_status_is_safe():
    response, mock_fetch = _create_draft(payload={"platform": "ebay"})

    assert response.status_code == 201
    mock_fetch.assert_not_called()
    provider_status = response.json()["data"]["provider_status"]
    assert provider_status["justtcg"]["status"] == "not_used_for_listing_assistant"
    assert provider_status["justtcg"]["live_enabled"] is False


def test_no_usd_or_justtcg_fallback_leaks_into_draft_pricing():
    response, _ = _create_draft(payload={"platform": "ebay"})

    assert response.status_code == 201
    pricing_text = json.dumps(response.json()["data"]["pricing"]).lower()
    assert "usd" not in pricing_text
    assert "justtcg_fallback" not in pricing_text
    assert "market_price" not in pricing_text
    assert "4.99" not in pricing_text


def test_no_raw_filesystem_paths_provider_payloads_headers_or_candidates_appear():
    response, _ = _create_draft(payload={"platform": "shopify"})

    assert response.status_code == 201
    payload_text = json.dumps(response.json()).lower()
    forbidden = [
        "/media/",
        "/home/",
        "private_provider_payloads",
        "x-api-key",
        "authorization",
        "raw provider",
        "sanitized candidates",
        "account metadata",
    ]
    for marker in forbidden:
        assert marker not in payload_text


def test_create_validates_platform_and_quantity():
    invalid_payloads = [
        {"platform": "mercari"},
        {"quantity": 0},
    ]
    for payload in invalid_payloads:
        response, mock_fetch = _create_draft(payload=payload)
        assert response.status_code == 422
        mock_fetch.assert_not_called()
