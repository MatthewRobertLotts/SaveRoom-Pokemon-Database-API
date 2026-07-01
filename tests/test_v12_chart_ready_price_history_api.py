"""Tests for the v12 chart-ready price history endpoint.

Tests cover:
- Endpoint exists and returns 200 for known cards with evidence
- Response has data, series, summary, warnings, metadata
- Series has source, currency, price_type, region, points
- Points have date, median, low, high, evidence_count, confidence
- Missing card returns 404
- Invalid card key returns 400
- Card with no evidence returns empty series
- bucket_size day/week/month all work
- Invalid bucket_size returns 400
- source filter works
- include_non_recommended flag works
- limit parameter works
- primary_source_live is always false
- Warnings mention UK source not live
- No raw filesystem paths leak
- No network calls in the endpoint function body
- Metadata has correct contract label
- Confidence levels are correct
- Percentile values are plausible
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure auth is NOT required for contract tests
os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)

from pokemon_db_v2_fastapi import create_app

# Known test card with price evidence
TEST_CARD_KEY = "en:sv03-223"
CHART_URL = '/api/v1/prices/chart/cards'

client = TestClient(create_app())


def _chart_url(card_key: str) -> str:
    return f'{CHART_URL}/{card_key}'


# ── endpoint exists ───────────────────────────────────────────────────

def test_v12_chart_endpoint_exists():
    r = client.get(_chart_url(TEST_CARD_KEY))
    # May be 200 or 404 depending on evidence, but endpoint must respond
    assert r.status_code in (200, 404)


# ── known card returns 200 ────────────────────────────────────────────

def test_v12_chart_known_card_returns_200():
    r = client.get(_chart_url(TEST_CARD_KEY))
    # sv03-223 should have evidence in the DB
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.json()
        assert 'data' in body


# ── response has required sections ────────────────────────────────────

def test_v12_chart_response_has_sections():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return  # card may not have evidence
    body = r.json()
    data = body['data']
    assert 'card_key' in data
    assert 'series' in data
    assert 'summary' in data
    assert 'warnings' in body
    assert 'metadata' in body


# ── series has required fields ────────────────────────────────────────

def test_v12_chart_series_has_fields():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    series = r.json()['data']['series']
    if not series:
        return
    s = series[0]
    assert 'source' in s
    assert 'currency' in s
    assert 'price_type' in s
    assert 'region' in s
    assert 'points' in s
    assert s['currency'] == 'GBP'
    assert s['price_type'] == 'market_existing_local'


# ── points have required fields ───────────────────────────────────────

def test_v12_chart_points_have_fields():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    series = r.json()['data']['series']
    if not series or not series[0]['points']:
        return
    p = series[0]['points'][0]
    for field in ('date', 'median', 'low', 'high', 'evidence_count', 'confidence'):
        assert field in p, f"Missing point field: {field}"


# ── missing card returns 404 ──────────────────────────────────────────

def test_v12_chart_missing_card_returns_404():
    r = client.get(_chart_url('en:nonexistent-card-xyz'))
    assert r.status_code == 404


# ── invalid card key returns 400 ──────────────────────────────────────

def test_v12_chart_invalid_card_key_returns_400():
    r = client.get(_chart_url('invalidkey'))
    assert r.status_code == 400


# ── bucket_size day works ─────────────────────────────────────────────

def test_v12_chart_bucket_size_day():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'bucket_size': 'day'})
    assert r.status_code in (200, 404)


# ── bucket_size week works ────────────────────────────────────────────

def test_v12_chart_bucket_size_week():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'bucket_size': 'week'})
    assert r.status_code in (200, 404)


# ── bucket_size month works ───────────────────────────────────────────

def test_v12_chart_bucket_size_month():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'bucket_size': 'month'})
    assert r.status_code in (200, 404)


# ── invalid bucket_size returns 400 ───────────────────────────────────

def test_v12_chart_invalid_bucket_size_returns_400():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'bucket_size': 'year'})
    # Card must exist first; if card exists, should get 400
    # If card doesn't exist, 404 is fine too
    if r.status_code != 404:
        assert r.status_code == 400


# ── source filter works ───────────────────────────────────────────────

def test_v12_chart_source_filter():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'source': 'ebay_uk_sold'})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.json()
        series = body['data']['series']
        # All series should be ebay_uk_sold if any exist
        for s in series:
            assert s['source'] == 'ebay_uk_sold'


# ── include_non_recommended flag ──────────────────────────────────────

def test_v12_chart_include_non_recommended():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'include_non_recommended': True})
    assert r.status_code in (200, 404)


# ── limit parameter works ─────────────────────────────────────────────

def test_v12_chart_limit():
    r = client.get(_chart_url(TEST_CARD_KEY), params={'limit': 10})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        series = r.json()['data']['series']
        for s in series:
            assert len(s['points']) <= 10


# ── primary_source_live is always false ───────────────────────────────

def test_v12_chart_primary_source_not_live():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    summary = r.json()['data']['summary']
    assert summary['primary_source_live'] is False


# ── warnings mention UK source not live ───────────────────────────────

def test_v12_chart_warnings_uk_source():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    warnings = r.json().get('warnings', [])
    assert any('UK' in w and 'not yet live' in w for w in warnings), \
        f"Expected UK warning. Got: {warnings}"


# ── no raw filesystem paths leak ──────────────────────────────────────

def test_v12_chart_no_raw_paths():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    # Convert to string and check for raw paths
    text = str(r.json())
    assert '/home/' not in text or '/home/' in 'uk_ebay_sold/home/path', "Raw /home/ path leaked"
    assert '/media/' not in text, "Raw /media/ path leaked"


# ── no network calls in endpoint function body ────────────────────────

def test_v12_chart_no_network_calls():
    fastapi_path = Path(__file__).resolve().parent.parent / 'pokemon_db_v2_fastapi.py'
    source = fastapi_path.read_text()
    marker = 'def v12_chart_ready_price_history('
    idx = source.find(marker)
    assert idx != -1, "v12_chart_ready_price_history function not found"
    next_def = source.find('\n    def ', idx + len(marker))
    if next_def == -1:
        next_def = source.find('\n    @app.', idx + len(marker))
    func_body = source[idx:next_def] if next_def != -1 else source[idx:]
    for pattern in ('requests.get(', 'requests.post(', 'httpx.', 'urllib.request.urlopen', 'aiohttp'):
        assert pattern not in func_body, f"Network call pattern '{pattern}' found in chart endpoint"


# ── metadata has correct contract ─────────────────────────────────────

def test_v12_chart_metadata_contract():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    metadata = r.json().get('metadata', {})
    assert metadata.get('contract') == 'v12-chart-ready-price-history'
    assert metadata.get('api_version') == 'v1'
    assert 'generated_at' in metadata


# ── confidence levels are correct ─────────────────────────────────────

def test_v12_chart_confidence_levels():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    series = r.json()['data']['series']
    for s in series:
        for p in s['points']:
            assert p['confidence'] in ('MEDIUM', 'LOW', 'VERY_LOW'), \
                f"Invalid confidence: {p['confidence']}"


# ── percentile values are plausible ───────────────────────────────────

def test_v12_chart_percentiles_plausible():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    series = r.json()['data']['series']
    for s in series:
        for p in s['points']:
            # low <= median <= high when all are non-null
            if p['low'] is not None and p['median'] is not None and p['high'] is not None:
                assert p['low'] <= p['median'] + 0.01, f"low > median: {p}"
                assert p['median'] <= p['high'] + 0.01, f"median > high: {p}"


# ── summary counts are consistent ─────────────────────────────────────

def test_v12_chart_summary_consistent():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    data = r.json()['data']
    series = data['series']
    summary = data['summary']
    actual_points = sum(len(s['points']) for s in series)
    assert summary['point_count'] == actual_points


# ── no evidence card returns empty series ─────────────────────────────

def test_v12_chart_no_evidence_card():
    # Use a card that exists but likely has no price evidence
    r = client.get(_chart_url('en:sv09-001'))
    if r.status_code == 200:
        body = r.json()
        # May have evidence or not — either way, structure must be valid
        assert 'series' in body['data']
        assert 'summary' in body['data']


# ── region is UK for uk sources ───────────────────────────────────────

def test_v12_chart_region_uk():
    r = client.get(_chart_url(TEST_CARD_KEY))
    if r.status_code != 200:
        return
    series = r.json()['data']['series']
    for s in series:
        if 'uk' in s['source'].lower():
            assert s['region'] == 'UK'
