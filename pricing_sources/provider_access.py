"""Provider access safety gate for pricing sources.

Defines a conservative access-control model that defaults to BLOCKED for
every provider permission. Future adapters MUST call
`require_provider_live_access()` before making any external API call.

This module does NOT call any external APIs. It only inspects configuration
mappings and returns access decisions.

Design: docs/V11_2_PROVIDER_ACCESS_READINESS.md
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping


class ProviderAccessStatus(str, enum.Enum):
    """High-level access status for a provider."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED_DISABLED = "CONFIGURED_DISABLED"
    ENABLED_TERMS_UNCONFIRMED = "ENABLED_TERMS_UNCONFIRMED"
    ENABLED_TERMS_CONFIRMED = "ENABLED_TERMS_CONFIRMED"
    BLOCKED = "BLOCKED"


class ProviderPermission(str, enum.Enum):
    """Individual permissions that can be granted for a provider."""
    LIVE_CALLS = "live_calls"
    RAW_CACHE = "raw_cache"
    FIXTURE_STORAGE = "fixture_storage"
    NORMALIZED_STORAGE = "normalized_storage"
    INTERNAL_DISPLAY = "internal_display"
    CUSTOMER_DISPLAY = "customer_display"
    COMMERCIAL_USE = "commercial_use"


@dataclass(frozen=True)
class ProviderAccessDecision:
    """Result of an access check for a provider."""
    provider_code: str
    status: str
    live_calls_allowed: bool
    raw_cache_allowed: bool
    fixture_storage_allowed: bool
    normalized_storage_allowed: bool
    internal_display_allowed: bool
    customer_display_allowed: bool
    commercial_use_allowed: bool
    reasons: tuple[str, ...] = ()

    def __str__(self) -> str:
        """Safe string representation that never includes secrets."""
        return (
            f"ProviderAccessDecision(provider={self.provider_code}, "
            f"status={self.status}, live_calls={self.live_calls_allowed})"
        )

    def __repr__(self) -> str:
        return self.__str__()


# Default env-var name patterns. Override by passing explicit names if needed.
def _env_prefix(provider_code: str) -> str:
    return f"POKEMON_PRICE_SOURCE_{provider_code.upper()}"


def _key_name(provider_code: str) -> str:
    return f"{_env_prefix(provider_code)}_API_KEY"


def _enabled_name(provider_code: str) -> str:
    return f"{_env_prefix(provider_code)}_ENABLED"


def _terms_name(provider_code: str) -> str:
    return f"{_env_prefix(provider_code)}_TERMS_CONFIRMED"


def _flag_name(provider_code: str, permission: str) -> str:
    return f"{_env_prefix(provider_code)}_ALLOW_{permission.upper()}"


def _is_truthy(value: str | None) -> bool:
    """Check if a config value represents an explicit true flag."""
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_provider_access_status(
    provider_code: str,
    config: Mapping[str, str],
    *,
    key_name: str | None = None,
    enabled_name: str | None = None,
    terms_name: str | None = None,
) -> ProviderAccessDecision:
    """Evaluate the full access decision for a provider.

    Args:
        provider_code: short provider identifier, e.g. "justtcg".
        config: mapping of env-var names to values (e.g. os.environ).
        key_name / enabled_name / terms_name: optional overrides for env-var names.

    Returns a ProviderAccessDecision. Defaults to safe/blocked.
    """
    key = key_name or _key_name(provider_code)
    enabled = enabled_name or _enabled_name(provider_code)
    terms = terms_name or _terms_name(provider_code)

    has_key = bool(config.get(key, "").strip())
    is_enabled = _is_truthy(config.get(enabled))
    terms_confirmed = _is_truthy(config.get(terms))

    # Determine individual permissions — each requires explicit opt-in
    live_allowed = has_key and is_enabled and terms_confirmed
    raw_cache = _is_truthy(config.get(_flag_name(provider_code, "raw_cache"))) and terms_confirmed
    fixtures = _is_truthy(config.get(_flag_name(provider_code, "fixtures"))) and terms_confirmed
    normalized = _is_truthy(config.get(_flag_name(provider_code, "normalized_storage"))) and terms_confirmed
    internal = _is_truthy(config.get(_flag_name(provider_code, "internal_display"))) and terms_confirmed
    customer = _is_truthy(config.get(_flag_name(provider_code, "customer_display"))) and terms_confirmed
    commercial = _is_truthy(config.get(_flag_name(provider_code, "commercial_use"))) and terms_confirmed

    # Determine overall status
    if not has_key:
        status = ProviderAccessStatus.NOT_CONFIGURED
    elif not is_enabled:
        status = ProviderAccessStatus.CONFIGURED_DISABLED
    elif not terms_confirmed:
        status = ProviderAccessStatus.ENABLED_TERMS_UNCONFIRMED
    else:
        status = ProviderAccessStatus.ENABLED_TERMS_CONFIRMED

    reasons: list[str] = []
    if not has_key:
        reasons.append(f"API key not configured ({key})")
    if has_key and not is_enabled:
        reasons.append(f"Provider not enabled ({enabled})")
    if is_enabled and not terms_confirmed:
        reasons.append(f"Terms not confirmed ({terms})")
    if live_allowed and not raw_cache:
        reasons.append("Raw response caching not allowed")
    if live_allowed and not fixtures:
        reasons.append("Fixture storage not allowed")

    return ProviderAccessDecision(
        provider_code=provider_code,
        status=status.value,
        live_calls_allowed=live_allowed,
        raw_cache_allowed=raw_cache,
        fixture_storage_allowed=fixtures,
        normalized_storage_allowed=normalized,
        internal_display_allowed=internal,
        customer_display_allowed=customer,
        commercial_use_allowed=commercial,
        reasons=tuple(reasons),
    )


def provider_is_live_call_allowed(
    provider_code: str,
    config: Mapping[str, str],
) -> bool:
    """Return True only if the provider is fully allowed to make live API calls."""
    decision = get_provider_access_status(provider_code, config)
    return decision.live_calls_allowed


def require_provider_live_access(
    provider_code: str,
    config: Mapping[str, str],
) -> None:
    """Raise PermissionError if the provider is not allowed to make live calls.

    Future adapters MUST call this before any external API request.
    The error message never includes the API key value.
    """
    decision = get_provider_access_status(provider_code, config)
    if not decision.live_calls_allowed:
        raise PermissionError(
            f"Provider '{provider_code}' is not allowed to make live API calls. "
            f"Status: {decision.status}. Reasons: {'; '.join(decision.reasons)}"
        )
