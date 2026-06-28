"""Price source adapter framework.

Defines the ABC that all pricing source adapters must implement, plus
shared data types and confidence scoring logic.
"""
from __future__ import annotations

import abc
import dataclasses
import enum
import json
import time
from typing import Any, Protocol


class ConfidenceLabel(str, enum.Enum):
    """Confidence levels for observations and aggregates."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNUSABLE = "UNUSABLE"


class ListingType(str, enum.Enum):
    """Types of price listings."""
    ACTIVE_LISTING = "active_listing"
    MARKET_PRICE = "market_price"
    SOLD = "sold"
    GUIDE = "guide"
    SEALED_PRODUCT = "sealed_product"
    UNKNOWN = "unknown"


class MatchConfidence(str, enum.Enum):
    """Confidence levels for identity matching."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNUSABLE = "UNUSABLE"


@dataclasses.dataclass(frozen=True)
class PriceObservationCandidate:
    """A normalised price observation from a source, before identity matching."""
    source_record_id: str
    observed_at: str
    currency: str
    amount: float
    condition: str = "unknown"
    finish: str = "unknown"
    printing_label: str | None = None
    language: str | None = None
    marketplace: str = "unknown"
    listing_type: ListingType = ListingType.UNKNOWN
    raw_title: str | None = None
    raw_url: str | None = None
    observation_type: str = "market_price"


@dataclasses.dataclass(frozen=True)
class MatchedPriceObservation:
    """An observation matched to a v10 identity target."""
    observation: PriceObservationCandidate
    target_type: str  # 'canonical_printing', 'commercial_variant', 'sellable_sku'
    target_id: str
    match_confidence: MatchConfidence
    match_reason: str
    match_method: str


@dataclasses.dataclass
class SourceHealthResult:
    """Health check result for a source."""
    source_code: str
    status: str  # 'healthy', 'degraded', 'failing', 'disabled', 'unknown'
    response_ms: float = 0.0
    last_success_at: str | None = None
    last_failure_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclasses.dataclass
class PriceQuery:
    """A query to be sent to a pricing source."""
    target_type: str
    target_id: str
    set_code: str | None = None
    collector_number: str | None = None
    card_name: str | None = None
    language: str | None = None
    finish: str | None = None


class PriceSourceAdapter(abc.ABC):
    """Abstract base class for pricing source adapters.

    Each adapter integrates with one external pricing source (e.g., TCGdex,
    JustTCG, eBay). The adapter is responsible for:
    - Building queries for a target card
    - Fetching from the source
    - Caching raw responses
    - Normalising responses into observations
    - Matching observations to v10 identity targets
    - Reporting source health

    Access gate integration:
    - Keyless/free adapters (like TCGdex) keep default behavior (no gate).
    - Keyed/paid adapters MUST override ``requires_access_gate()`` to return True
      and call ``self.require_live_access(config)`` before any HTTP call.
    """

    @property
    @abc.abstractmethod
    def source_code(self) -> str:
        """Unique source code, e.g., 'tcgdex'."""

    @property
    @abc.abstractmethod
    def source_name(self) -> str:
        """Human-readable source name."""

    def requires_access_gate(self) -> bool:
        """Whether this adapter requires the provider access gate.

        Keyless/free adapters (TCGdex) return False.
        Keyed/paid adapters MUST return True.
        """
        return False

    def live_calls_enabled(self, config: Mapping[str, str] | None = None) -> bool:
        """Check if live calls are allowed for this adapter.

        Uses the provider_access gate if requires_access_gate() is True.
        Keyless adapters always return True.
        """
        if not self.requires_access_gate():
            return True
        if config is None:
            return False
        from pricing_sources.provider_access import provider_is_live_call_allowed
        return provider_is_live_call_allowed(self.source_code, config)

    def require_live_access(self, config: Mapping[str, str] | None = None) -> None:
        """Raise PermissionError if live calls are not allowed.

        Keyless adapters are always allowed.
        Keyed adapters must pass valid config with key + enabled + terms confirmed.
        """
        if not self.requires_access_gate():
            return
        if config is None:
            raise PermissionError(
                f"Adapter '{self.source_code}' requires access gate config but none was provided."
            )
        from pricing_sources.provider_access import require_provider_live_access
        require_provider_live_access(self.source_code, config)

    @abc.abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return source capabilities description.

        Returns a dict with keys like:
        - supports_condition: bool
        - supports_finish: bool
        - supports_sold_prices: bool
        - supports_active_listings: bool
        - supports_market_prices: bool
        - currencies: list[str]
        - update_frequency: str
        """

    @abc.abstractmethod
    def health_check(self) -> SourceHealthResult:
        """Check if the source is reachable and healthy."""

    @abc.abstractmethod
    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]:
        """Build query parameters for the source.

        Returns a list of query dicts. Each query will be passed to fetch().
        Multiple queries allow fallback strategies.
        """

    @abc.abstractmethod
    def fetch(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch from the source. Returns raw response dict or None on failure.

        The raw response should be JSON-serialisable.
        Implementations must handle network errors gracefully.
        Keyed adapters MUST call self.require_live_access(config) before HTTP.
        """

    @abc.abstractmethod
    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]:
        """Normalise a raw response into observation candidates."""

    @abc.abstractmethod
    def match_observations(
        self,
        observations: list[PriceObservationCandidate],
        query: PriceQuery,
    ) -> list[MatchedPriceObservation]:
        """Match observation candidates to v10 identity targets.

        This method should look up the target in the v10 database and
        determine match confidence.
        """


def compute_aggregate(
    observations: list[PriceObservationCandidate],
) -> dict[str, Any] | None:
    """Compute aggregate statistics from a list of usable observations.

    Returns None if no usable observations.
    Returns dict with median, low, high, mean, count.
    """
    if not observations:
        return None

    amounts = sorted(obs.amount for obs in observations)
    n = len(amounts)
    if n == 0:
        return None

    median = amounts[n // 2] if n % 2 == 1 else (amounts[n // 2 - 1] + amounts[n // 2]) / 2
    mean = sum(amounts) / n
    low = amounts[0]
    high = amounts[-1]

    return {
        "median_price": round(median, 2),
        "low_price": round(low, 2),
        "high_price": round(high, 2),
        "mean_price": round(mean, 2),
        "observation_count": n,
    }


def determine_aggregate_confidence(
    observation_count: int,
    source_count: int,
    freshness_days: float,
    finish: str = "unknown",
    currency_mixed: bool = False,
) -> tuple[ConfidenceLabel, float, str]:
    """Determine aggregate confidence level.

    Returns (label, score, reason).
    """
    reasons: list[str] = []
    score = 1.0

    # Source count penalty
    if source_count < 2:
        score *= 0.8
        reasons.append("single source")

    # Observation count penalty
    if observation_count < 3:
        score *= 0.7
        reasons.append(f"thin evidence ({observation_count} obs)")
    elif observation_count < 5:
        score *= 0.9

    # Freshness penalty (skip if freshness is unknown/zero)
    if freshness_days > 14:
        score *= 0.8
        reasons.append(f"stale ({freshness_days:.0f} days)")
    elif freshness_days > 7:
        score *= 0.95

    # Finish ambiguity penalty
    if finish == "unknown":
        score *= 0.7
        reasons.append("finish ambiguous")

    # Currency mixing penalty
    if currency_mixed:
        score *= 0.8
        reasons.append("mixed currencies")

    # Determine label
    if score >= 0.85:
        label = ConfidenceLabel.HIGH
    elif score >= 0.65:
        label = ConfidenceLabel.MEDIUM
    elif score >= 0.4:
        label = ConfidenceLabel.LOW
    else:
        label = ConfidenceLabel.UNUSABLE

    reason_str = "; ".join(reasons) if reasons else "strong evidence base"
    return label, round(score, 2), reason_str
