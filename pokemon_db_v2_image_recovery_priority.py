#!/usr/bin/env python3
"""Prioritise no-display-image rows and gather verified source images.

Creates:
- v2_image_recovery_priority_report_<date>.json/.csv
- recovered image folder hierarchy on the same drive as the Brain DB
- v2_image_recovery_gather_manifest_<date>.json/.csv

Safety:
- does not update cards.image_url or v2 views;
- downloads only when a TCGdex API card exists and the derived TCGdex asset URL
  responds with an image content-type;
- records source API URL, asset URL, local path, and verification status.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import random
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
API_BASE = 'https://api.tcgdex.net/v2'
ASSET_BASE = 'https://assets.tcgdex.net'

LANGUAGE_WEIGHT = {
    'en': 80, 'ja': 70, 'ko': 48, 'zh-tw': 45, 'zh-cn': 42, 'id': 40, 'th': 34,
    'de': 26, 'fr': 25, 'it': 22, 'es': 22, 'pt': 20, 'es-mx': 15, 'pt-br': 15,
}
MODERN_WORDS = ['sv', 'scarlet', 'violet', 'mega', 'paldean', '151', '夢', '메가', '超級', 'mega dream']
HIGH_VALUE_NAMES = ['charizard', 'pikachu', 'mew', 'mewtwo', 'eevee', 'umbreon', 'sylveon', 'rayquaza', 'lucario', 'gengar', 'latias', 'latios', 'venusaur', 'blastoise', 'mega']


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def date_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def safe_name(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r'(\d{4})', value)
    return int(m.group(1)) if m else None


def source_strategy(lang: str, core_set_id: str | None, set_name: str | None) -> str:
    blob = f'{core_set_id or ""} {set_name or ""}'.lower()
    if lang == 'ja':
        return 'TCGdex JP asset/API first; fallback to official Japanese card database/manual review for missing assets.'
    if lang == 'ko':
        return 'TCGdex/Daldagury Korean API first; fallback to Pokemon Korea/manual review.'
    if lang in {'zh-tw', 'zh-cn'}:
        return 'TCGdex/official Asia Pokémon card search first; manual review if assets unavailable.'
    if lang in {'id', 'th'}:
        return 'Official Asia Pokémon card-search pages plus TCGdex asset verification.'
    if 'tcgp' in blob or core_set_id in {'B1a', 'B2a'}:
        return 'TCGdex Pocket API; assets may lag for future Pocket sets, manual/source refresh likely needed.'
    return 'TCGdex API exact card + verified asset URL.'


def score_row(r: dict[str, Any]) -> tuple[int, list[str], str]:
    reasons: list[str] = []
    score = LANGUAGE_WEIGHT.get(r['language_code'], 8)
    if r['language_code'] == 'en': reasons.append('English row')
    if r['language_code'] == 'ja': reasons.append('Japanese row')
    name_blob = f"{r.get('card_name') or ''} {r.get('resolved_set_name') or ''} {r.get('core_set_name') or ''} {r.get('core_set_id') or ''}".lower()
    year = parse_year(r.get('resolved_release_date'))
    if year:
        if year >= 2025:
            score += 55; reasons.append(f'modern/future release {year}')
        elif year >= 2023:
            score += 38; reasons.append(f'modern release {year}')
        elif year >= 2019:
            score += 20; reasons.append(f'recent-ish release {year}')
    if any(w in name_blob for w in MODERN_WORDS):
        score += 25; reasons.append('modern/Mega/Pocket keyword')
    if any(w in name_blob for w in HIGH_VALUE_NAMES):
        score += 30; reasons.append('high-demand Pokémon/product keyword')
    if 'promo' in name_blob or '-p' in (r.get('core_set_id') or '').lower():
        score += 28; reasons.append('promo bucket')
    if r.get('rarity'):
        score += 12; reasons.append('has rarity/detail')
    if r.get('resolved_set_name') or r.get('core_set_name'):
        score += 10; reasons.append('resolved set metadata')
    prov = int(r.get('provenance_record_count') or 0) + int(r.get('legacy_provenance_count') or 0)
    if prov:
        score += min(12, prov); reasons.append('has provenance')
    if score >= 150:
        tier = 'urgent'
    elif score >= 115:
        tier = 'high'
    elif score >= 75:
        tier = 'medium'
    else:
        tier = 'low'
    return score, reasons, tier


def shopify_usefulness(r: dict[str, Any]) -> str:
    has_detail = bool(r.get('rarity') or r.get('hp') or r.get('types') or r.get('description'))
    has_set = bool(r.get('resolved_set_name') or r.get('core_set_name'))
    if has_detail and has_set:
        return 'ready_except_image'
    if has_set:
        return 'useful_after_image'
    return 'poor_candidate'


def priority_rows(limit: int | None = None) -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    raw = rows(cur, '''
        SELECT language_code, language_name, card_id, raw_set_id, resolved_set_id, core_set_id,
               local_id, local_id_sort, card_name, resolved_set_name, core_set_name,
               resolved_series_name, resolved_release_date, category, hp, types, rarity,
               stage, illustrator, has_display_image, attacks, description,
               provenance_record_count, legacy_provenance_count
        FROM v2_card_detail
        WHERE has_display_image=0
    ''')
    out = []
    seen: set[tuple[str, str, str, str]] = set()
    for r in raw:
        key = (r['language_code'], r.get('core_set_id') or r.get('resolved_set_id') or r.get('raw_set_id') or '', r.get('local_id') or '', r.get('card_name') or '')
        # Product-oriented dedupe keeps alias rows from flooding the action list.
        if key in seen:
            continue
        seen.add(key)
        score, reasons, tier = score_row(r)
        item = dict(r)
        item.update({
            'priority_score': score,
            'priority_tier': tier,
            'priority_reason': '; '.join(reasons),
            'source_strategy': source_strategy(r['language_code'], r.get('core_set_id'), r.get('resolved_set_name') or r.get('core_set_name')),
            'shopify_usefulness': shopify_usefulness(r),
        })
        out.append(item)
    out.sort(key=lambda x: (-x['priority_score'], x['language_code'], x.get('core_set_id') or '', x.get('local_id_sort') or 999999, x['card_id']))
    return out[:limit] if limit else out


def write_priority_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS / f'v2_image_recovery_priority_report_{date_stamp()}.json'
    csv_path = REPORTS / f'v2_image_recovery_priority_report_{date_stamp()}.csv'
    tier_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    for i in items:
        tier_counts[i['priority_tier']] = tier_counts.get(i['priority_tier'], 0) + 1
        lang_counts[i['language_code']] = lang_counts.get(i['language_code'], 0) + 1
    payload = {
        'generated_at': now_utc(),
        'database': str(DB),
        'total_prioritized_rows': len(items),
        'tier_counts': tier_counts,
        'language_counts': lang_counts,
        'image_root': str(IMAGE_ROOT),
        'items': items,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        fields = ['priority_score','priority_tier','language_code','card_id','card_name','core_set_id','resolved_set_name','core_set_name','local_id','rarity','resolved_release_date','shopify_usefulness','source_strategy','priority_reason']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i in items:
            w.writerow({k: i.get(k) for k in fields})
    return {'json_path': str(json_path), 'csv_path': str(csv_path), 'tier_counts': tier_counts, 'language_counts': lang_counts}


class TCGdexClient:
    def __init__(self, timeout: int = 8):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SaveRoomPokemonImageRecovery/1.0'})
        self.timeout = timeout
        self.set_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

    def get_set(self, lang: str, set_id: str) -> dict[str, Any] | None:
        key = (lang, set_id)
        if key in self.set_cache:
            return self.set_cache[key]
        url = f'{API_BASE}/{lang}/sets/{set_id}'
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                self.set_cache[key] = r.json(); return self.set_cache[key]
        except requests.RequestException:
            pass
        self.set_cache[key] = None
        return None

    def card_exists(self, lang: str, card_id: str) -> bool:
        url = f'{API_BASE}/{lang}/cards/{card_id}'
        try:
            r = self.session.get(url, timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def candidate_asset_urls(self, lang: str, serie_id: str, set_id: str, local_id: str) -> list[str]:
        locals_ = []
        if local_id:
            locals_.extend([local_id, local_id.lstrip('0') or local_id])
        locals_ = list(dict.fromkeys(locals_))
        set_ids = list(dict.fromkeys([set_id, set_id.upper(), set_id.lower()]))
        urls = []
        for sid in set_ids:
            for lid in locals_:
                for quality in ['high']:
                    for ext in ['webp', 'png', 'jpg']:
                        urls.append(f'{ASSET_BASE}/{lang}/{serie_id}/{sid}/{lid}/{quality}.{ext}')
        return urls

    def verify_asset(self, url: str) -> tuple[bool, str | None, int | None]:
        try:
            r = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            ctype = r.headers.get('content-type')
            size = int(r.headers.get('content-length') or 0) if r.headers.get('content-length') else None
            return r.status_code == 200 and bool(ctype and ctype.startswith('image/')), ctype, size
        except requests.RequestException:
            return False, None, None

    def download(self, url: str, path: Path) -> tuple[bool, str | None, int]:
        try:
            r = self.session.get(url, timeout=self.timeout, stream=True)
            ctype = r.headers.get('content-type')
            if r.status_code != 200 or not (ctype and ctype.startswith('image/')):
                return False, ctype, 0
            path.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256(); total = 0
            with path.open('wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk); h.update(chunk); total += len(chunk)
            return True, h.hexdigest(), total
        except requests.RequestException:
            return False, None, 0


def local_image_path(item: dict[str, Any], url: str) -> Path:
    ext = url.rsplit('.', 1)[-1].split('?', 1)[0].lower()
    if ext not in {'webp','png','jpg','jpeg'}:
        ext = 'img'
    return IMAGE_ROOT / date_stamp() / safe_name(item['language_code']) / safe_name(item.get('core_set_id') or item.get('resolved_set_id') or item.get('raw_set_id') or 'unknown_set') / f"{safe_name(item['card_id'])}.{ext}"


def gather_images(items: list[dict[str, Any]], max_attempts: int, max_downloads: int) -> dict[str, Any]:
    client = TCGdexClient()
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    downloaded = 0
    attempted = 0
    for item in items:
        if attempted >= max_attempts or downloaded >= max_downloads:
            break
        attempted += 1
        lang = item['language_code']
        set_id = item.get('core_set_id') or item.get('resolved_set_id') or item.get('raw_set_id')
        local_id = item.get('local_id') or ''
        card_id = item.get('card_id') or f'{set_id}-{local_id}'
        entry = {k: item.get(k) for k in ['priority_score','priority_tier','language_code','card_id','card_name','core_set_id','local_id','resolved_set_name','source_strategy']}
        entry.update({'attempted_at': now_utc(), 'status': 'not_found', 'source_api_url': f'{API_BASE}/{lang}/cards/{card_id}'})
        if not set_id or not local_id:
            entry['status'] = 'missing_set_or_local_id'; manifest.append(entry); continue
        set_doc = client.get_set(lang, set_id)
        if not set_doc:
            entry['status'] = 'set_api_not_found'; manifest.append(entry); continue
        serie_id = (set_doc.get('serie') or {}).get('id')
        if not serie_id:
            entry['status'] = 'set_api_missing_serie'; manifest.append(entry); continue
        if not client.card_exists(lang, card_id):
            # Many alias rows have card IDs like set-name-001; try core_set-local fallback for source validation.
            alt_card_id = f'{set_id}-{local_id}'
            if alt_card_id != card_id and client.card_exists(lang, alt_card_id):
                entry['source_api_url'] = f'{API_BASE}/{lang}/cards/{alt_card_id}'
                card_id = alt_card_id
            else:
                entry['status'] = 'card_api_not_found'; manifest.append(entry); continue
        verified_url = None; verified_type = None; verified_size = None
        for url in client.candidate_asset_urls(lang, serie_id, set_id, local_id):
            ok, ctype, size = client.verify_asset(url)
            if ok:
                verified_url, verified_type, verified_size = url, ctype, size
                break
        if not verified_url:
            entry['status'] = 'asset_not_available'; entry['tcgdex_serie_id'] = serie_id; manifest.append(entry); continue
        path = local_image_path(item, verified_url)
        ok, sha, size = client.download(verified_url, path)
        if ok:
            downloaded += 1
            entry.update({'status': 'downloaded', 'asset_url': verified_url, 'content_type': verified_type, 'head_content_length': verified_size, 'local_path': str(path), 'sha256': sha, 'bytes': size, 'tcgdex_serie_id': serie_id})
        else:
            entry.update({'status': 'download_failed', 'asset_url': verified_url, 'content_type': verified_type})
        manifest.append(entry)
    json_path = REPORTS / f'v2_image_recovery_gather_manifest_{date_stamp()}.json'
    csv_path = REPORTS / f'v2_image_recovery_gather_manifest_{date_stamp()}.csv'
    status_counts: dict[str, int] = {}
    for m in manifest:
        status_counts[m['status']] = status_counts.get(m['status'], 0) + 1
    payload = {'generated_at': now_utc(), 'image_root': str(IMAGE_ROOT), 'attempted': attempted, 'downloaded': downloaded, 'status_counts': status_counts, 'manifest': manifest}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        fields = sorted(set().union(*(m.keys() for m in manifest))) if manifest else ['status']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(manifest)
    return {'json_path': str(json_path), 'csv_path': str(csv_path), 'attempted': attempted, 'downloaded': downloaded, 'status_counts': status_counts}


def main() -> int:
    parser = argparse.ArgumentParser(description='Create no-image priority report and gather verified source images.')
    parser.add_argument('--priority-limit', type=int, default=0, help='Limit rows in report; 0 = all product-deduped rows.')
    parser.add_argument('--gather', action='store_true', help='Attempt verified image download for priority rows.')
    parser.add_argument('--gather-attempts', type=int, default=750)
    parser.add_argument('--max-downloads', type=int, default=100)
    parser.add_argument('--random-gather-sample', action='store_true', help='Shuffle prioritized rows before gathering; useful when top future sets have no published assets yet.')
    args = parser.parse_args()
    items = priority_rows(args.priority_limit or None)
    priority = write_priority_report(items)
    gather_items = list(items)
    if args.random_gather_sample:
        random.Random(42).shuffle(gather_items)
    gather = gather_images(gather_items, args.gather_attempts, args.max_downloads) if args.gather else None
    result = {'priority_report': priority, 'gather_report': gather, 'image_root': str(IMAGE_ROOT)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
