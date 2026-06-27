"""Tests for the TCGdex pricing source adapter.

Uses fixture data captured from live TCGdex API. No live calls in tests.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from pricing_sources.tcgdex import TCGdexAdapter
from pricing_sources.base import ListingType, MatchConfidence


# Fixture: TCGdex card detail response for swsh3-136 (Furret)
FIXTURE_TCGDEX_CARD = {
    "id": "swsh3-136",
    "name": "Furret",
    "localId": "136",
    "set": {
        "id": "swsh3",
        "name": "Sword & Shield",
    },
    "category": "Pokemon",
    "rarity": "Uncommon",
    "variants": {
        "firstEdition": False,
        "holo": False,
        "normal": True,
        "reverse": True,
        "wPromo": False,
    },
    "pricing": {
        "tcgplayer": {
            "updated": "2026-06-26T21:04:42.789Z",
            "unit": "USD",
            "normal": {
                "productId": 219333,
                "lowPrice": 0.04,
                "midPrice": 0.20,
                "highPrice": 25.11,
                "marketPrice": 0.11,
                "directLowPrice": None,
            },
            "reverse-holofoil": {
                "productId": 219333,
                "lowPrice": 0.15,
                "midPrice": 0.37,
                "highPrice": 19.98,
                "marketPrice": 0.37,
                "directLowPrice": 0.46,
            },
        },
        "cardmarket": {
            "updated": "2026-06-26T21:03:30.623Z",
            "unit": "EUR",
            "idProduct": 123456,
            "avg": 0.12,
            "low": 0.02,
            "trend": 0.10,
            "avg1": 0.08,
            "avg7": 0.10,
            "avg30": 0.12,
            "avg-holo": 0.43,
            "low-holo": 0.04,
            "trend-holo": 0.38,
            "avg1-holo": 0.30,
            "avg7-holo": 0.35,
            "avg30-holo": 0.40,
        },
    },
}

# Fixture: TCGdex set response (subset)
FIXTURE_TCGDEX_SET = {
    "id": "swsh3",
    "name": "Sword & Shield Series 3",
    "cardCount": 3,
    "cards": [
        {
            "id": "swsh3-1",
            "name": "Butterfree V",
            "localId": "1",
            "set": {"id": "swsh3"},
            "pricing": {
                "tcgplayer": {
                    "updated": "2026-06-26T21:04:42.789Z",
                    "unit": "USD",
                    "holofoil": {
                        "lowPrice": 0.50,
                        "marketPrice": 1.33,
                    },
                },
            },
        },
        {
            "id": "swsh3-2",
            "name": "Butterfree VMAX",
            "localId": "2",
            "set": {"id": "swsh3"},
            "pricing": {
                "tcgplayer": {
                    "updated": "2026-06-26T21:04:42.789Z",
                    "unit": "USD",
                    "holofoil": {
                        "lowPrice": 4.05,
                        "marketPrice": 5.97,
                    },
                },
                "cardmarket": {
                    "updated": "2026-06-26T21:03:30.623Z",
                    "unit": "EUR",
                    "avg": 4.96,
                    "trend": 5.09,
                },
            },
        },
        {
            "id": "swsh3-3",
            "name": "Caterpie",
            "localId": "3",
            "set": {"id": "swsh3"},
            "pricing": {},  # No pricing for this card
        },
    ],
}

# Fixture: Search result
FIXTURE_TCGDEX_SEARCH = [
    {
        "id": "swsh3-136",
        "name": "Furret",
        "localId": "136",
        "set": {"id": "swsh3"},
        "pricing": FIXTURE_TCGDEX_CARD["pricing"],
    },
]


class TestTCGdexAdapter:
    """Test TCGdex adapter with fixture data."""

    def test_source_code(self):
        adapter = TCGdexAdapter()
        assert adapter.source_code == "tcgdex"

    def test_source_name(self):
        adapter = TCGdexAdapter()
        assert adapter.source_name == "TCGdex Market API"

    def test_capabilities(self):
        adapter = TCGdexAdapter()
        caps = adapter.capabilities()
        assert caps["supports_condition"] is False
        assert caps["supports_finish"] is True
        assert caps["supports_sold_prices"] is False
        assert caps["supports_market_prices"] is True
        assert "USD" in caps["currencies"]
        assert "EUR" in caps["currencies"]

    def test_build_queries_with_set_code(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test",
            set_code="swsh3",
            card_name="Charizard",
            language="en",
        )
        queries = adapter.build_queries(query)
        assert len(queries) == 1
        assert queries[0]["type"] == "set_traversal"
        assert queries[0]["set_code"] == "swsh3"

    def test_build_queries_without_set_code(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test",
            card_name="Pikachu",
        )
        queries = adapter.build_queries(query)
        assert len(queries) == 1
        assert queries[0]["type"] == "name_search"
        assert queries[0]["card_name"] == "Pikachu"

    def test_normalise_card_detail(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery("canonical_printing", "cp-test")
        obs = adapter.normalise(FIXTURE_TCGDEX_CARD, query)

        # Should produce:
        # 1. tcgplayer normal marketPrice (USD 0.11)
        # 2. tcgplayer normal low (USD 0.04)
        # 3. tcgplayer reverse-holofoil marketPrice (USD 0.37)
        # 4. tcgplayer reverse-holofoil low (USD 0.15)
        # 5. cardmarket normal avg (EUR 0.12)
        # 6. cardmarket normal trend (EUR 0.10)
        # 7. cardmarket holo avg (EUR 0.43)
        # 8. cardmarket holo trend (EUR 0.38)
        assert len(obs) >= 5

        # Check TCGPlayer market price
        tcg_market = [o for o in obs if o.marketplace == "tcgplayer" and o.listing_type == ListingType.MARKET_PRICE]
        assert len(tcg_market) >= 2  # normal + reverse
        amounts = [o.amount for o in tcg_market]
        assert 0.11 in amounts
        assert 0.37 in amounts

        # Check Cardmarket
        cm_obs = [o for o in obs if o.marketplace == "cardmarket"]
        assert len(cm_obs) >= 2
        cm_amounts = [o.amount for o in cm_obs]
        assert 0.12 in cm_amounts  # normal avg

    def test_normalise_set_response(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery("canonical_printing", "cp-test")
        obs = adapter.normalise(FIXTURE_TCGDEX_SET, query)

        # Should include pricing from swsh3-1 and swsh3-2, but not swsh3-3 (no pricing)
        assert len(obs) >= 2

        # Check that we got the Butterfree V pricing
        butterfree_amounts = [o.amount for o in obs if "Butterfree" in (o.raw_title or "")]
        assert len(butterfree_amounts) >= 2

    def test_normalise_no_pricing(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery("canonical_printing", "cp-test")
        card = {
            "id": "swsh3-3",
            "name": "Caterpie",
            "localId": "3",
            "set": {"id": "swsh3"},
            "pricing": {},
        }
        obs = adapter.normalise(card, query)
        assert obs == []

    def test_normalise_missing_fields(self):
        """Handle cards with missing optional fields gracefully."""
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        query = PriceQuery("canonical_printing", "cp-test")
        card = {
            "id": "test-1",
            "name": "Test Card",
            "set": {"id": "test"},
            # No pricing field at all
        }
        obs = adapter.normalise(card, query)
        assert obs == []

    def test_match_observations_with_set_and_number(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceQuery
        from pricing_sources.base import PriceObservationCandidate

        obs_list = [
            PriceObservationCandidate(
                source_record_id="swsh3-136:tcgplayer:normal",
                observed_at="2026-06-26T21:04:42Z",
                currency="USD",
                amount=0.11,
                finish="normal",
            ),
        ]
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test",
            set_code="swsh3",
            collector_number="136",
        )
        matched = adapter.match_observations(obs_list, query)
        assert len(matched) == 1
        assert matched[0].match_confidence == MatchConfidence.HIGH
        assert matched[0].match_method == "set_code+collector_number"

    def test_match_observations_name_only(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceObservationCandidate, PriceQuery

        obs_list = [
            PriceObservationCandidate(
                source_record_id="test",
                observed_at="2026-06-26T21:04:42Z",
                currency="USD",
                amount=10.0,
            ),
        ]
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test",
            card_name="Charizard",
        )
        matched = adapter.match_observations(obs_list, query)
        assert len(matched) == 1
        assert matched[0].match_confidence == MatchConfidence.MEDIUM

    def test_match_observations_no_identity(self):
        adapter = TCGdexAdapter()
        from pricing_sources.base import PriceObservationCandidate, PriceQuery

        obs_list = [
            PriceObservationCandidate(
                source_record_id="test",
                observed_at="2026-06-26T21:04:42Z",
                currency="USD",
                amount=10.0,
            ),
        ]
        query = PriceQuery(target_type="canonical_printing", target_id="cp-test")
        matched = adapter.match_observations(obs_list, query)
        assert len(matched) == 1
        assert matched[0].match_confidence == MatchConfidence.UNUSABLE

    def test_tcgplayer_variant_to_finish(self):
        adapter = TCGdexAdapter()
        assert adapter._tcgplayer_variant_to_finish("normal") == "normal"
        assert adapter._tcgplayer_variant_to_finish("holofoil") == "holo"
        assert adapter._tcgplayer_variant_to_finish("reverse-holofoil") == "reverse_holo"
        assert adapter._tcgplayer_variant_to_finish("1st-edition") == "normal"
        assert adapter._tcgplayer_variant_to_finish("unknown-variant") == "unknown"

    def test_hash_raw(self):
        payload = {"test": True, "value": 42}
        hash1 = TCGdexAdapter.hash_raw(payload)
        hash2 = TCGdexAdapter.hash_raw(payload)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

        # Different payloads produce different hashes
        payload2 = {"test": True, "value": 43}
        hash3 = TCGdexAdapter.hash_raw(payload2)
        assert hash3 != hash1

    def test_fetch_returns_none_on_error(self):
        """Test that fetch returns None when the URL is invalid."""
        adapter = TCGdexAdapter(base_url="http://localhost:99999")
        result = adapter.fetch({"type": "card_detail", "card_id": "test"})
        assert result is None

    def test_health_check_returns_result(self):
        """Health check should return a result (not raise)."""
        adapter = TCGdexAdapter()
        result = adapter.health_check()
        assert result.source_code == "tcgdex"
        # Status depends on network, but should be one of the valid values
        assert result.status in ("healthy", "degraded", "failing", "unknown")
