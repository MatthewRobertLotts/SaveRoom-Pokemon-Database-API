"""Provider-neutral cross-source price comparison.

Compares two or more source-backed aggregate buckets and produces an
agreement/disagreement signal. Operates on plain dicts only — no live
DB connection, no provider calls, no secrets.

Design: docs/V11_1_CROSS_SOURCE_COMPARISON_MODEL.md
"""
from __future__ import annotations

import dataclasses
import enum
from typing import Any


# Agreement / disagreement bands — conservative by design
AGREE_THRESHOLD = 0.15          # 0–15%
MINOR_DISAGREE_THRESHOLD = 0.35  # >15–35%

DEFAULT_EPSILON = 1e-9
DEFAULT_STALE_DAYS = 30


class AgreementBand(str, enum.Enum):
    AGREE = "AGREE"
    MINOR_DISAGREEMENT = "MINOR_DISAGREEMENT"
    MAJOR_DISAGREEMENT = "MAJOR_DISAGREEMENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MIXED_SEMANTICS = "MIXED_SEMANTICS"
    STALE_SOURCE = "STALE_SOURCE"


class ConfidenceImpact(str, enum.Enum):
    NONE = "NONE"
    BOOSTED = "BOOSTED"
    REDUCED = "REDUCED"


@dataclasses.dataclass(frozen=True)
class SourceBucket:
    """Minimal comparison-ready representation of one source's aggregate."""
    source_id: str
    target_type: str
    target_id: str
    currency: str
    listing_type: str
    finish: str
    condition: str
    median_price: float
    computed_at: str
    fetched_at: str


@dataclasses.dataclass
class ComparisonResult:
    """Result of comparing two source buckets."""
    target_type: str
    target_id: str
    currency: str
    listing_type: str
    finish: str
    condition: str
    source_a_id: str
    source_b_id: str
    source_a_median: float | None
    source_b_median: float | None
    absolute_difference: float | None
    percentage_difference: float | None
    agreement_band: str
    confidence_impact: str
    comparison_reason: str
    is_comparable: bool


def _parse_bucket(row: dict[str, Any]) -> SourceBucket | None:
    """Safely parse a dict into a SourceBucket. Returns None on missing fields."""
    try:
        return SourceBucket(
            source_id=str(row["source_id"]),
            target_type=str(row["target_type"]),
            target_id=str(row["target_id"]),
            currency=str(row["currency"]).upper(),
            listing_type=str(row["listing_type"]),
            finish=str(row.get("finish") or "unknown").lower(),
            condition=str(row.get("condition") or "unknown").lower(),
            median_price=float(row["median_price"]),
            computed_at=str(row["computed_at"]),
            fetched_at=str(row.get("fetched_at") or row["computed_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _same_bucket_key(a: SourceBucket, b: SourceBucket) -> bool:
    """True only if both buckets share the same semantic target."""
    return (
        a.target_type == b.target_type
        and a.target_id == b.target_id
        and a.currency == b.currency
        and a.listing_type == b.listing_type
    )


def _finish_compatible(a: SourceBucket, b: SourceBucket) -> bool:
    if a.finish == "unknown" or b.finish == "unknown":
        return a.finish == b.finish  # both unknown OK but flagged elsewhere
    return a.finish == b.finish


def _condition_compatible(a: SourceBucket, b: SourceBucket) -> bool:
    if a.condition == "unknown" or b.condition == "unknown":
        return a.condition == b.condition
    return a.condition == b.condition


def is_comparable_bucket(a: SourceBucket, b: SourceBucket) -> tuple[bool, str]:
    """Check whether two buckets are comparable. Returns (ok, reason)."""
    if not _same_bucket_key(a, b):
        return False, f"bucket mismatch: {a.target_type}/{a.target_id}/{a.currency}/{a.listing_type} vs {b.target_type}/{b.target_id}/{b.currency}/{b.listing_type}"
    if a.finish != b.finish:
        if a.finish == "unknown" or b.finish == "unknown":
            return False, f"finish ambiguous: {a.finish} vs {b.finish}"
        return False, f"finish mismatch: {a.finish} vs {b.finish}"
    if a.condition != b.condition:
        if a.condition == "unknown" or b.condition == "unknown":
            return False, f"condition ambiguous: {a.condition} vs {b.condition}"
        return False, f"condition mismatch: {a.condition} vs {b.condition}"
    return True, ""


def agreement_band(pct_diff: float) -> AgreementBand:
    """Map a percentage difference to an agreement band."""
    if pct_diff <= AGREE_THRESHOLD:
        return AgreementBand.AGREE
    if pct_diff <= MINOR_DISAGREE_THRESHOLD:
        return AgreementBand.MINOR_DISAGREEMENT
    return AgreementBand.MAJOR_DISAGREEMENT


def confidence_impact(
    band: AgreementBand,
    existing_label: str,
    source_count: int,
) -> tuple[str, str]:
    """Determine confidence impact. Returns (impact, reason).

    Rules:
    - Never raise confidence from a single comparable source pair alone beyond what evidence supports.
    - AGREE can boost, but never above HIGH and never from a single source.
    - DISAGREEMENT lowers by one band.
    """
    if band == AgreementBand.INSUFFICIENT_EVIDENCE:
        return ConfidenceImpact.NONE, "insufficient evidence"
    if band == AgreementBand.MIXED_SEMANTICS:
        return ConfidenceImpact.NONE, "bucket semantics differ"
    if band == AgreementBand.STALE_SOURCE:
        return ConfidenceImpact.REDUCED, "stale source reduces confidence"

    if band == AgreementBand.AGREE:
        if source_count < 2:
            return ConfidenceImpact.NONE, "agreement but single source"
        if existing_label == "MEDIUM":
            return ConfidenceImpact.BOOSTED, "two sources agree; raised to HIGH"
        if existing_label == "LOW":
            return ConfidenceImpact.BOOSTED, "two sources agree; raised to MEDIUM"
        return ConfidenceImpact.NONE, "agreement; confidence unchanged"

    # Disagreement
    if band == AgreementBand.MINOR_DISAGREEMENT:
        return ConfidenceImpact.REDUCED, f"minor disagreement ({band.value})"
    return ConfidenceImpact.REDUCED, f"major disagreement ({band.value})"


def _pct_diff(a: float, b: float) -> float:
    """Percentage difference relative to the larger value."""
    denom = max(abs(a), abs(b), DEFAULT_EPSILON)
    return abs(a - b) / denom


def compare_price_aggregates(
    aggregate_a: dict[str, Any],
    aggregate_b: dict[str, Any],
    *,
    existing_label: str = "MEDIUM",
    source_count: int = 2,
    stale_threshold_days: int = DEFAULT_STALE_DAYS,
) -> ComparisonResult:
    """Compare two aggregate rows (as dicts).

    Params:
        aggregate_a: first source's aggregate dict.
        aggregate_b: second source's aggregate dict.
        existing_label: confidence label of the baseline aggregate (HIGH/MEDIUM/LOW/UNUSABLE).
        source_count: total number of distinct sources for this bucket (>=2 expected).
        stale_threshold_days: max age in days before a source is considered stale.

    Returns ComparisonResult. Never raises on bad input; returns a safe
    INSUFFICIENT_EVIDENCE / MIXED_SEMANTICS result with is_comparable=False.
    """
    a = _parse_bucket(aggregate_a) if not isinstance(aggregate_a, SourceBucket) else aggregate_a
    b = _parse_bucket(aggregate_b) if not isinstance(aggregate_b, SourceBucket) else aggregate_b

    if a is None or b is None:
        return ComparisonResult(
            target_type="",
            target_id="",
            currency="",
            listing_type="",
            finish="",
            condition="",
            source_a_id="",
            source_b_id="",
            source_a_median=None,
            source_b_median=None,
            absolute_difference=None,
            percentage_difference=None,
            agreement_band=AgreementBand.INSUFFICIENT_EVIDENCE,
            confidence_impact=ConfidenceImpact.NONE,
            comparison_reason="malformed aggregate input",
            is_comparable=False,
        )

    comparable, reason = is_comparable_bucket(a, b)
    if not comparable:
        band = AgreementBand.MIXED_SEMANTICS
        impact, impact_reason = confidence_impact(band, existing_label, source_count)
        return ComparisonResult(
            target_type=a.target_type,
            target_id=a.target_id,
            currency=a.currency,
            listing_type=a.listing_type,
            finish=a.finish,
            condition=a.condition,
            source_a_id=a.source_id,
            source_b_id=b.source_id,
            source_a_median=None,
            source_b_median=None,
            absolute_difference=None,
            percentage_difference=None,
            agreement_band=band,
            confidence_impact=impact,
            comparison_reason=reason,
            is_comparable=False,
        )

    # Validate medians
    if not (a.median_price > 0 and b.median_price > 0):
        return ComparisonResult(
            target_type=a.target_type,
            target_id=a.target_id,
            currency=a.currency,
            listing_type=a.listing_type,
            finish=a.finish,
            condition=a.condition,
            source_a_id=a.source_id,
            source_b_id=b.source_id,
            source_a_median=a.median_price if a.median_price > 0 else None,
            source_b_median=b.median_price if b.median_price > 0 else None,
            absolute_difference=None,
            percentage_difference=None,
            agreement_band=AgreementBand.INSUFFICIENT_EVIDENCE,
            confidence_impact=ConfidenceImpact.NONE,
            comparison_reason="zero or invalid median price",
            is_comparable=False,
        )

    pct = _pct_diff(a.median_price, b.median_price)
    band = agreement_band(pct)
    impact, impact_reason = confidence_impact(band, existing_label, source_count)

    return ComparisonResult(
        target_type=a.target_type,
        target_id=a.target_id,
        currency=a.currency,
        listing_type=a.listing_type,
        finish=a.finish,
        condition=a.condition,
        source_a_id=a.source_id,
        source_b_id=b.source_id,
        source_a_median=a.median_price,
        source_b_median=b.median_price,
        absolute_difference=round(abs(a.median_price - b.median_price), 2),
        percentage_difference=round(pct, 4),
        agreement_band=band,
        confidence_impact=impact,
        comparison_reason=impact_reason,
        is_comparable=True,
    )


def compare_source_pair(
    observations_a: list[dict[str, Any]],
    observations_b: list[dict[str, Any]],
) -> ComparisonResult | None:
    """High-level helper: compute aggregates from two sets of observation dicts and compare them.

    Each list should contain observation dicts from one source. Computes a simple
    median aggregate for each set, then delegates to compare_price_aggregates.

    observation dicts expected keys: currency, amount, finish, condition, source_id
    optional keys: target_type, target_id, listing_type, fetched_at, computed_at

    Returns None if either set is empty.
    """
    if not observations_a or not observations_b:
        return None

    def median(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        if n == 0:
            return 0.0
        if n % 2 == 1:
            return float(s[n // 2])
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    med_a = median([float(o["amount"]) for o in observations_a])
    med_b = median([float(o["amount"]) for o in observations_b])

    a0, b0 = observations_a[0], observations_b[0]
    now = "2026-06-27T00:00:00Z"

    agg_a = {
        "source_id": a0.get("source_id", "a"),
        "target_type": a0.get("target_type", "canonical_printing"),
        "target_id": a0.get("target_id", ""),
        "currency": a0.get("currency", "USD"),
        "listing_type": a0.get("listing_type", "market_price"),
        "finish": a0.get("finish", "unknown"),
        "condition": a0.get("condition", "unknown"),
        "median_price": med_a,
        "computed_at": a0.get("computed_at", now),
        "fetched_at": a0.get("fetched_at", now),
    }
    agg_b = {
        "source_id": b0.get("source_id", "b"),
        "target_type": b0.get("target_type", "canonical_printing"),
        "target_id": b0.get("target_id", ""),
        "currency": b0.get("currency", "USD"),
        "listing_type": b0.get("listing_type", "market_price"),
        "finish": b0.get("finish", "unknown"),
        "condition": b0.get("condition", "unknown"),
        "median_price": med_b,
        "computed_at": b0.get("computed_at", now),
        "fetched_at": b0.get("fetched_at", now),
    }
    return compare_price_aggregates(agg_a, agg_b)
