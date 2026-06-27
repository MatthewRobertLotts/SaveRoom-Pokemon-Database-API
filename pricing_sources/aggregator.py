"""Conservative price aggregation logic.

Computes aggregate valuations from usable observations, with confidence
scoring that accounts for evidence freshness, count, and ambiguity.
"""
from __future__ import annotations

import statistics
from typing import Any

from pricing_sources.base import (
    ConfidenceLabel,
    PriceObservationCandidate,
    compute_aggregate,
    determine_aggregate_confidence,
)


def aggregate_observations(
    observations: list[PriceObservationCandidate],
    target_type: str,
    target_id: str,
    currency: str,
    listing_type: str,
    finish: str = "unknown",
) -> dict[str, Any] | None:
    """Compute aggregate valuation for a specific bucket.

    Bucket = (target_type, target_id, currency, listing_type, finish).

    Returns None if no usable observations.
    """
    # Filter to usable observations matching the bucket criteria
    usable = [
        obs for obs in observations
        if obs.listing_type.value == listing_type and obs.currency == currency
    ]

    if not usable:
        return None

    # Compute base statistics
    stats = compute_aggregate(usable)
    if stats is None:
        return None

    # Determine confidence
    # Freshness: use 0 as placeholder (actual freshness requires timestamps)
    freshness_days = 0.0
    source_count = 1  # Single source in v11.0

    confidence_label, confidence_score, confidence_reason = determine_aggregate_confidence(
        observation_count=stats["observation_count"],
        source_count=source_count,
        freshness_days=freshness_days,
        finish=finish,
        currency_mixed=False,
    )

    return {
        "target_type": target_type,
        "target_id": target_id,
        "currency": currency,
        "listing_type": listing_type,
        "finish": finish,
        "median_price": stats["median_price"],
        "low_price": stats["low_price"],
        "high_price": stats["high_price"],
        "mean_price": stats["mean_price"],
        "observation_count": stats["observation_count"],
        "source_count": source_count,
        "freshness_days": freshness_days,
        "confidence_label": confidence_label.value,
        "confidence_score": confidence_score,
        "confidence_reason": confidence_reason,
    }


def aggregate_all_buckets(
    observations: list[PriceObservationCandidate],
    target_type: str,
    target_id: str,
) -> list[dict[str, Any]]:
    """Compute aggregates for all relevant buckets from a list of observations.

    Buckets are grouped by (currency, listing_type, finish).
    """
    # Group observations into buckets
    buckets: dict[tuple[str, str, str], list[PriceObservationCandidate]] = {}
    for obs in observations:
        key = (obs.currency, obs.listing_type.value, obs.finish)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(obs)

    # Compute aggregate per bucket
    results: list[dict[str, Any]] = []
    for (currency, listing_type, finish), obs_list in buckets.items():
        agg = aggregate_observations(
            observations=obs_list,
            target_type=target_type,
            target_id=target_id,
            currency=currency,
            listing_type=listing_type,
            finish=finish,
        )
        if agg is not None:
            results.append(agg)

    return results


def should_allow_sku_price(
    observations: list[PriceObservationCandidate],
    finish: str,
    match_confidence: str,
) -> tuple[bool, str]:
    """Determine if an exact SKU price is allowed.

    SKU exact price requires:
    - match_confidence = HIGH
    - finish != 'unknown'
    - At least 3 usable observations

    Returns (allowed, reason).
    """
    if match_confidence != "HIGH":
        return False, f"match confidence is {match_confidence}, need HIGH"

    if finish == "unknown":
        return False, "finish is unknown, cannot create exact SKU price"

    usable = [o for o in observations if o.condition != "graded"]
    if len(usable) < 3:
        return False, f"only {len(usable)} usable observations, need 3+"

    return True, "evidence supports SKU-level price"
