#!/usr/bin/env python3
"""Signed URL end-to-end test."""
import hashlib, io, json, os, sqlite3, time, uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

SECRET = "test-signed-url-secret-32bytes!!"
READER = "signed-url-test-reader"


@pytest.fixture(scope='module')
def app_setup():
    import os as _os
    _os.environ['POKEMON_DB_REQUIRE_API_KEY'] = '1'
    _os.environ['POKEMON_DB_SIGNED_URL_SECRET'] = SECRET
    from pokemon_db_v2_fastapi import create_app
    app = create_app()
    db = str(app.state.db)
    c = sqlite3.connect(db, timeout=30)
    kh = hashlib.sha256(READER.encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO developer_api_keys(key_hash,label,scopes,is_active) VALUES (?,?,?,1)",
              (kh, 'su-key', json.dumps(['images:read','cards:read'])))
    c.execute("UPDATE developer_api_keys SET membership_id=(SELECT membership_id FROM tenant_memberships WHERE tenant_id=1 LIMIT 1) WHERE label='su-key'")
    c.execute("INSERT OR REPLACE INTO v2_card_detail_api_cache(language_code,card_id,local_display_image_url,resolved_set_id,display_image_source_type,has_display_image) VALUES ('en','signed-test-1','test-signed-url-card.webp','base1','tcgplayer',1)")
    c.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
    c.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='source' AND scope_value='tcgplayer'")
    c.execute("INSERT OR IGNORE INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason, created_at, updated_at) VALUES ('source','tcgplayer',1,'test',datetime('now'),datetime('now'))")
    c.commit(); c.close()
    client = TestClient(app)
    yield app, client
    # Teardown: close all connections to release WAL locks
    try:
        import pokemon_db_v2_search_api
        if hasattr(pokemon_db_v2_search_api, 'close_all'):
            pokemon_db_v2_search_api.close_all()
    except Exception:
        pass


H = {'X-API-Key': READER}


def _token(image_id=0, size='medium', exp=3600):
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(image_id, size, SECRET, expires_in=exp)
    return t


def _req(client, token, size='medium', card_key=None):
    url = f'/api/v1/images/assets/0/content?size={size}&token={token}'
    if card_key:
        url += f'&card_key={card_key}'
    return client.get(url, headers=H)


def test_valid_signed_url(app_setup):
    _, c = app_setup
    r = _req(c, _token(), card_key='en:signed-test-1')
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    assert r.headers['content-type'] == 'image/webp'


def test_tampered_image_id(app_setup):
    _, c = app_setup
    p = _token().split(':'); p[2] = '99'
    assert _req(c, ':'.join(p)).status_code == 403


def test_tampered_sig(app_setup):
    _, c = app_setup
    p = _token().split(':'); p[1] = 'deadbeefdeadbeef'
    assert _req(c, ':'.join(p)).status_code == 403


def test_tampered_expiry(app_setup):
    _, c = app_setup
    p = _token().split(':'); p[0] = str(int(time.time()) + 99999)
    assert _req(c, ':'.join(p)).status_code == 403


def test_expired(app_setup):
    _, c = app_setup
    t = _token(exp=1); time.sleep(2)
    assert _req(c, t).status_code == 403


def test_policy_block(app_setup):
    _, c = app_setup
    t = _token()
    _req(c, t, card_key='en:signed-test-1')  # ensure image found
    conn = sqlite3.connect(str(c.app.state.db), timeout=10)
    conn.execute("INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason,created_at,updated_at) VALUES ('card','en:signed-test-1',0,'test',datetime('now'),datetime('now'))")
    conn.commit(); conn.close()
    assert _req(c, t, card_key='en:signed-test-1').status_code == 403
    conn = sqlite3.connect(str(c.app.state.db), timeout=10)
    conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='card' AND scope_value='en:signed-test-1'")
    conn.commit(); conn.close()


def test_delivery_log(app_setup):
    _, c = app_setup
    conn = sqlite3.connect(str(c.app.state.db), timeout=10)
    b = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]; conn.close()
    _req(c, _token(), card_key='en:signed-test-1')
    conn = sqlite3.connect(str(c.app.state.db), timeout=10)
    a = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]; conn.close()
    assert a > b


def test_hmac_compare_digest(app_setup):
    from pokemon_db_v2_fastapi import _verify_signed_url
    t = _token()
    r = _verify_signed_url(t, SECRET)
    assert r is not None and r['image_id'] == 0
    assert _verify_signed_url("999:deadbeef:0:medium", SECRET) is None


def test_token_format():
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, exp = _generate_signed_url(0, 'medium', SECRET, expires_in=3600)
    p = t.split(':')
    assert len(p) == 4
    assert int(p[0]) > 0
    assert len(p[1]) == 16
    assert p[2] == '0'; assert p[3] == 'medium'
