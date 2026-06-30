"""Pure UK-primary fallback pricing recommendation model.

This module contains deterministic pricing recommendation helpers only.
It performs no database access, HTTP calls, FastAPI imports, environment
reads, provider calls, or secret handling.

v12 milestones use this as the calculation foundation before listing
assistant or endpoint wiring. UK sold/completed GBP evidence remains the
primary pricing source. Foreign/global market prices may only contribute
after FX conversion and UK adjustment, and must never be labelled as UK
sold evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Evidence strength ────────────────────────────────────────────────

UK_EVIDENCE_STRONG = "strong"
UK_EVIDENCE_MEDIUM = "medium"
UK_EVIDENCE_THIN = "thin"
UK_EVIDENCE_NONE = "none"

# ── Source hierarchy ─────────────────────────────────────────────────

TIER_UK_EBAY_SOLD = 1
TIER_OTHER_UK_SOLD = 2
TIER_CARDMARKET_EU_ADJUSTED = 3
TIER_GLOBAL_MARKET_ADJUSTED = 4
TIER_ACTIVE_LISTING_REFERENCE = 5

SOURCE_HIERARCHY: dict[int, dict[str, str]] = {
    TIER_UK_EBAY_SOLD: {
        "name": "UK eBay sold/completed evidence",
        "role": "primary_uk_sold_completed",
        "currency_basis": "GBP",
    },
    TIER_OTHER_UK_SOLD: {
        "name": "Other UK marketplace sold evidence",
        "role": "secondary_uk_sold_completed",
        "currency_basis": "GBP",
    },
    TIER_CARDMARKET_EU_ADJUSTED: {
        "name": "Cardmarket/EU evidence converted to GBP and UK-adjusted",
        "role": "eu_fallback_reference",
        "currency_basis": "converted_to_gbp_then_uk_adjusted",
    },
    TIER_GLOBAL_MARKET_ADJUSTED: {
        "name": "TotalTCG / JustTCG / TCGplayer USD/global market prices converted to GBP and UK-adjusted",
        "role": "global_market_reference",
        "currency_basis": "converted_to_gbp_then_uk_adjusted",
    },
    TIER_ACTIVE_LISTING_REFERENCE: {
        "name": "Active listings only as weak sanity/reference",
        "role": "active_listing_reference_only",
        "currency_basis": "reference_only",
    },
}

# ── Provider classification ──────────────────────────────────────────

PROVIDER_EBAY_UK = "ebay_uk"
PROVIDER_UK_EBAY_SOLD = "uk_ebay_sold"
PROVIDER_CARDMARKET = "cardmarket"
PROVIDER_TOTALTCG = "totaltcg"
PROVIDER_JUSTTCG = "justtcg"
PROVIDER_TCGPLAYER = "tcgplayer"

PROVIDER_FAMILY_UK_SOLD = "uk_sold_completed"
PROVIDER_FAMILY_EU_REFERENCE = "eu_market_reference"
PROVIDER_FAMILY_GLOBAL_REFERENCE = "global_market_reference"
PROVIDER_FAMILY_ACTIVE_REFERENCE = "active_listing_reference"

GLOBAL_REFERENCE_PROVIDERS = frozenset({
    PROVIDER_TOTALTCG,
    PROVIDER_JUSTTCG,
    PROVIDER_TCGPLAYER,
})

RESTRICTED_PROVIDER_NOTES: dict[str, str] = {
    PROVIDER_JUSTTCG: "Restricted: SaveRoom ecosystem apps only; no standalone external developer pricing API resale.",
}

PROVIDER_CLASSIFICATION: dict[str, dict[str, Any]] = {
    PROVIDER_EBAY_UK: {
        "provider_family": PROVIDER_FAMILY_UK_SOLD,
        "default_tier": TIER_UK_EBAY_SOLD,
        "role": "primary_uk_sold_completed",
        "can_be_uk_sold_evidence": True,
        "restricted_note": None,
    },
    PROVIDER_UK_EBAY_SOLD: {
        "provider_family": PROVIDER_FAMILY_UK_SOLD,
        "default_tier": TIER_UK_EBAY_SOLD,
        "role": "primary_uk_sold_completed",
        "can_be_uk_sold_evidence": True,
        "restricted_note": None,
    },
    PROVIDER_CARDMARKET: {
        "provider_family": PROVIDER_FAMILY_EU_REFERENCE,
        "default_tier": TIER_CARDMARKET_EU_ADJUSTED,
        "role": "eu_converted_uk_adjusted_fallback",
        "can_be_uk_sold_evidence": False,
        "restricted_note": None,
    },
    PROVIDER_TOTALTCG: {
        "provider_family": PROVIDER_FAMILY_GLOBAL_REFERENCE,
        "default_tier": TIER_GLOBAL_MARKET_ADJUSTED,
        "role": "global_market_reference_fallback",
        "can_be_uk_sold_evidence": False,
        "restricted_note": None,
    },
    PROVIDER_JUSTTCG: {
        "provider_family": PROVIDER_FAMILY_GLOBAL_REFERENCE,
        "default_tier": TIER_GLOBAL_MARKET_ADJUSTED,
        "role": "supporting_usd_fallback",
        "can_be_uk_sold_evidence": False,
        "restricted_note": RESTRICTED_PROVIDER_NOTES[PROVIDER_JUSTTCG],
    },
    PROVIDER_TCGPLAYER: {
        "provider_family": PROVIDER_FAMILY_GLOBAL_REFERENCE,
        "default_tier": TIER_GLOBAL_MARKET_ADJUSTED,
        "role": "global_market_reference_fallback",
        "can_be_uk_sold_evidence": False,
        "restricted_note": None,
    },
}

# ── Adjustment multiplier levels ─────────────────────────────────────

MULTIPLIER_EXACT_CARD = "exact_card"
MULTIPLIER_SET = "set"
MULTIPLIER_ERA_BLOCK = "era_block"
MULTIPLIER_RARITY = "rarity"
MULTIPLIER_LANGUAGE = "language"
MULTIPLIER_PROVIDER_GLOBAL = "provider_global"
MULTIPLIER_DEFAULT_CONSERVATIVE = "default_conservative"

MULTIPLIER_LEVEL_ORDER = (
    MULTIPLIER_EXACT_CARD,
    MULTIPLIER_SET,
    MULTIPLIER_ERA_BLOCK,
    MULTIPLIER_RARITY,
    MULTIPLIER_LANGUAGE,
    MULTIPLIER_PROVIDER_GLOBAL,
    MULTIPLIER_DEFAULT_CONSERVATIVE,
)

DEFAULT_CONSERVATIVE_MULTIPLIER = 1.00

# ── Listing strategies ───────────────────────────────────────────────

LISTING_STRATEGY_CONSERVATIVE = "conservative"
LISTING_STRATEGY_BALANCED = "balanced"
LISTING_STRATEGY_PREMIUM = "premium"

LISTING_STRATEGY_MULTIPLIERS = {
    LISTING_STRATEGY_CONSERVATIVE: 0.90,
    LISTING_STRATEGY_BALANCED: 1.00,
    LISTING_STRATEGY_PREMIUM: 1.10,
}

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_VERY_LOW = "very_low"
CONFIDENCE_NONE = "none"


@dataclass(frozen=True)
class AdjustmentMultiplier:
    """A learned or default multiplier for UK-adjusting foreign evidence."""

    level: str
    multiplier: float
    sample_size: int = 0
    basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "multiplier": self.multiplier,
            "sample_size": self.sample_size,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class AdjustedFallbackPrice:
    """A foreign/global fallback price after GBP conversion and UK adjustment."""

    amount: float
    currency: str
    converted_price_gbp: float
    adjustment_multiplier: float
    adjustment_multiplier_level: str
    adjustment_multiplier_sample_size: int
    adjustment_basis: str
    provider: str | None = None
    provider_family: str | None = None
    source_tier: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "converted_price_gbp": self.converted_price_gbp,
            "adjustment_multiplier": self.adjustment_multiplier,
            "adjustment_multiplier_level": self.adjustment_multiplier_level,
            "adjustment_multiplier_sample_size": self.adjustment_multiplier_sample_size,
            "adjustment_basis": self.adjustment_basis,
            "provider": self.provider,
            "provider_family": self.provider_family,
            "source_tier": self.source_tier,
        }


@dataclass(frozen=True)
class SourceBreakdownItem:
    """Serializable source contribution metadata."""

    tier: int
    provider: str
    role: str
    currency: str
    evidence_count: int = 0
    used_for: tuple[str, ...] = ()
    provider_family: str | None = None
    can_be_uk_sold_evidence: bool = False
    restricted_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "provider": self.provider,
            "role": self.role,
            "currency": self.currency,
            "evidence_count": self.evidence_count,
            "used_for": list(self.used_for),
            "provider_family": self.provider_family,
            "can_be_uk_sold_evidence": self.can_be_uk_sold_evidence,
            "restricted_note": self.restricted_note,
        }


@dataclass(frozen=True)
class PricingRecommendation:
    """Serializable UK-primary pricing recommendation result."""

    currency: str
    region_basis: str
    primary_uk_price: float | None
    uk_adjusted_fallback_price: float | None
    general_market_estimate: float | None
    recommended_listing_price: float | None
    source_breakdown: tuple[SourceBreakdownItem, ...]
    evidence_count: int
    uk_evidence_strength: str
    confidence: str
    confidence_score: float
    confidence_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    calculation_method: str
    adjustment_multiplier: float | None
    adjustment_multiplier_level: str | None
    adjustment_multiplier_sample_size: int | None
    adjustment_basis: str | None
    provider_status_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "region_basis": self.region_basis,
            "primary_uk_price": self.primary_uk_price,
            "uk_adjusted_fallback_price": self.uk_adjusted_fallback_price,
            "general_market_estimate": self.general_market_estimate,
            "recommended_listing_price": self.recommended_listing_price,
            "source_breakdown": [item.to_dict() for item in self.source_breakdown],
            "evidence_count": self.evidence_count,
            "uk_evidence_strength": self.uk_evidence_strength,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "confidence_reasons": list(self.confidence_reasons),
            "warnings": list(self.warnings),
            "calculation_method": self.calculation_method,
            "adjustment_multiplier": self.adjustment_multiplier,
            "adjustment_multiplier_level": self.adjustment_multiplier_level,
            "adjustment_multiplier_sample_size": self.adjustment_multiplier_sample_size,
            "adjustment_basis": self.adjustment_basis,
            "provider_status_summary": self.provider_status_summary,
        }


def classify_uk_evidence_strength(evidence_count: int, freshness_days: int | None = None) -> str:
    """Classify UK sold/completed evidence strength.

    Freshness is accepted for forward compatibility but does not change
    the v12 milestone-0 bands yet.
    """
    if evidence_count >= 10:
        return UK_EVIDENCE_STRONG
    if evidence_count >= 5:
        return UK_EVIDENCE_MEDIUM
    if evidence_count >= 1:
        return UK_EVIDENCE_THIN
    return UK_EVIDENCE_NONE


def classify_provider(provider: str) -> dict[str, Any]:
    """Return conservative provider classification metadata."""
    provider_key = provider.lower().strip()
    default = {
        "provider_family": "unknown_reference",
        "default_tier": TIER_ACTIVE_LISTING_REFERENCE,
        "role": "unknown_reference_only",
        "can_be_uk_sold_evidence": False,
        "restricted_note": None,
    }
    metadata = PROVIDER_CLASSIFICATION.get(provider_key, default)
    return {"provider": provider_key, **metadata}


def can_provider_be_uk_sold_evidence(provider: str) -> bool:
    """Return True only for providers classified as UK sold/completed evidence."""
    return bool(classify_provider(provider)["can_be_uk_sold_evidence"])


def select_adjustment_multiplier(
    candidate_multipliers: list[AdjustmentMultiplier] | None,
) -> AdjustmentMultiplier:
    """Select the strongest available multiplier by predefined level order."""
    valid_candidates = [
        candidate
        for candidate in (candidate_multipliers or [])
        if candidate.level in MULTIPLIER_LEVEL_ORDER and candidate.multiplier > 0
    ]
    if not valid_candidates:
        return AdjustmentMultiplier(
            level=MULTIPLIER_DEFAULT_CONSERVATIVE,
            multiplier=DEFAULT_CONSERVATIVE_MULTIPLIER,
            sample_size=0,
            basis="Default conservative multiplier; no learned UK adjustment overlap available.",
        )

    order = {level: index for index, level in enumerate(MULTIPLIER_LEVEL_ORDER)}
    return sorted(valid_candidates, key=lambda candidate: order[candidate.level])[0]


def calculate_uk_adjusted_fallback(
    converted_price_gbp: float | None,
    multiplier: AdjustmentMultiplier,
    provider: str | None = None,
) -> AdjustedFallbackPrice | None:
    """Apply a UK adjustment multiplier to an already-converted GBP fallback price."""
    if converted_price_gbp is None:
        return None
    if converted_price_gbp < 0:
        raise ValueError("converted_price_gbp must be non-negative")
    if multiplier.multiplier <= 0:
        raise ValueError("adjustment multiplier must be positive")

    provider_metadata = classify_provider(provider or "unknown")
    adjusted = _round_money(converted_price_gbp * multiplier.multiplier)
    return AdjustedFallbackPrice(
        amount=adjusted,
        currency="GBP",
        converted_price_gbp=_round_money(converted_price_gbp),
        adjustment_multiplier=multiplier.multiplier,
        adjustment_multiplier_level=multiplier.level,
        adjustment_multiplier_sample_size=multiplier.sample_size,
        adjustment_basis=multiplier.basis,
        provider=provider_metadata["provider"],
        provider_family=provider_metadata["provider_family"],
        source_tier=provider_metadata["default_tier"],
    )


def blend_uk_and_fallback(
    primary_uk_price: float | None,
    adjusted_fallback_price: float | None,
    evidence_strength: str,
) -> tuple[float | None, float, float, str]:
    """Blend UK primary and UK-adjusted fallback based on evidence strength."""
    if evidence_strength == UK_EVIDENCE_STRONG and primary_uk_price is not None:
        return _round_money(primary_uk_price), 1.0, 0.0, "strong_uk_100_0_blend"
    if evidence_strength == UK_EVIDENCE_MEDIUM and primary_uk_price is not None:
        if adjusted_fallback_price is None:
            return _round_money(primary_uk_price), 1.0, 0.0, "medium_uk_no_fallback_100_0_blend"
        return _round_money(primary_uk_price * 0.8 + adjusted_fallback_price * 0.2), 0.8, 0.2, "medium_uk_80_20_blend"
    if evidence_strength == UK_EVIDENCE_THIN and primary_uk_price is not None:
        if adjusted_fallback_price is None:
            return _round_money(primary_uk_price), 1.0, 0.0, "thin_uk_no_fallback_100_0_blend"
        return _round_money(primary_uk_price * 0.6 + adjusted_fallback_price * 0.4), 0.6, 0.4, "thin_uk_60_40_blend"
    if adjusted_fallback_price is not None:
        return _round_money(adjusted_fallback_price), 0.0, 1.0, "fallback_only_0_100_blend"
    return None, 0.0, 0.0, "no_pricing_evidence"


def calculate_confidence(
    evidence_strength: str,
    has_adjusted_fallback: bool,
    multiplier_level: str | None = None,
) -> tuple[str, float, tuple[str, ...]]:
    """Calculate confidence label, score, and reasons."""
    if evidence_strength == UK_EVIDENCE_STRONG:
        return CONFIDENCE_HIGH, 0.92, ("Strong UK sold/completed evidence available.",)
    if evidence_strength == UK_EVIDENCE_MEDIUM:
        reasons = ["Medium UK sold/completed evidence available."]
        score = 0.74
        if has_adjusted_fallback:
            reasons.append("UK-adjusted fallback used as a small supporting influence.")
        return CONFIDENCE_MEDIUM, score, tuple(reasons)
    if evidence_strength == UK_EVIDENCE_THIN:
        reasons = ["Thin UK sold/completed evidence available."]
        score = 0.52
        if has_adjusted_fallback:
            reasons.append("UK-adjusted fallback used to support thin UK evidence.")
        return CONFIDENCE_LOW, score, tuple(reasons)
    if has_adjusted_fallback:
        if multiplier_level == MULTIPLIER_DEFAULT_CONSERVATIVE:
            return CONFIDENCE_VERY_LOW, 0.28, (
                "No UK sold/completed evidence available.",
                "Fallback-only estimate used with default conservative multiplier.",
            )
        return CONFIDENCE_LOW, 0.38, (
            "No UK sold/completed evidence available.",
            "Fallback-only estimate used after UK adjustment.",
        )
    return CONFIDENCE_NONE, 0.0, ("No usable pricing evidence available.",)


def build_pricing_recommendation(
    primary_uk_price: float | None,
    uk_evidence_count: int,
    fallback_converted_price_gbp: float | None = None,
    fallback_provider: str | None = None,
    candidate_multipliers: list[AdjustmentMultiplier] | None = None,
    listing_strategy: str = LISTING_STRATEGY_BALANCED,
    freshness_days: int | None = None,
    provider_status_summary: dict[str, Any] | None = None,
) -> PricingRecommendation:
    """Build a serializable UK-primary pricing recommendation.

    ``primary_uk_price`` remains pure UK sold/completed evidence. Fallback
    evidence can influence ``general_market_estimate`` and
    ``recommended_listing_price`` but never populates ``primary_uk_price``.
    """
    if uk_evidence_count < 0:
        raise ValueError("uk_evidence_count must be non-negative")
    if primary_uk_price is not None and primary_uk_price < 0:
        raise ValueError("primary_uk_price must be non-negative")

    evidence_strength = classify_uk_evidence_strength(uk_evidence_count, freshness_days)
    pure_primary_uk_price = _round_money(primary_uk_price) if uk_evidence_count > 0 and primary_uk_price is not None else None

    selected_multiplier = select_adjustment_multiplier(candidate_multipliers)
    adjusted_fallback = calculate_uk_adjusted_fallback(
        fallback_converted_price_gbp,
        selected_multiplier,
        provider=fallback_provider,
    )
    adjusted_amount = adjusted_fallback.amount if adjusted_fallback is not None else None

    general_estimate, uk_weight, fallback_weight, blend_method = blend_uk_and_fallback(
        pure_primary_uk_price,
        adjusted_amount,
        evidence_strength,
    )
    recommended_listing_price = _calculate_recommended_listing_price(general_estimate, listing_strategy)

    confidence, confidence_score, confidence_reasons = calculate_confidence(
        evidence_strength,
        adjusted_fallback is not None,
        selected_multiplier.level if adjusted_fallback is not None else None,
    )
    warnings = _build_warnings(evidence_strength, adjusted_fallback, fallback_weight)

    source_breakdown = _build_source_breakdown(
        uk_evidence_count=uk_evidence_count,
        fallback_provider=fallback_provider,
        adjusted_fallback=adjusted_fallback,
        fallback_weight=fallback_weight,
    )
    region_basis = _region_basis(evidence_strength, adjusted_fallback is not None)
    calculation_method = f"{blend_method}; listing_strategy={listing_strategy}; uk_weight={uk_weight:.2f}; fallback_weight={fallback_weight:.2f}"

    return PricingRecommendation(
        currency="GBP",
        region_basis=region_basis,
        primary_uk_price=pure_primary_uk_price,
        uk_adjusted_fallback_price=adjusted_amount,
        general_market_estimate=general_estimate,
        recommended_listing_price=recommended_listing_price,
        source_breakdown=tuple(source_breakdown),
        evidence_count=uk_evidence_count,
        uk_evidence_strength=evidence_strength,
        confidence=confidence,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        warnings=tuple(warnings),
        calculation_method=calculation_method,
        adjustment_multiplier=selected_multiplier.multiplier if adjusted_fallback is not None else None,
        adjustment_multiplier_level=selected_multiplier.level if adjusted_fallback is not None else None,
        adjustment_multiplier_sample_size=selected_multiplier.sample_size if adjusted_fallback is not None else None,
        adjustment_basis=selected_multiplier.basis if adjusted_fallback is not None else None,
        provider_status_summary=provider_status_summary or {},
    )


def _build_source_breakdown(
    uk_evidence_count: int,
    fallback_provider: str | None,
    adjusted_fallback: AdjustedFallbackPrice | None,
    fallback_weight: float,
) -> list[SourceBreakdownItem]:
    items: list[SourceBreakdownItem] = []
    if uk_evidence_count > 0:
        items.append(SourceBreakdownItem(
            tier=TIER_UK_EBAY_SOLD,
            provider=PROVIDER_EBAY_UK,
            role="primary_uk_sold_completed",
            currency="GBP",
            evidence_count=uk_evidence_count,
            used_for=("primary_uk_price", "general_market_estimate"),
            provider_family=PROVIDER_FAMILY_UK_SOLD,
            can_be_uk_sold_evidence=True,
        ))

    if adjusted_fallback is not None and fallback_provider is not None:
        metadata = classify_provider(fallback_provider)
        used_for = ("uk_adjusted_fallback_price",)
        if fallback_weight > 0:
            used_for = ("uk_adjusted_fallback_price", "general_market_estimate")
        items.append(SourceBreakdownItem(
            tier=int(metadata["default_tier"]),
            provider=metadata["provider"],
            role=str(metadata["role"]),
            currency="GBP",
            evidence_count=0,
            used_for=used_for,
            provider_family=str(metadata["provider_family"]),
            can_be_uk_sold_evidence=bool(metadata["can_be_uk_sold_evidence"]),
            restricted_note=metadata["restricted_note"],
        ))
    return items


def _build_warnings(
    evidence_strength: str,
    adjusted_fallback: AdjustedFallbackPrice | None,
    fallback_weight: float,
) -> list[str]:
    warnings: list[str] = []
    if evidence_strength == UK_EVIDENCE_THIN:
        warnings.append("UK sold/completed evidence is thin; treat the recommendation as indicative.")
    if evidence_strength == UK_EVIDENCE_NONE and adjusted_fallback is not None:
        warnings.append("No UK sold/completed evidence available; recommendation uses UK-adjusted fallback/reference pricing only.")
    if adjusted_fallback is not None and fallback_weight > 0:
        warnings.append("Fallback/global data influenced the general market estimate after GBP conversion and UK adjustment.")
    if adjusted_fallback is not None and adjusted_fallback.provider in GLOBAL_REFERENCE_PROVIDERS:
        warnings.append("TotalTCG / JustTCG / TCGplayer style data is global market reference data, not UK sold evidence.")
    if adjusted_fallback is not None and adjusted_fallback.provider == PROVIDER_CARDMARKET:
        warnings.append("Cardmarket/EU data is converted to GBP and UK-adjusted; it is not UK sold evidence.")
    if adjusted_fallback is not None and adjusted_fallback.provider in RESTRICTED_PROVIDER_NOTES:
        warnings.append(RESTRICTED_PROVIDER_NOTES[adjusted_fallback.provider])
    return warnings


def _region_basis(evidence_strength: str, has_adjusted_fallback: bool) -> str:
    if evidence_strength == UK_EVIDENCE_STRONG:
        return "uk_primary"
    if evidence_strength in (UK_EVIDENCE_MEDIUM, UK_EVIDENCE_THIN) and has_adjusted_fallback:
        return "uk_primary_with_adjusted_fallback"
    if evidence_strength in (UK_EVIDENCE_MEDIUM, UK_EVIDENCE_THIN):
        return "uk_primary_thin_or_medium"
    if has_adjusted_fallback:
        return "uk_adjusted_foreign_fallback"
    return "no_pricing_evidence"


def _calculate_recommended_listing_price(general_market_estimate: float | None, strategy: str) -> float | None:
    if general_market_estimate is None:
        return None
    multiplier = LISTING_STRATEGY_MULTIPLIERS.get(strategy)
    if multiplier is None:
        raise ValueError(f"Unknown listing strategy: {strategy}")
    return _round_money(general_market_estimate * multiplier)


def _round_money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


__all__ = [
    "AdjustmentMultiplier",
    "AdjustedFallbackPrice",
    "PricingRecommendation",
    "SourceBreakdownItem",
    "SOURCE_HIERARCHY",
    "PROVIDER_CLASSIFICATION",
    "GLOBAL_REFERENCE_PROVIDERS",
    "RESTRICTED_PROVIDER_NOTES",
    "MULTIPLIER_LEVEL_ORDER",
    "DEFAULT_CONSERVATIVE_MULTIPLIER",
    "UK_EVIDENCE_STRONG",
    "UK_EVIDENCE_MEDIUM",
    "UK_EVIDENCE_THIN",
    "UK_EVIDENCE_NONE",
    "MULTIPLIER_EXACT_CARD",
    "MULTIPLIER_SET",
    "MULTIPLIER_ERA_BLOCK",
    "MULTIPLIER_RARITY",
    "MULTIPLIER_LANGUAGE",
    "MULTIPLIER_PROVIDER_GLOBAL",
    "MULTIPLIER_DEFAULT_CONSERVATIVE",
    "PROVIDER_CARDMARKET",
    "PROVIDER_TOTALTCG",
    "PROVIDER_JUSTTCG",
    "PROVIDER_TCGPLAYER",
    "classify_uk_evidence_strength",
    "classify_provider",
    "can_provider_be_uk_sold_evidence",
    "select_adjustment_multiplier",
    "calculate_uk_adjusted_fallback",
    "blend_uk_and_fallback",
    "calculate_confidence",
    "build_pricing_recommendation",
]
