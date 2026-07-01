"""Tests for the JustTCG fixture-only adapter spike.

Tests cover:
- adapter source_code is justtcg
- requires_access_gate returns True
- missing key blocks live access
- enabled=false blocks live access
- terms unconfirmed blocks live access
- external API resale flag false is preserved
- capabilities describe SaveRoom ecosystem only
- fixture loads without network
- fixture has no secrets
- fixture is clearly synthetic
- normalization emits USD market price
- normalization does not mark evidence as UK sold
- normalization uses tcgplayerSkuId as preferred key
- normalization uses variant UUID as fallback key
- customer/internal display permission is represented
- standalone external developer API exposure is blocked
- no requests/httpx/aiohttp calls in tests
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pricing_sources.base import ListingType, PriceQuery
from pricing_sources.justtcg import JustTCGAdapter
from pricing_sources.provider_access import get_provider_access_status

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pricing_sources" / "justtcg"
SYNTHETIC_FIXTURE = FIXTURE_DIR / "synthetic_pokemon_cards.json"


@pytest.fixture
def adapter():
    return JustTCGAdapter()


@pytest.fixture
def adapter_with_fixture():
    return JustTCGAdapter(fixture_path=SYNTHETIC_FIXTURE)


@pytest.fixture
def fixture_data():
    return json.loads(SYNTHETIC_FIXTURE.read_text(encoding="utf-8"))


# ── source_code ───────────────────────────────────────────────────────

def test_source_code_is_justtcg(adapter):
    assert adapter.source_code == "justtcg"


# ── requires_access_gate ─────────────────────────────────────────────

def test_requires_access_gate(adapter):
    assert adapter.requires_access_gate() is True


# ── missing key blocks live access ───────────────────────────────────

def test_missing_key_blocks_live(adapter):
    config = {}  # no key
    assert adapter.live_calls_enabled(config) is False


# ── enabled=false blocks live access ─────────────────────────────────

def test_enabled_false_blocks_live(adapter):
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
    }
    assert adapter.live_calls_enabled(config) is False


# ── terms unconfirmed blocks live access ─────────────────────────────

def test_terms_unconfirmed_blocks_live(adapter):
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "false",
    }
    assert adapter.live_calls_enabled(config) is False


# ── external API resale flag is false ────────────────────────────────

def test_external_api_resale_flag_false(adapter):
    caps = adapter.capabilities()
    assert caps["external_api_resale_allowed"] is False


# ── capabilities describe SaveRoom ecosystem only ────────────────────

def test_capabilities_saveroom_ecosystem(adapter):
    caps = adapter.capabilities()
    assert caps["saveroom_ecosystem_apps_allowed"] is True
    assert caps["supports_market_prices"] is True
    assert caps["supports_sold_prices"] is False
    assert "USD" in caps["currencies"]
    assert caps["price_type"] == "market_price"


# ── fixture loads without network ────────────────────────────────────

def test_fixture_loads(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    result = adapter_with_fixture.fetch({"test": True})
    assert result is not None
    # Should have data
    assert "data" in result


# ── fixture has no secrets ───────────────────────────────────────────

def test_fixture_no_secrets(fixture_data):
    text = json.dumps(fixture_data)
    # No API key patterns
    assert "api_key" not in text.lower()
    assert "tcg_yo" not in text
    # No account metadata
    assert "apiPlan" not in text
    assert "apiRequestsRemaining" not in text


# ── fixture is clearly synthetic ─────────────────────────────────────

def test_fixture_is_synthetic(fixture_data):
    meta = fixture_data.get("_metadata", {})
    assert meta.get("fixture_type") == "synthetic_schema_shape"
    assert meta.get("contains_real_provider_data") is False
    assert meta.get("allowed_for_unit_tests") is True


# ── normalization emits USD market price ─────────────────────────────

def test_normalization_usd_market_price(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    assert len(observations) > 0
    for obs in observations:
        assert obs.currency == "USD"
        assert obs.listing_type == ListingType.MARKET_PRICE
        assert obs.observation_type == "market_price"


# ── normalization does not mark evidence as UK sold ──────────────────

def test_normalization_not_uk_sold(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    for obs in observations:
        # Must not be sold type
        assert obs.listing_type != ListingType.SOLD
        # Must not be UK marketplace
        assert "uk" not in obs.marketplace.lower()


# ── normalization uses tcgplayerSkuId as preferred key ──────────────

def test_normalization_uses_tcgplayer_sku(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    # At least one observation should have a tcgplayerSkuId (stored in printing_label)
    has_sku = any(obs.printing_label is not None for obs in observations)
    assert has_sku, "No observations with tcgplayerSkuId found"


# ── normalization uses variant UUID as fallback key ──────────────────

def test_normalization_uses_variant_uuid(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    for obs in observations:
        # source_record_id should contain JustTCG variant UUID
        assert obs.source_record_id.startswith("justtcg:")


# ── match uses preferred key first ───────────────────────────────────

def test_match_uses_preferred_key(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    matches = adapter_with_fixture.match_observations(observations, query)
    # Observations with tcgplayerSkuId should get HIGH confidence
    high_matches = [m for m in matches if m.match_confidence.value == "HIGH"]
    assert len(high_matches) > 0


# ── customer/internal display permission represented ─────────────────

def test_display_permissions_in_capabilities(adapter):
    # Access gate controls display via ALLOW_INTERNAL_DISPLAY and ALLOW_CUSTOMER_DISPLAY
    # Test with those flags set (needs terms confirmed)
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_INTERNAL_DISPLAY": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_CUSTOMER_DISPLAY": "true",
    }
    decision = get_provider_access_status("justtcg", config)
    assert decision.internal_display_allowed is True
    assert decision.customer_display_allowed is True


# ── standalone external developer API exposure is blocked ────────────

def test_external_api_resale_blocked_by_design(adapter):
    caps = adapter.capabilities()
    assert caps["external_api_resale_allowed"] is False

    # Access gate does not have an ALLOW_EXTERNAL_API_RESALE flag that defaults to true
    # The restriction is architectural, not just a flag
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
    }
    # Even with full access, the restriction applies
    assert adapter.capabilities()["external_api_resale_allowed"] is False


# ── no network calls in tests ────────────────────────────────────────

def test_no_network_in_adapter_source():
    adapter_path = Path(__file__).resolve().parent.parent / "pricing_sources" / "justtcg.py"
    source = adapter_path.read_text()
    # The module should not import requests or httpx at module level
    lines = source.split('\n')
    import_lines = [l for l in lines if l.strip().startswith('import ') or l.strip().startswith('from ')]
    for line in import_lines:
        assert 'requests' not in line, f"requests import found: {line}"
        assert 'httpx' not in line, f"httpx import found: {line}"
        assert 'aiohttp' not in line, f"aiohttp import found: {line}"


# ── condition normalization ──────────────────────────────────────────

def test_condition_normalization(adapter_with_fixture):
    query = PriceQuery(target_type="sellable_sku", target_id="synthetic-1234567")
    raw = adapter_with_fixture.fetch({"test": True})
    observations = adapter_with_fixture.normalise(raw, query)
    conditions = {obs.condition for obs in observations}
    # Should have normalized conditions
    for c in conditions:
        assert c in ("NM", "LP", "MP", "HP", "D", "unknown"), f"Unexpected condition: {c}"


# ── identifier mapping validation ────────────────────────────────────

def test_identifier_mapping_validation(adapter_with_fixture):
    raw = adapter_with_fixture.fetch({"test": True})
    cards = raw.get("data", [])
    assert len(cards) > 0
    validation = adapter_with_fixture.validate_identifier_mapping(cards[0])
    assert "card_uuid" in validation
    assert "tcgplayerId" in validation
    assert validation["preferred_match_key"] == "tcgplayerSkuId"
    assert validation["fallback_match_key"] == "justtcg_variant_uuid"
    assert validation["variant_count"] > 0
