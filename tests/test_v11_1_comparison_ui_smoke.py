"""Smoke tests for v11.1 comparison UI.

Verifies that index.html and app.js contain the expected DOM IDs,
endpoint references, and handler logic for the read-only comparison panel.
No live server or browser required.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "pokemon_db_v2_browser_ui"
INDEX_HTML = UI_DIR / "index.html"
APP_JS = UI_DIR / "app.js"


@pytest.fixture
def index_content():
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture
def app_content():
    return APP_JS.read_text(encoding="utf-8")


class TestIndexHtml:
    def test_exactly_one_app_js_script_tag(self, index_content):
        """There must be exactly one app.js script tag (no duplicates)."""
        matches = re.findall(r'<script[^>]+src="app\.js[^"]*"[^>]*>', index_content)
        assert len(matches) == 1, f"Expected 1 app.js script tag, found {len(matches)}: {matches}"

    def test_script_tag_uses_correct_cache_bust(self, index_content):
        """The script tag must use the comparison UI cache-bust version."""
        assert "app.js?v=20260628-comparison-ui-v1" in index_content

    def test_evidence_comparison_dom_ids(self, index_content):
        """Required comparison DOM IDs must exist."""
        for dom_id in ["evidenceComparison", "loadComparisonBtn", "comparisonSummary", "comparisonRows"]:
            assert f'id="{dom_id}"' in index_content, f"Missing DOM ID: {dom_id}"

    def test_existing_evidence_panel_ids_preserved(self, index_content):
        """Existing evidence panel IDs must still exist."""
        for dom_id in ["evidenceTargetId", "evidenceCurrency", "loadEvidenceBtn",
                       "evidenceHealth", "evidenceAggregate", "evidenceObservations"]:
            assert f'id="{dom_id}"' in index_content, f"Missing existing DOM ID: {dom_id}"


class TestAppJs:
    def test_references_comparison_endpoint(self, app_content):
        """app.js must reference the comparison API endpoint."""
        assert "/api/v1/prices/comparison/" in app_content

    def test_has_load_comparison_handler(self, app_content):
        """app.js must have a loadComparison function."""
        assert "function loadComparison(" in app_content or "async function loadComparison(" in app_content

    def test_renders_summary(self, app_content):
        """app.js must render comparison summary fields."""
        assert "comparisonSummary" in app_content
        assert "source_count" in app_content
        assert "comparison_count" in app_content
        assert "highest_disagreement" in app_content
        assert "confidence_note" in app_content

    def test_renders_comparison_rows(self, app_content):
        """app.js must render comparison rows."""
        assert "comparisonRows" in app_content
        assert "comparison-table" in app_content

    def test_handles_insufficient_evidence(self, app_content):
        """app.js must handle INSUFFICIENT_EVIDENCE case."""
        assert "INSUFFICIENT_EVIDENCE" in app_content or "comparison-insufficient" in app_content

    def test_agreement_band_classes(self, app_content):
        """app.js must define all agreement band CSS classes."""
        for cls in ["comparison-agree", "comparison-minor", "comparison-major",
                     "comparison-insufficient", "comparison-mixed", "comparison-stale"]:
            assert cls in app_content, f"Missing band class: {cls}"

    def test_no_provider_specific_api_calls(self, app_content):
        """app.js must not contain JustTCG/PokéWallet/Cardmarket/eBay API calls."""
        forbidden = ["justtcg.com", "pokewallet.io", "cardmarket.com/api",
                     "api.ebay.com", "ebay-average-selling-price"]
        for term in forbidden:
            assert term not in app_content.lower(), f"Found provider-specific reference: {term}"

    def test_uses_existing_target_input(self, app_content):
        """Comparison must reuse the existing evidenceTargetId input."""
        assert "evidenceTargetId" in app_content

    def test_conservative_messaging(self, app_content):
        """UI must use conservative language, not overclaim."""
        lower = app_content.lower()
        # Should NOT contain overclaiming terms
        forbidden_phrases = ["accurate price", "correct price", "pricing solved", "recommended sale price"]
        for phrase in forbidden_phrases:
            assert phrase not in lower, f"Found overclaiming phrase: {phrase}"

    def test_existing_evidence_functions_preserved(self, app_content):
        """Existing evidence functions must still exist."""
        assert "function loadEvidence(" in app_content or "async function loadEvidence(" in app_content
        assert "function loadHealth(" in app_content or "async function loadHealth(" in app_content
        assert "function renderObservations(" in app_content
        assert "function renderAggregates(" in app_content
