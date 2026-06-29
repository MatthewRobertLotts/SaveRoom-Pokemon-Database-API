"""Tests for the sanitized JustTCG live fixture.

Verifies the committed fixture is safe (no secrets) and that the
Just normalize and match it correctly.

Fixture: Charizard / Base Set (Shadowless) / 004/102
Source: sanitized JustTCG live smoke test 2026-06-29
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pricing_sources.base import ListingType, PriceQuery
from pricing_sources.justtcg import JustTCGAdapter
from pricing_sources.exposure_policy import (
    JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED,
    can_expose_source,
    SURFACE_SAVEROOM_INTERNAL,
    SURFACE_SAVEROOM_CUSTOMER_APP,
    SURFACE_EXTERNAL_DEVELOPER_API,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "pricing_sources" / "justtcg" / "sanitized_live_charizard_shadowless_004.json"


@pytest.fixture
def fixture_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def adapter():
    return JustTCGAdapter(fixture_path=FIXTURE_PATH)


# ── Safety: no secrets in fixture ────────────────────────────────────

def test_fixture_no_api_key(fixture_data):
    text = json.dumps(fixture_data).lower()
    # Check for actual API key patterns, not the word "api_key" in metadata fields
    import re
    # Look for key-like values (tcg_ prefix, hex strings that look like keys)
    key_patterns = [
        r'"x-api-key"\s*:\s*"',
        r'"authorization"\s*:\s*"',
        r'"api_key"\s*:\s*"',
        r'"apikey"\s*:\s*"',
        r'tcg_[a-z0-9]{20,}',  # JustTCG key format
    ]
    for pattern in key_patterns:
        assert not re.search(pattern, text), f"Found potential API key pattern: {pattern}"


def test_fixture_no_account_metadata(fixture_data):
    text = json.dumps(fixture_data).lower()
    assert "apiplan" not in text
    assert "apirequestsremaining" not in text
    assert "accountid" not in text
    assert "subscriptionid" not in text


def test_fixture_no_headers(fixture_data):
    text = json.dumps(fixture_data).lower()
    assert "request-header" not in text
    assert '"x-api-key"' not in text


# ── Fixture structure ────────────────────────────────────────────────

def test_fixture_has_one_card(fixture_data):
    cards = fixture_data.get("data", [])
    assert len(cards) == 1


def test_fixture_card_is_charizard(fixture_data):
    card = fixture_data["data"][0]
    assert card["name"] == "Charizard"


def test_fixture_set_is_base_set_shadowless(fixture_data):
    card = fixture_data["data"][0]
    assert "shadowless" in card.get("set", "").lower()
    assert "Base Set (Shadowless)" in card.get("set_name", "")


def test_fixture_number(fixture_data):
    card = fixture_data["data"][0]
    assert card["number"] == "004/102"


def test_fixture_has_variants(fixture_data):
    card = fixture_data["data"][0]
    assert len(card.get("variants", [])) > 0


def test_fixture_variant_has_uuid(fixture_data):
    card = fixture_data["data"][0]
    for v in card["variants"]:
        assert v.get("uuid"), "Every variant must have a UUID"


def test_fixture_variant_has_tcgplayer_sku(fixture_data):
    card = fixture_data["data"][0]
    has_sku = any(v.get("tcgplayerSkuId") for v in card["variants"])
    assert has_sku, "At least one variant must have tcgplayerSkuId"


def test_fixture_variant_has_price(fixture_data):
    card = fixture_data["data"][0]
    has_price = any(v.get("price") is not None for v in card["variants"])
    assert has_price, "At least one variant must have a price"


def test_fixture_has_price_history(fixture_data):
    card = fixture_data["data"][0]
    has_history = any(v.get("priceHistory") is not None for v in card["variants"])
    assert has_history, "At least one variant must have priceHistory"


# ── Normalization ────────────────────────────────────────────────────

def test_normalize_emits_usd(adapter):
    query = PriceQuery(target_type="sellable_sku", target_id="2998644")
    raw = adapter.fetch({"test": True})
    observations = adapter.normalise(raw, query)
    assert len(observations) > 0
    for obs in observations:
        assert obs.currency == "USD"


def test_normalize_market_price_only(adapter):
    query = PriceQuery(target_type="sellable_sku", target_id="2998644")
    raw = adapter.fetch({"test": True})
    observations = adapter.normalise(raw, query)
    for obs in observations:
        assert obs.listing_type == ListingType.MARKET_PRICE
        assert obs.observation_type == "market_price"


def test_normalize_not_uk_sold(adapter):
    query = PriceQuery(target_type="sellable_sku", target_id="2998644")
    raw = adapter.fetch({"test": True})
    observations = adapter.normalise(raw, query)
    for obs in observations:
        assert obs.listing_type != ListingType.SOLD
        assert "uk" not in obs.marketplace.lower()


# ── Matching ─────────────────────────────────────────────────────────

def test_match_uses_tcgplayer_sku(adapter):
    query = PriceQuery(target_type="sellable_sku", target_id="2998644")
    raw = adapter.fetch({"test": True})
    observations = adapter.normalise(raw, query)
    matches = adapter.match_observations(observations, query)
    # At least one match should use tcgplayerSkuId
    sku_matches = [m for m in matches if m.match_method == "tcgplayerSkuId"]
    assert len(sku_matches) > 0


def test_match_has_high_confidence(adapter):
    query = PriceQuery(target_type="sellable_sku", target_id="2998644")
    raw = adapter.fetch({"test": True})
    observations = adapter.normalise(raw, query)
    matches = adapter.match_observations(observations, query)
    high_matches = [m for m in matches if m.match_confidence.value == "HIGH"]
    assert len(high_matches) > 0


# ── Exposure policy ──────────────────────────────────────────────────

def test_external_api_resale_blocked():
    assert JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED is True


def test_justtcg_internal_allowed():
    assert can_expose_source("justtcg", SURFACE_SAVEROOM_INTERNAL) is True


def test_justtcg_customer_app_allowed():
    assert can_expose_source("justtcg", SURFACE_SAVEROOM_CUSTOMER_APP) is True


def test_justtcg_external_blocked():
    assert can_expose_source("justtcg", SURFACE_EXTERNAL_DEVELOPER_API) is False


# ── Fixture metadata ─────────────────────────────────────────────────

def test_fixture_metadata_present(fixture_data):
    meta = fixture_data.get("_fixture_metadata", {})
    assert meta["fixture_type"] == "sanitized_live_shape"
    assert meta["contains_api_key"] is False
    assert meta["contains_account_metadata"] is False
    assert meta["external_api_resale_allowed"] is False
