"""Tests for the gated JustTCG live adapter — no network calls.

Verifies that fetch() respects the access gate, that queries are built
correctly, and that normalize/match behavior is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pricing_sources.base import PriceQuery
from pricing_sources.justtcg import JustTCGAdapter, JUSTTCG_BASE_URL, JUSTTCG_BROWSER_UA
from pricing_sources.exposure_policy import (
    JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED,
    can_expose_source,
    SURFACE_EXTERNAL_DEVELOPER_API,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "pricing_sources" / "justtcg" / "sanitized_live_charizard_shadowless_004.json"

FULL_CONFIG = {
    "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key_placeholder",
    "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
    "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
}


# ── Access gate blocking ─────────────────────────────────────────────

def test_fetch_raises_without_config():
    """fetch() with no config and no fixture raises PermissionError."""
    adapter = JustTCGAdapter()
    with pytest.raises(PermissionError, match="requires access gate config"):
        adapter.fetch({"params": {"name": "Charizard"}})


def test_fetch_raises_with_missing_key():
    """fetch() raises when API key missing."""
    adapter = JustTCGAdapter()
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
    }
    with pytest.raises(PermissionError):
        adapter.fetch({"params": {"name": "Charizard"}}, config=config)


def test_fetch_raises_with_enabled_false():
    """fetch() raises when enabled=false."""
    adapter = JustTCGAdapter()
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
    }
    with pytest.raises(PermissionError):
        adapter.fetch({"params": {"name": "Charizard"}}, config=config)


def test_fetch_raises_with_terms_unconfirmed():
    """fetch() raises when terms_confirmed=false."""
    adapter = JustTCGAdapter()
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "false",
    }
    with pytest.raises(PermissionError):
        adapter.fetch({"params": {"name": "Charizard"}}, config=config)


def test_fetch_does_not_hit_network_when_gate_fails():
    """fetch() must fail BEFORE any network call."""
    adapter = JustTCGAdapter()
    config = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(PermissionError):
            adapter.fetch({"params": {"name": "Pikachu"}}, config=config)
        mock_urlopen.assert_not_called()


# ── Query builder ────────────────────────────────────────────────────

def test_build_url_includes_game_pokemon():
    url = JustTCGAdapter._build_url({"name": "Charizard"})
    assert "game=pokemon" in url


def test_build_url_encodes_names():
    url = JustTCGAdapter._build_url({"name": "Pikachu VMAX"})
    assert "Pikachu" in url
    assert " " not in url.split("?")[1]


def test_build_url_includes_set_condition_printing():
    url = JustTCGAdapter._build_url({
        "name": "Charizard",
        "set": "base1",
        "condition": "NM",
        "printing": "Normal",
    })
    assert "set=base1" in url
    assert "condition=NM" in url
    assert "printing=Normal" in url


def test_build_url_removes_empty_params():
    url = JustTCGAdapter._build_url({"name": "Charizard", "set": "", "condition": None})
    query_string = url.split("?")[1]
    assert "set=" not in query_string
    assert "condition=" not in query_string


def test_build_url_uses_base_url():
    url = JustTCGAdapter._build_url({"name": "Test"})
    assert url.startswith(JUSTTCG_BASE_URL)


# ── Headers ──────────────────────────────────────────────────────────

def test_fetch_sends_correct_headers():
    """Verify headers include x-api-key, Accept, and User-Agent."""
    adapter = JustTCGAdapter()
    captured_req = {}

    class FakeResponse:
        def read(self):
            return b'{"data": [], "meta": {"total": 0}}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=None):
        captured_req["headers"] = dict(req.headers)
        captured_req["url"] = req.full_url
        return FakeResponse()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        adapter.fetch({"params": {"name": "Test"}}, config=FULL_CONFIG)

    headers = captured_req["headers"]
    assert "X-api-key" in headers
    assert "application/json" in headers.get("Accept", "")
    # urllib may normalize header names; check case-insensitively
    ua = headers.get("User-Agent") or headers.get("user-agent") or headers.get("User-agent") or ""
    assert "Mozilla" in ua


def test_fetch_does_not_log_key():
    """Ensure the API key is not in any string representation."""
    adapter = JustTCGAdapter()
    adapter_str = str(adapter)
    assert "tcg_test_key_placeholder" not in adapter_str
    assert "tcg_" not in adapter_str


# ── Fixture fallback still works ─────────────────────────────────────

def test_fixture_path_still_works():
    """When fixture_path is set, no network call needed."""
    adapter = JustTCGAdapter(fixture_path=FIXTURE_PATH)
    result = adapter.fetch({"params": {"name": "Anything"}})
    assert result is not None
    assert "data" in result


# ── Normalization unchanged ──────────────────────────────────────────

def test_normalize_usd_market_price():
    """Sanitized fixture normalizes to USD market_price only."""
    adapter = JustTCGAdapter(fixture_path=FIXTURE_PATH)
    raw = adapter.fetch({"test": True})
    query = PriceQuery(target_type="sellable_sku", target_id="2998642")
    observations = adapter.normalise(raw, query)
    assert len(observations) > 0
    for obs in observations:
        assert obs.currency == "USD"
        assert obs.observation_type == "market_price"


def test_normalize_not_uk_sold():
    """JustTCG is never UK sold evidence."""
    adapter = JustTCGAdapter(fixture_path=FIXTURE_PATH)
    raw = adapter.fetch({"test": True})
    query = PriceQuery(target_type="sellable_sku", target_id="2998642")
    observations = adapter.normalise(raw, query)
    for obs in observations:
        assert "uk" not in obs.marketplace.lower()


def test_match_by_tcgplayer_sku():
    """Sanitized fixture matches via tcgplayerSkuId."""
    adapter = JustTCGAdapter(fixture_path=FIXTURE_PATH)
    raw = adapter.fetch({"test": True})
    query = PriceQuery(target_type="sellable_sku", target_id="2998642")
    observations = adapter.normalise(raw, query)
    matches = adapter.match_observations(observations, query)
    sku_matches = [m for m in matches if m.match_method == "tcgplayerSkuId"]
    assert len(sku_matches) > 0


# ── Capabilities ─────────────────────────────────────────────────────

def test_capabilities_external_resale_false():
    adapter = JustTCGAdapter()
    caps = adapter.capabilities()
    assert caps["external_api_resale_allowed"] is False
    assert caps["saveroom_ecosystem_apps_allowed"] is True
    assert caps["price_type"] == "market_price"


def test_permanent_resale_block():
    assert JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED is True


def test_exposure_policy_blocks_external():
    assert can_expose_source("justtcg", SURFACE_EXTERNAL_DEVELOPER_API) is False
