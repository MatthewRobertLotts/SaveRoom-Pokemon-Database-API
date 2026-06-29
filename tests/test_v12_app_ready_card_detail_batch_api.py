"""Tests for the v12 app-ready card detail batch endpoint.

Tests cover:
- Batch endpoint exists
- Valid batch returns 200
- Two known cards return ok items
- Response has items and summary
- Ok item detail has card/set/images/commercial/pricing/provider_status
- Missing card returns item-level error
- Invalid card key returns item-level error
- Empty card_keys rejected
- More than 50 card_keys rejected
- Duplicate card_keys handled predictably
- include_pricing false sets pricing to null
- include_images false sets images to null
- include_commercial false sets commercial to null
- JustTCG is not live and terms_confirmed is false
- primary_price remains null when UK source unavailable
- No raw filesystem paths leak
- No network calls in the batch endpoint function body
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure auth is NOT required for contract tests
os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)

from pokemon_db_v2_fastapi import create_app

# Known test cards
TEST_CARD_KEY = "en:sv03-223"
TEST_CARD_KEY_2 = "en:sv09-001"
MISSING_CARD_KEY = "en:nonexistent-card-xyz"
INVALID_CARD_KEY = "invalidkey"

BATCH_URL = '/api/v1/cards/detail/batch'

client = TestClient(create_app())


def _post_batch(card_keys, **kwargs):
    """Helper to POST to the batch endpoint."""
    body = {'card_keys': card_keys}
    body.update(kwargs)
    return client.post(BATCH_URL, json=body)


# ── batch endpoint exists ───────────────────────────────────────────────

def test_v12_batch_endpoint_exists():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200


# ── valid batch returns 200 ─────────────────────────────────────────────

def test_v12_batch_valid_returns_200():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body


# ── two known cards return ok items ─────────────────────────────────────

def test_v12_batch_two_known_cards():
    r = _post_batch([TEST_CARD_KEY, TEST_CARD_KEY_2])
    assert r.status_code == 200
    body = r.json()
    items = body['data']['items']
    # At least one should be ok (TEST_CARD_KEY is known)
    ok_items = [i for i in items if i['status'] == 'ok']
    assert len(ok_items) >= 1, f"Expected at least 1 ok item, got: {items}"


# ── response has items and summary ──────────────────────────────────────

def test_v12_batch_has_items_and_summary():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    body = r.json()
    data = body['data']
    assert 'items' in data
    assert 'summary' in data
    summary = data['summary']
    assert 'requested' in summary
    assert 'returned' in summary
    assert 'errors' in summary


# ── ok item detail has required sections ────────────────────────────────

def test_v12_batch_ok_item_has_sections():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    assert item['status'] == 'ok'
    detail = item['detail']
    for section in ('card', 'set', 'images', 'commercial', 'pricing', 'provider_status'):
        assert section in detail, f"Missing section: {section}"


# ── missing card returns item-level error ───────────────────────────────

def test_v12_batch_missing_card_item_error():
    r = _post_batch([MISSING_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    assert item['status'] == 'error'
    assert item['detail'] is None
    assert item['error'] is not None
    assert 'code' in item['error']
    assert 'message' in item['error']


# ── invalid card key returns item-level error ───────────────────────────

def test_v12_batch_invalid_card_key_item_error():
    r = _post_batch([INVALID_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    assert item['status'] == 'error'
    assert item['error'] is not None


# ── empty card_keys rejected ────────────────────────────────────────────

def test_v12_batch_empty_card_keys_rejected():
    r = _post_batch([])
    # Should be 422 (validation error) since min_length=1
    assert r.status_code == 422


# ── more than 50 card_keys rejected ─────────────────────────────────────

def test_v12_batch_over_50_rejected():
    keys = [f"en:fake-{i}" for i in range(51)]
    r = _post_batch(keys)
    # Should be 422 (validation error) since max_length=50
    assert r.status_code == 422


# ── duplicate card_keys handled predictably ──────────────────────────────

def test_v12_batch_duplicates_handled():
    """Duplicate card_keys should each produce their own item."""
    r = _post_batch([TEST_CARD_KEY, TEST_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 2
    # Both should be ok (or both error, but same status)
    assert items[0]['status'] == items[1]['status']
    assert items[0]['card_key'] == items[1]['card_key']


# ── include_pricing false sets pricing to null ──────────────────────────

def test_v12_batch_include_pricing_false():
    r = _post_batch([TEST_CARD_KEY], include_pricing=False)
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    if item['status'] == 'ok':
        assert item['detail']['pricing'] is None


# ── include_images false sets images to null ────────────────────────────

def test_v12_batch_include_images_false():
    r = _post_batch([TEST_CARD_KEY], include_images=False)
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    if item['status'] == 'ok':
        assert item['detail']['images'] is None


# ── include_commercial false sets commercial to null ────────────────────

def test_v12_batch_include_commercial_false():
    r = _post_batch([TEST_CARD_KEY], include_commercial=False)
    assert r.status_code == 200
    items = r.json()['data']['items']
    assert len(items) == 1
    item = items[0]
    if item['status'] == 'ok':
        assert item['detail']['commercial'] is None


# ── JustTCG not live and terms_confirmed false ──────────────────────────

def test_v12_batch_justtcg_not_live():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    item = items[0]
    if item['status'] == 'ok':
        ps = item['detail']['provider_status']
        justtcg = ps.get('justtcg', {})
        assert justtcg.get('status') == 'blocked_pending_terms'
        assert justtcg.get('live_enabled') is False
        assert justtcg.get('terms_confirmed') is False


# ── primary_price null when UK source unavailable ───────────────────────

def test_v12_batch_primary_price_null_no_uk():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    item = items[0]
    if item['status'] == 'ok':
        pricing = item['detail']['pricing']
        assert pricing['primary_price'] is None


# ── no raw filesystem paths leak ────────────────────────────────────────

def test_v12_batch_no_raw_paths():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    items = r.json()['data']['items']
    for item in items:
        if item['status'] == 'ok' and item['detail'].get('images'):
            images = item['detail']['images']
            for key in ('primary_image_url', 'signed_image_url', 'thumbnail_url'):
                val = images.get(key)
                if val is not None:
                    assert not val.startswith('/home/'), f"Raw path leaked in {key}: {val}"
                    assert not val.startswith('/media/'), f"Raw path leaked in {key}: {val}"
                    assert not val.startswith('file://'), f"Raw path leaked in {key}: {val}"


# ── no network calls in the batch endpoint function body ────────────────

def test_v12_batch_endpoint_no_network_calls():
    """Verify the batch endpoint function does not make network calls.

    We inspect the source to ensure it does not contain HTTP call patterns.
    """
    fastapi_path = Path(__file__).resolve().parent.parent / 'pokemon_db_v2_fastapi.py'
    source = fastapi_path.read_text()
    marker = 'def v12_app_ready_card_detail_batch('
    idx = source.find(marker)
    assert idx != -1, "v12_app_ready_card_detail_batch function not found"
    # Find the next function definition or decorator at same indent
    next_def = source.find('\n    def ', idx + len(marker))
    if next_def == -1:
        next_def = source.find('\n    @app.', idx + len(marker))
    func_body = source[idx:next_def] if next_def != -1 else source[idx:]
    for pattern in ('requests.get(', 'requests.post(', 'httpx.', 'urllib.request.urlopen', 'aiohttp'):
        assert pattern not in func_body, f"Network call pattern '{pattern}' found in batch endpoint"


# ── partial success: mix of ok and error items ──────────────────────────

def test_v12_batch_partial_success():
    r = _post_batch([TEST_CARD_KEY, MISSING_CARD_KEY])
    assert r.status_code == 200
    body = r.json()
    items = body['data']['items']
    assert len(items) == 2
    summary = body['data']['summary']
    assert summary['requested'] == 2
    assert summary['returned'] >= 1  # at least one ok
    assert summary['errors'] >= 1   # at least one error


# ── metadata has correct contract label ─────────────────────────────────

def test_v12_batch_metadata_contract():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    metadata = r.json().get('metadata', {})
    assert metadata.get('contract') == 'v12-app-ready-card-detail-batch'
    assert metadata.get('api_version') == 'v1'
    assert 'generated_at' in metadata
    assert metadata.get('max_batch_size') == 50


# ── warnings mention UK source not live ─────────────────────────────────

def test_v12_batch_warnings_uk_source():
    r = _post_batch([TEST_CARD_KEY])
    assert r.status_code == 200
    warnings = r.json().get('warnings', [])
    assert any('UK' in w and 'not yet live' in w for w in warnings), \
        f"Expected UK warning. Got: {warnings}"


# ── summary counts are consistent with items ────────────────────────────

def test_v12_batch_summary_counts_consistent():
    r = _post_batch([TEST_CARD_KEY, MISSING_CARD_KEY, INVALID_CARD_KEY])
    assert r.status_code == 200
    body = r.json()
    items = body['data']['items']
    summary = body['data']['summary']
    ok_count = sum(1 for i in items if i['status'] == 'ok')
    err_count = sum(1 for i in items if i['status'] == 'error')
    assert summary['requested'] == 3
    assert summary['returned'] == ok_count
    assert summary['errors'] == err_count


# ── all include flags false still returns 200 ───────────────────────────

def test_v12_batch_all_includes_false():
    r = _post_batch([TEST_CARD_KEY], include_pricing=False, include_commercial=False, include_images=False)
    assert r.status_code == 200
    items = r.json()['data']['items']
    item = items[0]
    if item['status'] == 'ok':
        assert item['detail']['pricing'] is None
        assert item['detail']['commercial'] is None
        assert item['detail']['images'] is None
