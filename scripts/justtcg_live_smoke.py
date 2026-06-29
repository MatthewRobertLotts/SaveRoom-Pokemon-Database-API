#!/usr/bin/env python3
"""JustTCG one-card live smoke test.

Makes exactly one JustTCG API request to verify connectivity,
payload shape, and identifier mapping. Saves raw and sanitized
payloads to private_provider_payloads/ (outside Git).

Usage:
    # Set env flags first (see .env.example for full list)
    export POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY=your_key
    export POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_NORMALIZED_STORAGE=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_INTERNAL_DISPLAY=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_CUSTOMER_DISPLAY=true
    export POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE=true
    # DO NOT set ALLOW_EXTERNAL_API_RESALE=true

    python scripts/justtcg_live_smoke.py

Safety:
- Access gate is checked FIRST. Script exits if not configured.
- Raw payload saved to private_provider_payloads/justtcg/ (git-ignored).
- Sanitized candidate saved alongside.
- API key is never logged or printed.
- Only ONE request is made.
- No data committed to Git.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path so pricing_sources can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ── Paths ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = PROJECT_ROOT / "private_provider_payloads" / "justtcg"
SANITIZED_DIR = PRIVATE_DIR / "sanitized_candidates"

# ── Access gate check ─────────────────────────────────────────────────

def check_access_gate() -> dict[str, str]:
    """Verify all required env flags are set. Returns config dict."""
    config = dict(os.environ)

    required = [
        "POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY",
        "POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED",
        "POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED",
    ]

    missing = [k for k in required if not config.get(k, "").strip()]
    if missing:
        print(f"BLOCKED: Missing required env flags: {missing}")
        print("Configure them before running the live smoke test.")
        print("See .env.example for the full list.")
        sys.exit(1)

    # Verify gate passes
    from pricing_sources.provider_access import require_provider_live_access
    try:
        require_provider_live_access("justtcg", config)
    except PermissionError as e:
        print(f"BLOCKED: Access gate denied: {e}")
        sys.exit(1)

    # Check resale flag is NOT true
    resale = config.get("POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_EXTERNAL_API_RESALE", "false")
    if resale.lower() in ("true", "1", "yes"):
        print("BLOCKED: ALLOW_EXTERNAL_API_RESALE must remain false per JustTCG terms.")
        sys.exit(1)

    return config


# ── Live request ──────────────────────────────────────────────────────

def make_one_card_request(config: dict[str, str]) -> dict:
    """Make exactly one JustTCG API request. Returns raw response dict."""
    api_key = config["POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY"]
    base_url = "https://api.justtcg.com/v1"

    # Use a targeted query: specific card (Charizard from Base Set)
    # with condition/printing to avoid sealed products and loose matches.
    url = f"{base_url}/cards?game=pokemon&set=base1&name=Charizard&condition=NM&printing=Normal&limit=1"

    print(f"Requesting: GET {url}")
    print("(API key is included in header but never printed)")

    req = Request(url)
    req.add_header("x-api-key", api_key)
    req.add_header("Accept", "application/json")
    # Cloudflare blocks default Python UA; send a browser-like one
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    try:
        with urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"HTTP Error {e.code}: {e.reason}")
        # Print non-secret error details
        try:
            error_data = json.loads(body)
            for k, v in error_data.items():
                if k.lower() not in ("authorization", "x-api-key"):
                    print(f"  {k}: {v}")
        except json.JSONDecodeError:
            print(f"  Body (truncated): {body[:200]}")
        sys.exit(1)
    except URLError as e:
        print(f"Network Error: {e.reason}")
        sys.exit(1)


# ── Save raw ─────────────────────────────────────────────────────────

def save_raw(raw: dict) -> Path:
    """Save raw payload to private directory."""
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = PRIVATE_DIR / f"live_smoke_raw_{ts}.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


# ── Sanitize ──────────────────────────────────────────────────────────

def sanitize(raw: dict) -> dict:
    """Create a sanitized copy suitable for future fixture use."""
    # Deep copy
    sanitized = json.loads(json.dumps(raw))

    # Remove account/quota metadata
    sanitized.pop("_metadata", None)

    # Strip rate-limit / account info from any nested structures
    def strip_meta(obj):
        if isinstance(obj, dict):
            obj.pop("apiPlan", None)
            obj.pop("apiRequestsRemaining", None)
            obj.pop("apiDailyRequestsRemaining", None)
            obj.pop("apiRateLimit", None)
            obj.pop("accountId", None)
            obj.pop("subscriptionId", None)
            for v in obj.values():
                strip_meta(v)
        elif isinstance(obj, list):
            for v in obj:
                strip_meta(v)

    strip_meta(sanitized)

    # Add provenance label
    sanitized["_sanitized"] = {
        "source": "justtcg",
        "sanitized_at": datetime.now(timezone.utc).isoformat(),
        "sanitized_by": "justtcg_live_smoke.py",
        "contains_real_provider_data": True,
        "permission_basis": "JustTCG terms approved 2026-06-29; fixture storage allowed",
        "note": "Sanitized live payload with account metadata removed. NOT yet committed to Git.",
    }

    return sanitized


def save_sanitized(sanitized: dict) -> Path:
    """Save sanitized candidate to private directory."""
    SANITIZED_DIR.mkdir(parents=True, exist_ok=True)
    path = SANITIZED_DIR / "justtcg_live_smoke_sanitized_candidate.json"
    path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    return path


# ── Inspect ───────────────────────────────────────────────────────────

def inspect(raw: dict) -> None:
    """Print non-secret metadata about the response."""
    print("\n" + "=" * 60)
    print("RESPONSE INSPECTION")
    print("=" * 60)

    # Top-level keys
    print(f"Top-level keys: {sorted(raw.keys())}")

    # Meta
    meta = raw.get("meta", {})
    print(f"Meta: total={meta.get('total')}, limit={meta.get('limit')}, hasMore={meta.get('hasMore')}")

    # Cards
    cards = raw.get("data", [])
    if not isinstance(cards, list):
        cards = [cards] if isinstance(cards, dict) else []
    print(f"Card count: {len(cards)}")

    for i, card in enumerate(cards[:3]):
        if not isinstance(card, dict):
            continue
        print(f"\n  Card {i}:")
        print(f"    uuid: {card.get('uuid', 'N/A')}")
        print(f"    name: {card.get('name', 'N/A')}")
        print(f"    game: {card.get('game', 'N/A')}")
        print(f"    set: {card.get('set', 'N/A')} ({card.get('set_name', 'N/A')})")
        print(f"    number: {card.get('number', 'N/A')}")
        print(f"    tcgplayerId: {card.get('tcgplayerId', 'N/A')}")
        print(f"    rarity: {card.get('rarity', 'N/A')}")

        variants = card.get("variants", [])
        print(f"    Variants: {len(variants)}")
        for j, v in enumerate(variants[:3]):
            if not isinstance(v, dict):
                continue
            print(f"      Variant {j}:")
            print(f"        uuid: {v.get('uuid', 'N/A')}")
            print(f"        condition: {v.get('condition', 'N/A')}")
            print(f"        printing: {v.get('printing', 'N/A')}")
            print(f"        language: {v.get('language', 'N/A')}")
            print(f"        tcgplayerSkuId: {v.get('tcgplayerSkuId', 'N/A')}")
            print(f"        price: {v.get('price', 'N/A')}")
            print(f"        lastUpdated: {v.get('lastUpdated', 'N/A')}")
            has_history = "priceHistory" in v
            print(f"        has_priceHistory: {has_history}")

    # Account metadata (non-secret)
    acct_meta = raw.get("_metadata", {})
    if acct_meta:
        print(f"\n  Account metadata keys: {sorted(acct_meta.keys())}")
        # Print non-identifying fields only
        for k in ("apiPlan", "apiRateLimit"):
            if k in acct_meta:
                print(f"    {k}: {acct_meta[k]}")

    # ── Sealed-product detection ─────────────────────────────────────
    print("\n  Sealed-product check:")
    SEALED_CONDITIONS = {"Sealed"}
    SEALED_NAME_MARKERS = [
        "booster box", "booster pack", "etb", "elite trainer box",
        "display", "tin", "blister", "bundle",
    ]
    for card in cards:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name", "")).lower()
        variants = card.get("variants", [])
        for v in variants:
            if not isinstance(v, dict):
                continue
            condition = str(v.get("condition", ""))
            is_sealed_condition = condition in SEALED_CONDITIONS
            is_sealed_name = any(marker in name for marker in SEALED_NAME_MARKERS)
            if is_sealed_condition or is_sealed_name:
                print(f"    WARNING: Result appears to be sealed product, not an individual card.")
                print(f"    Card: {card.get('name')} | Condition: {condition}")
                print(f"    Do not use as card fixture.")
                return

    print("    OK: Result appears to be individual card(s).")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("JustTCG One-Card Live Smoke Test")
    print("=" * 40)

    # Step 1: Check access gate
    print("\n1. Checking access gate...")
    config = check_access_gate()
    print("   Access gate: PASS")

    # Step 2: Make one request
    print("\n2. Making one live request...")
    raw = make_one_card_request(config)
    print("   Request: SUCCESS")

    # Step 3: Save raw
    print("\n3. Saving raw payload...")
    raw_path = save_raw(raw)
    print(f"   Saved to: {raw_path}")

    # Step 4: Inspect
    print("\n4. Inspecting response...")
    inspect(raw)

    # Step 5: Sanitize
    print("\n5. Creating sanitized candidate...")
    sanitized = sanitize(raw)
    sanitized_path = save_sanitized(sanitized)
    print(f"   Saved to: {sanitized_path}")

    # Step 6: Safety reminder
    print("\n" + "=" * 60)
    print("SAFETY REMINDER")
    print("=" * 60)
    print(f"Raw payload: {raw_path} (git-ignored)")
    print(f"Sanitized:   {sanitized_path} (git-ignored)")
    print("Neither file is tracked by Git.")
    print("Do not commit raw or sanitized provider payloads without review.")
    print("The sanitized candidate requires manual review before moving to tests/fixtures/.")


if __name__ == "__main__":
    main()
