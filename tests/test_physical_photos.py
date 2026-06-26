#!/usr/bin/env python3
r"""Physical item photo integration tests — single TestClient."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pokemon_db_v2_fastapi import create_app
from test_gateway_fixture import _get_settings, _seed_database

os.environ['POKEMON_DB_REQUIRE_API_KEY'] = '1'
_TEMP_DIR = tempfile.TemporaryDirectory(prefix='physical_photos_')
_BASE_DIR = Path(_TEMP_DIR.name)
_DB_PATH = _BASE_DIR / 'test.db'
_IMAGE_ROOT = _BASE_DIR / 'images'
_IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
_seed_database(_DB_PATH, _IMAGE_ROOT)
client = TestClient(create_app(_get_settings(_DB_PATH, _IMAGE_ROOT)))

ADMIN_A = 'uniq-phy-admin-a-X'
READER_A = 'uniq-phy-reader-a-Y'
ADMIN_B = 'uniq-phy-admin-b-Z'
READER_B = 'uniq-phy-reader-b-W'


def teardown_module():
    client.close()
    _TEMP_DIR.cleanup()


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(client.app.state.db), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _ensure_photo_inventory_schema() -> None:
    """Create the minimal v9 inventory/photo tables used by these tests.

    The gateway fixture intentionally seeds image-gateway tables only. These
    tests add the inventory subset locally so they never write to the real
    development database during test collection.
    """
    with closing(_db_connect()) as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sellable_skus("
            "sku_id INTEGER PRIMARY KEY, printing_id INTEGER, language_code TEXT, "
            "condition_code TEXT, sku_key TEXT UNIQUE)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS physical_items("
            "item_id TEXT PRIMARY KEY, sku_id INTEGER, tenant_id INTEGER DEFAULT 1, "
            "status TEXT DEFAULT 'owned', created_at TEXT, updated_at TEXT, "
            "revision INTEGER DEFAULT 0)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS physical_item_photos("
            "photo_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, "
            "tenant_id INTEGER NOT NULL, uploaded_by INTEGER, original_filename TEXT, "
            "storage_path TEXT NOT NULL, mime_type TEXT NOT NULL, file_bytes INTEGER, "
            "is_published INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()


def _provision():
    with closing(_db_connect()) as conn:
        cur = conn.cursor()

        cur.execute("INSERT OR IGNORE INTO tenants(tenant_id, tenant_name, tenant_slug) VALUES (2, 'Tenant B', 'tenant-b')")
        cur.execute("INSERT OR IGNORE INTO tenant_memberships(tenant_id, user_id, role) VALUES (2, 999, 'admin')")

        for raw, label, scopes, tid in [
            (ADMIN_A,  'uphy-aa', ['admin:all'], 1),
            (READER_A, 'uphy-ra', ['read:inventory', 'cards:read'], 1),
            (ADMIN_B,  'uphy-ab', ['admin:all', 'write:inventory'], 2),
            (READER_B, 'uphy-rb', ['read:inventory', 'cards:read'], 2),
        ]:
            kh = hashlib.sha256(raw.encode()).hexdigest()
            scopes_json = json.dumps(scopes)
            cur.execute(
                "INSERT OR IGNORE INTO developer_api_keys(key_hash, label, scopes, is_active) "
                "VALUES (?, ?, ?, 1)",
                (kh, label, scopes_json),
            )
            cur.execute(
                "UPDATE developer_api_keys SET label=?, scopes=?, is_active=1, membership_id="
                "(SELECT membership_id FROM tenant_memberships WHERE tenant_id=? AND role='admin' LIMIT 1) "
                "WHERE key_hash=?",
                (label, scopes_json, tid, kh),
            )

        conn.commit()


_ensure_photo_inventory_schema()
_provision()


def _item(tenant_id: int = 1) -> str:
    iid = str(uuid.uuid4())
    with closing(_db_connect()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT sku_id FROM sellable_skus LIMIT 1")
        row = cur.fetchone()
        sku = row[0] if row else 99999
        if not row:
            cur.execute("INSERT OR IGNORE INTO sellable_skus(sku_id, printing_id, language_code, condition_code, sku_key) VALUES (99999, 1, 'en', 'NM', 'test-sku')")
        cur.execute("INSERT INTO physical_items(item_id, sku_id, tenant_id, status, created_at) VALUES (?, ?, ?, 'owned', datetime('now'))",
                    (iid, sku, tenant_id))
        conn.commit()
    return iid


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (100, 100), color='red').save(buf, format='JPEG')
    return buf.getvalue()


# ── Upload tests ──


def test_upload_jpeg():
    _provision()
    iid = _item(1)
    data = _jpeg()
    resp = client.post(f'/api/v1/inventory/items/{iid}/photos',
                       files={'file': ('t.jpg', io.BytesIO(data), 'image/jpeg')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text}"
    b = resp.json()['data']
    assert b['mime_type'] == 'image/jpeg'
    assert b['file_bytes'] == len(data)
    assert 'storage_path' not in b


def test_upload_png():
    _provision()
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (100, 100), color='blue').save(buf, format='PNG')
    resp = client.post(f'/api/v1/inventory/items/{_item(1)}/photos',
                       files={'file': ('t.png', io.BytesIO(buf.getvalue()), 'image/png')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 200
    assert resp.json()['data']['mime_type'] == 'image/png'


def test_upload_webp():
    _provision()
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (100, 100), color='green').save(buf, format='WEBP')
    resp = client.post(f'/api/v1/inventory/items/{_item(1)}/photos',
                       files={'file': ('t.webp', io.BytesIO(buf.getvalue()), 'image/webp')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 200
    assert resp.json()['data']['mime_type'] == 'image/webp'


def test_upload_invalid_mime():
    _provision()
    resp = client.post(f'/api/v1/inventory/items/{_item(1)}/photos',
                       files={'file': ('t.txt', io.BytesIO(b'nope'), 'text/plain')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 400


def test_upload_malformed():
    _provision()
    resp = client.post(f'/api/v1/inventory/items/{_item(1)}/photos',
                       files={'file': ('t.jpg', io.BytesIO(b'not an image'), 'image/jpeg')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 400


def test_upload_oversized():
    _provision()
    class _Fk:
        def __init__(self):
            self._sent = False

        def read(self, size=-1):
            if self._sent:
                return b''
            self._sent = True
            return b'x' * (11 * 1024 * 1024)
    resp = client.post(f'/api/v1/inventory/items/{_item(1)}/photos',
                       files={'file': ('t.jpg', _Fk(), 'image/jpeg')},
                       headers={'X-API-Key': ADMIN_A})
    assert resp.status_code == 400


def test_list_photos():
    _provision()
    iid = _item(1)
    client.post(f'/api/v1/inventory/items/{iid}/photos',
                files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                headers={'X-API-Key': ADMIN_A})
    resp = client.get(f'/api/v1/inventory/items/{iid}/photos', headers={'X-API-Key': READER_A})
    assert resp.status_code == 200
    assert len(resp.json()['data']) >= 1


def test_retrieve_binary():
    _provision()
    iid = _item(1)
    ur = client.post(f'/api/v1/inventory/items/{iid}/photos',
                     files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                     headers={'X-API-Key': ADMIN_A})
    pid = ur.json()['data']['photo_id']
    resp = client.get(f'/api/v1/inventory/items/{iid}/photos/{pid}', headers={'X-API-Key': READER_A})
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'


def test_delete_photo():
    _provision()
    iid = _item(1)
    ur = client.post(f'/api/v1/inventory/items/{iid}/photos',
                     files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                     headers={'X-API-Key': ADMIN_A})
    pid = ur.json()['data']['photo_id']
    dr = client.delete(f'/api/v1/inventory/items/{iid}/photos/{pid}', headers={'X-API-Key': ADMIN_A})
    assert dr.status_code == 200
    gr = client.get(f'/api/v1/inventory/items/{iid}/photos/{pid}', headers={'X-API-Key': READER_A})
    assert gr.status_code == 404


# ── Cross-tenant tests ──


def test_cross_tenant_cannot_upload():
    _provision()
    iid = _item(1)  # tenant A item
    resp = client.post(f'/api/v1/inventory/items/{iid}/photos',
                       files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                       headers={'X-API-Key': ADMIN_B})
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


def test_cross_tenant_list_empty():
    _provision()
    iid = _item(1)  # tenant A item
    client.post(f'/api/v1/inventory/items/{iid}/photos',
                files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                headers={'X-API-Key': ADMIN_A})
    resp = client.get(f'/api/v1/inventory/items/{iid}/photos', headers={'X-API-Key': READER_B})
    assert resp.status_code == 200
    assert resp.json()['data'] == []


def test_cross_tenant_retrieve_404():
    _provision()
    iid = _item(1)  # tenant A item
    ur = client.post(f'/api/v1/inventory/items/{iid}/photos',
                     files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                     headers={'X-API-Key': ADMIN_A})
    pid = ur.json()['data']['photo_id']
    resp = client.get(f'/api/v1/inventory/items/{iid}/photos/{pid}', headers={'X-API-Key': READER_B})
    assert resp.status_code == 404


def test_cross_tenant_delete_404():
    _provision()
    iid = _item(1)  # tenant A item
    ur = client.post(f'/api/v1/inventory/items/{iid}/photos',
                     files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                     headers={'X-API-Key': ADMIN_A})
    pid = ur.json()['data']['photo_id']
    # Use admin_b (has write:inventory but is tenant 2) — should get 404 (item not found for tenant 2)
    resp = client.delete(f'/api/v1/inventory/items/{iid}/photos/{pid}', headers={'X-API-Key': ADMIN_B})
    assert resp.status_code == 404


def test_tenant_b_own_upload_and_list():
    _provision()
    iid = _item(2)  # tenant B item
    ur = client.post(f'/api/v1/inventory/items/{iid}/photos',
                     files={'file': ('t.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
                     headers={'X-API-Key': ADMIN_B})
    assert ur.status_code == 200, f"Upload: {ur.text}"
    lr = client.get(f'/api/v1/inventory/items/{iid}/photos', headers={'X-API-Key': READER_B})
    assert lr.status_code == 200 and len(lr.json()['data']) >= 1
    la = client.get(f'/api/v1/inventory/items/{iid}/photos', headers={'X-API-Key': READER_A})
    assert la.status_code == 200
    assert la.json()['data'] == []


def test_repeated_upload_list_delete_does_not_lock_database():
    """Regression: repeated write/log/delete cycles must close DB handles."""
    _provision()
    for idx in range(5):
        iid = _item(1)
        upload = client.post(
            f'/api/v1/inventory/items/{iid}/photos',
            files={'file': (f't-{idx}.jpg', io.BytesIO(_jpeg()), 'image/jpeg')},
            headers={'X-API-Key': ADMIN_A},
        )
        assert upload.status_code == 200, upload.text
        photo_id = upload.json()['data']['photo_id']

        listed = client.get(f'/api/v1/inventory/items/{iid}/photos', headers={'X-API-Key': READER_A})
        assert listed.status_code == 200, listed.text
        assert any(row['photo_id'] == photo_id for row in listed.json()['data'])

        deleted = client.delete(f'/api/v1/inventory/items/{iid}/photos/{photo_id}', headers={'X-API-Key': ADMIN_A})
        assert deleted.status_code == 200, deleted.text