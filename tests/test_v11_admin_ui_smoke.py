"""Smoke tests for v11 Market Evidence admin UI.

Verifies that the browser UI files:
1. Exist and are well-formed
2. Reference the correct v11 API endpoints
3. Contain expected DOM element IDs
4. Include the v11 CSS styles

These are static-structure tests — they do not render the UI in a browser.
Run: python -m pytest tests/test_v11_admin_ui_smoke.py -v
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
UI_DIR = HERE.parent / "pokemon_db_v2_browser_ui"


class TestV11AdminUIFiles:
    """Verify v11 admin UI files exist and are well-formed."""

    def test_index_html_exists(self):
        html = UI_DIR / "index.html"
        assert html.exists(), f"Missing {html}"
        content = html.read_text()
        assert len(content) > 1000, "index.html seems too small"

    def test_app_js_exists(self):
        js = UI_DIR / "app.js"
        assert js.exists(), f"Missing {js}"
        content = js.read_text()
        assert len(content) > 5000, "app.js seems too small"

    def test_styles_css_exists(self):
        css = UI_DIR / "styles.css"
        assert css.exists(), f"Missing {css}"
        content = css.read_text()
        assert len(content) > 1000, "styles.css seems too small"


class TestV11AdminUIReferences:
    """Verify UI files reference the correct v11 API endpoints."""

    def test_html_references_evidence_panel(self):
        html = (UI_DIR / "index.html").read_text()
        assert 'evidence-panel' in html, "Missing evidence-panel class"
        assert 'evidenceTargetId' in html, "Missing evidenceTargetId input"
        assert 'loadEvidenceBtn' in html, "Missing loadEvidenceBtn button"
        assert 'refreshEvidenceBtn' in html, "Missing refreshEvidenceBtn button"
        assert 'loadHealthBtn' in html, "Missing loadHealthBtn button"

    def test_js_calls_sources_health(self):
        js = (UI_DIR / "app.js").read_text()
        assert '/api/v1/prices/sources/tcgdex/health' in js, "Missing health API call"

    def test_js_calls_observations(self):
        js = (UI_DIR / "app.js").read_text()
        assert '/api/v1/prices/observations' in js, "Missing observations API call"

    def test_js_calls_aggregate(self):
        js = (UI_DIR / "app.js").read_text()
        assert '/api/v1/prices/aggregate' in js, "Missing aggregate API call"

    def test_js_calls_refresh(self):
        js = (UI_DIR / "app.js").read_text()
        assert '/api/v1/prices/refresh' in js, "Missing refresh API call"

    def test_js_renders_confidence_classes(self):
        js = (UI_DIR / "app.js").read_text()
        assert 'conf-high' in js, "Missing HIGH confidence class"
        assert 'conf-medium' in js, "Missing MEDIUM confidence class"
        assert 'conf-low' in js, "Missing LOW confidence class"

    def test_css_has_evidence_styles(self):
        css = (UI_DIR / "styles.css").read_text()
        assert '.evidence-panel' in css, "Missing .evidence-panel style"
        assert '.obs-table' in css, "Missing .obs-table style"
        assert '.conf-high' in css, "Missing .conf-high style"


class TestV11AdminUIJsStructure:
    """Verify JS functions are defined and balanced."""

    def test_js_braces_balanced(self):
        js = (UI_DIR / "app.js").read_text()
        assert js.count("{") == js.count("}"), "Unbalanced braces in app.js"

    def test_js_functions_defined(self):
        js = (UI_DIR / "app.js").read_text()
        expected_fns = [
            "function loadHealth",
            "function loadEvidence",
            "function renderObservations",
            "function renderAggregates",
            "function refreshEvidence",
            "function confClassName",
        ]
        for fn in expected_fns:
            assert fn in js, f"Missing function: {fn}"

    def test_js_event_listeners_attached(self):
        js = (UI_DIR / "app.js").read_text()
        assert "$('loadEvidenceBtn').addEventListener" in js
        assert "$('loadHealthBtn').addEventListener" in js
        assert "$('refreshEvidenceBtn').addEventListener" in js
