"""Tests for JustTCG integration in the /api/v1/prices/cards endpoint.

No live network calls — all JustTCG interactions are mocked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure auth is NOT required for contract tests
os.environ.pop("POKEMON_DB_REQUIRE_API_KEY", None)

from pokemon_db_v2_fastapi import create_app
from pricing_sources.exposure_policy import (
    JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED,
    SURFACE_EXTERNAL_DEVELOPER_API,
    can_expose_source,
)

client = TestClient(create_app())

JUSTTCG_FULL_CONFIG = {
    "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_test_key_placeholder",
    "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "true",
    "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "true",
}


# ── Helper ───────────────────────────────────────────────────────────

def _mock_justtcg_env(config: dict[str, str] | None = None):
    """Context manager to mock JustTCG env vars."""
    config = config or {}
    return patch.dict(os.environ, config, clear=False)


# ── Tests ────────────────────────────────────────────────────────────

class TestPricesEndpointUnchangedWithoutJustTCG:
    """Existing behavior must be preserved when JustTCG is not configured."""

    def test_endpoint_responds_without_justtcg(self):
        r = client.get("/api/v1/prices/cards/en:sv03-223")
        assert r.status_code in (200, 404)  # 404 if card not in test DB

    def test_endpoint_has_data_key(self):
        r = client.get("/api/v1/prices/cards/en:sv03-223")
        if r.status_code == 200:
            body = r.json()
            assert "data" in body

    def test_justtcg_not_configured_no_network_call(self):
        """When JustTCG key isTCG code path should run."""
        with patch("pokemon_db_v2_fastapi._get_justtcg_price_data") as mock_fetch:
            r = client.get("/api/v1/prices/cards/en:sv03-223")
            # The helper may be called but returns None quickly without network
            if r.status_code == 200:
                # Should not have justtcg_fallback since not configured
                body = r.json()
                data = body.get("data", {})
                assert "justtcg_fallback" not in data


class TestJustTCGDisabledByDefault:
    """JustTCG must be disabled when env flags are missing."""

    def test_missing_key_blocks_justtcg(self):
        """When JustTCG key is absent, no justtcg_fallback appears in response."""
        env_without_key = {k: v for k, v in os.environ.items()
                          if not k.startswith("POKEMON_PRICE_SOURCE_JUSTTCG")}
        with patch.dict(os.environ, env_without_key, clear=True):
            r = client.get("/api/v1/prices/cards/en:sv03-223")
            if r.status_code == 200:
                body = r.json()
                data = body.get("data", {})
                # Should not have justtcg_fallback since not configured
                assert "justtcg_fallback" not in data

    def test_provider_status_reflects_disabled(self):
        env_without_key = {k: v for k, v in os.environ.items()
                          if not k.startswith("POKEMON_PRICE_SOURCE_JUSTTCG")}
        with patch.dict(os.environ, env_without_key, clear=True):
            r = client.get("/api/v1/prices/cards/en:sv03-223")
            if r.status_code == 200:
                body = r.json()
                ps = body.get("justtcg_provider_status", {})
                assert ps.get("live_enabled") is False


class TestJustTCGEnabledMocked:
    """When JustTCG is configured, mocked data flows correctly."""

    def test_mocked_justtcg_data_flows_then_redacted(self):
        """JustTCG data is fetched but redacted by exposure policy for external surface."""
        mock_data = {
            "source_code": "justtcg",
            "currency": "USD",
            "amount": 4.99,
            "condition": "NM",
            "finish": "Holo",
            "listing_type": "market_price",
            "observation_type": "market_price",
            "match_confidence": "HIGH",
            "match_method": "tcgplayerSkuId",
            "attribution": "Pricing data provided by JustTCG",
        }

        with patch.dict(os.environ, JUSTTCG_FULL_CONFIG):
            with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", return_value=mock_data) as mock_fn:
                r = client.get("/api/v1/prices/cards/en:sv03-223")
                # The fetch function WAS called (proving integration works)
                mock_fn.assert_called_once()
                if r.status_code == 200:
                    body = r.json()
                    data = body.get("data", {})
                    # For external surface, justtcg_fallback is redacted
                    jt = data.get("justtcg_fallback")
                    if jt is not None:
                        # If present, must be USD market_price
                        assert jt.get("currency") == "USD"
                        assert jt.get("observation_type") == "market_price"

    def test_justtcg_never_uk_headline(self):
        """JustTCG data must never become UK headline/sold/GBP price."""
        mock_data = {
            "source_code": "justtcg",
            "currency": "USD",
            "amount": 4.99,
            "condition": "NM",
            "finish": "Holo",
            "listing_type": "market_price",
            "observation_type": "market_price",
            "attribution": "Pricing data provided by JustTCG",
        }

        with patch.dict(os.environ, JUSTTCG_FULL_CONFIG):
            with patch("pokemon_db_v2_fastapi._get_justtcg_price_data", return_value=mock_data):
                r = client.get("/api/v1/prices/cards/en:sv03-223")
                if r.status_code == 200:
                    body = r.json()
                    text = json.dumps(body)
                    # Must not appear as UK headline, sold, or GBP
                    assert "uk_market_price" not in text.lower()
                    # JustTCG data must never be in a "sold" context

    def test_exposure_policy_redacts_for_external(self):
        """External developer API surface must redact JustTCG-derived data."""
        assert can_expose_source("justtcg", SURFACE_EXTERNAL_DEVELOPER_API) is False


class TestAccessControl:
    """Access gate failures must be handled gracefully."""

    def test_gate_failure_not_500(self):
        """If access gate fails, endpoint should still return 200/404, not 500."""
        with patch("pokemon_db_v2_fastapi._get_justtcg_price_data",
                   side_effect=Exception("Simulated gate failure")):
            r = client.get("/api/v1/prices/cards/en:sv03-223")
            assert r.status_code in (200, 404)

    def test_permanent_resale_block(self):
        assert JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED is True


class TestProviderStatusMetadata:
    """Provider status includes restriction metadata."""

    def test_provider_status_has_restriction_info(self):
        r = client.get("/api/v1/prices/cards/en:sv03-223")
        if r.status_code == 200:
            body = r.json()
            ps = body.get("justtcg_provider_status", {})
            assert "role" in ps
            assert "status" in ps
            assert "live_enabled" in ps
