#!/usr/bin/env python3
"""v9.2 health/readiness endpoint tests."""
from __future__ import annotations

from test_gateway_fixture import gw


def test_readiness_reports_component_checks(gw):
    client, _fd = gw

    resp = client.get('/api/v1/readiness', headers={'X-API-Key': 'test-reader-key'})

    assert resp.status_code == 200, resp.text
    body = resp.json()['data']
    assert body['service'] == 'saveroom-pokemon-api'
    assert set(body['checks']) >= {
        'database_reachable',
        'support_ready',
        'required_schema_present',
        'image_root_available',
        'configuration_valid',
    }
    assert body['checks']['database_reachable'] is True
