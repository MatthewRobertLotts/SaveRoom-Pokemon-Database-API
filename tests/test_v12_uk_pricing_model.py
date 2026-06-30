"""Tests for the pure v12 UK-primary fallback pricing model.

Synthetic in-memory inputs only. No DB access, HTTP, provider calls, env
reads, live fixtures, or API credits.
"""
from __future__ import annotations

from pricing_sources.uk_pricing_model import (
    AdjustmentMultiplier,
    MULTIPLIER_DEFAULT_CONSERVATIVE,
    MULTIPLIER_ERA_BLOCK,
    MULTIPLIER_EXACT_CARD,
    MULTIPLIER_PROVIDER_GLOBAL,
    MULTIPLIER_SET,
    PROVIDER_CARDMARKET,
    PROVIDER_JUSTTCG,
    PROVIDER_TCGPLAYER,
    PROVIDER_TOTALTCG,
    TIER_ACTIVE_LISTING_REFERENCE,
    TIER_CARDMARKET_EU_ADJUSTED,
    TIER_GLOBAL_MARKET_ADJUSTED,
    TIER_UK_EBAY_SOLD,
    UK_EVIDENCE_MEDIUM,
    UK_EVIDENCE_NONE,
    UK_EVIDENCE_STRONG,
    UK_EVIDENCE_THIN,
    build_pricing_recommendation,
    calculate_uk_adjusted_fallback,
    can_provider_be_uk_sold_evidence,
    classify_provider,
    classify_uk_evidence_strength,
    select_adjustment_multiplier,
)


def _mult(level: str, value: float, sample_size: int = 10) -> AdjustmentMultiplier:
    return AdjustmentMultiplier(
        level=level,
        multiplier=value,
        sample_size=sample_size,
        basis=f"{level} test basis",
    )


# 1. Strong UK evidence uses 100% UK price.
def test_strong_uk_evidence_uses_100_percent_uk_price():
    rec = build_pricing_recommendation(
        primary_uk_price=18.64,
        uk_evidence_count=12,
        fallback_converted_price_gbp=15.80,
        fallback_provider=PROVIDER_JUSTTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.18)],
    )

    assert rec.uk_evidence_strength == UK_EVIDENCE_STRONG
    assert rec.primary_uk_price == 18.64
    assert rec.uk_adjusted_fallback_price == 18.64
    assert rec.general_market_estimate == 18.64
    assert "strong_uk_100_0_blend" in rec.calculation_method


# 2. Medium UK evidence uses 80/20 blend.
def test_medium_uk_evidence_uses_80_20_blend():
    rec = build_pricing_recommendation(
        primary_uk_price=20.00,
        uk_evidence_count=7,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_TCGPLAYER,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.5)],
    )

    assert rec.uk_evidence_strength == UK_EVIDENCE_MEDIUM
    assert rec.uk_adjusted_fallback_price == 15.00
    assert rec.general_market_estimate == 19.00
    assert "medium_uk_80_20_blend" in rec.calculation_method


# 3. Thin UK evidence uses 60/40 blend.
def test_thin_uk_evidence_uses_60_40_blend():
    rec = build_pricing_recommendation(
        primary_uk_price=20.00,
        uk_evidence_count=3,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_TOTALTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.5)],
    )

    assert rec.uk_evidence_strength == UK_EVIDENCE_THIN
    assert rec.general_market_estimate == 18.00
    assert "thin_uk_60_40_blend" in rec.calculation_method


# 4. No UK evidence uses adjusted fallback only.
def test_no_uk_evidence_uses_adjusted_fallback_only():
    rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=15.80,
        fallback_provider=PROVIDER_JUSTTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.18)],
    )

    assert rec.uk_evidence_strength == UK_EVIDENCE_NONE
    assert rec.primary_uk_price is None
    assert rec.uk_adjusted_fallback_price == 18.64
    assert rec.general_market_estimate == 18.64
    assert "fallback_only_0_100_blend" in rec.calculation_method


# 5. primary_uk_price is never populated by fallback-only data.
def test_primary_uk_price_never_populated_by_fallback_only_data():
    rec = build_pricing_recommendation(
        primary_uk_price=99.99,  # ignored because evidence_count is zero
        uk_evidence_count=0,
        fallback_converted_price_gbp=12.00,
        fallback_provider=PROVIDER_JUSTTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.1)],
    )

    assert rec.primary_uk_price is None
    assert rec.general_market_estimate == 13.20


# 6. USD/global provider never becomes UK sold evidence.
def test_usd_global_provider_never_becomes_uk_sold_evidence():
    assert can_provider_be_uk_sold_evidence(PROVIDER_JUSTTCG) is False
    assert classify_provider(PROVIDER_JUSTTCG)["default_tier"] == TIER_GLOBAL_MARKET_ADJUSTED


# 7. JustTCG / TotalTCG / TCGplayer are never labelled as UK sold evidence.
def test_global_reference_providers_never_labelled_uk_sold_evidence():
    for provider in (PROVIDER_JUSTTCG, PROVIDER_TOTALTCG, PROVIDER_TCGPLAYER):
        metadata = classify_provider(provider)
        assert metadata["provider_family"] == "global_market_reference"
        assert metadata["can_be_uk_sold_evidence"] is False
        assert metadata["default_tier"] == TIER_GLOBAL_MARKET_ADJUSTED


# 8. Cardmarket/EU data is converted and UK-adjusted before use.
def test_cardmarket_eu_data_is_converted_and_uk_adjusted():
    rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_CARDMARKET,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.2)],
    )

    assert rec.uk_adjusted_fallback_price == 12.00
    assert rec.region_basis == "uk_adjusted_foreign_fallback"
    item = rec.source_breakdown[0]
    assert item.tier == TIER_CARDMARKET_EU_ADJUSTED
    assert item.can_be_uk_sold_evidence is False
    assert any("Cardmarket/EU data is converted" in warning for warning in rec.warnings)


# 9. Active listings never drive primary sold/completed value.
def test_active_listing_reference_never_drives_primary_value():
    metadata = classify_provider("random_active_listing_source")
    assert metadata["default_tier"] == TIER_ACTIVE_LISTING_REFERENCE
    assert metadata["can_be_uk_sold_evidence"] is False

    rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=30.00,
        fallback_provider="random_active_listing_source",
    )
    assert rec.primary_uk_price is None


# 10. Exact-card multiplier is preferred over set-level.
def test_exact_card_multiplier_preferred_over_set_level():
    selected = select_adjustment_multiplier([
        _mult(MULTIPLIER_SET, 1.20, 40),
        _mult(MULTIPLIER_EXACT_CARD, 1.10, 6),
    ])

    assert selected.level == MULTIPLIER_EXACT_CARD
    assert selected.multiplier == 1.10


# 11. Set-level is preferred over era/global.
def test_set_level_preferred_over_era_and_global():
    selected = select_adjustment_multiplier([
        _mult(MULTIPLIER_PROVIDER_GLOBAL, 1.05, 250),
        _mult(MULTIPLIER_ERA_BLOCK, 1.12, 80),
        _mult(MULTIPLIER_SET, 1.18, 30),
    ])

    assert selected.level == MULTIPLIER_SET
    assert selected.multiplier == 1.18


# 12. Default multiplier is used when no learned multiplier exists.
def test_default_multiplier_used_when_no_learned_multiplier_exists():
    selected = select_adjustment_multiplier([])
    adjusted = calculate_uk_adjusted_fallback(15.80, selected, provider=PROVIDER_JUSTTCG)

    assert selected.level == MULTIPLIER_DEFAULT_CONSERVATIVE
    assert selected.multiplier == 1.00
    assert adjusted is not None
    assert adjusted.amount == 15.80


# 13. Confidence is high for strong UK evidence.
def test_confidence_high_for_strong_uk_evidence():
    rec = build_pricing_recommendation(primary_uk_price=10.00, uk_evidence_count=10)

    assert rec.confidence == "high"
    assert rec.confidence_score >= 0.9
    assert any("Strong UK" in reason for reason in rec.confidence_reasons)


# 14. Confidence is low/very_low for fallback-only pricing.
def test_confidence_low_or_very_low_for_fallback_only_pricing():
    rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_JUSTTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.2)],
    )
    default_rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_JUSTTCG,
    )

    assert rec.confidence == "low"
    assert default_rec.confidence == "very_low"


# 15. Warnings explain when fallback/global data influenced recommendation.
def test_warnings_explain_fallback_global_influence():
    rec = build_pricing_recommendation(
        primary_uk_price=20.00,
        uk_evidence_count=2,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_TCGPLAYER,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.5)],
    )

    assert any("Fallback/global data influenced" in warning for warning in rec.warnings)
    assert any("not UK sold evidence" in warning for warning in rec.warnings)


# 16. Recommended listing price changes by strategy.
def test_recommended_listing_price_changes_by_strategy():
    conservative = build_pricing_recommendation(20.00, 12, listing_strategy="conservative")
    balanced = build_pricing_recommendation(20.00, 12, listing_strategy="balanced")
    premium = build_pricing_recommendation(20.00, 12, listing_strategy="premium")

    assert conservative.recommended_listing_price == 18.00
    assert balanced.recommended_listing_price == 20.00
    assert premium.recommended_listing_price == 22.00


# 17. Source breakdown records tiers and provider roles.
def test_source_breakdown_records_tiers_and_provider_roles():
    rec = build_pricing_recommendation(
        primary_uk_price=20.00,
        uk_evidence_count=7,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_JUSTTCG,
        candidate_multipliers=[_mult(MULTIPLIER_SET, 1.5)],
    )

    breakdown = rec.to_dict()["source_breakdown"]
    assert breakdown[0]["tier"] == TIER_UK_EBAY_SOLD
    assert breakdown[0]["role"] == "primary_uk_sold_completed"
    assert breakdown[1]["tier"] == TIER_GLOBAL_MARKET_ADJUSTED
    assert breakdown[1]["provider"] == PROVIDER_JUSTTCG
    assert breakdown[1]["role"] == "supporting_usd_fallback"


# 18. Restricted provider notes can be represented without exposing raw data.
def test_restricted_provider_notes_without_raw_data_exposure():
    rec = build_pricing_recommendation(
        primary_uk_price=None,
        uk_evidence_count=0,
        fallback_converted_price_gbp=10.00,
        fallback_provider=PROVIDER_JUSTTCG,
    )

    item = rec.source_breakdown[0].to_dict()
    assert item["provider"] == PROVIDER_JUSTTCG
    assert "Restricted" in item["restricted_note"]
    assert "raw" not in item
    assert rec.provider_status_summary == {}


def test_evidence_strength_bands_are_explicit():
    assert classify_uk_evidence_strength(10) == UK_EVIDENCE_STRONG
    assert classify_uk_evidence_strength(5) == UK_EVIDENCE_MEDIUM
    assert classify_uk_evidence_strength(1) == UK_EVIDENCE_THIN
    assert classify_uk_evidence_strength(0) == UK_EVIDENCE_NONE
