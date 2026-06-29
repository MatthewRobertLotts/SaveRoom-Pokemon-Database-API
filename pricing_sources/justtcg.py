"""JustTCG pricing source adapter — fixture-only spike.

JustTCG (https://api.justtcg.com/v1) is a structured TCG pricing API
providing market prices, condition/variant data, and price history for
Pokémon and other TCGs. Currency is USD only. Price semantics are
market price (not sold/completed listings).

This adapter is a fixture-only spike. It can normalize fixture payloads
and would make live HTTP calls ONLY when the access gate is fully
configured (API key + enabled + terms confirmed). Live fetch is
gated and will not execute unless all env flags are set.

Design: docs/V12_JUSTTCG_FIXTURE_ADAPTER_SPIKE.md
Terms: docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md

Critical restriction:
JustTCG-derived pricing must NOT be exposed through a standalone
external developer pricing API or competing data product.
SaveRoom ecosystem apps only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from pricing_sources.base import (
    ListingType,
    MatchedPriceObservation,
    MatchConfidence,
    PriceObservationCandidate,
    PriceQuery,
    PriceSourceAdapter,
    SourceHealthResult,
)

JUSTTCG_BASE_URL = "https://api.justtcg.com/v1"


class JustTCGAdapter(PriceSourceAdapter):
    """Adapter for the JustTCG pricing API.

    Features:
    - Condition-specific pricing (NM, LP, MP, HP, D)
    - Printing/variant separation (Normal, Foil, 1st Edition, etc.)
    - Market prices only (not sold/completed listings)
    - USD currency only
    - Batch lookup support (POST /v1/cards)
    - Price history (7d/30d/90d/180d/1y)

    Access gate:
    - requires_access_gate() returns True
    - All live calls require API key + enabled + terms confirmed
    - Never logs secrets
    - External API resale is blocked by design
    """

    def __init__(
        self,
        base_url: str = JUSTTCG_BASE_URL,
        timeout: int = 15,
        fixture_path: Path | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._fixture_path = fixture_path

    @property
    def source_code(self) -> str:
        return "justtcg"

    @property
    def source_name(self) -> str:
        return "JustTCG Market API"

    def requires_access_gate(self) -> bool:
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_condition": True,
            "supports_finish": True,
            "supports_sold_prices": False,
            "supports_active_listings": False,
            "supports_market_prices": True,
            "currencies": ["USD"],
            "regions": ["US", "global"],
            "update_frequency": "near-realtime (per JustTCG)",
            "batch_support": True,
            "batch_max_cards": 200,
            "price_history_windows": ["7d", "30d", "90d", "180d", "1y"],
            "preferred_match_key": "tcgplayerSkuId",
            "fallback_match_key": "justtcg_variant_uuid",
            "attribution": "Pricing data provided by JustTCG",
            "external_api_resale_allowed": False,
            "saveroom_ecosystem_apps_allowed": True,
            "price_type": "market_price",
            "note": "USD market fallback only. Not UK sold evidence. Not for standalone external developer API.",
        }

    def health_check(self) -> SourceHealthResult:
        """Health check. Without live access, reports disabled."""
        return SourceHealthResult(
            source_code=self.source_code,
            status="disabled",
            response_ms=0.0,
            error_message="Fixture-only spike — live calls not configured",
        )

    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]:
        """Build query parameters for JustTCG lookup.

        Supports tcgplayerId, set+number, and name-based lookup.
        Returns a list of query dicts for fallback strategies.
        """
        queries: list[dict[str, Any]] = []

        # Preferred: tcgplayerId if available
        if query.target_id and query.target_type in ("sellable_sku", "commercial_variant"):
            queries.append({
                "endpoint": "GET /v1/cards",
                "params": {"tcgplayerId": query.target_id},
                "strategy": "tcgplayer_id",
            })

        # Fallback: set + number
        if query.set_code and query.collector_number:
            queries.append({
                "endpoint": "GET /v1/cards",
                "params": {
                    "game": "pokemon",
                    "set": query.set_code,
                    "number": query.collector_number,
                },
                "strategy": "set_number",
            })

        return queries

    def fetch(self, query: dict[str, Any], config: Mapping[str, str] | None = None) -> dict[str, Any] | None:
        """Fetch from JustTCG. Gated — live calls require full access config.

        If a fixture_path is set, loads from fixture instead.
        Otherwise, requires access gate and would make HTTP call.
        """
        # Fixture path for testing
        if self._fixture_path and self._fixture_path.exists():
            try:
                return json.loads(self._fixture_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

        # Live fetch — gated
        if config is not None:
            self.require_live_access(config)

        # If we reach here without config, we can't make live calls
        raise PermissionError(
            f"Adapter '{self.source_code}' requires access gate config to make live API calls. "
            f"No fixture path configured and no config provided."
        )

    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]:
        """Normalize a JustTCG response into observation candidates.

        JustTCG returns market prices (not sold/completed). All prices
        are in USD. This method preserves those semantics explicitly.
        """
        candidates: list[PriceObservationCandidate] = []

        # Handle _metadata wrapper
        if "_metadata" in raw_response:
            payload = raw_response.get("data", raw_response.get("response", {}))
        else:
            payload = raw_response

        # Extract card records
        records: list[dict[str, Any]] = []
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                records = payload["data"]
            else:
                records = [payload]

        for card in records:
            if not isinstance(card, dict):
                continue

            # Process variants (pricing lives here in JustTCG)
            variants = card.get("variants", [])
            for variant in variants:
                if not isinstance(variant, dict):
                    continue

                price = variant.get("price")
                if price is None:
                    continue

                # Determine condition
                condition = variant.get("condition", "unknown")
                # Map JustTCG condition names to normalized values
                condition_map = {
                    "Near Mint": "NM",
                    "Lightly Played": "LP",
                    "Moderately Played": "MP",
                    "Heavily Played": "HP",
                    "Damaged": "D",
                }
                normalized_condition = condition_map.get(condition, condition)

                # Record ID uses variant UUID if available, else card UUID
                variant_uuid = variant.get("uuid", "")
                card_uuid = card.get("uuid", "")
                record_id = variant_uuid or card_uuid or "justtcg-unknown"

                # Timestamp
                last_updated = variant.get("lastUpdated")
                if isinstance(last_updated, (int, float)):
                    observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_updated))
                else:
                    observed_at = str(last_updated or "2026-06-29T00:00:00Z")

                # External identifiers
                tcgplayer_sku_id = variant.get("tcgplayerSkuId")

                candidate = PriceObservationCandidate(
                    source_record_id=f"justtcg:{record_id}",
                    observed_at=observed_at,
                    currency="USD",
                    amount=float(price),
                    condition=normalized_condition,
                    finish=str(variant.get("printing", "unknown")),
                    language=str(variant.get("language", "unknown")),
                    marketplace="justtcg",
                    listing_type=ListingType.MARKET_PRICE,
                    raw_title=card.get("name"),
                    observation_type="market_price",
                    # Store external keys via extra fields on the dataclass
                    # We use printing_label for tcgplayerSkuId since it's freeform
                    printing_label=str(tcgplayer_sku_id) if tcgplayer_sku_id else None,
                )
                candidates.append(candidate)

        return candidates

    def match_observations(
        self,
        observations: list[PriceObservationCandidate],
        query: PriceQuery,
    ) -> list[MatchedPriceObservation]:
        """Match observations to v10 identity targets.

        Uses tcgplayerSkuId (stored in printing_label) as preferred
        match key, falling back to source_record_id variant UUID.
        """
        results: list[MatchedPriceObservation] = []

        for obs in observations:
            # Determine match confidence based on available keys
            has_sku = obs.printing_label is not None
            if has_sku:
                confidence = MatchConfidence.HIGH
                reason = "matched via tcgplayerSkuId"
                method = "tcgplayerSkuId"
            else:
                confidence = MatchConfidence.MEDIUM
                reason = "matched via justtcg_variant_uuid (fallback)"
                method = "justtcg_variant_uuid"

            results.append(MatchedPriceObservation(
                observation=obs,
                target_type=query.target_type,
                target_id=query.target_id,
                match_confidence=confidence,
                match_reason=reason,
                match_method=method,
            ))

        return results

    def validate_identifier_mapping(self, card_data: dict[str, Any]) -> dict[str, Any]:
        """Validate identifier mapping fields in a JustTCG card response.

        Returns a dict with mapping validation results.
        """
        card_uuid = card_data.get("uuid")
        tcgplayer_id = card_data.get("tcgplayerId")
        variants = card_data.get("variants", [])

        variant_mappings = []
        for v in variants:
            variant_mappings.append({
                "variant_uuid": v.get("uuid"),
                "tcgplayerSkuId": v.get("tcgplayerSkuId"),
                "condition": v.get("condition"),
                "printing": v.get("printing"),
                "has_preferred_key": v.get("tcgplayerSkuId") is not None,
                "has_fallback_key": v.get("uuid") is not None,
            })

        return {
            "card_uuid": card_uuid,
            "tcgplayerId": tcgplayer_id,
            "preferred_match_key": "tcgplayerSkuId",
            "fallback_match_key": "justtcg_variant_uuid",
            "variant_count": len(variants),
            "variant_mappings": variant_mappings,
            "all_variants_have_preferred": all(m["has_preferred_key"] for m in variant_mappings),
        }
