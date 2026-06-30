"""Pricing-source exposure policy guard.

Enforces JustTCG terms restriction: JustTCG-derived pricing may be used
within SaveRoom-owned apps and tools (internal/admin, paid SaveRoom apps,
and customer-facing SaveRoom apps) but must NOT be exposed through a
public standalone pricing API, data feed, or competing data product for
third-party developers.

This policy is enforced in code, not just by documentation. The
JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED constant makes the
restriction explicit and prevents env-flag override.

Design: docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md
Terms: docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md
"""
from __future__ import annotations

import copy
from typing import Any

# ── Surface constants ────────────────────────────────────────────────

SURFACE_SAVEROOM_INTERNAL = "saveroom_internal"
SURFACE_SAVEROOM_CUSTOMER_APP = "saveroom_customer_app"
SURFACE_INTERNAL_ADMIN = "internal_admin"
SURFACE_CUSTOMER_SAVEROOM_APP = "customer_saveroom_app"
SURFACE_SAVEROOM_OWNED_PAID_APPS = "saveroom_owned_paid_apps"
SURFACE_EXTERNAL_DEVELOPER_API = "external_developer_api"
SURFACE_STANDALONE_PRICING_API = "standalone_pricing_api"

ALL_SURFACES = {
    SURFACE_SAVEROOM_INTERNAL,
    SURFACE_SAVEROOM_CUSTOMER_APP,
    SURFACE_INTERNAL_ADMIN,
    SURFACE_CUSTOMER_SAVEROOM_APP,
    SURFACE_SAVEROOM_OWNED_PAID_APPS,
    SURFACE_EXTERNAL_DEVELOPER_API,
    SURFACE_STANDALONE_PRICING_API,
}

SAVEROOM_ALLOWED_APP_SURFACES = {
    SURFACE_SAVEROOM_INTERNAL,
    SURFACE_SAVEROOM_CUSTOMER_APP,
    SURFACE_INTERNAL_ADMIN,
    SURFACE_CUSTOMER_SAVEROOM_APP,
    SURFACE_SAVEROOM_OWNED_PAID_APPS,
}

EXTERNAL_BLOCKED_PRICING_SURFACES = {
    SURFACE_EXTERNAL_DEVELOPER_API,
    SURFACE_STANDALONE_PRICING_API,
}

# ── Source constants ──────────────────────────────────────────────────

SOURCE_JUSTTCG = "justtcg"
SOURCE_TCGDEX = "tcgdex"
SOURCE_UK_EBAY_SOLD = "uk_ebay_sold"
SOURCE_EBAY_UK = "ebay_uk"
SOURCE_CARDMARKET = "cardmarket"
SOURCE_TCGPLAYER = "tcgplayer"

# ── Permanent restriction ─────────────────────────────────────────────

# JustTCG terms allow SaveRoom-owned apps and tools to show JustTCG-derived
# pricing through the SaveRoom backend, including paid SaveRoom products.
# The same clarification blocks a public standalone pricing API, data feed,
# or competing data product for third-party developers.
# This constant is True and MUST remain True. It cannot be overridden
# by env flags or config. If JustTCG's terms change in the future,
# this constant requires an explicit code change + test update + docs
# update, ensuring the change is deliberate and recorded.
JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED: bool = True

# ── Attribution ───────────────────────────────────────────────────────

JUSTTCG_ATTRIBUTION_TEXT = "Pricing data provided by JustTCG"

# ── Source exposure rules ─────────────────────────────────────────────

# Each entry: source_code -> {surface -> allowed}
# Sources not listed default to: internal=allowed, customer=allowed, external=allowed
# unless they carry the _restricted_for_resale flag.

_SOURCE_RULES: dict[str, dict[str, bool]] = {
    SOURCE_JUSTTCG: {
        SURFACE_SAVEROOM_INTERNAL: True,
        SURFACE_SAVEROOM_CUSTOMER_APP: True,
        SURFACE_INTERNAL_ADMIN: True,
        SURFACE_CUSTOMER_SAVEROOM_APP: True,
        SURFACE_SAVEROOM_OWNED_PAID_APPS: True,
        SURFACE_EXTERNAL_DEVELOPER_API: False,  # permanent restriction
        SURFACE_STANDALONE_PRICING_API: False,  # permanent restriction
    },
}

# Sources that are permanently restricted from external API resale.
# Unknown sources are blocked for external developer API by default.
_RESTRICTED_SOURCES: set[str] = {SOURCE_JUSTTCG}


def can_expose_source(
    source_code: str,
    surface: str,
    field_type: str = "pricing",
) -> bool:
    """Check whether a source's data can be exposed on a given surface.

    Args:
        source_code: The pricing source identifier (e.g. "justtcg").
        surface: The API surface (e.g. "external_developer_api").
        field_type: The type of field being exposed (default "pricing").

    Returns:
        True if the source's data may be exposed, False otherwise.
    """
    if surface not in ALL_SURFACES:
        # Unknown surface — safest default is to block
        return False

    # Check explicit rules
    rules = _SOURCE_RULES.get(source_code)
    if rules is not None:
        allowed = rules.get(surface)
        if allowed is not None:
            return allowed

    # Default policy:
    # - Restricted sources are blocked for external pricing/API surfaces
    # - All other sources are allowed on all surfaces
    if surface in EXTERNAL_BLOCKED_PRICING_SURFACES:
        if source_code in _RESTRICTED_SOURCES:
            return False
        # Unknown sources are blocked for external pricing/API surfaces by default
        # unless they are in the explicit rules (handled above)
        # Known unrestricted sources pass through
        known_unrestricted = {SOURCE_TCGDEX, SOURCE_UK_EBAY_SOLD, SOURCE_EBAY_UK,
                             SOURCE_CARDMARKET, SOURCE_TCGPLAYER,
                             "ebay_uk", "ebay_uk_sold"}
        if source_code in known_unrestricted:
            return True
        # Unknown source — conservative default: block
        return False

    # Internal/admin/customer/SaveRoom-owned paid app surfaces allow all sources by default
    return surface in SAVEROOM_ALLOWED_APP_SURFACES


def filter_price_payload_for_surface(
    payload: dict[str, Any],
    surface: str,
) -> dict[str, Any]:
    """Filter a pricing payload for a given surface.

    For external developer API surfaces, removes or redacts fields
    derived from restricted sources. Adds warnings when redaction
    occurs.

    For SaveRoom internal/admin/customer/owned-app surfaces, returns the
    payload unchanged (preserving source labels and attribution).

    Args:
        payload: The pricing payload dict to filter.
        surface: The API surface.

    Returns:
        A (possibly modified) copy of the payload.
    """
    if surface in SAVEROOM_ALLOWED_APP_SURFACES:
        # Internal surfaces see everything — no filtering
        return payload

    if surface in EXTERNAL_BLOCKED_PRICING_SURFACES:
        result = copy.deepcopy(payload)
        redacted = _redact_blocked_sources_recursive(result, surface)
        if redacted:
            # Add warning about withheld fields
            warnings = result.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            warning_text = (
                "Some pricing fields were withheld because their source "
                "is not licensed for standalone external developer API resale."
            )
            if warning_text not in warnings:
                warnings.append(warning_text)
            result["warnings"] = warnings
        return result

    # Unknown surface — safest default: redact restricted sources
    result = copy.deepcopy(payload)
    _redact_blocked_sources_recursive(result, surface)
    return result


def _redact_blocked_sources_recursive(
    obj: Any,
    surface: str,
) -> bool:
    """Recursively redact fields from blocked sources.

    Returns True if any redaction occurred.
    """
    redacted = False

    if isinstance(obj, dict):
        # Check if this dict has a source/provider field that identifies it
        source = obj.get("source") or obj.get("source_code") or obj.get("provider") or obj.get("provider_code")

        if source and isinstance(source, str):
            if not can_expose_source(source, surface):
                # Redact pricing-related fields from this dict
                for key in ("price", "amount", "median", "low", "high",
                            "primary_price", "fallback_price", "market_price",
                            "avg_price", "price_gbp", "price_usd"):
                    if key in obj:
                        obj[key] = None
                        redacted = True
                # Clear source_breakdown items from this source
                if "source_breakdown" in obj and isinstance(obj["source_breakdown"], list):
                    obj["source_breakdown"] = [
                        item for item in obj["source_breakdown"]
                        if not (isinstance(item, dict) and
                                item.get("source") == source and
                                not can_expose_source(item.get("source", ""), surface))
                    ]
                    redacted = True
                # Mark the source as redacted
                if "source" in obj:
                    obj["source"] = f"{source}_redacted_for_surface"
                    redacted = True

        # Recurse into nested dicts and lists
        for key, value in list(obj.items()):
            if isinstance(value, dict):
                if _redact_blocked_sources_recursive(value, surface):
                    redacted = True
            elif isinstance(value, list):
                if _redact_list_recursive(value, surface):
                    redacted = True

    return redacted


def _redact_list_recursive(
    items: list,
    surface: str,
) -> bool:
    """Recursively redact blocked sources in a list.

    Returns True if any redaction occurred.
    """
    redacted = False
    # Track items to remove (source_breakdown items from blocked sources)
    to_remove = set()

    for i, item in enumerate(items):
        if isinstance(item, dict):
            source = item.get("source") or item.get("source_code") or item.get("provider") or item.get("provider_code")
            if source and isinstance(source, str) and not can_expose_source(source, surface):
                to_remove.add(i)
                redacted = True
                continue
            if _redact_blocked_sources_recursive(item, surface):
                redacted = True
        elif isinstance(item, list):
            if _redact_list_recursive(item, surface):
                redacted = True

    # Remove blocked items (reverse order to preserve indices)
    for i in sorted(to_remove, reverse=True):
        items.pop(i)

    return redacted


def redact_blocked_sources(
    value: Any,
    surface: str,
) -> Any:
    """Public API: redact blocked sources from a value.

    Returns a deep copy with blocked source data redacted.
    """
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        _redact_blocked_sources_recursive(result, surface)
    elif isinstance(result, list):
        _redact_list_recursive(result, surface)
    return result


def apply_pricing_exposure_policy(
    payload: dict[str, Any],
    surface: str,
) -> dict[str, Any]:
    """Apply the pricing source exposure policy to a response payload.

    This is the main entry point for endpoint code. It filters pricing
    fields based on the requesting surface and adds appropriate warnings.

    For now, all v12 endpoints default to SaveRoom internal/admin/customer
    app surfaces. External developer API or standalone pricing API mode must
    be explicitly requested and tested.

    Args:
        payload: The API response payload.
        surface: The surface type (use the SURFACE_* constants).

    Returns:
        The payload, possibly with redacted pricing and added warnings.
    """
    return filter_price_payload_for_surface(payload, surface)


def get_source_exposure_metadata(source_code: str) -> dict[str, Any]:
    """Return exposure metadata for a source.

    Useful for including in provider_status responses.
    """
    return {
        "source_code": source_code,
        "saveroom_internal_allowed": can_expose_source(source_code, SURFACE_SAVEROOM_INTERNAL),
        "saveroom_customer_app_allowed": can_expose_source(source_code, SURFACE_SAVEROOM_CUSTOMER_APP),
        "internal_admin_allowed": can_expose_source(source_code, SURFACE_INTERNAL_ADMIN),
        "customer_saveroom_app_allowed": can_expose_source(source_code, SURFACE_CUSTOMER_SAVEROOM_APP),
        "saveroom_owned_paid_apps_allowed": can_expose_source(source_code, SURFACE_SAVEROOM_OWNED_PAID_APPS),
        "external_developer_api_allowed": can_expose_source(source_code, SURFACE_EXTERNAL_DEVELOPER_API),
        "standalone_pricing_api_allowed": can_expose_source(source_code, SURFACE_STANDALONE_PRICING_API),
        "attribution": JUSTTCG_ATTRIBUTION_TEXT if source_code == SOURCE_JUSTTCG else None,
    }
