"""Observation-to-identity matching and confidence scoring.

Matches normalised observations to v10 canonical printings, commercial
variants, and sellable SKUs using set code + collector number.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from pricing_sources.base import MatchConfidence


def find_canonical_printing(
    conn: sqlite3.Connection,
    set_code: str | None,
    collector_number: str | None,
    card_name: str | None = None,
    language: str | None = None,
) -> list[tuple[str, MatchConfidence, str]]:
    """Find canonical printings matching the given identity.

    Returns list of (canonical_printing_id, confidence, reason).
    """
    cur = conn.cursor()

    # Exact match: set_code + collector_number
    if set_code and collector_number:
        cur.execute(
            """SELECT canonical_printing_id, canonical_name
            FROM v10_canonical_printings
            WHERE set_code = ? AND collector_number = ?
            LIMIT 5""",
            (set_code, collector_number),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.HIGH, f"exact set_code={set_code} + number={collector_number}")
                for row in rows
            ]

    # Match: set_code + name
    if set_code and card_name:
        cur.execute(
            """SELECT canonical_printing_id, canonical_name
            FROM v10_canonical_printings
            WHERE set_code = ? AND (canonical_name LIKE ? OR name_english LIKE ?)
            LIMIT 5""",
            (set_code, f"%{card_name}%", f"%{card_name}%"),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.MEDIUM, f"set_code={set_code} + name match={card_name}")
                for row in rows
            ]

    # Name-only match
    if card_name:
        cur.execute(
            """SELECT canonical_printing_id, canonical_name
            FROM v10_canonical_printings
            WHERE canonical_name LIKE ? OR name_english LIKE ?
            LIMIT 10""",
            (f"%{card_name}%", f"%{card_name}%"),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.LOW, f"name-only match={card_name}")
                for row in rows
            ]

    return []


def find_commercial_variant(
    conn: sqlite3.Connection,
    canonical_printing_id: str,
    language: str | None = None,
    finish: str | None = None,
) -> list[tuple[str, MatchConfidence, str]]:
    """Find commercial variants for a canonical printing.

    Returns list of (commercial_variant_id, confidence, reason).
    """
    cur = conn.cursor()

    if language and finish and finish != "unknown":
        # Specific language + finish filter
        cur.execute(
            """SELECT commercial_variant_id, finish, language_code
            FROM v10_commercial_variants
            WHERE canonical_printing_id = ? AND language_code = ? AND finish = ?
            LIMIT 5""",
            (canonical_printing_id, language, finish),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.HIGH, f"canonical={canonical_printing_id} + lang={language} + finish={row[1]}")
                for row in rows
            ]
        # No match with this specific finish — try same language, any finish
        cur.execute(
            """SELECT commercial_variant_id, finish, language_code
            FROM v10_commercial_variants
            WHERE canonical_printing_id = ? AND language_code = ?
            LIMIT 5""",
            (canonical_printing_id, language),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.LOW, f"canonical={canonical_printing_id} + lang={language}, finish mismatch (wanted {finish}, got {row[1]})")
                for row in rows
            ]
        return []

    if language:
        # Language filter only (finish is unknown or None)
        cur.execute(
            """SELECT commercial_variant_id, finish, language_code
            FROM v10_commercial_variants
            WHERE canonical_printing_id = ? AND language_code = ?
            LIMIT 5""",
            (canonical_printing_id, language),
        )
        rows = cur.fetchall()
        if rows:
            return [
                (row[0], MatchConfidence.MEDIUM, f"canonical={canonical_printing_id} + lang={language}, finish unknown")
                for row in rows
            ]
        return []

    # No language filter — return all variants for this canonical
    cur.execute(
        """SELECT commercial_variant_id, finish, language_code
        FROM v10_commercial_variants
        WHERE canonical_printing_id = ?
        LIMIT 10""",
        (canonical_printing_id,),
    )
    rows = cur.fetchall()
    return [
        (row[0], MatchConfidence.LOW, f"canonical={canonical_printing_id}, no lang/finish match")
        for row in rows
    ]


def find_sellable_sku(
    conn: sqlite3.Connection,
    commercial_variant_id: str,
    condition: str | None = None,
) -> list[tuple[str, MatchConfidence, str]]:
    """Find sellable SKUs for a commercial variant.

    Returns list of (sellable_sku_id, confidence, reason).
    """
    cur = conn.cursor()

    cur.execute(
        """SELECT sellable_sku_id, item_class
        FROM v10_sellable_skus
        WHERE commercial_variant_id = ?
        LIMIT 5""",
        (commercial_variant_id,),
    )
    rows = cur.fetchall()
    return [
        (row[0], MatchConfidence.MEDIUM, f"variant={commercial_variant_id}")
        for row in rows
    ]


def match_observation_to_identity(
    conn: sqlite3.Connection,
    set_code: str | None,
    collector_number: str | None,
    card_name: str | None = None,
    language: str | None = None,
    finish: str | None = None,
) -> dict[str, Any]:
    """Full matching pipeline: canonical → variant → SKU.

    Returns a dict with match results and confidence.
    """
    result: dict[str, Any] = {
        "canonical_printings": [],
        "commercial_variants": [],
        "sellable_skus": [],
    }

    # Step 1: Find canonical printings
    canonical_matches = find_canonical_printing(
        conn, set_code, collector_number, card_name, language
    )
    result["canonical_printings"] = [
        {"id": cp_id, "confidence": conf.value, "reason": reason}
        for cp_id, conf, reason in canonical_matches
    ]

    if not canonical_matches:
        return result

    # Step 2: For each canonical, find variants
    for cp_id, cp_conf, cp_reason in canonical_matches:
        variant_matches = find_commercial_variant(
            conn, cp_id, language, finish
        )
        result["commercial_variants"].extend([
            {"id": cv_id, "confidence": conf.value, "reason": reason, "canonical_id": cp_id}
            for cv_id, conf, reason in variant_matches
        ])

        # Step 3: For each variant, find SKUs
        for cv_id, cv_conf, cv_reason in variant_matches:
            sku_matches = find_sellable_sku(conn, cv_id, condition=None)
            result["sellable_skus"].extend([
                {"id": sku_id, "confidence": conf.value, "reason": reason, "variant_id": cv_id}
                for sku_id, conf, reason in sku_matches
            ])

    return result


def determine_match_confidence(
    set_code_match: bool,
    number_match: bool,
    name_match: bool,
    finish_match: bool,
    language_match: bool,
) -> tuple[MatchConfidence, str]:
    """Determine overall match confidence from individual factors.

    Returns (confidence, reason).
    """
    if set_code_match and number_match and finish_match and language_match:
        return MatchConfidence.HIGH, "exact set+number+finish+language"
    elif set_code_match and number_match and finish_match:
        return MatchConfidence.HIGH, "exact set+number+finish"
    elif set_code_match and number_match:
        return MatchConfidence.MEDIUM, "exact set+number, finish/language unknown"
    elif set_code_match and name_match:
        return MatchConfidence.MEDIUM, "set+name match, number unknown"
    elif name_match:
        return MatchConfidence.LOW, "name-only match"
    else:
        return MatchConfidence.UNUSABLE, "no reliable match"
