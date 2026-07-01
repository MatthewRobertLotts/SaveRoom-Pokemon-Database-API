"""Tests for the v12 app-ready card detail endpoint.

Tests cover:
- Endpoint exists and returns 200 for known cards
- Response has all required top-level sections
- Card section has stable identity fields
- Image section does not expose raw local paths
- Commercial section is present even if arrays are empty
- Pricing section has correct UK-first shell shape
- primary_price is null when UK-first source is unavailable
- Warnings mention UK source unavailable/not live
- Provider status marks JustTCG as blocked/not implemented
- Provider status does not claim terms confirmed
- Unsupported type returns 400 or documented error
- Missing card returns 404
- No external network libraries/calls are used by this endpoint
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure auth is NOT required for contract tests
os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)

from pokemon_db_v2_fastapi import create_app

# Known test card with price evidence
TEST_CARD_KEY = "en:sv03-223"
TEST_LANG_CODE = "en"
TEST_CARD_ID = "sv03-223"

# A card that likely has no price evidence
TEST_CARD_KEY_NO_PRICE = "en:sv09-001"

client = TestClient(create_app())


# ── endpoint exists ────────────────────────────────────────────────────

def test_v12_endpoint_exists():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    assert r.status_code == 200


# ── known card returns 200 ──────────────────────────────────────────────

def test_v12_known_card_returns_200():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body


# ── response has all top-level sections ─────────────────────────────────

def test_v12_response_has_all_sections():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    assert r.status_code == 200
    body = r.json()
    data = body['data']
    # Required sections
    for section in ('card', 'set', 'images', 'commercial', 'pricing', 'provider_status'):
        assert section in data, f"Missing section: {section}"
    # Top-level warnings and metadata
    assert 'warnings' in body
    assert 'metadata' in body


# ── card section has stable identity fields ─────────────────────────────

def test_v12_card_section_has_identity_fields():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    data = r.json()['data']
    card = data['card']
    assert 'card_key' in card
    assert card['card_key'] == TEST_CARD_KEY
    assert 'name' in card
    assert 'language_code' in card
    assert card['language_code'] == TEST_LANG_CODE


# ── image section does not expose unsafe raw local paths ─────────────────

def test_v12_image_section_no_raw_paths():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    images = r.json()['data']['images']
    # Should not contain raw filesystem paths
    for key in ('primary_image_url', 'signed_image_url', 'thumbnail_url'):
        val = images.get(key)
        if val is not None:
            # Should be a URL or gateway path, not a raw filesystem path
            assert not val.startswith('/home/'), f"Raw path leaked in {key}: {val}"
            assert not val.startswith('/media/'), f"Raw path leaked in {key}: {val}"
            assert not val.startswith('file://'), f"Raw path leaked in {key}: {val}"


# ── commercial section present even if empty ─────────────────────────────

def test_v12_commercial_section_present():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    commercial = r.json()['data']['commercial']
    assert 'canonical_printing' in commercial
    assert 'commercial_variants' in commercial
    assert 'sellable_skus' in commercial
    assert 'external_references' in commercial
    # Should be lists (or None)
    assert isinstance(commercial.get('commercial_variants'), list) or commercial.get('commercial_variants') is None
    assert isinstance(commercial.get('sellable_skus'), list) or commercial.get('sellable_skus') is None


# ── pricing section has correct UK-first shell shape ────────────────────

def test_v12_pricing_section_has_shell_shape():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    pricing = r.json()['data']['pricing']
    for field in ('primary_price', 'fallback_price', 'source_breakdown',
                  'evidence_summary', 'confidence', 'warnings', 'last_refresh'):
        assert field in pricing, f"Missing pricing field: {field}"


# ── primary_price is null when UK-first source unavailable ───────────────

def test_v12_primary_price_null_when_no_uk_source():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    pricing = r.json()['data']['pricing']
    # UK eBay sold/completed is not live, so primary_price must be null
    assert pricing['primary_price'] is None, "primary_price should be null when UK source is not live"


# ── warnings mention UK source unavailable ──────────────────────────────

def test_v12_warnings_mention_uk_source_unavailable():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    body = r.json()
    warnings = body.get('warnings', [])
    assert any('UK' in w and ('not yet live' in w or 'not' in w.lower()) for w in warnings), \
        f"Expected warning about UK source not being live. Got: {warnings}"


# ── provider_status marks JustTCG as blocked ────────────────────────────

def test_v12_provider_status_justtcg_blocked():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    ps = r.json()['data']['provider_status']
    justtcg = ps.get('justtcg', {})
    # Without API key configured, status is 'not_configured' (gate dynamic)
    assert justtcg.get('status') in ('not_configured', 'disabled', 'blocked_pending_terms')
    assert justtcg.get('live_enabled') is False


# ── provider_status does not claim terms confirmed ──────────────────────

def test_v12_provider_status_no_terms_confirmed():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    ps = r.json()['data']['provider_status']
    for provider_name, provider_info in ps.items():
        assert provider_info.get('terms_confirmed') is False, \
            f"Provider {provider_name} should not have terms_confirmed=True"


# ── provider_status has all expected providers ──────────────────────────

def test_v12_provider_status_has_expected_providers():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    ps = r.json()['data']['provider_status']
    for expected in ('uk_ebay_sold', 'tcgdex', 'justtcg', 'cardmarket', 'tcgplayer'):
        assert expected in ps, f"Missing provider: {expected}"


# ── missing card returns 404 ────────────────────────────────────────────

def test_v12_missing_card_returns_404():
    r = client.get('/api/v1/cards/en:nonexistent-card-xyz/detail')
    assert r.status_code == 404


# ── invalid card key format returns 400 ─────────────────────────────────

def test_v12_invalid_card_key_returns_400():
    r = client.get('/api/v1/cards/invalidkey/detail')
    assert r.status_code == 400


# ── metadata section present ────────────────────────────────────────────

def test_v12_metadata_present():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    body = r.json()
    metadata = body.get('metadata', {})
    assert metadata.get('contract') == 'v12-app-ready-card-detail'
    assert 'generated_at' in metadata


# ── no external network calls made by the detail endpoint ───────────────

def test_v12_detail_endpoint_makes_no_network_calls():
    """Verify the v12 detail endpoint function does not make network calls.

    We inspect the source of the endpoint function to ensure it does not
    contain HTTP call patterns (requests.get, httpx, urllib, etc.).
    """
    fastapi_path = Path(__file__).resolve().parent.parent / 'pokemon_db_v2_fastapi.py'
    source = fastapi_path.read_text()
    # Extract the v12 function body
    marker = 'def v12_app_ready_card_detail('
    idx = source.find(marker)
    assert idx != -1, "v12_app_ready_card_detail function not found"
    # Find the next function definition or class at the same indentation level
    next_def = source.find('\n    def ', idx + len(marker))
    if next_def == -1:
        next_def = source.find('\n    @app.', idx + len(marker))
    func_body = source[idx:next_def] if next_def != -1 else source[idx:]
    # Check for network call patterns within the function
    for pattern in ('requests.get(', 'requests.post(', 'httpx.', 'urllib.request.urlopen', 'aiohttp'):
        assert pattern not in func_body, f"Network call pattern '{pattern}' found in v12 detail endpoint"


# ── card with no price evidence still returns valid structure ────────────

def test_v12_card_no_price_evidence_still_valid():
    """Even if a card has no price evidence, the endpoint should return a valid structure."""
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY_NO_PRICE}/detail')
    # May be 200 (card exists) or 404 (card not in DB) — both are fine
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.json()
        assert 'pricing' in body['data']
        assert body['data']['pricing']['primary_price'] is None


# ── response is valid JSON and parseable ────────────────────────────────

def test_v12_response_is_valid_json():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}/detail')
    assert r.status_code == 200
    # Should not raise
    body = r.json()
    assert isinstance(body, dict)
