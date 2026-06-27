"""Smoke tests for browser card image loading fallbacks after v11.0.

These tests are intentionally local/static except for the isolated FastAPI
fixture. They do not call external image hosts.
"""
from __future__ import annotations

import re
from pathlib import Path

from test_gateway_fixture import READER_KEY, gw as _gw_fixture

HERE = Path(__file__).resolve().parent
UI_DIR = HERE.parent / "pokemon_db_v2_browser_ui"
CACHE_BUST = "20260627-image-fix-v4"
GATEWAY_ROUTE = "/api/v1/images/card/"


def _html() -> str:
    return (UI_DIR / "index.html").read_text()


def _js() -> str:
    return (UI_DIR / "app.js").read_text()


def _function_body(js: str, name: str) -> str:
    marker = f"function {name}"
    start = js.find(marker)
    assert start != -1, f"Missing {marker}"
    brace = js.find("{", start)
    assert brace != -1, f"Missing opening brace for {marker}"
    depth = 0
    for idx in range(brace, len(js)):
        if js[idx] == "{":
            depth += 1
        elif js[idx] == "}":
            depth -= 1
            if depth == 0:
                return js[brace + 1:idx]
    raise AssertionError(f"Could not parse body for {marker}")


def test_index_has_exactly_one_app_js_script_tag() -> None:
    html = _html()
    app_scripts = re.findall(r'<script\s+src="app\.js(?:\?v=[^"]*)?"\s*>\s*</script>', html)
    assert len(app_scripts) == 1, f"Expected exactly one app.js script tag, found {len(app_scripts)}"


def test_index_uses_latest_cache_bust_string() -> None:
    html = _html()
    assert f'<script src="app.js?v={CACHE_BUST}"></script>' in html
    assert "20260627-image-gateway-v2" not in html
    assert "20260627-image-fallback-v3" not in html


def test_app_has_exactly_one_image_url_candidates_function() -> None:
    js = _js()
    assert js.count("function imageUrlCandidates") == 1


def test_app_has_no_display_image_url_function() -> None:
    js = _js()
    assert "function displayImageUrl" not in js
    assert "displayImageUrl(" not in js


def test_image_url_candidates_has_no_return_early_gateway_logic() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    assert "return apiBase()" not in body
    assert "return images." not in body
    assert body.count("return urls;") == 1


def test_image_url_candidates_prefers_real_backend_gateway_route() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    assert GATEWAY_ROUTE in body
    assert "encodeURIComponent(key)" in body
    assert "function cardKey" in _js()


def test_image_url_candidates_includes_signed_url_fallbacks() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    assert "images.signed_image_url" in body
    assert "card.signed_image_url" in body


def test_image_url_candidates_includes_local_display_fallback() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    assert "images.local_display_image_url" in body
    assert "url.startsWith('/api/v1/')" in body
    assert "url.startsWith('http')" in body


def test_image_url_candidates_includes_external_display_fallbacks() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    assert "addUrl(images.display_image_url)" in body
    assert "addUrl(images.exact_image_url)" in body


def test_image_url_candidate_order_keeps_external_fallbacks_after_local_paths() -> None:
    body = _function_body(_js(), "imageUrlCandidates")
    order = [
        "'/api/v1/images/card/'",
        "images.signed_image_url",
        "card.signed_image_url",
        "images.local_display_image_url",
        "images.display_image_url",
        "images.exact_image_url",
    ]
    positions = [body.index(token) for token in order]
    assert positions == sorted(positions), positions


def test_render_uses_single_try_next_image_error_handler() -> None:
    js = _js()
    assert "img.onerror = tryNextImage" in js
    assert "img.onerror = () =>" not in js
    assert js.count("img.onerror") == 1


def test_representative_local_image_endpoint_returns_200(_gw_fixture) -> None:
    client, _fixture_data = _gw_fixture
    response = client.get(
        "/api/v1/images/card/en:card-a/content?size=medium",
        headers={"X-API-Key": READER_KEY},
    )
    assert response.status_code == 200, response.text[:200]
    assert response.headers.get("content-type", "").startswith("image/")
    assert response.content
