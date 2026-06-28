"""Tests for v11.2 provider access safety gate.

Uses fake config values only. No external calls. No real secrets.
"""
from __future__ import annotations

import pytest

from pricing_sources.provider_access import (
    ProviderAccessStatus,
    get_provider_access_status,
    provider_is_live_call_allowed,
    require_provider_live_access,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _base_config(**overrides: str) -> dict[str, str]:
    """Build a minimal config with JustTCG key set."""
    cfg = {
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_fake_test_key_not_real",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_NORMALIZED_STORAGE": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_INTERNAL_DISPLAY": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_CUSTOMER_DISPLAY": "false",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE": "false",
    }
    cfg.update(overrides)
    return cfg


# ── Missing key blocks provider ─────────────────────────────────────────

class TestMissingKeyBlocks:
    def test_no_key_not_configured(self):
        config = {}
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.NOT_CONFIGURED.value
        assert d.live_calls_allowed is False

    def test_empty_key_blocks(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY"] = ""
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.NOT_CONFIGURED.value

    def test_whitespace_key_blocks(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY"] = "   "
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.NOT_CONFIGURED.value


# ── Key present but disabled ────────────────────────────────────────────

class TestKeyPresentDisabled:
    def test_disabled_blocks_live_calls(self):
        config = _base_config()  # key present, enabled=false
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "false"
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.CONFIGURED_DISABLED.value
        assert d.live_calls_allowed is False

    def test_enabled_flag_absent_blocks(self):
        config = _base_config()
        del config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"]
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.CONFIGURED_DISABLED.value


# ── Enabled but terms not confirmed ─────────────────────────────────────

class TestEnabledTermsUnconfirmed:
    def test_enabled_no_terms_blocks_live_calls(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.status == ProviderAccessStatus.ENABLED_TERMS_UNCONFIRMED.value
        assert d.live_calls_allowed is False

    def test_enabled_truthy_variants(self):
        for truthy in ["1", "True", "YES", "on"]:
            config = _base_config()
            config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = truthy
            config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
            config["POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE"] = "true"
            d = get_provider_access_status("justtcg", config)
            assert d.live_calls_allowed is True, f"Failed for truthy={truthy}"


# ── Raw caching requires explicit allow ─────────────────────────────────

class TestRawCache:
    def test_raw_cache_without_flag_blocked(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.live_calls_allowed is True
        assert d.raw_cache_allowed is False

    def test_raw_cache_with_flag_allowed(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.raw_cache_allowed is True


# ── Fixture storage requires explicit allow ─────────────────────────────

class TestFixtureStorage:
    def test_fixtures_without_flag_blocked(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.fixture_storage_allowed is False

    def test_fixtures_with_flag_allowed(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.fixture_storage_allowed is True


# ── Commercial use requires explicit allow ──────────────────────────────

class TestCommercialUse:
    def test_commercial_without_flag_blocked(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.commercial_use_allowed is False

    def test_commercial_with_flag_allowed(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.commercial_use_allowed is True


# ── Live calls allowed only with all three conditions ───────────────────

class TestLiveCalls:
    def test_full_allow_works(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        d = get_provider_access_status("justtcg", config)
        assert d.live_calls_allowed is True
        assert d.status == ProviderAccessStatus.ENABLED_TERMS_CONFIRMED.value

    def test_provider_is_live_call_allowed_true(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        assert provider_is_live_call_allowed("justtcg", config) is True

    def test_provider_is_live_call_allowed_false_when_disabled(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "false"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        assert provider_is_live_call_allowed("justtcg", config) is False


# ── Unknown provider is blocked ─────────────────────────────────────────

class TestUnknownProvider:
    def test_unknown_provider_not_configured(self):
        config = {}
        d = get_provider_access_status("unknownprovider", config)
        assert d.status == ProviderAccessStatus.NOT_CONFIGURED.value
        assert d.live_calls_allowed is False

    def test_require_raises_for_unknown(self):
        config = {}
        with pytest.raises(PermissionError):
            require_provider_live_access("unknownprovider", config)


# ── Secrets not exposed ─────────────────────────────────────────────────

class TestSecretSafety:
    def test_decision_str_does_not_contain_key(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        d = get_provider_access_status("justtcg", config)
        text = str(d)
        assert "tcg_fake_test_key_not_real" not in text
        assert "tcg_" not in text.lower()

    def test_error_message_does_not_include_key(self):
        config = {"POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY": "tcg_secret_value_do_not_leak"}
        with pytest.raises(PermissionError) as exc_info:
            require_provider_live_access("justtcg", config)
        assert "tcg_secret_value_do_not_leak" not in str(exc_info.value)

    def test_repr_safe(self):
        config = _base_config()
        d = get_provider_access_status("justtcg", config)
        text = repr(d)
        assert "tcg_fake_test_key_not_real" not in text


# ── require_provider_live_access ────────────────────────────────────────

class TestRequireLiveAccess:
    def test_raises_when_not_allowed(self):
        config = _base_config()
        with pytest.raises(PermissionError) as exc_info:
            require_provider_live_access("justtcg", config)
        assert "not allowed" in str(exc_info.value).lower()

    def test_does_not_raise_when_allowed(self):
        config = _base_config()
        config["POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED"] = "true"
        config["POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED"] = "true"
        # Should not raise
        require_provider_live_access("justtcg", config)

    def test_error_includes_status(self):
        config = _base_config()
        with pytest.raises(PermissionError) as exc_info:
            require_provider_live_access("justtcg", config)
        assert "CONFIGURED_DISABLED" in str(exc_info.value)
