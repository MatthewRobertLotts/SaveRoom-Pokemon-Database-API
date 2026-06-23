"""Contract tests for the v1 API foundation.

Tests cover:
- /api/v1/health
- /api/v1/search/cards (pagination, filters, errors)
- /api/v1/cards/{card_key} (detail, images, prices, errors)
- /api/v1/sets, /api/v1/sets/{set_id}
- /api/v1/languages
- /api/v1/images/cards/{card_key}
- /api/v1/prices/cards/{card_key}
- /api/v1/prices/history/cards/{card_key}
- /api/v1/admin/keys (create, list, deactivate)
- /api/v1/admin/quota
- API key auth enforcement
- Legacy route compatibility
- No RapidAPI requests spent
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure auth is NOT required for v1 contract tests
os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)

from pokemon_db_v2_fastapi import create_app

# Use a known test card that has price evidence
TEST_CARD_KEY = "en:sv03-223"
TEST_LANG_CODE = "en"
TEST_CARD_ID = "sv03-223"
TEST_SET_ID = "sv03"


client = TestClient(create_app())


# ── /api/v1/health ───────────────────────────────────────────────────

def test_v1_health_envelope():
    r = client.get('/api/v1/health')
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {'data'}
    d = body['data']
    assert d['ok'] is True
    assert d['version'] == 'v1'
    assert d['service'] == 'saveroom-pokemon-api'
    assert d['counts']['support_ready'] is True
    assert isinstance(d['auth'], dict)


# ── /api/v1/search/cards ─────────────────────────────────────────────

def test_v1_search_basic():
    r = client.get('/api/v1/search/cards?q=charizard&limit=5')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['data'], list)
    assert 1 <= len(body['data']) <= 5
    assert body['pagination']['limit'] == 5
    assert body['pagination']['offset'] == 0
    assert body['pagination']['count'] == len(body['data'])
    assert body['pagination']['total'] >= len(body['data'])
    assert body['pagination']['has_more'] == (body['pagination']['offset'] + len(body['data']) < body['pagination']['total'])
    for card in body['data']:
        assert 'card_key' in card
        assert 'language' in card
        assert 'images' in card
        assert 'price' in card


def test_v1_search_language_filter():
    r = client.get('/api/v1/search/cards?q=charizard&language_code=en&limit=10')
    assert r.status_code == 200
    body = r.json()
    assert body['data']
    langs = {c['language']['code'] for c in body['data']}
    assert langs == {'en'}


def test_v1_search_no_query_returns_results():
    r = client.get('/api/v1/search/cards?limit=3')
    assert r.status_code == 200
    body = r.json()
    assert len(body['data']) == 3


def test_v1_search_pagination_offset():
    r1 = client.get('/api/v1/search/cards?q=pikachu&limit=3&offset=0')
    r2 = client.get('/api/v1/search/cards?q=pikachu&limit=3&offset=3')
    assert r1.status_code == 200
    assert r2.status_code == 200
    ids1 = {c['card_key'] for c in r1.json()['data']}
    ids2 = {c['card_key'] for c in r2.json()['data']}
    assert not ids1.intersection(ids2)


def test_v1_search_invalid_limit():
    r = client.get('/api/v1/search/cards?q=charizard&limit=201')
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'invalid_limit'


def test_v1_search_invalid_offset():
    # FastAPI ge=0 guard returns 422 for negative offset before our code runs
    r = client.get('/api/v1/search/cards?q=charizard&offset=-1')
    assert r.status_code in (400, 422)


def test_v1_search_unsupported_sort():
    r = client.get('/api/v1/search/cards?q=charizard&sort=price_desc')
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'unsupported_sort'


# ── /api/v1/cards/{card_key} ─────────────────────────────────────────

def test_v1_card_detail():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}')
    assert r.status_code == 200
    body = r.json()
    card = body['data']
    assert card['card_key'] == TEST_CARD_KEY
    assert card['language']['code'] == TEST_LANG_CODE
    assert card['card_id'] == TEST_CARD_ID
    assert card['name'] == 'Charizard ex'
    assert card['price']['currency'] == 'GBP'
    assert card['price']['evidence_count'] >= 0
    assert 'images' in card
    assert 'set' in card
    assert 'provenance' in card


def test_v1_card_detail_slash_alias():
    r = client.get(f'/api/v1/cards/en/sv03-223')
    assert r.status_code == 200
    assert r.json()['data']['card_key'] == 'en:sv03-223'


def test_v1_card_detail_not_found():
    r = client.get('/api/v1/cards/en:nonexistent-card-xyz')
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'card_not_found'


def test_v1_card_detail_invalid_key():
    r = client.get('/api/v1/cards/not-a-valid-key')
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'invalid_card_key'


def test_v1_card_detail_has_price_fields():
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}')
    assert r.status_code == 200
    price = r.json()['data']['price']
    assert 'evidence_count' in price
    assert 'recommended_raw_count' in price
    assert 'raw_median' in price
    assert 'graded_count' in price
    assert 'currency' in price


# ── /api/v1/sets ─────────────────────────────────────────────────────

def test_v1_sets_list():
    r = client.get('/api/v1/sets?limit=5')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['data'], list)
    assert 1 <= len(body['data']) <= 5
    assert body['pagination']['limit'] == 5
    assert body['pagination']['total'] >= len(body['data'])
    for s in body['data']:
        assert 'set_id' in s
        assert 'name' in s


def test_v1_sets_list_language_filter():
    r = client.get('/api/v1/sets?language_code=en&limit=5')
    assert r.status_code == 200
    for s in r.json()['data']:
        assert s['language_code'] == 'en'


def test_v1_sets_list_name_search():
    r = client.get('/api/v1/sets?q=obsidian&limit=5')
    assert r.status_code == 200
    assert r.json()['data']


def test_v1_sets_detail():
    r = client.get(f'/api/v1/sets/{TEST_SET_ID}')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    s = body['data']
    assert s['set_id'] == TEST_SET_ID


def test_v1_sets_detail_not_found():
    r = client.get('/api/v1/sets/nonexistent-set-xyz')
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'set_not_found'


# ── /api/v1/languages ────────────────────────────────────────────────

def test_v1_languages_list():
    r = client.get('/api/v1/languages')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['data'], list)
    assert len(body['data']) >= 10
    codes = {l['code'] for l in body['data']}
    assert 'en' in codes
    assert 'ja' in codes
    for lang in body['data']:
        assert 'code' in lang
        assert 'name' in lang


# ── /api/v1/images/cards/{card_key} ──────────────────────────────────

def test_v1_card_images():
    r = client.get(f'/api/v1/images/cards/{TEST_CARD_KEY}')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    assert body['card_key'] == TEST_CARD_KEY
    assert body['language_code'] == TEST_LANG_CODE
    assert body['card_id'] == TEST_CARD_ID
    img = body['data']
    assert 'has_exact_image' in img
    assert 'has_display_image' in img
    assert 'display_image_source_type' in img
    assert 'language_matches_card' in img


def test_v1_card_images_not_found():
    r = client.get('/api/v1/images/cards/en:nonexistent')
    assert r.status_code == 404


# ── /api/v1/prices/cards/{card_key} ──────────────────────────────────

def test_v1_card_price_summary():
    r = client.get(f'/api/v1/prices/cards/{TEST_CARD_KEY}')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    assert body['card_key'] == TEST_CARD_KEY
    price = body['data']
    assert price['currency'] == 'GBP'
    assert price['evidence_count'] > 0
    assert price['recommended_raw_count'] > 0


def test_v1_card_price_summary_not_found():
    r = client.get('/api/v1/prices/cards/en:nonexistent')
    assert r.status_code == 404


def test_v1_card_price_history():
    r = client.get(f'/api/v1/prices/history/cards/{TEST_CARD_KEY}?limit=5')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['data'], list)
    assert body['pagination']['limit'] == 5
    assert body['card_key'] == TEST_CARD_KEY
    if body['data']:
        row = body['data'][0]
        assert 'id' in row
        assert 'price_gbp' in row
        assert 'bucket' in row


def test_v1_card_price_history_bucket_filter():
    r = client.get(f'/api/v1/prices/history/cards/{TEST_CARD_KEY}?bucket=raw&limit=5')
    assert r.status_code == 200
    for row in r.json()['data']:
        assert row['bucket'] == 'raw'


def test_v1_card_price_history_not_found():
    r = client.get('/api/v1/prices/history/cards/en:nonexistent')
    assert r.status_code == 404


# ── /api/v1/admin/keys ───────────────────────────────────────────────

def test_v1_admin_create_key():
    r = client.post('/api/v1/admin/keys', json={'label': 'test-key', 'scopes': ['cards:read', 'admin']})
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    key_data = body['data']
    assert 'key' in key_data
    assert key_data['label'] == 'test-key'
    assert key_data['is_active'] is True
    assert 'id' in key_data
    # Store for later tests
    test_v1_admin_create_key.key_id = key_data['id']
    test_v1_admin_create_key.raw_key = key_data['key']


def test_v1_admin_list_keys():
    # Ensure at least one key exists
    client.post('/api/v1/admin/keys', json={'label': 'list-test', 'scopes': ['admin']})
    r = client.get('/api/v1/admin/keys')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['data'], list)
    assert len(body['data']) >= 1
    for k in body['data']:
        assert 'id' in k
        assert 'key_hash' not in k
        assert 'key' not in k
        assert 'scopes' in k
        assert 'is_active' in k


def test_v1_admin_deactivate_key():
    # Create a key first
    r = client.post('/api/v1/admin/keys', json={'label': 'deactivate-me', 'scopes': ['admin']})
    key_id = r.json()['data']['id']
    # Deactivate
    r = client.post(f'/api/v1/admin/keys/{key_id}/deactivate')
    assert r.status_code == 200
    assert r.json()['data']['is_active'] is False
    # Verify it's inactive
    r = client.get('/api/v1/admin/keys')
    keys = {k['id']: k for k in r.json()['data']}
    assert keys[key_id]['is_active'] is False


def test_v1_admin_deactivate_nonexistent_key():
    r = client.post('/api/v1/admin/keys/99999/deactivate')
    assert r.status_code == 404


# ── /api/v1/admin/quota ──────────────────────────────────────────────

def test_v1_admin_quota_status():
    # Create a key with quota
    r = client.post('/api/v1/admin/keys', json={'label': 'quota-test', 'scopes': ['admin'], 'monthly_quota': 100})
    key_id = r.json()['data']['id']
    r = client.get(f'/api/v1/admin/quota?key_id={key_id}')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    q = body['data']
    assert q['api_key_id'] == key_id
    assert q['monthly_quota'] == 100
    assert 'used_this_month' in q
    assert 'remaining' in q
    assert 'window_start' in q
    assert 'window_end' in q


def test_v1_admin_quota_nonexistent_key():
    r = client.get('/api/v1/admin/quota?key_id=99999')
    assert r.status_code == 404


# ── API key auth enforcement ─────────────────────────────────────────

def test_v1_no_key_required_by_default():
    """Without POKEMON_DB_REQUIRE_API_KEY, all v1 routes work without a key."""
    r = client.get('/api/v1/health')
    assert r.status_code == 200


# ── Legacy route compatibility ───────────────────────────────────────

def test_legacy_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['ok'] is True


def test_legacy_search():
    r = client.get('/search?q=charizard&limit=1')
    assert r.status_code == 200
    assert r.json()['count'] == 1


def test_legacy_card_detail():
    r = client.get(f'/cards/{TEST_LANG_CODE}/{TEST_CARD_ID}')
    assert r.status_code == 200


def test_legacy_coverage():
    r = client.get('/reports/coverage')
    assert r.status_code == 200
    assert r.json()['total_rows'] > 0


# ── DB migration table exists ────────────────────────────────────────

def test_schema_migrations_table():
    db_path = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='name' AND name='schema_migrations'")
    # Just verify the table exists (it's created at app startup via TestClient)
    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    count = cur.fetchone()[0]
    assert count == 1
    conn.close()


# ── No RapidAPI requests spent ───────────────────────────────────────

def test_no_rapidapi_spend():
    """Verify that running v1 endpoints does not increase RapidAPI usage."""
    db_path = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status='ok'")
    count_before = cur.fetchone()[0]
    # Hit several v1 endpoints
    client.get('/api/v1/health')
    client.get('/api/v1/search/cards?q=pikachu&limit=5')
    client.get(f'/api/v1/cards/{TEST_CARD_KEY}')
    client.get(f'/api/v1/prices/cards/{TEST_CARD_KEY}')
    client.get(f'/api/v1/prices/history/cards/{TEST_CARD_KEY}?limit=5')
    cur.execute("SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status='ok'")
    count_after = cur.fetchone()[0]
    conn.close()
    assert count_after == count_before, f"RapidAPI usage changed: {count_before} -> {count_after}"


# ── Translation layer tests ─────────────────────────────────────────

def test_v1_card_detail_has_name_english():
    """Non-English cards should include name_english field."""
    r = client.get(f'/api/v1/cards/{TEST_CARD_KEY}')
    assert r.status_code == 200
    card = r.json()['data']
    assert 'name_english' in card
    # English card: name_english should equal name
    assert card['name_english'] == card['name']


def test_v1_card_detail_non_english_has_translation():
    """A German card should have an English name translation."""
    # Charizard ex in German
    r = client.get('/api/v1/cards/de/sv03-223')
    assert r.status_code == 200
    card = r.json()['data']
    assert card['name'] == 'Glurak-ex'
    assert card['name_english'] == 'Charizard ex'


def test_v1_card_detail_japanese_has_translation():
    """A Japanese card with known Pokémon name should have English translation."""
    # Pikachu in Japanese (if available)
    r = client.get('/api/v1/cards/ja/base1-58')
    if r.status_code == 200:
        card = r.json()['data']
        assert 'name_english' in card


def test_v1_search_results_include_name_english():
    """Search results should include name_english for non-English cards."""
    r = client.get('/api/v1/search/cards?q=charizard&language_code=de&limit=3')
    assert r.status_code == 200
    body = r.json()
    for card in body['data']:
        assert 'name_english' in card


def test_v1_i18n_coverage_endpoint():
    """Translation coverage endpoint should return stats by language."""
    r = client.get('/api/v1/i18n/coverage')
    assert r.status_code == 200
    body = r.json()
    assert 'data' in body
    data = body['data']
    assert 'by_language' in data
    assert 'total_untranslated' in data
    # European languages should be 100%
    for lang_info in data['by_language']:
        if lang_info['language_code'] in ('fr', 'de', 'it', 'es', 'pt'):
            assert lang_info['coverage_pct'] == 100.0, \
                f"{lang_info['language_code']} coverage is {lang_info['coverage_pct']}%, expected 100%"
    # Total coverage should be > 90%
    total = sum(l['total'] for l in data['by_language'])
    translated = sum(l['translated'] for l in data['by_language'])
    assert translated / total > 0.90, f"Overall coverage {translated/total:.1%} is below 90%"


def test_translation_table_exists():
    """card_name_translations table should exist and have entries."""
    db_path = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='card_name_translations'")
    assert cur.fetchone() is not None, "card_name_translations table does not exist"
    cur.execute("SELECT COUNT(*) FROM card_name_translations")
    count = cur.fetchone()[0]
    assert count > 200000, f"Expected >200K translations, got {count}"
    conn.close()


# ── Cross-language search tests ──────────────────────────────────────

def test_search_finds_non_english_cards_by_english_name():
    """Searching 'charizard' should find non-English cards via name_english."""
    r = client.get('/api/v1/search/cards?q=charizard&limit=50')
    assert r.status_code == 200
    body = r.json()
    cards = body['data']
    assert len(cards) > 0, "Should find Charizard cards"
    # Should find cards in multiple languages (cross-language search works)
    langs = {c['language']['code'] for c in cards}
    assert len(langs) > 1, f"Should find cards in multiple languages, got: {langs}"
    # Check that non-English cards have name_english populated
    non_en_cards = [c for c in cards if c['language']['code'] != 'en']
    assert len(non_en_cards) > 0, "Should find non-English Charizard cards"
    for card in non_en_cards:
        assert card.get('name_english') is not None, \
            f"Non-English card ({card['language']['code']}) should have name_english"
        assert 'Charizard' in card['name_english'], \
            f"name_english should contain 'Charizard', got {card['name_english']!r}"


def test_search_finds_japanese_cards_by_english_name():
    """Searching 'Pikachu' should find Japanese ピカチュウ cards."""
    r = client.get('/api/v1/search/cards?q=pikachu&limit=20')
    assert r.status_code == 200
    body = r.json()
    cards = body['data']
    assert len(cards) > 0, "Should find Pikachu cards"
    # Check that Japanese cards are included
    ja_cards = [c for c in cards if c['language']['code'] == 'ja']
    if ja_cards:
        for card in ja_cards:
            assert card.get('name_english') is not None, \
                f"Japanese card should have name_english, got {card.get('name_english')!r}"


def test_search_finds_german_cards_by_english_name():
    """Searching 'Glurak' should find German cards (local name)."""
    r = client.get('/api/v1/search/cards?q=glurak&limit=10')
    assert r.status_code == 200
    body = r.json()
    cards = body['data']
    assert len(cards) > 0, "Should find Glurak cards"
    # Should find German cards
    de_cards = [c for c in cards if c['language']['code'] == 'de']
    assert len(de_cards) > 0, "Should find German Glurak cards"


def test_price_query_uses_english_name():
    """build_price_query should use English name for eBay searches."""
    from pokemon_db_v2_fastapi import build_price_query
    # German card - should use English name, clean query
    card_de = {
        'name': 'Glurak-ex', 'name_english': 'Charizard ex',
        'card_id': 'sv03-223', 'language_code': 'de',
        'collector_number': '223', 'core_set_id': 'sv03',
        'core_set_name': 'Obsidian Flames', 'rarity': 'Double rare',
        'types': 'Fire', 'category': 'Pokemon', 'stage': 'Stage2',
    }
    query_de = build_price_query(card_de)
    assert 'Charizard ex' in query_de, f"Price query should use English name, got: {query_de}"
    assert 'German' not in query_de, f"Price query should NOT include language hint, got: {query_de}"
    assert 'Pokémon card' not in query_de, f"Price query should not have suffix, got: {query_de}"
    assert 'Fire' not in query_de, f"Price query should not include type keywords, got: {query_de}"
    assert 'sv03-223' in query_de.lower() or 'sv03' in query_de.lower(), f"Query should include set code and number combo: {query_de}"

    # Japanese card - same English query
    card_ja = {
        'name': 'リザードンex', 'name_english': 'Charizard ex',
        'card_id': 'sv03-223', 'language_code': 'ja',
        'collector_number': '223', 'core_set_id': 'sv03',
        'core_set_name': 'Obsidian Flames', 'rarity': 'Double rare',
        'types': 'Fire', 'category': 'Pokemon', 'stage': 'Stage2',
    }
    query_ja = build_price_query(card_ja)
    assert 'Charizard ex' in query_ja, f"Price query should use English name, got: {query_ja}"
    assert 'Japanese' not in query_ja, f"Price query should NOT include language hint, got: {query_ja}"
    # German and Japanese cards should produce the same query
    assert query_de == query_ja, f"Non-English cards should produce same English query: {query_de} vs {query_ja}"

    # English card
    card_en = {
        'name': 'Charizard ex', 'name_english': 'Charizard ex',
        'card_id': 'sv03-223', 'language_code': 'en',
        'collector_number': '223', 'core_set_id': 'sv03',
        'core_set_name': 'Obsidian Flames', 'rarity': 'Double rare',
        'types': 'Fire', 'category': 'Pokemon', 'stage': 'Stage2',
    }
    query_en = build_price_query(card_en)
    assert 'Charizard ex' in query_en
    # All three should produce the same query
    assert query_en == query_de, f"English and non-English should produce same query: {query_en} vs {query_de}"


def test_price_query_db_lookup():
    """build_price_query should look up English name from DB when missing from card dict."""
    from pokemon_db_v2_fastapi import build_price_query
    import sqlite3
    from pathlib import Path
    db_path = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
    conn = sqlite3.connect(db_path)

    # S12a-212 is Japanese "リザードンVSTAR" with English name "Charizard" in translations
    card = {
        'card_id': 'S12a-212',
        'language_code': 'ja',
        'name': 'リザードンVSTAR',
        'card_name': 'リザードンVSTAR',
        'collector_number': '212',
        'local_id': '212',
        'core_set_id': 'S12a',
        'core_set_name': 'VSTAR Semesta',
        'rarity': '',
        'types': 'Fire',
    }
    # Without conn — uses card name directly (Japanese)
    query_no_conn = build_price_query(card)
    assert 'リザードン' in query_no_conn, f"Without conn should fall back to card name: {query_no_conn}"
    assert 'Charizard' not in query_no_conn, f"Without conn should NOT find English name: {query_no_conn}"

    # With conn — looks up English name from translation table
    query_with_conn = build_price_query(card, conn)
    assert 'Charizard' in query_with_conn, f"With conn should use English name: {query_with_conn}"
    assert 'リザードン' not in query_with_conn, f"With conn should NOT use Japanese: {query_with_conn}"
    assert 'S12a' in query_with_conn, f"Query should include set code: {query_with_conn}"
    assert 'Fire' not in query_with_conn, f"Price query should not include type keywords: {query_with_conn}"

    conn.close()


def test_v1_card_detail_includes_price_query():
    """Card detail response should include price_query field."""
    r = client.get('/api/v1/cards/ja/S10b-011')
    assert r.status_code == 200
    data = r.json()
    assert 'data' in data
    assert 'price_query' in data['data'], f"Card detail should include price_query field: {list(data['data'].keys())}"
    query = data['data']['price_query']
    assert 'Radiant Charizard' in query, f"Price query should include English name: {query}"
    assert 'S10b' in query or 's10b' in query, f"Price query should include set code: {query}"
    assert 'Pokémon card' not in query, f"Price query should not have suffix: {query}"

    # Japanese card with Japanese name should still get English query
    r = client.get('/api/v1/cards/ja/S12a-212')
    assert r.status_code == 200
    data = r.json()
    assert 'price_query' in data['data']
    query = data['data']['price_query']
    assert 'Charizard' in query, f"Japanese card should get English name in query: {query}"
    assert 'リザードン' not in query, f"Japanese card should NOT have Japanese name in query: {query}"


def test_price_query_strips_template_rarity():
    """build_price_query should strip {{TCG ID|...}} template syntax from rarity."""
    from pokemon_db_v2_fastapi import build_price_query
    card = {
        'card_id': 'S10b-011',
        'language_code': 'ja',
        'name': 'Radiant Charizard',
        'name_english': 'Radiant Charizard',
        'collector_number': '011',
        'core_set_id': 'S10b',
        'core_set_name': 'Pokémon GO',
        'rarity': '{{TCG ID|Pokémon GO|Radiant Charizard|11',
        'types': '',
    }
    query = build_price_query(card)
    assert '{{' not in query, f"Query should not have template syntax: {query}"
    assert 'Pokémon GO' not in query, f"Query should not have set name with special chars: {query}"
    assert 'Radiant Charizard' in query, f"Query should include English name: {query}"
    assert 'S10b' in query, f"Query should include set code: {query}"
    assert '011' in query, f"Query should include collector number: {query}"
