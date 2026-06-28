"""Tests for v11.2 adapter-framework access gate integration.

Verifies that the provider access gate is properly wired into the adapter
framework. Uses fake adapter classes. No external calls. No real secrets.
"""
from __future__ import annotations

import pytest

from pricing_sources.base import PriceSourceAdapter, PriceQuery
from pricing_sources.provider_access import ProviderAccessStatus


# ── Fake keyed adapter for testing ───────────────────────────────────────

class FakeKeyedAdapter(PriceSourceAdapter):
    """Simulates a future keyed/paid adapter."""

    def __init__(self, code: str = "fakekeyed"):
        self._code = code

    @property
    def source_code(self) -> str:
        return self._code

    @property
    def source_name(self) -> str:
        return "Fake Keyed Adapter"

    def requires_access_gate(self) -> bool:
        return True

    def capabilities(self) -> dict:
        return {"supports_market_prices": True}

    def health_check(self):
        from pricing_sources.base import SourceHealthResult
        return SourceHealthResult(source_code=self._code, status="unknown")

    def build_queries(self, query: PriceQuery) -> list[dict]:
        return [{"test": True}]

    def fetch(self, query: dict) -> dict | None:
        # Real adapter would call self.require_live_access(config) here
        return {"price": 1.0}

    def normalise(self, raw_response: dict, query: PriceQuery):
        return []

    def match_observations(self, observations, query):
        return []


# ── TCGdex-like keyless adapter ─────────────────────────────────────────

class FakeKeylessAdapter(PriceSourceAdapter):
    """Simulates a keyless/free adapter like TCGdex."""

    @property
    def source_code(self) -> str:
        return "fakekeyless"

    @property
    def source_name(self) -> str:
        return "Fake Keyless Adapter"

    def requires_access_gate(self) -> bool:
        return False  # default, but explicit for clarity

    def capabilities(self) -> dict:
        return {"supports_market_prices": True}

    def health_check(self):
        from pricing_sources.base import SourceHealthResult
        return SourceHealthResult(source_code="fakekeyless", status="healthy")

    def build_queries(self, query: PriceQuery) -> list[dict]:
        return [{"test": True}]

    def fetch(self, query: dict) -> dict | None:
        return {"price": 1.0}

    def normalise(self, raw_response: dict, query: PriceQuery):
        return []

    def match_observations(self, observations, query):
        return []


# ── Helpers ──────────────────────────────────────────────────────────────

def _full_config(code: str = "fakekeyed", **overrides: str) -> dict[str, str]:
    """Build a fully-approved config for a fake provider."""
    prefix = f"POKEMON_PRICE_SOURCE_{code.upper()}"
    cfg = {
        f"{prefix}_API_KEY": "fake_test_key_not_real",
        f"{prefix}_ENABLED": "true",
        f"{prefix}_TERMS_CONFIRMED": "true",
        f"{prefix}_ALLOW_RAW_CACHE": "true",
        f"{prefix}_ALLOW_FIXTURES": "true",
        f"{prefix}_ALLOW_INTERNAL_DISPLAY": "true",
    }
    cfg.update(overrides)
    return cfg


# ── Tests ────────────────────────────────────────────────────────────────

class TestKeylessAdapter:
    def test_does_not_require_access_gate(self):
        adapter = FakeKeylessAdapter()
        assert adapter.requires_access_gate() is False

    def test_live_calls_always_enabled(self):
        adapter = FakeKeylessAdapter()
        assert adapter.live_calls_enabled() is True
        assert adapter.live_calls_enabled(None) is True
        assert adapter.live_calls_enabled({}) is True

    def test_require_live_access_noop(self):
        adapter = FakeKeylessAdapter()
        # Should never raise
        adapter.require_live_access()
        adapter.require_live_access(None)
        adapter.require_live_access({})


class TestKeyedAdapter:
    def test_requires_access_gate(self):
        adapter = FakeKeyedAdapter()
        assert adapter.requires_access_gate() is True

    def test_blocks_live_calls_with_missing_key(self):
        adapter = FakeKeyedAdapter()
        config = {}
        assert adapter.live_calls_enabled(config) is False

    def test_blocks_live_calls_when_disabled(self):
        adapter = FakeKeyedAdapter()
        config = _full_config()
        config["POKEMON_PRICE_SOURCE_FAKEKEYED_ENABLED"] = "false"
        assert adapter.live_calls_enabled(config) is False

    def test_blocks_live_calls_when_terms_unconfirmed(self):
        adapter = FakeKeyedAdapter()
        config = _full_config()
        config["POKEMON_PRICE_SOURCE_FAKEKEYED_TERMS_CONFIRMED"] = "false"
        assert adapter.live_calls_enabled(config) is False

    def test_allows_live_calls_when_fully_approved(self):
        adapter = FakeKeyedAdapter()
        config = _full_config()
        assert adapter.live_calls_enabled(config) is True

    def test_require_live_access_raises_when_blocked(self):
        adapter = FakeKeyedAdapter()
        with pytest.raises(PermissionError):
            adapter.require_live_access({})

    def test_require_live_access_raises_without_config(self):
        adapter = FakeKeyedAdapter()
        with pytest.raises(PermissionError):
            adapter.require_live_access(None)

    def test_require_live_access_passes_when_approved(self):
        adapter = FakeKeyedAdapter()
        config = _full_config()
        # Should not raise
        adapter.require_live_access(config)


class TestSecretSafety:
    def test_error_message_does_not_expose_key(self):
        adapter = FakeKeyedAdapter()
        config = {"POKEMON_PRICE_SOURCE_FAKEKEYED_API_KEY": "super_secret_key_12345"}
        with pytest.raises(PermissionError) as exc_info:
            adapter.require_live_access(config)
        assert "super_secret_key_12345" not in str(exc_info.value)

    def test_error_includes_status(self):
        adapter = FakeKeyedAdapter()
        with pytest.raises(PermissionError) as exc_info:
            adapter.require_live_access({})
        assert "NOT_CONFIGURED" in str(exc_info.value)


class TestDefaultBehavior:
    def test_default_requires_access_gate_is_false(self):
        """Any adapter that doesn't override should default to no gate."""
        adapter = FakeKeylessAdapter()
        # The base class default is False
        assert adapter.requires_access_gate() is False

    def test_unknown_provider_blocked(self):
        """A keyed adapter with unknown provider code is blocked without config."""
        adapter = FakeKeyedAdapter(code="unknownprovider")
        assert adapter.live_calls_enabled({}) is False
