#!/usr/bin/env python3
"""Recover exact European/Portuguese images from TCGdex.

Strict policy: same language only, no placeholders, no cross-language fallback.
The script derives DB set -> TCGdex set mappings from existing verified URLs and
TCGdex set APIs, then downloads exact local_id assets.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB = ROOT / 'full_tcgdex' / 'pokemon_tcg_set_knowledge_base.sqlite'
REPORTS = ROOT / 'full_tcgdex' / 'reports'
OUT_ROOT = ROOT / 'recovered_images' / 'euro_tcgdex'
UA = 'Mozilla/5.0 (Hermes SaveRoom source-backed image recovery)'
CANDIDATE_TYPE = 'exact_tcgdex_set_api_recovered_asset'
LANG_TO_TCGDEX = {'pt': 'pt', 'pt-br': 'pt-br'}

# Human DB labels seen in v2_card_search -> TCGdex codes.
POCKET_NAME_TO_CODE = {
    'Genetic Apex': 'A1',
    'Mythical Island': 'A1a',
    'Space-Time Smackdown': 'A2',
    'Triumphant Light': 'A2a',
    'Shining Revelry': 'A2b',
    'Celestial Guardians': 'A3',
    'Extradimensional Crisis': 'A3a',
    'Eevee Grove': 'A3b',
    'Wisdom of Sea and Sky': 'A4',
    'Secluded Springs': 'A4a',
    'Promos-A': 'P-A',
}
MAIN_NAME_TO_CODE = {
    'Ascended Heroes': 'me02.5',
    'Fusion Strike': 'swsh8',
    'Paldea Evolved': 'sv02',
    'Cosmic Eclipse': 'sm12',
    'Paradox Rift': 'sv04',
    'Unified Minds': 'sm11',
    'Scarlet & Violet': 'sv01',
    'Surging Sparks': 'sv08',
    'Lost Origin': 'swsh11',
    'Astral Radiance': 'swsh10',
    'Paldean Fates': 'sv04.5',
    'Silver Tempest': 'swsh12',
    'Destined Rivals': 'sv10',
    'Evolving Skies': 'swsh7',
    'Lost Thunder': 'sm8',
    'Unbroken Bonds': 'sm10',
    'Chilling Reign': 'swsh6',
    'Obsidian Flames': 'sv03',
    'Crown Zenith': 'swsh12.5',
    'SWSH Black Star Promos': 'swshp',
}


def get_json(url: str, timeout: int = 15) -> Any | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status == 200:
                return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None
    return None


def get_image(url: str, timeout: int = 15) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get('content-type') or '').lower()
            if r.status == 200 and 'image' in ctype:
                return r.read()
    except Exception:
        return None
    return None


def norm(s: str | None) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def existing_mappings(conn: sqlite3.Connection, lang: str) -> dict[str, tuple[str, str]]:
    """Return DB set/name -> (tcgdex_series, tcgdex_set)."""
    mapping: dict[str, tuple[str, str]] = {}
    q = """
    SELECT resolved_set_id, resolved_set_name, display_image_url
    FROM v2_card_search
    WHERE language_code=?
      AND has_display_image=1
      AND display_image_source_language_code=?
      AND display_image_url LIKE 'https://assets.tcgdex.net/%'
    """
    for row in conn.execute(q, (lang, lang)):
        m = re.search(r'assets\.tcgdex\.net/([^/]+)/([^/]+)/([^/]+)', row['display_image_url'] or '')
        if not m:
            continue
        series, set_code = m.group(2), m.group(3)
        keys = [row['resolved_set_id'], row['resolved_set_name'], norm(row['resolved_set_name']), set_code]
        for k in keys:
            if k:
                mapping[str(k)] = (series, set_code)
    return mapping


def infer_mapping(lang_api: str, sid: str, set_name: str | None, known: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    for key in [sid, set_name, norm(set_name)]:
        if key and str(key) in known:
            return known[str(key)]
    code = POCKET_NAME_TO_CODE.get(sid) or POCKET_NAME_TO_CODE.get(set_name or '')
    if code:
        return ('tcgp', code)
    code = MAIN_NAME_TO_CODE.get(sid) or MAIN_NAME_TO_CODE.get(set_name or '')
    if code:
        for maybe in [code, code.lower(), code.upper()]:
            data = get_json(f'https://api.tcgdex.net/v2/{lang_api}/sets/{maybe}', timeout=10)
            if data and data.get('id'):
                return (data.get('serie', {}).get('id') or code.split('.')[0], data['id'])
    # Direct code probe — try the set code and common legacy prefixes.
    probe_codes = [sid, sid.lower(), sid.upper()]
    # Also try common legacy series prefixes with the set code.
    for prefix in ['ex', 'xy', 'bw', 'dp', 'neo', 'hgss', 'ecard', 'sm', 'swsh', 'sv', 'tcgp', 'me']:
        if not sid.lower().startswith(prefix):
            probe_codes.append(f'{prefix}{sid}')
            probe_codes.append(f'{prefix}{sid}'.lower())
            probe_codes.append(f'{prefix}{sid}'.upper())
    for maybe in probe_codes:
        data = get_json(f'https://api.tcgdex.net/v2/{lang_api}/sets/{maybe}', timeout=10)
        if data and data.get('id'):
            return (data.get('serie', {}).get('id') or maybe, data['id'])
    return None


def card_index(lang_api: str, set_code: str) -> dict[str, dict]:
    data = get_json(f'https://api.tcgdex.net/v2/{lang_api}/sets/{set_code}')
    idx: dict[str, dict] = {}
    if not data:
        return idx
    for c in data.get('cards') or []:
        cid = str(c.get('localId') or c.get('id') or '').strip()
        if cid:
            idx[cid] = c
            m = re.search(r'(\d+)', cid)
            if m:
                idx[str(int(m.group(1)))] = c
                idx[f'{int(m.group(1)):03d}'] = c
    return idx


def local_keys(local_id: str | None) -> list[str]:
    out=[]
    def add(x):
        if x and x not in out: out.append(str(x))
    if local_id is None: return out
    s=str(local_id).strip()
    add(s)
    m=re.search(r'(\d+)', s)
    if m:
        n=int(m.group(1)); add(f'{n:03d}'); add(str(n))
    return out


def download_one(row: dict, lang_api: str, series: str, set_code: str, c: dict) -> dict | None:
    asset_base = c.get('image') or f'https://assets.tcgdex.net/{lang_api}/{series}/{set_code}/{c.get("localId")}'
    # high.webp is the real binary; keep canonical base as image_url if API supplies it.
    image_url = asset_base
    download_url = asset_base + '/high.webp' if not str(asset_base).endswith(('.webp','.png','.jpg','.jpeg')) else asset_base
    data = get_image(download_url)
    if not data:
        # Some existing DB rows use base URL directly; try it too.
        data = get_image(asset_base)
        download_url = asset_base
    if not data:
        return None
    safe = re.sub(r'[^A-Za-z0-9_.-]+','_', row['card_id'])
    out_dir = OUT_ROOT / row['language_code'] / row['resolved_set_id']
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{safe}.webp'
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    return {
        'language_code': row['language_code'],
        'card_id': row['card_id'],
        'name': row.get('card_name') or '',
        'local_id': row.get('local_id'),
        'image_url': image_url,
        'asset_url': image_url,
        'local_path': str(path),
        'status': 'downloaded',
        'candidate_type': CANDIDATE_TYPE,
        'core_set_id': row['resolved_set_id'],
        'resolved_set_id': row['resolved_set_id'],
        'source_set_id': set_code,
        'source_card_id': c.get('id') or f'{set_code}-{c.get("localId")}',
        'source_api_url': f'https://api.tcgdex.net/v2/{lang_api}/sets/{set_code}',
        'download_url': download_url,
        'bytes': len(data),
        'sha256': sha,
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--languages', default='fr,de,it,es,pt,pt-br')
    ap.add_argument('--limit-sets-per-language', type=int, default=0)
    ap.add_argument('--limit-cards-per-set', type=int, default=0)
    ap.add_argument('--workers', type=int, default=20)
    args=ap.parse_args()
    langs=[x.strip() for x in args.languages.split(',') if x.strip()]
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest=[]; set_results=[]
    OUT_ROOT.mkdir(parents=True, exist_ok=True); REPORTS.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        lang_api = LANG_TO_TCGDEX.get(lang, lang)
        known = existing_mappings(conn, lang)
        sets=[dict(r) for r in conn.execute("""
            SELECT resolved_set_id, resolved_set_name, COUNT(*) n
            FROM v2_card_search
            WHERE language_code=? AND has_display_image=0
            GROUP BY resolved_set_id,resolved_set_name
            ORDER BY n DESC
        """, (lang,))]
        if args.limit_sets_per_language:
            sets=sets[:args.limit_sets_per_language]
        print(f'{lang}: {len(sets)} missing set buckets')
        for srow in sets:
            sid=srow['resolved_set_id']; sname=srow['resolved_set_name']
            mapped=infer_mapping(lang_api, sid, sname, known)
            if not mapped:
                set_results.append({'language_code':lang,'resolved_set_id':sid,'resolved_set_name':sname,'status':'no_mapping','cards':srow['n']})
                continue
            series,set_code=mapped
            idx=card_index(lang_api, set_code)
            if not idx:
                set_results.append({'language_code':lang,'resolved_set_id':sid,'resolved_set_name':sname,'status':'empty_api','series':series,'set_code':set_code,'cards':srow['n']})
                continue
            limit_sql=f' LIMIT {int(args.limit_cards_per_set)}' if args.limit_cards_per_set else ''
            rows=[dict(r) for r in conn.execute("""
                SELECT language_code, card_id, card_name, local_id, resolved_set_id
                FROM v2_card_search
                WHERE language_code=? AND resolved_set_id=? AND has_display_image=0
                ORDER BY local_id_sort, local_id, card_id
            """+limit_sql, (lang, sid))]
            jobs=[]
            for row in rows:
                c=None
                for k in local_keys(row.get('local_id')):
                    c=idx.get(k)
                    if c: break
                if c and c.get('image'):
                    jobs.append((row,c))
            downloaded=0
            with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
                futs=[ex.submit(download_one,row,lang_api,series,set_code,c) for row,c in jobs]
                for fut in cf.as_completed(futs):
                    item=fut.result()
                    if item:
                        manifest.append(item); downloaded+=1
            print(f'{lang} {sid} -> {set_code}: {downloaded}/{len(rows)} downloaded')
            set_results.append({'language_code':lang,'resolved_set_id':sid,'resolved_set_name':sname,'series':series,'set_code':set_code,'status':'downloaded','cards':len(rows),'matched_jobs':len(jobs),'downloaded':downloaded})
    stamp=time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    out=REPORTS/f'euro_tcgdex_recovery_{stamp}.json'
    out.write_text(json.dumps({'generated_at':stamp,'source':'TCGdex','manifest':manifest,'set_results':set_results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'MANIFEST={out}')
    print(f'ENTRIES={len(manifest)}')
    conn.close()
    return 0
if __name__=='__main__':
    raise SystemExit(main())
