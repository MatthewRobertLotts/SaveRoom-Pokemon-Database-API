#!/usr/bin/env python3
"""Recover exact English display images from set-scoped sources only.

Safety rules:
- Never search globally by card name.
- Only use a source when the DB set maps to the same English set id/name.
- Match cards by source set + local/collector number (with small documented
  promo/classic numbering normalizations).
- Write a manifest for pokemon_db_v2_apply_recovered_images.py; do not mutate DB.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
REPORTS = DB.parent / 'reports'
OUT_ROOT = ROOT / 'recovered_images' / dt.datetime.now(dt.UTC).strftime('%Y-%m-%d') / 'en'
GH_BASE = 'https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master'
CANDIDATE_TYPE = 'exact_ptcg_io_set'
TCGDEX_CANDIDATE_TYPE = 'exact_tcgdex_set_api_recovered_asset'
LIMITLESS_POCKET_CANDIDATE_TYPE = 'exact_limitless_tcg_pocket_asset'
PKMNCARDS_CANDIDATE_TYPE = 'exact_pkmncards_asset'
DITTOBASE_CANDIDATE_TYPE = 'exact_dittobase_asset'
CARDSREALM_CANDIDATE_TYPE = 'exact_cardsrealm_asset'

# TCGdex/DB set ids that do not equal the PokemonTCG.io JSON set id.
MANUAL_PTCG_SET_MAP = {
    'sm7.5': 'sm75',
    '2011bw': 'mcd11',
    '2012bw': 'mcd12',
    '2014xy': 'mcd14',
    '2015xy': 'mcd15',
    '2016xy': 'mcd16',
    '2017sm': 'mcd17',
    '2018sm': 'mcd18',
    '2019sm': 'mcd19',
    '2021swsh': 'mcd21',
    '2022swsh': 'mcd22',
    'rc': 'g1',
}

# Extra exact set ids present in PokemonTCG.io that share DB set rows.
# These are still set-scoped, not name-global.
EXTRA_PTCG_SET_IDS = {
    'cel25': ['cel25c'],  # Celebrations Classic Collection subset.
}


def fetch_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes SaveRoom image recovery/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_bytes(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes SaveRoom image recovery/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get('content-type', '')


def norm_text(s: str | None) -> str:
    s = (s or '').lower().replace('’', "'").replace('é', 'e')
    return re.sub(r'[^a-z0-9]+', '', s)


def norm_num(s: str | None) -> str:
    s = (s or '').strip()
    return s.upper().lstrip('0') or s.upper()


def num_base(s: str | None) -> str:
    m = re.match(r'0*([0-9]+)', (s or '').strip())
    return str(int(m.group(1))) if m else norm_num(s)


def local_id_variants(local_id: str) -> list[str]:
    raw = (local_id or '').strip()
    out = [raw]
    if raw.isdigit():
        out.append(str(int(raw)))
        out.append(raw.zfill(3))
    # Celebrations Classic-style DB ids: 15A2 -> PokemonTCG id suffix 15_A2.
    m = re.match(r'^(\d+)[Aa](\d*)$', raw)
    if m:
        out.append(f"{int(m.group(1))}_A{m.group(2)}" if m.group(2) else f"{int(m.group(1))}_A")
        out.append(str(int(m.group(1))))
    # Keep order, unique.
    seen = set(); uniq = []
    for x in out:
        if x and x not in seen:
            seen.add(x); uniq.append(x)
    return uniq


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def card_matches_local(src: dict[str, Any], local_id: str, db_name: str) -> bool:
    variants = {norm_num(v) for v in local_id_variants(local_id)}
    src_number = src.get('number') or src.get('localId') or ''
    src_suffix = src.get('id', '').split('-', 1)[-1]
    if norm_num(src_number) in variants or norm_num(src_suffix) in variants:
        return True
    # Classic Collection card ids encode the variant suffix while number is base.
    if num_base(src_number) == num_base(local_id):
        dbn = norm_text(db_name)
        srcn = norm_text(src.get('name'))
        return bool(dbn and srcn and (dbn == srcn or dbn in srcn or srcn in dbn))
    return False


def build_ptcg_set_map() -> dict[str, list[str]]:
    sets = fetch_json(f'{GH_BASE}/sets/en.json')
    by_name: dict[str, str] = {}
    for s in sets:
        by_name.setdefault(norm_text(s.get('name')), s['id'])
    mapping: dict[str, list[str]] = {}
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    for row in cur.execute("""
        SELECT DISTINCT resolved_set_id, resolved_set_name
        FROM v2_card_search
        WHERE language_code='en' AND has_display_image=0
    """):
        sid = row['resolved_set_id']; name = row['resolved_set_name']
        ids: list[str] = []
        if sid in MANUAL_PTCG_SET_MAP:
            ids.append(MANUAL_PTCG_SET_MAP[sid])
        if sid in by_name.values():
            ids.append(sid)
        byn = by_name.get(norm_text(name))
        if byn:
            ids.append(byn)
        ids.extend(EXTRA_PTCG_SET_IDS.get(sid, []))
        seen = set(); mapping[sid] = []
        for x in ids:
            if x and x not in seen:
                seen.add(x); mapping[sid].append(x)
    conn.close()
    return mapping


def load_cards_for_set(ptcg_set_id: str, cache: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if ptcg_set_id in cache:
        return cache[ptcg_set_id]
    try:
        cache[ptcg_set_id] = fetch_json(f'{GH_BASE}/cards/en/{ptcg_set_id}.json')
    except Exception:
        cache[ptcg_set_id] = []
    return cache[ptcg_set_id]


def tcgdex_asset_url(set_id: str, local_id: str) -> str | None:
    # TCG Pocket English assets live under /en/tcgp/<set>/<local>/high.webp
    if not re.match(r'^(A|B|P-|me)', set_id, re.I):
        return None
    local = local_id.strip()
    candidates = [local]
    if local.isdigit():
        candidates = [local.zfill(3), str(int(local))]
    for lid in candidates:
        url = f'https://assets.tcgdex.net/en/tcgp/{set_id}/{lid}/high.webp'
        try:
            status, data, ctype = fetch_bytes(url, timeout=20)
            if status == 200 and data and 'image' in ctype:
                return url
        except Exception:
            pass
    return None


def limitless_pocket_asset_url(set_id: str, local_id: str) -> str | None:
    """Return verified Limitless TCG Pocket English image URL for exact set/local."""
    if set_id not in {'B2a', 'P-A'}:
        return None
    if not local_id or not local_id.strip().isdigit():
        return None
    padded = f'{int(local_id.strip()):03d}'
    for suffix in ('EN.webp', 'EN_SM.webp'):
        url = f'https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/pocket/{set_id}/{set_id}_{padded}_{suffix}'
        try:
            status, data, ctype = fetch_bytes(url, timeout=20)
            if status == 200 and data and 'image' in ctype:
                return url
        except Exception:
            pass
    return None


def pkmncards_asset(set_id: str, local_id: str, name: str) -> tuple[str, str] | None:
    """Find a PkmnCards image using exact set code + collector number verification."""
    set_codes = {
        'svp': 'SVP',
        'mep': 'MEP',
        'swshp': 'SWSH',
        'hgssp': 'HGSS',
    }
    code = set_codes.get(set_id)
    if not code:
        return None
    local = (local_id or '').strip().upper()
    if not local:
        return None
    # Fast direct patterns for known modern promo image filenames.
    direct_patterns = []
    if set_id == 'mep' and local.isdigit():
        direct_patterns.append(f'https://pkmncards.com/wp-content/uploads/mebsp_en_{int(local):03d}_std.jpg')
    if set_id == 'svp' and local.isdigit():
        direct_patterns.append(f'https://pkmncards.com/wp-content/uploads/svbsp_en_{int(local):03d}_std.jpg')
    for url in direct_patterns:
        try:
            status, data, ctype = fetch_bytes(url, timeout=20)
            if status == 200 and data and 'image' in ctype:
                return url, url
        except Exception:
            pass

    query = urllib.parse.quote(f'{name} {code} {local}')
    search_url = f'https://pkmncards.com/?s={query}'
    try:
        html = fetch_text(search_url, timeout=20)
    except Exception:
        return None
    links = []
    for m in re.findall(r'https://pkmncards.com/card/[^"\']+', html):
        link = m.split('#', 1)[0]
        if link.endswith('/feed/'):
            continue
        if link not in links:
            links.append(link)
    for link in links[:5]:
        try:
            page = fetch_text(link, timeout=20)
        except Exception:
            continue
        # Verify page is exactly the desired set code and collector number.
        has_set_code = f'({code})' in page or f'#{local}' in page or local in link.upper()
        has_number = f'#{local}' in page or (local.isdigit() and f'#{int(local)}' in page)
        if not (has_set_code and has_number):
            continue
        if norm_text(name) and norm_text(name) not in norm_text(page[:20000]):
            continue
        imgs = re.findall(r'https://pkmncards.com/wp-content/uploads/[^"\'<> ]+?\.(?:jpg|png|jpeg|webp)', page)
        card_imgs = [u for u in imgs if 'favicon' not in u and 'clefairy' not in u and ('_std' in u or code.lower() in u.lower() or local.lower() in u.lower())]
        if card_imgs:
            return card_imgs[0], link
    return None


def fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes SaveRoom image recovery/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def slugify_name(name: str) -> str:
    s = name.lower().replace('’', '').replace("'", '').replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


def secondary_catalogue_asset(set_id: str, local_id: str, name: str) -> tuple[str, str, str] | None:
    """Exact assets from secondary catalogues with deterministic set/local URLs."""
    local = (local_id or '').strip()
    if not local:
        return None
    # Dittobase hosts exact McDonald's 2017/2018 card images by set/local.
    dittobase_sets = {'2017sm': 'mcd17', '2018sm': 'mcd18'}
    if set_id in dittobase_sets and local.isdigit():
        source_set = dittobase_sets[set_id]
        url = f'https://assets.dittobase.com/tcg/cards/{source_set}/{int(local)}.png'
        try:
            status, data, ctype = fetch_bytes(url, timeout=20)
            if status == 200 and data and 'image' in ctype:
                page = f'https://www.dittobase.com/tcg/cards/{source_set}/{int(local)}-{slugify_name(name)}'
                return url, page, DITTOBASE_CANDIDATE_TYPE
        except Exception:
            pass
    # CardsRealm hosts exact McDonald's 2014/2015 pages/images by set/local/name.
    cardsrealm_sets = {'2014xy': 'mcd14', '2015xy': 'mcd15'}
    if set_id in cardsrealm_sets and local.isdigit():
        source_set = cardsrealm_sets[set_id]
        page = f'https://pokemon.cardsrealm.com/en-us/card/{slugify_name(name)}-{source_set}-{int(local)}'
        try:
            html = fetch_text(page, timeout=20)
        except Exception:
            html = ''
        if source_set in html and f'#{int(local)}' in html and norm_text(name) in norm_text(html[:20000]):
            imgs = re.findall(r'https://cdn\.cardsrealm\.com/images/cartas/[^"\'<> ]+?\.(?:png|jpg|jpeg|webp)', html)
            for url in imgs:
                if f'/{source_set}-' in url and f'/{int(local)}' in url or f'-{int(local)}.' in url:
                    try:
                        status, data, ctype = fetch_bytes(url, timeout=20)
                        if status == 200 and data and 'image' in ctype:
                            return url, page, CARDSREALM_CANDIDATE_TYPE
                    except Exception:
                        continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.03)
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    set_map = build_ptcg_set_map()
    cards_cache: dict[str, list[dict[str, Any]]] = {}

    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT language_code, resolved_set_id, card_id, local_id, card_name, resolved_set_name, resolved_series_name
        FROM v2_card_search
        WHERE language_code='en' AND has_display_image=0
        ORDER BY resolved_set_id, local_id_sort, card_id
    """).fetchall()
    conn.close()

    manifest = []
    misses = []
    downloaded_by_url: dict[str, tuple[Path, int, str]] = {}

    for row in rows:
        if args.limit and len(manifest) >= args.limit:
            break
        sid = row['resolved_set_id']; local_id = row['local_id']; name = row['card_name']; card_id = row['card_id']
        source = None
        source_api = None
        candidate_type = CANDIDATE_TYPE
        ptcg_ids = set_map.get(sid, [])
        for ptcg_id in ptcg_ids:
            for src in load_cards_for_set(ptcg_id, cards_cache):
                if card_matches_local(src, local_id, name):
                    images = src.get('images') or {}
                    urls = [u for u in (images.get('large'), images.get('small'), f'https://images.pokemontcg.io/{ptcg_id}/{src.get("number")}_hires.png', f'https://images.pokemontcg.io/{ptcg_id}/{src.get("number")}.png') if u]
                    source = urls[0]
                    source_api = f'{GH_BASE}/cards/en/{ptcg_id}.json#{src.get("id")}'
                    src['_candidate_asset_urls'] = urls
                    break
            if source:
                break
        if not source:
            source = tcgdex_asset_url(sid, local_id)
            if source:
                source_api = f'https://api.tcgdex.net/v2/en/cards/{sid}-{local_id}'
                candidate_type = TCGDEX_CANDIDATE_TYPE
        if not source:
            source = limitless_pocket_asset_url(sid, local_id)
            if source:
                source_api = f'https://pocket.limitlesstcg.com/cards/{sid}/{int(local_id)}'
                candidate_type = LIMITLESS_POCKET_CANDIDATE_TYPE
        if not source:
            pkmn = pkmncards_asset(sid, local_id, name)
            if pkmn:
                source, source_api = pkmn
                candidate_type = PKMNCARDS_CANDIDATE_TYPE
        if not source:
            secondary = secondary_catalogue_asset(sid, local_id, name)
            if secondary:
                source, source_api, candidate_type = secondary
        if not source:
            misses.append({k: row[k] for k in row.keys()} | {'reason': 'no_set_scoped_source_match', 'ptcg_set_candidates': ptcg_ids})
            continue

        try:
            source_urls = [source]
            if source in downloaded_by_url:
                path, nbytes, sha = downloaded_by_url[source]
            else:
                errors = []
                data = b''
                ctype = ''
                # Try source URL, and if it is a hires PokemonTCG.io URL, fall back to the non-hires PNG.
                if source.endswith('_hires.png'):
                    source_urls.append(source.replace('_hires.png', '.png'))
                for candidate_source in source_urls:
                    try:
                        status, data, ctype = fetch_bytes(candidate_source, timeout=45)
                    except Exception as e:
                        errors.append(f'{candidate_source}:{type(e).__name__}:{e}')
                        continue
                    if status == 200 and data and 'image' in ctype:
                        source = candidate_source
                        break
                    errors.append(f'{candidate_source}:bad_download:{status}:{ctype}')
                else:
                    # If a PokemonTCG.io catalogue row pointed to a dead CDN URL,
                    # fall back to PkmnCards only after exact set/number verification.
                    pkmn_fallback = pkmncards_asset(sid, local_id, name)
                    if pkmn_fallback:
                        fallback_url, fallback_source = pkmn_fallback
                    else:
                        secondary_fallback = secondary_catalogue_asset(sid, local_id, name)
                        if secondary_fallback:
                            fallback_url, fallback_source, candidate_type = secondary_fallback
                        else:
                            fallback_url = fallback_source = None
                    if fallback_url:
                        try:
                            status, data, ctype = fetch_bytes(fallback_url, timeout=45)
                        except Exception as e:
                            errors.append(f'{fallback_url}:{type(e).__name__}:{e}')
                        else:
                            if status == 200 and data and 'image' in ctype:
                                source = fallback_url
                                source_api = fallback_source
                                if pkmn_fallback:
                                    candidate_type = PKMNCARDS_CANDIDATE_TYPE
                            else:
                                errors.append(f'{fallback_url}:bad_download:{status}:{ctype}')
                    if not data or 'image' not in ctype:
                        misses.append({k: row[k] for k in row.keys()} | {'reason': '; '.join(errors), 'asset_url': source})
                        continue
                safe_card = re.sub(r'[^A-Za-z0-9_.-]+', '_', card_id)
                out_dir = OUT_ROOT / sid
                out_dir.mkdir(parents=True, exist_ok=True)
                ext = '.webp' if 'webp' in ctype or source.endswith('.webp') else '.png'
                path = out_dir / f'{safe_card}{ext}'
                path.write_bytes(data)
                nbytes = len(data)
                sha = sha256_bytes(data)
                downloaded_by_url[source] = (path, nbytes, sha)
            manifest.append({
                'set_id': sid,
                'card_id': card_id,
                'local_id': local_id,
                'name': name,
                'image_url': source,
                'asset_url': source,
                'status': 'downloaded',
                'candidate_type': candidate_type,
                'language_code': 'en',
                'local_path': str(path),
                'bytes': nbytes,
                'core_set_id': sid,
                'resolved_set_id': sid,
                'source_set_id': sid,
                'source_card_id': card_id,
                'source_api_url': source_api,
                'sha256': sha,
            })
            time.sleep(args.sleep)
        except Exception as e:
            misses.append({k: row[k] for k in row.keys()} | {'reason': f'download_error:{type(e).__name__}:{e}', 'asset_url': source})

    stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    out = REPORTS / f'en_exact_image_recovery_{stamp}.json'
    report = {
        'generated_at': dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        'database': str(DB),
        'source_policy': 'set-scoped only: PokemonTCG.io JSON/CDN by exact set+local number, plus TCGdex tcgp CDN exact set+local when available',
        'rows_considered': len(rows),
        'downloaded_manifest_entries': len(manifest),
        'misses': len(misses),
        'ptcg_set_map': set_map,
        'manifest': manifest,
        'missed_entries': misses,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'report': str(out),
        'rows_considered': len(rows),
        'downloaded_manifest_entries': len(manifest),
        'misses': len(misses),
        'unique_asset_urls': len(downloaded_by_url),
    }, indent=2))
    return 0 if manifest else 2

if __name__ == '__main__':
    raise SystemExit(main())
