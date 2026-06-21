#!/usr/bin/env python3
"""Smoke-test the local FastAPI Pokémon DB service and write a JSON report."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import requests

from pokemon_db_v3_config import DEFAULT_REPORTS_DIR

REPORTS = DEFAULT_REPORTS_DIR


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp_date() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')


def fetch(base_url: str, path: str, *, timeout: int = 30) -> dict[str, Any]:
    url = base_url.rstrip('/') + path
    start = time.perf_counter()
    response = requests.get(url, timeout=timeout)
    elapsed_ms = (time.perf_counter() - start) * 1000
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = response.text[:1000]
    return {
        'url': url,
        'status_code': response.status_code,
        'elapsed_ms': round(elapsed_ms, 3),
        'ok': response.ok,
        'payload': payload,
    }


def summarize(endpoint: str, result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get('payload') if isinstance(result.get('payload'), dict) else {}
    summary: dict[str, Any] = {
        'endpoint': endpoint,
        'status_code': result['status_code'],
        'elapsed_ms': result['elapsed_ms'],
        'ok': result['ok'],
    }
    if endpoint == '/health':
        summary['api_ok'] = payload.get('ok')
        summary['support_ready'] = payload.get('counts', {}).get('support_ready')
    elif endpoint.startswith('/search') or endpoint.startswith('/sets'):
        summary['count'] = payload.get('count')
        first = (payload.get('results') or [None])[0]
        if first:
            summary['first_result'] = {
                'language_code': first.get('language_code'),
                'card_id': first.get('card_id'),
                'name': first.get('name'),
                'core_set_id': (first.get('set') or {}).get('core_set_id'),
                'has_display_image': (first.get('images') or {}).get('has_display_image'),
            }
    elif endpoint.startswith('/cards'):
        detail = payload.get('detail') or {}
        summary['found'] = bool(detail)
        summary['card_id'] = detail.get('card_id')
        summary['name'] = detail.get('name')
    elif endpoint == '/reports/coverage':
        summary['total_rows'] = payload.get('total_rows')
        summary['readiness_buckets'] = payload.get('readiness_buckets')
        summary['rows_without_display_image'] = payload.get('image_coverage', {}).get('rows_without_display_image')
    elif endpoint.startswith('/ui'):
        summary['content_ok'] = isinstance(result.get('payload'), str) and 'SaveRoom Pokémon Card Search' in result.get('payload', '')
    elif endpoint.startswith('/images'):
        summary['image_bytes_ok'] = result.get('status_code') == 200
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Smoke-test the SaveRoom Pokémon FastAPI service.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--out', default=str(REPORTS / f'v2_fastapi_smoke_test_{stamp_date()}.json'))
    args = parser.parse_args()

    endpoints = [
        '/health',
        '/search?q=charizard&limit=20',
        '/search?q=pikachu%20japanese&limit=20',
        '/sets/svp/cards?limit=20',
        '/cards/en/ex3-100',
        '/reports/coverage',
        '/ui/',
    ]
    results = {endpoint: fetch(args.base_url, endpoint) for endpoint in endpoints}
    charizard_results = results['/search?q=charizard&limit=20'].get('payload', {}).get('results') or []
    local_image_url = None
    for card in charizard_results:
        candidate = (card.get('images') or {}).get('local_display_image_url')
        if candidate:
            local_image_url = candidate
            break
    if local_image_url:
        results[local_image_url] = fetch(args.base_url, local_image_url)
    summaries = [summarize(endpoint, result) for endpoint, result in results.items()]
    checks = {
        'health_ok': summaries[0].get('api_ok') is True and summaries[0].get('support_ready') is True,
        'charizard_has_results': summaries[1].get('count', 0) > 0,
        'pikachu_japanese_has_results': summaries[2].get('count', 0) > 0,
        'svp_set_has_results': summaries[3].get('count', 0) > 0,
        'detail_found': summaries[4].get('found') is True,
        'coverage_total_positive': (summaries[5].get('total_rows') or 0) > 0,
        'ui_loads': summaries[6].get('content_ok') is True,
        'image_cache_mount_works': True if local_image_url is None else any(s['endpoint'] == local_image_url and s.get('image_bytes_ok') for s in summaries),
        'all_http_200': all(s['status_code'] == 200 for s in summaries),
    }
    report = {
        'generated_at': now_utc(),
        'base_url': args.base_url,
        'pass': all(checks.values()),
        'checks': checks,
        'summaries': summaries,
        'raw_results': results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'report': str(out),
        'pass': report['pass'],
        'checks': checks,
        'summaries': summaries,
    }, ensure_ascii=False, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
