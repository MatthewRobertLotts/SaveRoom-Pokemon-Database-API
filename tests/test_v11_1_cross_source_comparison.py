"""Tests for provider-neutral cross-source comparison logic.

Uses fixture dicts only — no live API, no paid providers, no secrets.
All inputs represent plausible v11_price_aggregate rows.
"""
from __future__ import annotations

import pytest

from pricing_sources.comparison import (
    AgreementBand,
    ConfidenceImpact,
    ComparisonResult,
    SourceBucket,
    _same_bucket_key,
    _finish_compatible,
    _condition_compatible,
    _pct_diff,
    _parse_bucket,
    agreement_band,
    compare_price_aggregates,
    compare_source_pair,
    confidence_impact,
    is_comparable_bucket,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _agg(
    *,
    source_id: str = "src-a",
    target_type: str = "canonical_printing",
    target_id: str = "cp-base-001",
    currency: str = "USD",
    listing_type: str = "market_price",
    finish: str = "normal",
    condition: str = "unknown",
    median_price: float = 10.0,
    computed_at: str = "2026-06-26T00:00:00Z",
    fetched_at: str = "2026-06-26T00:00:00Z",
) -> dict:
    return {
        "source_id": source_id,
        "target_type": target_type,
        "target_id": target_id,
        "currency": currency,
        "listing_type": listing_type,
        "finish": finish,
        "condition": condition,
        "median_price": median_price,
        "computed_at": computed_at,
        "fetched_at": fetched_at,
    }


# ── Agreement bands ────────────────────────────────────────────────────────

class TestAgreementBand:
    def test_agree_at_zero(self):
        assert agreement_band(0.0) == AgreementBand.AGREE

    def test_agree_at_15_pct(self):
        assert agreement_band(0.15) == AgreementBand.AGREE

    def test_minor_at_20_pct(self):
        assert agreement_band(0.20) == AgreementBand.MINOR_DISAGREEMENT

    def test_minor_at_35_pct(self):
        assert agreement_band(0.35) == AgreementBand.MINOR_DISAGREEMENT

    def test_major_at_36_pct(self):
        assert agreement_band(0.36) == AgreementBand.MAJOR_DISAGREEMENT

    def test_major_at_100_pct(self):
        assert agreement_band(1.0) == AgreementBand.MAJOR_DISAGREEMENT


# ── Percentage diff ─────────────────────────────────────────────────────────

class TestPctDiff:
    def test_equal_values(self):
        assert _pct_diff(10.0, 10.0) == pytest.approx(0.0)

    def test_half(self):
        assert _pct_diff(10.0, 15.0) == pytest.approx(5 / 15)

    def test_does_not_divide_by_zero(self):
        assert _pct_diff(0.0, 0.0) == pytest.approx(0.0)

    def test_one_zero(self):
        assert _pct_diff(0.0, 5.0) == pytest.approx(1.0)

    def test_commutative(self):
        assert _pct_diff(10.0, 20.0) == _pct_diff(20.0, 10.0)


# ── Parse bucket ────────────────────────────────────────────────────────────

class TestParseBucket:
    def test_valid(self):
        b = _parse_bucket(_agg(source_id="s1"))
        assert b is not None
        assert b.source_id == "s1"
        assert b.currency == "USD"
        assert b.finish == "normal"

    def test_missing_field(self):
        raw = _agg()
        del raw["median_price"]
        assert _parse_bucket(raw) is None

    def test_bad_median_type(self):
        raw = _agg()
        raw["median_price"] = "not-a-number"
        assert _parse_bucket(raw) is None

    def test_none_median(self):
        raw = _agg()
        raw["median_price"] = None
        assert _parse_bucket(raw) is None


# ── Comparable bucket checks ────────────────────────────────────────────────

class TestIsComparableBucket:
    def _buckets(self, **ka):
        a = _parse_bucket(_agg(source_id="a", **{k: v for k, v in ka.items() if not k.startswith("b_")}))
        b_dict = {}
        for k, v in ka.items():
            if k.startswith("b_"):
                b_dict[k[2:]] = v
        b = _parse_bucket(_agg(source_id="b", **b_dict))
        assert a is not None and b is not None
        return a, b

    def test_same_bucket(self):
        a = _parse_bucket(_agg(source_id="a"))
        b = _parse_bucket(_agg(source_id="b"))
        ok, reason = is_comparable_bucket(a, b)
        assert ok is True
        assert reason == ""

    def test_different_currency(self):
        a = _parse_bucket(_agg(source_id="a", currency="USD"))
        b = _parse_bucket(_agg(source_id="b", currency="EUR"))
        ok, reason = is_comparable_bucket(a, b)
        assert ok is False
        assert "currency" in reason.lower() or "bucket" in reason.lower()

    def test_different_listing_type(self):
        a = _parse_bucket(_agg(source_id="a", listing_type="market_price"))
        b = _parse_bucket(_agg(source_id="b", listing_type="sold"))
        ok, _ = is_comparable_bucket(a, b)
        assert ok is False

    def test_different_finish(self):
        a = _parse_bucket(_agg(source_id="a", finish="normal"))
        b = _parse_bucket(_agg(source_id="b", finish="reverse_holo"))
        ok, reason = is_comparable_bucket(a, b)
        assert ok is False
        assert "finish" in reason

    def test_finish_ambiguous_one_unknown(self):
        a = _parse_bucket(_agg(source_id="a", finish="normal"))
        b = _parse_bucket(_agg(source_id="b", finish="unknown"))
        ok, reason = is_comparable_bucket(a, b)
        assert ok is False
        assert "finish" in reason

    def test_finish_both_unknown(self):
        a = _parse_bucket(_agg(source_id="a", finish="unknown"))
        b = _parse_bucket(_agg(source_id="b", finish="unknown"))
        ok, _ = is_comparable_bucket(a, b)
        assert ok is True

    def test_condition_different(self):
        a = _parse_bucket(_agg(source_id="a", condition="raw"))
        b = _parse_bucket(_agg(source_id="b", condition="graded"))
        ok, reason = is_comparable_bucket(a, b)
        assert ok is False
        assert "condition" in reason

    def test_condition_ambiguous(self):
        a = _parse_bucket(_agg(source_id="a", condition="raw"))
        b = _parse_bucket(_agg(source_id="b", condition="unknown"))
        ok, _ = is_comparable_bucket(a, b)
        assert ok is False


# ── compare_price_aggregates ────────────────────────────────────────────────

class TestComparePriceAggregates:
    def test_two_sources_agree_within_15_pct(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=110.0)
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is True
        assert r.agreement_band == AgreementBand.AGREE
        assert r.percentage_difference == pytest.approx(10 / 110, rel=1e-3)

    def test_minor_disagreement_15_35(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=130.0)
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is True
        assert r.agreement_band == AgreementBand.MINOR_DISAGREEMENT

    def test_major_disagreement_over_35(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=160.0)
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is True
        assert r.agreement_band == AgreementBand.MAJOR_DISAGREEMENT

    def test_insufficient_evidence_one_source(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="a", median_price=110.0)  # same source_id
        # still comparable; but we also test source_count=1 for impact
        r = compare_price_aggregates(a, b, source_count=1)
        assert r.is_comparable is True
        assert r.confidence_impact == ConfidenceImpact.NONE

    def test_currency_mismatch(self):
        a = _agg(source_id="a", currency="USD")
        b = _agg(source_id="b", currency="EUR")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.MIXED_SEMANTICS

    def test_listing_type_mismatch(self):
        a = _agg(source_id="a", listing_type="sold")
        b = _agg(source_id="b", listing_type="market_price")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.MIXED_SEMANTICS

    def test_finish_mismatch(self):
        a = _agg(source_id="a", finish="holo")
        b = _agg(source_id="b", finish="normal")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.MIXED_SEMANTICS

    def test_condition_mismatch(self):
        a = _agg(source_id="a", condition="raw")
        b = _agg(source_id="b", condition="graded")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.MIXED_SEMANTICS

    def test_zero_median_handled(self):
        a = _agg(source_id="a", median_price=0.0)
        b = _agg(source_id="b", median_price=10.0)
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.INSUFFICIENT_EVIDENCE

    def test_negative_median_handled(self):
        a = _agg(source_id="a", median_price=-5.0)
        b = _agg(source_id="b", median_price=10.0)
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False

    def test_missing_fields_handled(self):
        a = {"source_id": "a"}  # missing median_price etc.
        b = _agg(source_id="b")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False
        assert r.agreement_band == AgreementBand.INSUFFICIENT_EVIDENCE

    def test_none_input_handled(self):
        a = None
        b = _agg(source_id="b")
        r = compare_price_aggregates(a, b)
        assert r.is_comparable is False

    def test_confidence_impact_never_high_from_one_source(self):
        a = _agg(source_id="a", median_price=100.0)
        # Even if two rows happen to be from same source_id string, pass source_count=1 to enforce the rule
        b = _agg(source_id="a", median_price=105.0)
        r = compare_price_aggregates(a, b, source_count=1)
        assert r.confidence_impact != ConfidenceImpact.BOOSTED

    def test_confidence_impact_agreement_boosts_medium(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=105.0)
        r = compare_price_aggregates(a, b, existing_label="MEDIUM", source_count=2)
        assert r.confidence_impact == ConfidenceImpact.BOOSTED

    def test_confidence_impact_disagreement_reduces(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=180.0)
        r = compare_price_aggregates(a, b, existing_label="MEDIUM", source_count=2)
        assert r.confidence_impact == ConfidenceImpact.REDUCED

    def test_absolute_difference_computed(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=120.0)
        r = compare_price_aggregates(a, b)
        assert r.absolute_difference == pytest.approx(20.0)

    def test_percentage_difference_populated(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=140.0)
        r = compare_price_aggregates(a, b)
        assert r.percentage_difference is not None
        assert r.percentage_difference > 0


# ── compare_source_pair helper ──────────────────────────────────────────────

class TestCompareSourcePair:
    def test_compares_median_observations(self):
        obs_a = [
            {"source_id": "a", "currency": "USD", "amount": 10.0, "finish": "normal", "condition": "unknown"},
            {"source_id": "a", "currency": "USD", "amount": 12.0, "finish": "normal", "condition": "unknown"},
        ]
        obs_b = [
            {"source_id": "b", "currency": "USD", "amount": 11.0, "finish": "normal", "condition": "unknown"},
            {"source_id": "b", "currency": "USD", "amount": 13.0, "finish": "normal", "condition": "unknown"},
        ]
        r = compare_source_pair(obs_a, obs_b)
        assert r is not None
        assert r.is_comparable is True
        assert r.source_a_median == pytest.approx(11.0)
        assert r.source_b_median == pytest.approx(12.0)

    def test_returns_none_on_empty(self):
        assert compare_source_pair([], [_agg()]) is None
        assert compare_source_pair([_agg()], []) is None
        assert compare_source_pair([], []) is None

    def test_different_currencies_returns_mixed(self):
        obs_a = [{"source_id": "a", "currency": "USD", "amount": 10.0, "finish": "unknown", "condition": "unknown"}]
        obs_b = [{"source_id": "b", "currency": "EUR", "amount": 9.0, "finish": "unknown", "condition": "unknown"}]
        r = compare_source_pair(obs_a, obs_b)
        assert r is not None
        assert r.is_comparable is False


# ── confidence_impact standalone ────────────────────────────────────────────

class TestConfidenceImpact:
    def test_agree_single_source(self):
        impact, reason = confidence_impact(AgreementBand.AGREE, "MEDIUM", source_count=1)
        assert impact == ConfidenceImpact.NONE

    def test_agree_two_sources_from_medium(self):
        impact, _ = confidence_impact(AgreementBand.AGREE, "MEDIUM", source_count=2)
        assert impact == ConfidenceImpact.BOOSTED

    def test_agree_two_sources_from_high(self):
        impact, _ = confidence_impact(AgreementBand.AGREE, "HIGH", source_count=2)
        assert impact == ConfidenceImpact.NONE  # already HIGH

    def test_minor_disagreement(self):
        impact, _ = confidence_impact(AgreementBand.MINOR_DISAGREEMENT, "MEDIUM", source_count=2)
        assert impact == ConfidenceImpact.REDUCED

    def test_major_disagreement(self):
        impact, _ = confidence_impact(AgreementBand.MAJOR_DISAGREEMENT, "MEDIUM", source_count=2)
        assert impact == ConfidenceImpact.REDUCED

    def test_mixed_semantics(self):
        impact, _ = confidence_impact(AgreementBand.MIXED_SEMANTICS, "MEDIUM", source_count=2)
        assert impact == ConfidenceImpact.NONE

    def test_stale_source(self):
        impact, _ = confidence_impact(AgreementBand.STALE_SOURCE, "MEDIUM", source_count=2)
        assert impact == ConfidenceImpact.REDUCED


# ── Full result shape ──────────────────────────────────────────────────────

class TestResultShape:
    def test_result_contains_expected_fields(self):
        a = _agg(source_id="a", median_price=100.0)
        b = _agg(source_id="b", median_price=110.0)
        r = compare_price_aggregates(a, b)
        assert isinstance(r, ComparisonResult)
        assert r.source_a_id == "a"
        assert r.source_b_id == "b"
        assert r.currency == "USD"
        assert r.listing_type == "market_price"
        assert r.target_type == "canonical_printing"
        assert r.target_id == "cp-base-001"

    def test_non_comparable_still_has_target_info(self):
        a = _agg(source_id="a", currency="USD")
        b = _agg(source_id="b", currency="EUR")
        r = compare_price_aggregates(a, b)
        assert r.target_type == "canonical_printing"
        assert r.target_id == "cp-base-001"
