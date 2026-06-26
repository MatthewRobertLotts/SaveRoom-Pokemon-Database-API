#!/usr/bin/env python3
"""Gateway integration tests with isolated fixture - byte-safe write."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from test_gateway_fixture import gw as _gw_fixture
from PIL import Image

H = {'X-API-Key': 'test-reader-key'}


def _assert_image_response(actual: bytes, expected_size: tuple[int, int]) -> None:
    """Validate that the response is a valid WebP image.

    The derivative pipeline preserves aspect ratio, so the output height
    may be smaller than the target. We verify the width matches exactly
    and height is within tolerance.
    """
    img = Image.open(io.BytesIO(actual))
    img.verify()
    img = Image.open(io.BytesIO(actual))
    assert img.format == 'WEBP', f'Expected WEBP, got {img.format}'
    w, h = img.size
    assert w == expected_size[0], f'Width mismatch: got {w}, expected {expected_size[0]}'
    assert abs(h - expected_size[1]) <= 30, f'Height mismatch: got {h}, expected {expected_size[1]}'


def _secret(fd):
    """Return the gateway fixture's signed URL secret."""
    return fd["secret"]


def test_fixture_creates_real_ids(_gw_fixture):
    client, fd = _gw_fixture
    assert fd['img_a_id'] > 0
    assert fd['img_b_id'] > 0
    assert fd['img_a_id'] != fd['img_b_id']
    assert len(fd['img_a_bytes']) > 0


def test_image_a_api_key_200(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert resp.status_code == 200, f'Got {resp.status_code}: {resp.text[:200]}'
    assert resp.headers['content-type'] == 'image/webp'
    _assert_image_response(resp.content, (350, 489))


def test_image_b_api_key_200(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_b_id']}/content?size=medium",
        headers=H,
    )
    assert resp.status_code == 200
    _assert_image_response(resp.content, (350, 489))


def test_image_id_zero_404(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get('/api/v1/images/assets/0/content?size=medium', headers=H)
    assert resp.status_code == 404


def test_image_id_negative_404(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get('/api/v1/images/assets/-1/content?size=medium', headers=H)
    assert resp.status_code == 404


def test_unknown_image_id_404(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get('/api/v1/images/assets/99999/content?size=medium', headers=H)
    assert resp.status_code == 404


def test_signed_url_image_a_200_no_api_key(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium&token={t}",
    )
    assert resp.status_code == 200, f'Got {resp.status_code}: {resp.text[:200]}'
    _assert_image_response(resp.content, (350, 489))


def test_token_image_a_for_b_403(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_b_id']}/content?size=medium&token={t}",
    )
    assert resp.status_code == 403


def test_tampered_sig_403(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    p = t.split(':')
    p[1] = 'deadbeef' * 8
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium&token={':'.join(p)}",
    )
    assert resp.status_code == 403


def test_tampered_image_id_403(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    p = t.split(':')
    p[2] = str(fd['img_b_id'])
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium&token={':'.join(p)}",
    )
    assert resp.status_code == 403


def test_tampered_expiry_403(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    import time as _t
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    p = t.split(':')
    p[0] = str(int(_t.time()) + 999999)
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium&token={':'.join(p)}",
    )
    assert resp.status_code == 403


def test_expired_token_403(_gw_fixture):
    client, fd = _gw_fixture
    from pokemon_db_v2_fastapi import _generate_signed_url
    import time as _t
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd), expires_in=1)
    _t.sleep(2)
    resp = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium&token={t}",
    )
    assert resp.status_code == 403


def test_global_disable_blocks(_gw_fixture):
    client, fd = _gw_fixture
    r1 = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert r1.status_code == 200

    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='global' AND scope_value='global'")
    conn.commit()
    conn.close()

    r2 = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert r2.status_code == 403

    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
    conn.commit()
    conn.close()

    r3 = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert r3.status_code == 200


def test_image_level_disable_blocks(_gw_fixture):
    client, fd = _gw_fixture
    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason,created_at,updated_at) VALUES ('image',?,0,'test',datetime('now'),datetime('now'))",
        (str(fd['img_a_id']),)
    )
    conn.commit()
    conn.close()

    r = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert r.status_code == 403

    # Image B still works
    r2 = client.get(
        f"/api/v1/images/assets/{fd['img_b_id']}/content?size=medium",
        headers=H,
    )
    assert r2.status_code == 200

    # Restore
    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    conn.execute("DELETE FROM image_delivery_policies WHERE scope_type='image' AND scope_value=?", (str(fd['img_a_id']),))
    conn.commit()
    conn.close()


def test_delivery_log_records_real_image_id(_gw_fixture):
    client, fd = _gw_fixture
    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    conn.close()

    r = client.get(
        f"/api/v1/images/assets/{fd['img_a_id']}/content?size=medium",
        headers=H,
    )
    assert r.status_code == 200

    conn = sqlite3.connect(str(fd['db_path']), timeout=10)
    after = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    rec = conn.execute(
        "SELECT image_id, card_key, response_status, response_outcome FROM image_delivery_policy_records ORDER BY record_id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert after > before
    assert rec[0] == fd['img_a_id']
    assert rec[2] == 200
    assert 'ok' in rec[3]


def test_token_format_5_parts(_gw_fixture):
    from pokemon_db_v2_fastapi import _generate_signed_url
    client, fd = _gw_fixture
    t, _ = _generate_signed_url(fd['img_a_id'], 'medium', _secret(fd))
    p = t.split(':')
    assert len(p) == 5
    assert int(p[0]) > 0
    assert len(p[1]) == 64  # full SHA-256
    assert int(p[2]) == fd['img_a_id']
    assert p[3] == 'medium'


def test_signing_rejects_nonexistent_image(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.post(
        '/api/v1/images/assets/signed-url?image_id=99999&size=medium',
        headers=H,
    )
    assert resp.status_code == 404


def test_card_compatibility_route(_gw_fixture):
    client, fd = _gw_fixture
    resp = client.get(
        '/api/v1/images/card/en:card-a/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 200
    _assert_image_response(resp.content, (350, 489))