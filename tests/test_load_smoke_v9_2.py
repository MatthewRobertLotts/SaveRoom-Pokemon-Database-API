#!/usr/bin/env python3
"""v9.2 lightweight concurrent API smoke test."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from test_gateway_fixture import gw


def test_concurrent_read_smoke_no_errors(gw):
    client, fd = gw
    headers = {'X-API-Key': 'test-reader-key'}
    paths = []
    for _ in range(8):
        paths.extend([
            '/api/v1/health',
            '/api/v1/readiness',
            '/api/v1/search/cards?limit=2',
            f"/api/v1/images/assets/{fd['img_a_id']}/content?size=thumbnail",
        ])

    def fetch(path: str) -> tuple[str, int, int]:
        resp = client.get(path, headers=headers)
        return path, resp.status_code, len(resp.content)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [future.result() for future in as_completed(pool.submit(fetch, p) for p in paths)]

    assert len(results) == len(paths)
    for path, status, size in results:
        assert status == 200, (path, status)
        assert size > 0, path
