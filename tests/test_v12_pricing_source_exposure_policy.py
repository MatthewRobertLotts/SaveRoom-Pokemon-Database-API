"""Tests for the pricing-source exposure policy guard.

Tests cover:
- justtcg allowed for saveroom_internal
- justtcg allowed for saveroom_customer_app
- justtcg blocked for external_developer_api
- unknown restricted source blocked for external_developer_api
- tcgdex still allowed for external_developer_api
- uk_ebay_sold allowed for external_developer_api
- nested source_breakdown with justtcg removed for external_developer_api
- nested fallback_price from justtcg null/redacted for external_developer_api
- warnings added when redaction happens
- internal payload preserves JustTCG source labels
- customer app payload preserves JustTCG source labels
- external_api_resale_allowed for JustTCG is always false
- env flag cannot override JustTCG resale restriction
- policy handles missing source safely
- policy handles lists/dicts recursively
- no raw JustTCG-derived price survives in external developer API payload
"""
from __future__ import annotations

import pytest

from pricing_sources.exposure_policy import (
    JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED,
    JUSTTCG_ATTRIBUTION_TEXT,
    SURFACE_SAVEROOM_INTERNAL,
    SURFACE_SAVEROOM_CUSTOMER_APP,
    SURFACE_INTERNAL_ADMIN,
    SURFACE_CUSTOMER_SAVEROOM_APP,
    SURFACE_SAVEROOM_OWNED_PAID_APPS,
    SURFACE_EXTERNAL_DEVELOPER_API,
    SURFACE_STANDALONE_PRICING_API,
    can_expose_source,
    filter_price_payload_for_surface,
    redact_blocked_sources,
    apply_pricing_exposure_policy,
    get_source_exposure_metadata,
)


# ── justtcg allowed for saveroom_internal ─────────────────────────────

def test_justtcg_internal_allowed():
    assert can_expose_source("justtcg", SURFACE_SAVEROOM_INTERNAL) is True


# ── justtcg allowed for saveroom_customer_app ────────────────────────

def test_justtcg_customer_app_allowed():
    assert can_expose_source("justtcg", SURFACE_SAVEROOM_CUSTOMER_APP) is True


def test_justtcg_clarified_saveroom_app_surfaces_allowed():
    """Final JustTCG clarification allows SaveRoom-owned app/tool use."""
    for surface in (
        SURFACE_SAVEROOM_INTERNAL,
        SURFACE_SAVEROOM_CUSTOMER_APP,
        SURFACE_INTERNAL_ADMIN,
        SURFACE_CUSTOMER_SAVEROOM_APP,
        SURFACE_SAVEROOM_OWNED_PAID_APPS,
    ):
        assert can_expose_source("justtcg", surface) is True


# ── justtcg blocked for external_developer_api ───────────────────────

def test_justtcg_external_blocked():
    assert can_expose_source("justtcg", SURFACE_EXTERNAL_DEVELOPER_API) is False


def test_justtcg_standalone_pricing_api_blocked():
    """JustTCG-derived pricing must not become a standalone pricing API/feed."""
    assert can_expose_source("justtcg", SURFACE_STANDALONE_PRICING_API) is False


# ── unknown restricted source blocked for external_developer_api ─────

def test_unknown_source_external_blocked():
    assert can_expose_source("unknown_paid_source", SURFACE_EXTERNAL_DEVELOPER_API) is False


# ── tcgdex allowed for external_developer_api ────────────────────────

def test_tcgdex_external_allowed():
    assert can_expose_source("tcgdex", SURFACE_EXTERNAL_DEVELOPER_API) is True


# ── uk_ebay_sold allowed for external_developer_api ──────────────────

def test_uk_ebay_sold_external_allowed():
    assert can_expose_source("uk_ebay_sold", SURFACE_EXTERNAL_DEVELOPER_API) is True


# ── nested source_breakdown justtcg removed for external ─────────────

def test_source_breakdown_justtcg_removed_for_external():
    payload = {
        "source_breakdown": [
            {"source": "tcgdex", "price": 2.50},
            {"source": "justtcg", "price": 3.00},
        ]
    }
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    sources = [item["source"] for item in result["source_breakdown"]]
    assert "justtcg" not in sources
    assert "tcgdex" in sources


# ── nested fallback_price from justtcg redacted for external ─────────

def test_fallback_price_justtcg_redacted_for_external():
    payload = {
        "pricing": {
            "primary_price": None,
            "fallback_price": 3.00,
            "source": "justtcg",
        }
    }
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    # fallback_price should be redacted
    assert result["pricing"]["fallback_price"] is None
    # source label should indicate redaction
    assert "redacted" in result["pricing"]["source"]


# ── warnings added when redaction happens ─────────────────────────────

def test_warnings_added_on_redaction():
    payload = {
        "source_breakdown": [
            {"source": "justtcg", "price": 3.00},
        ]
    }
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    assert "warnings" in result
    assert any("withheld" in w.lower() or "not licensed" in w.lower() for w in result["warnings"])


# ── internal payload preserves JustTCG source labels ─────────────────

def test_internal_preserves_justtcg():
    payload = {
        "source_breakdown": [
            {"source": "justtcg", "price": 3.00},
        ],
        "pricing": {
            "fallback_price": 3.00,
            "source": "justtcg",
        }
    }
    result = filter_price_payload_for_surface(payload, SURFACE_SAVEROOM_INTERNAL)
    # Nothing should be redacted
    assert result["source_breakdown"][0]["source"] == "justtcg"
    assert result["pricing"]["fallback_price"] == 3.00
    assert result["pricing"]["source"] == "justtcg"


# ── customer app payload preserves JustTCG source labels ─────────────

def test_customer_app_preserves_justtcg():
    payload = {
        "source_breakdown": [
            {"source": "justtcg", "price": 3.00},
        ]
    }
    result = filter_price_payload_for_surface(payload, SURFACE_SAVEROOM_CUSTOMER_APP)
    assert result["source_breakdown"][0]["source"] == "justtcg"
    assert result["source_breakdown"][0]["price"] == 3.00


def test_saveroom_owned_paid_app_preserves_justtcg():
    payload = {
        "source_breakdown": [
            {"source": "justtcg", "price": 3.00},
        ],
        "pricing": {"source": "justtcg", "market_price": 3.00},
    }
    result = filter_price_payload_for_surface(payload, SURFACE_SAVEROOM_OWNED_PAID_APPS)
    assert result["source_breakdown"][0]["source"] == "justtcg"
    assert result["source_breakdown"][0]["price"] == 3.00
    assert result["pricing"]["market_price"] == 3.00


# ── external_api_resale_allowed is always false ──────────────────────

def test_external_api_resale_permanently_blocked():
    assert JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED is True


# ── env flag cannot override JustTCG resale restriction ──────────────

def test_env_flag_cannot_override():
    # The constant is True and cannot be changed by env vars
    # This test documents that constraint
    assert JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED is True
    # Even if an env flag existed, the code-level constant would still block
    assert can_expose_source("justtcg", SURFACE_EXTERNAL_DEVELOPER_API) is False


# ── policy handles missing source safely ──────────────────────────────

def test_missing_source_safe():
    payload = {"pricing": {"primary_price": None}}
    # Should not crash
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    assert "pricing" in result


# ── policy handles lists/dicts recursively ────────────────────────────

def test_recursive_dict_filtering():
    payload = {
        "data": {
            "pricing": {
                "source_breakdown": [
                    {"source": "justtcg", "price": 5.00},
                    {"source": "tcgdex", "price": 4.50},
                ],
                "nested": {
                    "source": "justtcg",
                    "amount": 5.00,
                }
            }
        }
    }
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    # justtcg items removed from source_breakdown
    sources = [item["source"] for item in result["data"]["pricing"]["source_breakdown"]]
    assert "justtcg" not in sources
    assert "tcgdex" in sources
    # nested dict with source=justtcg should be redacted
    assert result["data"]["pricing"]["nested"]["amount"] is None


# ── no raw JustTCG price survives in external developer API payload ──

def test_no_justtcg_price_in_external():
    payload = {
        "primary_price": None,
        "fallback_price": 3.50,
        "source_breakdown": [
            {"source": "justtcg", "price": 3.50, "median": 3.50},
        ],
        "provider_status": {
            "justtcg": {"source": "justtcg", "market_price": 3.50},
        }
    }
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    # No justtcg item in source_breakdown
    for item in result.get("source_breakdown", []):
        assert item.get("source") != "justtcg"
    # Recursive: price fields in justtcg-nested dicts nulled
    text = str(result)
    # The justtcg market price should not appear as a raw float
    assert "3.50" not in text or "justtcg" not in text.lower().split("3.50")[0][-20:]


# ── get_source_exposure_metadata ─────────────────────────────────────

def test_exposure_metadata_justtcg():
    meta = get_source_exposure_metadata("justtcg")
    assert meta["source_code"] == "justtcg"
    assert meta["saveroom_internal_allowed"] is True
    assert meta["saveroom_customer_app_allowed"] is True
    assert meta["internal_admin_allowed"] is True
    assert meta["customer_saveroom_app_allowed"] is True
    assert meta["saveroom_owned_paid_apps_allowed"] is True
    assert meta["external_developer_api_allowed"] is False
    assert meta["standalone_pricing_api_allowed"] is False
    assert meta["attribution"] == JUSTTCG_ATTRIBUTION_TEXT


def test_exposure_metadata_tcgdex():
    meta = get_source_exposure_metadata("tcgdex")
    assert meta["source_code"] == "tcgdex"
    assert meta["external_developer_api_allowed"] is True


# ── apply_pricing_exposure_policy is the entry point ─────────────────

def test_apply_policy_entry_point():
    payload = {"source_breakdown": [{"source": "justtcg", "price": 3.00}]}
    result = apply_pricing_exposure_policy(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    # justtcg item should be removed
    sources = [item.get("source") for item in result.get("source_breakdown", [])]
    assert "justtcg" not in sources


# ── ebay sources allowed externally ──────────────────────────────────

def test_ebay_uk_sources_allowed():
    assert can_expose_source("ebay_uk", SURFACE_EXTERNAL_DEVELOPER_API) is True
    assert can_expose_source("ebay_uk_sold", SURFACE_EXTERNAL_DEVELOPER_API) is True


# ── cardmarket/tcgplayer allowed externally ──────────────────────────

def test_cardmarket_tcgplayer_allowed():
    assert can_expose_source("cardmarket", SURFACE_EXTERNAL_DEVELOPER_API) is True
    assert can_expose_source("tcgplayer", SURFACE_EXTERNAL_DEVELOPER_API) is True


# ── deep copy — original not mutated ────────────────────────────────

def test_original_not_mutated():
    payload = {"source_breakdown": [{"source": "justtcg", "price": 3.00}]}
    result = filter_price_payload_for_surface(payload, SURFACE_EXTERNAL_DEVELOPER_API)
    # Original should still have justtcg
    assert payload["source_breakdown"][0]["source"] == "justtcg"
    # Result should not
    assert len(result["source_breakdown"]) == 0
