"""TCGdex pricing source adapter.

TCGdex (https://tcgdex.dev) is a free, open-source Pokémon TCG API that
aggregates pricing from TCGPlayer (USD) and Cardmarket (EUR).

No API key required. Rate limits are generous (observed: ~50ms per request,
no limit observed on rapid sequential requests).

Data quality notes:
- TCGPlayer `lowPrice` is the lowest listed price (can be outlier).
- TCGPlayer `marketPrice` is the reliable market-level price.
- Cardmarket `avg` is the average selling price over 30 days.
- Separate pricing for normal, reverse-holo, holo variants.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
import urllib.error
from typing import Any

from pricing_sources.base import (
    ListingType,
    MatchedPriceObservation,
    MatchConfidence,
    PriceObservationCandidate,
    PriceQuery,
    PriceSourceAdapter,
    SourceHealthResult,
)

TCGDEX_BASE_URL = "https://api.tcgdex.net"


class TCGdexAdapter(PriceSourceAdapter):
    """Adapter for the TCGdex market pricing API."""

    def __init__(self, base_url: str = TCGDEX_BASE_URL, timeout: int = 15):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def source_code(self) -> str:
        return "tcgdex"

    @property
    def source_name(self) -> str:
        return "TCGdex Market API"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_condition": False,
            "supports_finish": True,     # normal/reverse/holo
            "supports_sold_prices": False,
            "supports_active_listings": True,
            "supports_market_prices": True,
            "currencies": ["USD", "EUR"],
            "update_frequency": "hourly (TCGPlayer) to daily (Cardmarket)",
            "languages": ["en", "de", "fr", "es", "it", "pt", "ja", "ko", "zh-cn", "zh-tw"],
            "note": "Cardmarket avg is trend price; TCGPlayer marketPrice is market average",
        }

    def health_check(self) -> SourceHealthResult:
        """Check TCGdex health by fetching a known card."""
        import time
        start = time.time()
        try:
            url = f"{self._base_url}/v2/en/cards/swsh3-1"
            req = urllib.request.Request(url, headers={"User-Agent": "PokemonDB/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                elapsed_ms = (time.time() - start) * 1000
                if resp.status == 200:
                    return SourceHealthResult(
                        source_code=self.source_code,
                        status="healthy",
                        response_ms=round(elapsed_ms, 1),
                    )
                return SourceHealthResult(
                    source_code=self.source_code,
                    status="degraded",
                    response_ms=round(elapsed_ms, 1),
                    error_code=str(resp.status),
                )
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            return SourceHealthResult(
                source_code=self.source_code,
                status="failing",
                response_ms=round(elapsed_ms, 1),
                error_message=str(e),
            )

    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]:
        """Build TCGdex queries.

        TCGdex uses sequential card IDs within sets. We need to iterate
        through cards in the target set to find matches. For efficiency,
        we start with set traversal.

        For now, the query returns the set traversal parameters.
        The actual card matching happens after fetching the set.
        """
        queries = []
        if query.set_code:
            queries.append({
                "type": "set_traversal",
                "set_code": query.set_code,
                "card_name": query.card_name,
                "language": query.language or "en",
            })
        elif query.card_name:
            queries.append({
                "type": "name_search",
                "card_name": query.card_name,
                "language": query.language or "en",
            })
        return queries

    def fetch(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch from TCGdex API."""
        qtype = query.get("type", "card_detail")

        if qtype == "set_traversal":
            return self._fetch_set_cards(query.get("set_code", ""), query.get("language", "en"))
        elif qtype == "name_search":
            return self._fetch_by_name(query.get("card_name", ""), query.get("language", "en"))
        else:
            return None

    def _fetch_set_cards(self, set_code: str, language: str) -> dict[str, Any] | None:
        """Fetch all cards in a set. Returns the set object with cards."""
        url = f"{self._base_url}/v2/{language}/sets/{set_code}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PokemonDB/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.HTTPError, Exception):
            return None

    def _fetch_by_name(self, card_name: str, language: str) -> dict[str, Any] | None:
        """Fetch cards by name using the name search endpoint."""
        import urllib.parse
        url = f"{self._base_url}/v2/{language}/cards?name={urllib.parse.quote(card_name)}&limit=50"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PokemonDB/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, list) and data:
                    return {"cards": data}
                return None
        except (urllib.error.HTTPError, Exception):
            return None

    def fetch_card_detail(self, card_id: str, language: str = "en") -> dict[str, Any] | None:
        """Fetch full card detail including pricing."""
        url = f"{self._base_url}/v2/{language}/cards/{card_id}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PokemonDB/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.HTTPError, Exception):
            return None

    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]:
        """Normalise TCGdex response into observation candidates.

        The response can be:
        - A single card detail (from fetch_card_detail)
        - A set object with cards list (from _fetch_set_cards)
        - A search result (from _fetch_by_name)
        """
        candidates: list[PriceObservationCandidate] = []

        # Determine what type of response we have
        if "pricing" in raw_response and "id" in raw_response:
            # Single card detail
            candidates.extend(self._normalise_card(raw_response))
        elif "cards" in raw_response and isinstance(raw_response["cards"], list):
            # Set object with cards list
            for card in raw_response["cards"]:
                candidates.extend(self._normalise_card(card))

        return candidates

    def _normalise_card(self, card: dict[str, Any]) -> list[PriceObservationCandidate]:
        """Normalise a single TCGdex card response."""
        candidates: list[PriceObservationCandidate] = []
        pricing = card.get("pricing", {})
        if not pricing:
            return candidates

        card_id = card.get("id", "unknown")
        card_name = card.get("name", "unknown")
        local_id = card.get("localId")
        set_info = card.get("set", {})
        set_id = set_info.get("id", "unknown") if isinstance(set_info, dict) else "unknown"

        # TCGPlayer pricing (USD)
        tcgplayer = pricing.get("tcgplayer", {})
        if tcgplayer:
            updated = tcgplayer.get("updated", "2026-01-01T00:00:00Z")
            for variant_key, variant_data in tcgplayer.items():
                if not isinstance(variant_data, dict) or not variant_data:
                    continue
                if variant_key in ("unit", "updated"):
                    continue

                finish = self._tcgplayer_variant_to_finish(variant_key)
                market_price = variant_data.get("marketPrice")
                low_price = variant_data.get("lowPrice")

                # Market price observation (most reliable)
                if market_price is not None:
                    candidates.append(PriceObservationCandidate(
                        source_record_id=f"{card_id}:tcgplayer:{variant_key}",
                        observed_at=updated,
                        currency="USD",
                        amount=market_price,
                        finish=finish,
                        printing_label=f"{card_name} ({variant_key})",
                        marketplace="tcgplayer",
                        listing_type=ListingType.MARKET_PRICE,
                        raw_title=f"{card_name} [{set_id}#{local_id}] TCGPlayer {variant_key}",
                        observation_type="market_price",
                    ))

                # Low price observation (may be outlier, but useful for range)
                if low_price is not None and low_price != market_price:
                    candidates.append(PriceObservationCandidate(
                        source_record_id=f"{card_id}:tcgplayer:{variant_key}:low",
                        observed_at=updated,
                        currency="USD",
                        amount=low_price,
                        finish=finish,
                        printing_label=f"{card_name} ({variant_key}) low",
                        marketplace="tcgplayer",
                        listing_type=ListingType.ACTIVE_LISTING,
                        raw_title=f"{card_name} [{set_id}#{local_id}] TCGPlayer {variant_key} low",
                        observation_type="active_listing",
                    ))

        # Cardmarket pricing (EUR)
        cardmarket = pricing.get("cardmarket", {})
        if cardmarket:
            updated = cardmarket.get("updated", "2026-01-01T00:00:00Z")
            for suffix, finish in [("", "normal"), ("-holo", "holo")]:
                avg = cardmarket.get(f"avg{suffix}")
                trend = cardmarket.get(f"trend{suffix}")
                low = cardmarket.get(f"low{suffix}")

                if avg is not None:
                    candidates.append(PriceObservationCandidate(
                        source_record_id=f"{card_id}:cardmarket:{finish}",
                        observed_at=updated,
                        currency="EUR",
                        amount=avg,
                        finish=finish,
                        printing_label=f"{card_name} ({finish})",
                        marketplace="cardmarket",
                        listing_type=ListingType.MARKET_PRICE,
                        raw_title=f"{card_name} [{set_id}#{local_id}] Cardmarket {finish} avg",
                        observation_type="market_price",
                    ))

                if trend is not None and trend != avg:
                    candidates.append(PriceObservationCandidate(
                        source_record_id=f"{card_id}:cardmarket:{finish}:trend",
                        observed_at=updated,
                        currency="EUR",
                        amount=trend,
                        finish=finish,
                        printing_label=f"{card_name} ({finish}) trend",
                        marketplace="cardmarket",
                        listing_type=ListingType.MARKET_PRICE,
                        raw_title=f"{card_name} [{set_id}#{local_id}] Cardmarket {finish} trend",
                        observation_type="market_price",
                    ))

        return candidates

    def _tcgplayer_variant_to_finish(self, variant_key: str) -> str:
        """Map TCGdex TCGPlayer variant key to our finish enum."""
        mapping = {
            "normal": "normal",
            "holofoil": "holo",
            "reverse-holofoil": "reverse_holo",
            "1st-edition": "normal",  # first edition is a printing, not finish
            "1st-edition-holofoil": "holo",
            "unlimited": "normal",
            "unlimited-holofoil": "holo",
        }
        return mapping.get(variant_key, "unknown")

    def match_observations(
        self,
        observations: list[PriceObservationCandidate],
        query: PriceQuery,
    ) -> list[MatchedPriceObservation]:
        """Match observations to v10 identity.

        TCGdex cards are identified by set + localId. We match to v10
        canonical printings using set_code + collector_number.
        """
        matched: list[MatchedPriceObservation] = []

        for obs in observations:
            # For now, match by set_code + collector_number from query
            if query.set_code and query.collector_number:
                matched.append(MatchedPriceObservation(
                    observation=obs,
                    target_type="canonical_printing",
                    target_id=f"cp-{query.set_code}-{query.collector_number}",
                    match_confidence=MatchConfidence.HIGH,
                    match_reason=f"set_code={query.set_code}, number={query.collector_number}",
                    match_method="set_code+collector_number",
                ))
            elif query.card_name:
                matched.append(MatchedPriceObservation(
                    observation=obs,
                    target_type="canonical_printing",
                    target_id=f"cp-{query.card_name}",
                    match_confidence=MatchConfidence.MEDIUM,
                    match_reason=f"name match: {query.card_name}",
                    match_method="name_match",
                ))
            else:
                matched.append(MatchedPriceObservation(
                    observation=obs,
                    target_type="canonical_printing",
                    target_id="unknown",
                    match_confidence=MatchConfidence.UNUSABLE,
                    match_reason="insufficient identity for matching",
                    match_method="none",
                ))

        return matched

    @staticmethod
    def hash_raw(payload: dict[str, Any]) -> str:
        """Hash a raw payload for deduplication."""
        raw_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw_str.encode()).hexdigest()
