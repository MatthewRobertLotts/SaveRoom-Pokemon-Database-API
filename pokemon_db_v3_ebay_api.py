#!/usr/bin/env python3
"""eBay Buy API (Browse API) wrapper — OAuth + search for the SaveRoom Pokémon Card DB.

Supports sandbox and production environments via the EBAY_ENV env var or parameter.
Credentials come from environment variables EBAY_CLIENT_ID and EBAY_CLIENT_SECRET.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

EBAY_ENDPOINTS = {
    'sandbox': {
        'oauth': 'https://api.sandbox.ebay.com/identity/v1/oauth2/token',
        'browse': 'https://api.sandbox.ebay.com/buy/browse/v1',
    },
    'production': {
        'oauth': 'https://api.ebay.com/identity/v1/oauth2/token',
        'browse': 'https://api.ebay.com/buy/browse/v1',
    },
}

BROWSE_SCOPE = 'https://api.ebay.com/oauth/api_scope'

_DEFAULT_ENV = os.environ.get('EBAY_ENV', 'sandbox').lower()
_DEFAULT_CLIENT_ID = os.environ.get('EBAY_CLIENT_ID', '')
_DEFAULT_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET', '')


@dataclass(frozen=True)
class EbayOAuthToken:
    access_token: str
    expires_at: float  # Unix timestamp when this token expires


class EbayBuyAPI:
    """Thin wrapper around the eBay Buy API (Browse API)."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        env: str | None = None,
    ):
        self.client_id = client_id or _DEFAULT_CLIENT_ID
        self.client_secret = client_secret or _DEFAULT_CLIENT_SECRET
        self.env = (env or _DEFAULT_ENV).lower()
        if self.env not in EBAY_ENDPOINTS:
            raise ValueError(f"Unknown eBay environment '{self.env}'. Use 'sandbox' or 'production'.")
        if not self.client_id or not self.client_secret:
            raise ValueError(
                'eBay client ID and secret are required. '
                'Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET environment variables.'
            )
        self._endpoints = EBAY_ENDPOINTS[self.env]
        self._token: EbayOAuthToken | None = None
        self._session = requests.Session()
        self._token_expiry_buffer = 120  # seconds before expiry we consider it stale

    def _basic_auth_header(self) -> str:
        raw = f'{self.client_id}:{self.client_secret}'
        return f'Basic {base64.b64encode(raw.encode()).decode()}'

    def _fetch_token(self) -> EbayOAuthToken:
        """Obtain a client-credentials OAuth token (Application Access Token)."""
        resp = requests.post(
            self._endpoints['oauth'],
            headers={
                'Authorization': self._basic_auth_header(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data={
                'grant_type': 'client_credentials',
                'scope': BROWSE_SCOPE,
            },
            timeout=30,
        )
        if not resp.ok:
            detail = resp.text[:500]
            raise RuntimeError(f'eBay OAuth failed (HTTP {resp.status_code}): {detail}')
        body = resp.json()
        access_token = body['access_token']
        expires_in = body.get('expires_in', 7200)
        expires_at = time.time() + expires_in - self._token_expiry_buffer
        logger.info('Obtained eBay OAuth token (expires in %s s, valid until %.0f)', expires_in, expires_at)
        return EbayOAuthToken(access_token=access_token, expires_at=expires_at)

    def _ensure_token(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at:
            self._token = self._fetch_token()
        return self._token.access_token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Make an authenticated request to the Browse API."""
        token = self._ensure_token()
        url = f'{self._endpoints["browse"]}{path}'
        headers = {
            'Authorization': f'Bearer {token}',
            'X-EBAY-C-MARKETPLACE-ID': 'EBAY_GB',
            'Accept': 'application/json',
        }
        headers.update(kwargs.pop('headers', {}))
        resp = self._session.request(method, url, headers=headers, timeout=kwargs.pop('timeout', 30), **kwargs)
        if not resp.ok:
            detail = resp.text[:500]
            raise RuntimeError(f'eBay Browse API error (HTTP {resp.status_code}): {detail}')
        return resp.json()

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        sold_items: bool = True,
        completed_items: bool = True,
    ) -> dict[str, Any]:
        """Search eBay UK listings via the Browse API (item_summary/search endpoint).

        Args:
            query: Free-text search query.
            limit: Max results (1–200).

        Returns:
            The raw Browse API response dict with 'itemSummaries' key.
        """
        params: dict[str, str] = {
            'q': query,
            'limit': str(min(max(limit, 1), 200)),
        }

        return self._request('GET', '/item_summary/search', params=params)

    def get_item(self, item_id: str) -> dict[str, Any]:
        """Get a single item by its eBay item ID."""
        return self._request('GET', f'/item/{item_id}')


def parse_api_listings(
    response: dict[str, Any],
    card_id: str,
    language_code: str | None,
    card_name: str,
    collector_number: str | None = None,
    set_name: str | None = None,
    set_code: str | None = None,
    *,
    raw_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Parse eBay Browse API search results into a reusable row format.

    Returns (listings, failures) where each listing dict has the same
    field names expected by the scraper's CSV/insert logic.
    """
    from pokemon_db_v3_ebay_uk_price_scraper import extract_condition, score_listing

    listings: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    summaries = response.get('itemSummaries', [])
    for item in summaries:
        title = (item.get('title') or '').strip()
        if not title:
            continue

        # Price
        price_info = item.get('price') or {}
        price_value = price_info.get('value')
        if price_value is None:
            failures.append({'reason': 'missing_price', 'raw_title': title, 'listing_url': item.get('itemWebUrl', '')})
            continue

        price_gbp = float(price_value)

        # Sold / ended date — use itemEndDate if available
        sold_date_raw = item.get('itemEndDate', '')
        if sold_date_raw:
            sold_date = sold_date_raw[:10]
        else:
            sold_date = time.strftime('%Y-%m-%d')

        # Condition
        condition = item.get('condition') or item.get('conditionId', '')
        if isinstance(condition, str) and condition:
            pass  # Use API-provided condition string
        else:
            condition = extract_condition(title)

        listing_url = (item.get('itemWebUrl') or '').split('?')[0]

        # Confidence scoring
        card_seed = _make_card_seed(
            card_id=card_id,
            language_code=language_code,
            card_name=card_name,
            collector_number=collector_number,
            set_name=set_name,
            set_code=set_code,
        )
        score, notes = score_listing(card_seed, title, raw_only=raw_only)

        row = {
            'card_id': card_id,
            'language_code': language_code,
            'card_name': card_name,
            'collector_number': collector_number,
            'set_name': set_name,
            'query': '',
            'condition': condition,
            'price_gbp': price_gbp,
            'sold_date': sold_date,
            'listing_url': listing_url,
            'source': 'ebay_uk',
            'confidence_score': score,
            'raw_title': title,
            'match_notes': ';'.join(notes),
        }
        listings.append(row)
        if score < 0.45:
            failures.append({'reason': f'low_confidence_{score}', 'raw_title': title, 'listing_url': listing_url})
    return listings, failures


def _make_card_seed(**kwargs: Any) -> Any:
    from dataclasses import dataclass as _dc

    @_dc(frozen=True)
    class _CardSeed:
        card_id: str
        language_code: str | None
        card_name: str
        collector_number: str | None
        set_name: str | None
        set_code: str | None

    return _CardSeed(**kwargs)
