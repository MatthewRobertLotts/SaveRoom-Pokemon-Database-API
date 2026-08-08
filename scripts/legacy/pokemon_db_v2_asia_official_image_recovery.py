#!/usr/bin/env python3
"""Targeted source-specific image recovery from official Asia Pokémon card search.

Manifest-first only: this script does not mutate the SQLite database. It gathers
verified same-language/same-expansion/same-collector-number card images from the
official Asia trainer sites, writes JSON/CSV reports under full_tcgdex/reports,
and stores downloaded assets under recovered_images/<date>/<language>/<core_set>/.

Apply the downloaded manifest with pokemon_db_v2_apply_recovered_images.py.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
SOURCE_BASE = 'https://asia.pokemon-card.com'
CANDIDATE_TYPE = 'exact_asia_official_recovered_asset'
UA = 'SaveRoomPokemonAsiaImageRecovery/1.0 (+manifest-first; contact: local SaveRoom DB maintenance)'

LANG_TO_SITE = {
    'id': {'site': 'id', 'image_prefix': 'id'},
    'zh-tw': {'site': 'tw', 'image_prefix': 'tw'},
}


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def date_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def local_id_key(value: str | None) -> str:
    if value is None:
        return ''
    v = str(value).strip()
    if re.fullmatch(r'0+\d+', v):
        return str(int(v))
    return v.lower()


def collector_local(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r'([A-Za-z]*\d+|[A-Z]{3}|no\d+)\s*/', value.strip(), re.I)
    if not m:
        return None
    return m.group(1).strip()


def visible_text(fragment: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', fragment)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def target_rows(db: Path, languages: list[str], set_codes: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    params: list[Any] = list(languages)
    lang_clause = ','.join('?' for _ in languages)
    set_clause = ''
    if set_codes:
        set_clause = ' AND lower(core_set_id) IN (' + ','.join('?' for _ in set_codes) + ')'
        params.extend([s.lower() for s in set_codes])
    # When specific set codes are given, skip the SV/Scarlet&Violet filter.
    series_filter = ''
    if not set_codes:
        series_filter = '''AND (
            core_set_id LIKE 'SV%' OR core_set_id LIKE 'sv%'
            OR resolved_series_name LIKE '%Scarlet%' OR resolved_series_name LIKE '%Violet%'
            OR resolved_series_name LIKE '%朱%' OR resolved_series_name LIKE '%紫%'
        )'''
    sql = f'''
        SELECT language_code, card_id, raw_set_id, resolved_set_id, core_set_id,
               local_id, local_id_sort, card_name, resolved_set_name,
               resolved_series_name, resolved_release_date
        FROM v2_card_detail
        WHERE language_code IN ({lang_clause})
          AND has_display_image=0
          AND core_set_id IS NOT NULL
          {series_filter}
          {set_clause}
        ORDER BY CASE language_code WHEN 'id' THEN 0 WHEN 'zh-tw' THEN 1 ELSE 9 END,
                 core_set_id, local_id_sort, card_id
    '''
    out = rows(cur, sql, tuple(params))
    conn.close()
    return out[:limit] if limit else out


class AsiaOfficialClient:
    def __init__(self, timeout: int = 20, sleep: float = 0.05):
        self.timeout = timeout
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': UA})
        self.set_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, url: str) -> requests.Response:
        r = self.session.get(url, timeout=self.timeout)
        time.sleep(self.sleep)
        return r

    def head_image(self, url: str) -> tuple[bool, int | None, str | None, int | None]:
        try:
            r = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            ctype = r.headers.get('content-type')
            size = int(r.headers.get('content-length') or 0) if r.headers.get('content-length') else None
            ok = r.status_code == 200 and bool(ctype and ctype.startswith('image/'))
            return ok, r.status_code, ctype, size
        except requests.RequestException:
            return False, None, None, None

    def download(self, url: str, path: Path) -> tuple[bool, str | None, int, str | None, int | None]:
        try:
            r = self.session.get(url, timeout=self.timeout, stream=True)
            ctype = r.headers.get('content-type')
            if r.status_code != 200 or not (ctype and ctype.startswith('image/')):
                return False, None, 0, ctype, r.status_code
            path.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256(); total = 0
            with path.open('wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk); h.update(chunk); total += len(chunk)
            return True, h.hexdigest(), total, ctype, r.status_code
        except requests.RequestException:
            return False, None, 0, None, None

    def set_catalog(self, language_code: str, expansion_code: str, max_pages: int = 50) -> dict[str, Any]:
        key = (language_code, expansion_code)
        if key in self.set_cache:
            return self.set_cache[key]
        site = LANG_TO_SITE[language_code]['site']
        details: dict[str, dict[str, Any]] = {}
        pages_checked = 0
        total_text: str | None = None
        for page in range(1, max_pages + 1):
            url = f'{SOURCE_BASE}/{site}/card-search/list/?expansionCodes={expansion_code}&pageNo={page}'
            try:
                r = self.get(url)
            except requests.RequestException as e:
                details.setdefault('__errors__', {'errors': []})['errors'].append({'url': url, 'error': str(e)})
                break
            if r.status_code != 200:
                break
            page_details = re.findall(rf'/{re.escape(site)}/card-search/detail/(\d+)/', r.text)
            page_imgs = re.findall(rf'https://asia\.pokemon-card\.com/{re.escape(site)}/card-img/{LANG_TO_SITE[language_code]["image_prefix"]}\d+\.png', r.text)
            if total_text is None:
                m = re.search(r'(\d+)\s*(?:buah|個)', visible_text(r.text))
                total_text = m.group(1) if m else None
            if not page_details and not page_imgs:
                break
            pages_checked += 1
            for detail_id, img_url in zip(page_details, page_imgs):
                details[detail_id] = {'detail_id': detail_id, 'image_url': img_url, 'list_url': url}
            # Official list returns 20 cards/page; a short page is final.
            if len(set(page_details)) < 20:
                break
        catalog = {'language_code': language_code, 'site': site, 'expansion_code': expansion_code,
                   'pages_checked': pages_checked, 'official_total_text': total_text,
                   'detail_count': len([k for k in details if k != '__errors__']), 'details': details}
        self.set_cache[key] = catalog
        return catalog

    def enrich_detail(self, language_code: str, detail_id: str, image_url: str) -> dict[str, Any]:
        site = LANG_TO_SITE[language_code]['site']
        detail_url = f'{SOURCE_BASE}/{site}/card-search/detail/{detail_id}/'
        out = {'detail_id': detail_id, 'detail_url': detail_url, 'image_url': image_url,
               'status': 'detail_error', 'local_id': None, 'collector_number': None, 'card_name': None}
        try:
            r = self.get(detail_url)
            out['http_status'] = r.status_code
            if r.status_code != 200:
                return out
        except requests.RequestException as e:
            out['error'] = str(e)
            return out
        text = r.text
        m = re.search(r'<h1[^>]*class="[^"]*cardDetail[^"]*"[^>]*>(.*?)</h1>', text, re.S)
        out['card_name'] = visible_text(m.group(1)).replace('basic ', '', 1).strip() if m else None
        cm = re.search(r'<span[^>]*class="collectorNumber"[^>]*>(.*?)</span>', text, re.S)
        collector = visible_text(cm.group(1)) if cm else None
        out['collector_number'] = collector
        out['local_id'] = collector_local(collector)
        out['status'] = 'detail_ok' if out['local_id'] else 'detail_missing_local_id'
        return out


def choose_expansion_attempts(rows_for_set: list[dict[str, Any]]) -> list[str]:
    vals: list[str] = []
    for r in rows_for_set:
        for k in ('core_set_id', 'resolved_set_id', 'raw_set_id'):
            v = r.get(k)
            if v:
                vals.append(v)
    out: list[str] = []
    for v in vals:
        for cand in (v, v.upper(), v.lower()):
            if cand and cand not in out:
                out.append(cand)
    return out


def local_image_path(item: dict[str, Any], url: str) -> Path:
    ext = url.rsplit('.', 1)[-1].split('?', 1)[0].lower()
    if ext not in {'png', 'webp', 'jpg', 'jpeg'}:
        ext = 'img'
    return IMAGE_ROOT / date_stamp() / safe_name(item['language_code']) / safe_name(item.get('core_set_id') or item.get('resolved_set_id') or item.get('raw_set_id')) / f"{safe_name(item['card_id'])}.{ext}"


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted(set().union(*(d.keys() for d in data))) if data else ['status']
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(data)


def gather(args: argparse.Namespace) -> dict[str, Any]:
    db = Path(args.db)
    languages = args.languages.split(',') if isinstance(args.languages, str) else args.languages
    set_codes = [s.strip() for s in args.sets.split(',') if s.strip()] if args.sets else None
    wanted = target_rows(db, languages, set_codes, args.limit)
    by_lang_set: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in wanted:
        by_lang_set.setdefault((r['language_code'], r['core_set_id']), []).append(r)

    client = AsiaOfficialClient(timeout=args.timeout, sleep=args.sleep)
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    set_reports: list[dict[str, Any]] = []
    downloaded = attempted_rows = matched = 0

    for (lang, core_set), group in by_lang_set.items():
        if lang not in LANG_TO_SITE:
            set_reports.append({'language_code': lang, 'core_set_id': core_set, 'status': 'unsupported_language', 'target_rows': len(group)})
            continue
        chosen_catalog = None
        chosen_expansion = None
        for exp in choose_expansion_attempts(group):
            catalog = client.set_catalog(lang, exp, args.max_pages)
            if catalog['detail_count'] > 0:
                chosen_catalog = catalog; chosen_expansion = exp; break
        if not chosen_catalog:
            set_reports.append({'language_code': lang, 'core_set_id': core_set, 'status': 'source_set_not_found', 'target_rows': len(group), 'attempted_expansions': choose_expansion_attempts(group)})
            for item in group:
                manifest.append({**item, 'attempted_at': now_utc(), 'status': 'source_set_not_found', 'candidate_type': CANDIDATE_TYPE, 'source_name': 'official_asia_pokemon_card_search'})
            continue

        # Fetch detail pages concurrently so list-card images can be mapped to collector local IDs.
        detail_items = [(did, d['image_url']) for did, d in chosen_catalog['details'].items() if did != '__errors__']
        enriched: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(client.enrich_detail, lang, did, img) for did, img in detail_items]
            for fut in as_completed(futs):
                enriched.append(fut.result())
        by_local: dict[str, dict[str, Any]] = {}
        for e in enriched:
            if e.get('local_id'):
                by_local.setdefault(local_id_key(e['local_id']), e)
        set_downloaded = set_matched = 0
        for item in group:
            attempted_rows += 1
            entry = {k: item.get(k) for k in ['language_code','card_id','card_name','raw_set_id','resolved_set_id','core_set_id','local_id','resolved_set_name','resolved_series_name']}
            entry.update({
                'attempted_at': now_utc(),
                'status': 'not_matched_in_official_set',
                'candidate_type': CANDIDATE_TYPE,
                'source_name': 'official_asia_pokemon_card_search',
                'source_expansion_code': chosen_expansion,
                'source_list_url': f'{SOURCE_BASE}/{LANG_TO_SITE[lang]["site"]}/card-search/list/?expansionCodes={chosen_expansion}',
            })
            detail = by_local.get(local_id_key(item.get('local_id')))
            if not detail:
                manifest.append(entry); continue
            matched += 1; set_matched += 1
            image_url = detail['image_url']
            ok, status_code, ctype, head_size = client.head_image(image_url)
            entry.update({'source_detail_id': detail['detail_id'], 'source_url': detail['detail_url'],
                          'source_api_url': detail['detail_url'], 'asset_url': image_url,
                          'official_card_name': detail.get('card_name'), 'official_collector_number': detail.get('collector_number'),
                          'http_status': status_code, 'content_type': ctype, 'head_content_length': head_size})
            if not ok:
                entry['status'] = 'asset_head_not_image'
                manifest.append(entry); continue
            path = local_image_path(item, image_url)
            if args.dry_run:
                entry.update({'status': 'verified_not_downloaded_dry_run', 'local_path': str(path)})
                manifest.append(entry); continue
            dl_ok, sha, size, dl_ctype, dl_status = client.download(image_url, path)
            if dl_ok:
                downloaded += 1; set_downloaded += 1
                entry.update({'status': 'downloaded', 'local_path': str(path), 'sha256': sha, 'bytes': size,
                              'download_http_status': dl_status, 'download_content_type': dl_ctype,
                              'verification_method': 'official_asia_detail_collector_number_and_image_http_verified'})
            else:
                entry.update({'status': 'download_failed', 'download_http_status': dl_status, 'download_content_type': dl_ctype})
            manifest.append(entry)
            if args.max_downloads and downloaded >= args.max_downloads:
                break
        set_reports.append({'language_code': lang, 'core_set_id': core_set, 'status': 'processed', 'target_rows': len(group),
                            'source_expansion_code': chosen_expansion, 'official_detail_count': chosen_catalog['detail_count'],
                            'official_total_text': chosen_catalog.get('official_total_text'), 'pages_checked': chosen_catalog['pages_checked'],
                            'matched_rows': set_matched, 'downloaded_rows': set_downloaded})
        if args.max_downloads and downloaded >= args.max_downloads:
            break

    status_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    for m in manifest:
        status_counts[m['status']] = status_counts.get(m['status'], 0) + 1
        lang_counts[m['language_code']] = lang_counts.get(m['language_code'], 0) + 1
    run_stamp = stamp()
    manifest_json = REPORTS / f'v2_asia_official_image_recovery_manifest_{run_stamp}.json'
    manifest_csv = REPORTS / f'v2_asia_official_image_recovery_manifest_{run_stamp}.csv'
    set_csv = REPORTS / f'v2_asia_official_image_recovery_sets_{run_stamp}.csv'
    payload = {
        'generated_at': now_utc(),
        'database': str(db),
        'source': 'official Asia Pokémon card-search/detail pages',
        'candidate_type': CANDIDATE_TYPE,
        'mode': 'dry_run' if args.dry_run else 'download',
        'target_rows': len(wanted),
        'attempted_rows': attempted_rows,
        'matched_rows': matched,
        'downloaded': downloaded,
        'status_counts': status_counts,
        'language_counts': lang_counts,
        'image_root': str(IMAGE_ROOT),
        'set_reports': set_reports,
        'manifest': manifest,
    }
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(manifest_csv, manifest)
    write_csv(set_csv, set_reports)
    payload['artifacts'] = {'manifest_json': str(manifest_json), 'manifest_csv': str(manifest_csv), 'set_csv': str(set_csv)}
    # Re-write with artifact paths included.
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Gather official Asia Pokémon card images for v2 missing-display rows.')
    p.add_argument('--db', default=str(DB))
    p.add_argument('--languages', default='id,zh-tw', help='Comma-separated DB language codes; supported: id,zh-tw')
    p.add_argument('--sets', default='', help='Optional comma-separated core set codes to target')
    p.add_argument('--limit', type=int, default=0, help='Max target DB rows; 0 = all matching rows')
    p.add_argument('--max-downloads', type=int, default=0, help='Stop after N downloads; 0 = unlimited')
    p.add_argument('--max-pages', type=int, default=50)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--timeout', type=int, default=20)
    p.add_argument('--sleep', type=float, default=0.03)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    if args.limit == 0: args.limit = None
    if args.max_downloads == 0: args.max_downloads = None
    result = gather(args)
    print(json.dumps({k: result[k] for k in ['generated_at','mode','target_rows','attempted_rows','matched_rows','downloaded','status_counts','language_counts','artifacts']}, ensure_ascii=False, indent=2))
    return 0 if result['downloaded'] > 0 or args.dry_run else 1


if __name__ == '__main__':
    raise SystemExit(main())
