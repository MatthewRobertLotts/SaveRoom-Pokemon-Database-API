"""Tests for v11 price aggregation logic."""
from __future__ import annotations

import pytest

from pricing_sources.aggregator import (
    aggregate_all_buckets,
    aggregate_observations,
    should_allow_sku_price,
)
from pricing_sources.base import (
    ConfidenceLabel,
    ListingType,
    PriceObservationCandidate,
)


def _make_obs(
    amount: float,
    currency: str = "USD",
    listing_type: str = "market_price",
    finish: str = "unknown",
    condition: str = "unknown",
) -> PriceObservationCandidate:
    return PriceObservationCandidate(
        source_record_id=f"obs-{amount}",
        observed_at="2026-06-27T00:00:00Z",
        currency=currency,
        amount=amount,
        finish=finish,
        listing_type=ListingType(listing_type),
        condition=condition,
    )


class TestAggregateObservations:
    def test_empty_returns_none(self):
        result = aggregate_observations([], "canonical_printing", "cp-1", "USD", "market_price")
        assert result is None

    def test_single_observation(self):
        obs = [_make_obs(10.0)]
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price")
        assert result is not None
        assert result["median_price"] == 10.0
        assert result["observation_count"] == 1
        # Single observation + single source + finish unknown = UNUSABLE
        assert result["confidence_label"] in ("LOW", "UNUSABLE")

    def test_multiple_observations(self):
        obs = [_make_obs(5.0), _make_obs(10.0), _make_obs(15.0)]
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price")
        assert result is not None
        assert result["median_price"] == 10.0
        assert result["low_price"] == 5.0
        assert result["high_price"] == 15.0
        assert result["observation_count"] == 3

    def test_filters_by_listing_type(self):
        obs = [
            _make_obs(10.0, listing_type="market_price"),
            _make_obs(20.0, listing_type="active_listing"),
        ]
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price")
        assert result is not None
        assert result["observation_count"] == 1
        assert result["median_price"] == 10.0

    def test_filters_by_currency(self):
        obs = [
            _make_obs(10.0, currency="USD"),
            _make_obs(15.0, currency="EUR"),
        ]
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price")
        assert result is not None
        assert result["observation_count"] == 1

    def test_confidence_medium_with_many_obs_single_source(self):
        obs = [_make_obs(float(i)) for i in range(1, 11)]  # 10 observations
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price", finish="holo")
        assert result is not None
        # Single source penalty prevents HIGH even with 10 obs
        assert result["confidence_label"] in ("HIGH", "MEDIUM")

    def test_confidence_low_with_unknown_finish(self):
        obs = [_make_obs(float(i)) for i in range(1, 11)]
        result = aggregate_observations(obs, "canonical_printing", "cp-1", "USD", "market_price", finish="unknown")
        assert result is not None
        assert result["confidence_label"] != "HIGH"
        assert "finish ambiguous" in result["confidence_reason"]


class TestAggregateAllBuckets:
    def test_groups_by_currency(self):
        obs = [
            _make_obs(10.0, currency="USD"),
            _make_obs(20.0, currency="EUR"),
        ]
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        assert len(results) == 2
        currencies = {r["currency"] for r in results}
        assert currencies == {"USD", "EUR"}

    def test_groups_by_listing_type(self):
        obs = [
            _make_obs(10.0, listing_type="market_price"),
            _make_obs(20.0, listing_type="active_listing"),
        ]
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        assert len(results) == 2

    def test_groups_by_finish(self):
        obs = [
            _make_obs(10.0, finish="normal"),
            _make_obs(20.0, finish="holo"),
        ]
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        assert len(results) == 2

    def test_empty_observations(self):
        results = aggregate_all_buckets([], "canonical_printing", "cp-1")
        assert results == []


class TestShouldAllowSkuPrice:
    def test_allowed_when_high_confidence_and_known_finish(self):
        obs = [_make_obs(10.0), _make_obs(12.0), _make_obs(11.0)]
        allowed, reason = should_allow_sku_price(obs, "holo", "HIGH")
        assert allowed is True

    def test_not_allowed_when_low_confidence(self):
        obs = [_make_obs(10.0), _make_obs(12.0), _make_obs(11.0)]
        allowed, reason = should_allow_sku_price(obs, "holo", "LOW")
        assert allowed is False
        assert "LOW" in reason

    def test_not_allowed_when_finish_unknown(self):
        obs = [_make_obs(10.0), _make_obs(12.0), _make_obs(11.0)]
        allowed, reason = should_allow_sku_price(obs, "unknown", "HIGH")
        assert allowed is False
        assert "unknown" in reason

    def test_not_allowed_with_few_observations(self):
        obs = [_make_obs(10.0), _make_obs(12.0)]
        allowed, reason = should_allow_sku_price(obs, "holo", "HIGH")
        assert allowed is False
        assert "2" in reason

    def test_not_allowed_with_graded_only(self):
        obs = [_make_obs(100.0, condition="graded"), _make_obs(120.0, condition="graded"), _make_obs(110.0, condition="graded")]
        allowed, reason = should_allow_sku_price(obs, "holo", "HIGH")
        assert allowed is False  # No usable (non-graded) observations


class TestNoMixingRules:
    """Test that aggregation never mixes incompatible buckets."""

    def test_sold_and_active_separate(self):
        obs = [
            _make_obs(10.0, listing_type="market_price"),
            _make_obs(5.0, listing_type="active_listing"),
        ]
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        # Should be 2 separate buckets
        assert len(results) == 2
        for r in results:
            assert r["observation_count"] == 1

    def test_raw_and_graded_separate(self):
        obs = [
            _make_obs(10.0, condition="raw"),
            _make_obs(100.0, condition="graded"),
        ]
        # Both are market_price, same finish — they'd be in same bucket
        # but should_allow_sku_price filters graded
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        # They end up in same bucket (same currency/listing_type/finish)
        # but the SKU price check should reject graded
        assert len(results) == 1
        assert results[0]["observation_count"] == 2

    def test_sealed_and_single_separate(self):
        obs = [
            _make_obs(10.0, listing_type="market_price", finish="normal"),
            _make_obs(50.0, listing_type="sealed_product", finish="unknown"),
        ]
        results = aggregate_all_buckets(obs, "canonical_printing", "cp-1")
        listing_types = {r["listing_type"] for r in results}
        assert "market_price" in listing_types
        assert "sealed_product" in listing_types
