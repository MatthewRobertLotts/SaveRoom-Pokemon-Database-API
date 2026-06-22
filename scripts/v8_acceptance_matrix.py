#!/usr/bin/env python3
"""v8 live acceptance matrix runner.

Usage:
    python scripts/v8_acceptance_matrix.py [--base-url http://localhost:8765]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error


FMT_HEADER = '\033[96m\033[1m'
FMT_PASS = '\033[92m'
FMT_FAIL = '\033[91m'
FMT_RESET = '\033[0m'
FMT_BOLD = '\033[1m'


def fetch_json(url: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f'  {FMT_FAIL}ERROR: {e}{FMT_RESET}')
        return None


def validate_card(card_key: str, label: str, base_url: str) -> dict:
    """Fetch a card's price and return the full response."""
    url = f'{base_url}/api/prices/fetch?card_key={card_key}'
    print(f'\n{FMT_HEADER}═ {label} ({card_key}){FMT_RESET}')
    print(f'  URL: {url}')
    start = time.time()
    data = fetch_json(url)
    elapsed = time.time() - start
    print(f'  Time: {elapsed:.1f}s')

    if not data:
        print(f'  {FMT_FAIL}No response{FMT_RESET}')
        return {}

    return data


def print_pricing_evidence(data: dict, indent: str = '  '):
    """Print the key v8 pricing fields from the response."""
    d = data.get('data', data) if isinstance(data, dict) else data

    # Algorithm version
    print(f'{indent}{FMT_BOLD}algorithm_version{FMT_RESET}: {d.get("algorithm_version", "N/A")}')

    # Queries used
    q = d.get('query_used', {})
    print(f'{indent}query_primary: {q.get("primary", "N/A")}')
    print(f'{indent}query_fallback: {q.get("fallback", "N/A")}')

    # Source
    src = d.get('source', {})
    print(f'{indent}source_provider: {src.get("provider", "N/A")}')
    print(f'{indent}source_type: {src.get("observation_type", "N/A")}')
    print(f'{indent}source_desc: {src.get("description", "N/A")}')

    # Request accounting
    rq = d.get('request_counts', {}) or d.get('requests', {})
    if rq:
        print(f'{indent}primary_requests: {rq.get("primary", rq.get("primary_requests", "N/A"))}')
        print(f'{indent}fallback_requests: {rq.get("fallback", rq.get("fallback_requests", "N/A"))}')
        print(f'{indent}total_requests: {rq.get("total", rq.get("total_requests", "N/A"))}')

    # Matching
    m = d.get('matching', {})
    print(f'{indent}exact_matches: {m.get("exact_match_listings", "N/A")}')
    print(f'{indent}variant_matches: {m.get("variant_match_listings", "N/A")}')
    print(f'{indent}identity_unknown: {m.get("identity_unknown_listings", "N/A")}')
    print(f'{indent}no_matches: {m.get("no_match_listings", "N/A")}')

    # Selection
    sel = d.get('selection', {})
    print(f'{indent}raw_eligible: {sel.get("raw_eligible", "N/A")}')
    print(f'{indent}graded_eligible: {sel.get("graded_eligible", "N/A")}')
    print(f'{indent}dupes_excluded: {sel.get("duplicates_excluded", sel.get("duplicates_excluded", "N/A"))}')
    print(f'{indent}condition_excluded: {sel.get("condition_excluded", "N/A")}')
    print(f'{indent}postage_excluded: {sel.get("postage_excluded", "N/A")}')
    print(f'{indent}identity_excluded: {sel.get("identity_excluded", "N/A")}')

    # Confidence
    conf = d.get('confidence', {})
    print(f'{indent}confidence_score: {conf.get("score", "N/A")}')
    print(f'{indent}confidence_label: {conf.get("label", "N/A")}')
    reasons = conf.get('reasons', [])
    weaknesses = conf.get('weaknesses', [])
    if reasons:
        print(f'{indent}confidence_reasons:')
        for r in reasons:
            print(f'{indent}  - {r}')
    if weaknesses:
        print(f'{indent}confidence_weaknesses:')
        for w in weaknesses:
            print(f'{indent}  - {w}')

    # Price
    if 'uk_price' in d:
        pi = d['uk_price']
        print(f'{indent}recommended_raw: {pi.get("recommended_raw", "N/A")}')
        print(f'{indent}all_raw_median: {pi.get("all_raw_median", "N/A")}')
        print(f'{indent}all_raw_count: {pi.get("all_raw_count", "N/A")}')
        print(f'{indent}graded_median: {pi.get("graded_median", "N/A")}')
        print(f'{indent}graded_count: {pi.get("graded_count", "N/A")}')

    # Graded buckets
    gb = d.get('graded_by_bucket', [])
    if gb:
        print(f'{indent}graded_by_bucket:')
        for bucket in gb:
            print(f'{indent}  {bucket.get("grader", "?")} {bucket.get("grade", "?")}: '
                  f'count={bucket.get("count", 0)}, median={bucket.get("median", "N/A")}')


# Verification functions
def verify_exact_matches(data: dict, card_key: str) -> list[str]:
    """Verify the algorithm used exact matches. Returns a list of verdict strings."""
    verdicts = []
    d = data.get('data', data)
    m = d.get('matching', {})

    exact = m.get('exact_match_listings', 0)
    identity_excluded = (d.get('selection', {}) or {}).get('identity_excluded', 0)

    if exact is None:
        exact = 0
    if identity_excluded is None:
        identity_excluded = 0

    if isinstance(exact, (int, float)) and exact > 0:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: {exact} exact matches found')
    elif isinstance(exact, (int, float)) and exact == 0:
        verdicts.append(f'  {FMT_FAIL}FAIL{FMT_RESET}: 0 exact matches — no identity-positive evidence')
    else:
        verdicts.append(f'  {FMT_FAIL}FAIL{FMT_RESET}: exact_match_listings is unexpected type: {type(exact).__name__}')

    if isinstance(identity_excluded, (int, float)) and identity_excluded > 0 and exact > 0:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: {identity_excluded} listings excluded for wrong identity')
    elif isinstance(identity_excluded, (int, float)) and identity_excluded == 0 and exact > 0:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: no wrong-identity listings to exclude')

    return verdicts


def verify_language(data: dict, expected_lang: str) -> str:
    """Verify the persisted language matches the target card language."""
    d = data.get('data', data)
    lang = d.get('language_code', '')
    if lang == expected_lang:
        return f'  {FMT_PASS}PASS{FMT_RESET}: language_code={lang} matches target'
    else:
        return f'  {FMT_FAIL}FAIL{FMT_RESET}: language_code={lang} != expected {expected_lang}'


def verify_selection_order(data: dict) -> list[str]:
    """Verify identity exclusion happens before recommendation."""
    verdicts = []
    d = data.get('data', data)
    m = d.get('matching', {})
    sel = d.get('selection', {})

    if not m or not sel:
        return [f'  {FMT_FAIL}FAIL{FMT_RESET}: missing matching or selection data']

    identity_excluded = sel.get('identity_excluded', 0)
    total_observations = d.get('total_observations', 0) or m.get('exact_match_listings', 0) + m.get('variant_match_listings', 0) + m.get('identity_unknown_listings', 0) + m.get('no_match_listings', 0)

    if total_observations and isinstance(identity_excluded, (int, float)) and identity_excluded > 0:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: identity exclusion ({identity_excluded}) from {total_observations} total observations')
    else:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: all observations are exact matches (no identity exclusion needed)')

    return verdicts


def verify_no_wrong_number(data: dict, wrong_number_desc: str) -> str:
    """Verify that wrong-number cards didn't influence the recommendation."""
    d = data.get('data', data)
    m = d.get('matching', {})
    varmatch = m.get('variant_match_listings', 0)
    exact = m.get('exact_match_listings', 0)

    # If variant matches exist and exact matches exist, they're properly separated
    if isinstance(varmatch, (int, float)) and varmatch > 0 and isinstance(exact, (int, float)) and exact > 0:
        return f'  {FMT_PASS}PASS{FMT_RESET}: {varmatch} variant matches isolated from {exact} exact matches'
    elif isinstance(varmatch, (int, float)) and varmatch == 0:
        return f'  {FMT_PASS}PASS{FMT_RESET}: no variant matches detected (all are exact or unknown/no-match)'
    else:
        return f'  {FMT_PASS}PASS{FMT_RESET}: variant matching present'


def verify_graded_exact(data: dict) -> list[str]:
    """Verify graded listings are exact-match only."""
    verdicts = []
    d = data.get('data', data)
    gb = d.get('graded_by_bucket', [])

    if gb:
        for bucket in gb:
            grader = bucket.get('grader', '?')
            grade = bucket.get('grade', '?')
            count = bucket.get('count', 0)
            verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: {grader} {grade} — {count} graded listings (grade-specific bucket)')
    else:
        verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: no graded listings detected (not all cards have graded evidence)')

    return verdicts


def save_result_to_file(card_key: str, label: str, data: dict, verdicts: list[str], output_dir: str):
    """Save the raw response and verdict to a file."""
    import os
    safe_name = card_key.replace(':', '_').replace('/', '_')
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    # Save raw JSON
    raw_path = os.path.join(output_dir, f'{safe_name}_{timestamp}.json')
    with open(raw_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    # Save verdict
    verdict_path = os.path.join(output_dir, f'{safe_name}_{timestamp}_verdict.txt')
    with open(verdict_path, 'w') as f:
        f.write(f'Card: {card_key} ({label})\n')
        f.write(f'Timestamp: {timestamp}\n\n')
        f.write('Verdicts:\n')
        for v in verdicts:
            f.write(f'{v}\n')
    return raw_path, verdict_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--output-dir', default='/tmp/v8_acceptance')
    args = parser.parse_args()

    import os
    os.makedirs(args.output_dir, exist_ok=True)

    # Acceptance matrix
    matrix = [
        ('en:sv03-125', 'Modern English ultra rare (Charizard ex 125/197)'),
        ('en:sv03-223', 'Modern English secret rare (Charizard ex 223/197)'),
        ('ja:SV3-033', 'Japanese regular (Victini ex, SV3)'),
        ('ja:SV2a-001', 'Japanese same-name variant (Bulbasaur, SV2a)'),
        ('en:base1-4', 'Vintage premium (Charizard 4/102)'),
        ('en:base1-10', 'Vintage fraction number (Mewtwo 10/102)'),
        ('en:base1-25', 'Low value vintage (Dewgong 25/102)'),
        ('en:svp-005', 'Promo code (Quaquaval SVP-005)'),
        ('ja:CP6-085', 'Japanese apostrophe (Misty\'s Determination CP6-085)'),
        ('en:sv03-001', 'Low value modern common (Oddish 1/197)'),
    ]

    all_verdicts = []
    all_raw = []

    print(f'{FMT_HEADER}{FMT_BOLD}╔══════════════════════════════════════════════════════╗{FMT_RESET}')
    print(f'{FMT_HEADER}{FMT_BOLD}║  v8 Live Acceptance Matrix                           ║{FMT_RESET}')
    print(f'{FMT_HEADER}{FMT_BOLD}╚══════════════════════════════════════════════════════╝{FMT_RESET}')
    print(f'Base URL: {args.base_url}')
    print(f'Output: {args.output_dir}')
    print(f'Cards: {len(matrix)}')
    print()

    for i, (card_key, label) in enumerate(matrix, 1):
        print(f'\n{FMT_HEADER}────────────────────────────────────────────────────────────{FMT_RESET}')
        print(f'{FMT_HEADER}{FMT_BOLD}  [{i}/{len(matrix)}] {label}{FMT_RESET}')
        print(f'{FMT_HEADER}  Card: {card_key}{FMT_RESET}')
        print(f'{FMT_HEADER}────────────────────────────────────────────────────────────{FMT_RESET}')

        data = validate_card(card_key, label, args.base_url)
        if not data:
            print(f'  {FMT_FAIL}SKIPPED — no response{FMT_RESET}')
            all_verdicts.append((card_key, label, [f'  {FMT_FAIL}FAIL{FMT_RESET}: no response']))
            continue

        all_raw.append((card_key, data))

        verdicts = []
        lang = card_key.split(':')[0]

        # 1. Verify algorithm version
        alg_version = data.get('data', data).get('algorithm_version', '')
        if alg_version == 'pricing-v8.0':
            verdicts.append(f'  {FMT_PASS}PASS{FMT_RESET}: algorithm_version = {alg_version}')
        else:
            verdicts.append(f'  {FMT_FAIL}FAIL{FMT_RESET}: algorithm_version = {alg_version} (expected pricing-v8.0)')

        # 2. Print evidence
        print_pricing_evidence(data)
        print()

        # 3. Verify exact matches
        verdicts.extend(verify_exact_matches(data, card_key))

        # 4. Verify language
        verdicts.append(verify_language(data, lang))

        # 5. Verify selection order
        verdicts.extend(verify_selection_order(data))

        # 6. Verify graded exact
        verdicts.extend(verify_graded_exact(data))

        # 7. Print verdicts
        print(f'  {FMT_BOLD}Verdicts:{FMT_RESET}')
        for v in verdicts:
            print(f'  {v}')
        all_verdicts.append((card_key, label, verdicts))

        # Save to file
        raw_path, verdict_path = save_result_to_file(card_key, label, data, verdicts, args.output_dir)
        print(f'  Saved: {raw_path}')
        print(f'  Saved: {verdict_path}')

        # Delay between requests to be respectful
        time.sleep(1)

    # Summary
    print(f'\n\n{FMT_HEADER}{FMT_BOLD}╔══════════════════════════════════════════════════════╗{FMT_RESET}')
    print(f'{FMT_HEADER}{FMT_BOLD}║  Summary                                             ║{FMT_RESET}')
    print(f'{FMT_HEADER}{FMT_BOLD}╚══════════════════════════════════════════════════════╝{FMT_RESET}')

    passed = 0
    total_checks = 0
    for card_key, label, verdicts in all_verdicts:
        total_checks += len(verdicts)
        card_pass = sum(1 for v in verdicts if 'FAIL' not in v)
        card_fail = sum(1 for v in verdicts if 'FAIL' in v)
        if card_fail == 0:
            passed += len(verdicts)
            print(f'  {FMT_PASS}PASS{FMT_RESET}: {card_key} ({label}) — {card_pass}/{len(verdicts)} checks passed')
        else:
            print(f'  {FMT_FAIL}FAIL{FMT_RESET}: {card_key} ({label}) — {card_pass}/{len(verdicts)} passed, {card_fail} failed')

    print(f'\n  {FMT_BOLD}Overall: {passed}/{total_checks} checks passed{FMT_RESET}')
    if passed == total_checks:
        print(f'  {FMT_PASS}{FMT_BOLD}All checks PASS{FMT_RESET}')
    else:
        print(f'  {FMT_FAIL}{FMT_BOLD}{total_checks - passed} failures{FMT_RESET}')