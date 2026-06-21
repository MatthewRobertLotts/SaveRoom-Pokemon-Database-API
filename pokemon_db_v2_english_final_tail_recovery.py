#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
REPORTS = DB.parent / 'reports'
OUT = ROOT / 'recovered_images' / dt.datetime.now(dt.UTC).strftime('%Y-%m-%d') / 'en_final_tail'
UA = {'User-Agent': 'Hermes SaveRoom exact English final tail recovery/1.0'}

# Exact, page-verified sources for the current English hard tail.
# These are not global name-search hits: each entry points to a catalogue page
# whose title/body identifies the exact set/product + collector/card number.
SOURCES = {
    # SVP 500: WonderClub page/product ID is POKEMON-SVP-500 and page lists set/card number.
    ('svp', '500', 'Terapagos & Friends'): {
        'image_url': 'https://wonderclub.com/images/CARDS/POKEMON/POKEMON-SVP-500.png',
        'source_api_url': 'https://wonderclub.com/puzzles/puzzle_single_page.php?u=pokemon-terapagos-friends-pokemon-svp-500',
        'candidate_type': 'exact_wonderclub_asset',
        'source_card_id': 'POKEMON-SVP-500',
    },
    # DP Trainer Kit exact TCGCollector pages.
    ('tk-dp-l', '8', 'Energy Search'): {
        'image_url': 'https://static.tcgcollector.com/content/images/e3/4c/d7/e34cd7c1ce295562043802b14c946cc53afc5210c94e66c2c514c4ef3b8e2af1.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/3968/energy-search-dp-trainer-kit-lucario-8-11',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-3968',
    },
    ('tk-dp-l', '11', 'Fighting Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/a7/d5/9e/a7d59eee3b57ad2c7aa0e040e291bd7291751b896cc59e1666b02a0ec36a9787.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/3971/fighting-energy-dp-trainer-kit-lucario-11-11',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-3971',
    },
    ('tk-dp-m', '10', 'Energy Search'): {
        'image_url': 'https://static.tcgcollector.com/content/images/90/7c/dd/907cddc815846049526af324cb98131d7c207e3f845c5b0f8eb641675f0bcd9b.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/3958/energy-search-dp-trainer-kit-manaphy-10-12',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-3958',
    },
    ('tk-dp-m', '12', 'Water Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/3a/ec/3c/3aec3c5c54119eb65203a44664c71da4763ce932807bf54160eac44001ccf0e4.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/3960/water-energy-dp-trainer-kit-manaphy-12-12',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-3960',
    },
    # My First Battle DB aggregates the four 12-card starter decks into one sequence.
    # The missing energy rows are the final energy card of each sub-deck (TCGCollector No. 012).
    ('mfb', '8', 'Grass Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/90/5a/cb/905acb2e7bc204905085601ec7cb4e4aee8b218f6030ca230702f0a97ec02518.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/42774/basic-grass-energy-my-first-battle-bulbasaur-no-012',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-42774',
    },
    ('mfb', '16', 'Fire Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/23/86/a5/2386a55cbcd22f0788bb12af13366bf287f8582e8e4864cd50144ae31f422e50.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/42786/basic-fire-energy-my-first-battle-charmander-no-012',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-42786',
    },
    ('mfb', '24', 'Lightning Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/ed/6e/b9/ed6eb9a417414c8bac10bd051de4544b07d5db24aa46aba0278a13b08d9bf9df.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/42798/basic-lightning-energy-my-first-battle-pikachu-no-012',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-42798',
    },
    ('mfb', '32', 'Water Energy'): {
        'image_url': 'https://static.tcgcollector.com/content/images/c9/6c/65/c96c6526d5571058ff243e3c092a409f640134e92462f0d7cb662cefa2339966.jpg',
        'source_api_url': 'https://www.tcgcollector.com/cards/42810/basic-water-energy-my-first-battle-squirtle-no-012',
        'candidate_type': 'exact_tcgcollector_asset',
        'source_card_id': 'tcgcollector-42810',
    },
    # Jumbo Warner Bros promo exact PriceCharting item page.
    ('jumbo', 'None', 'Articuno, Moltres, and Zapdos'): {
        'image_url': None,  # populated from exact PriceCharting page below
        'source_api_url': 'https://www.pricecharting.com/game/pokemon-promo/articuno-&-moltres-&-zapdos-jumbo',
        'candidate_type': 'exact_pricecharting_asset',
        'source_card_id': 'pricecharting-pokemon-promo-articuno-moltres-zapdos-jumbo',
    },
}


def fetch(url: str) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read(), r.headers.get('content-type', '')


def page_text(url: str) -> str:
    return fetch(url)[1].decode('utf-8', 'replace')


def pricecharting_image(page: str) -> str | None:
    try:
        html = page_text(page)
    except Exception:
        return None
    imgs = re.findall(r'https://storage.googleapis.com/images.pricecharting.com/[^"\'<> ]+/1600.jpg', html)
    return imgs[0] if imgs else None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select resolved_set_id, card_id, local_id, card_name
        from v2_card_search
        where language_code='en' and has_display_image=0
        order by resolved_set_id, local_id_sort, card_id
        """
    ).fetchall()
    conn.close()

    manifest = []
    misses = []
    downloaded = {}
    for row in rows:
        sid = row['resolved_set_id']
        local = str(row['local_id'])
        name = row['card_name']
        source = SOURCES.get((sid, local, name))
        if not source:
            misses.append(dict(row) | {'reason': 'no_safe_exact_source_registered'})
            continue
        image_url = source['image_url'] or pricecharting_image(source['source_api_url'])
        if not image_url:
            misses.append(dict(row) | {'reason': 'source_page_has_no_image', 'source_api_url': source['source_api_url']})
            continue
        try:
            if image_url in downloaded:
                local_path, nbytes, digest = downloaded[image_url]
            else:
                status, data, ctype = fetch(image_url)
                if status != 200 or 'image' not in ctype:
                    raise RuntimeError(f'bad image response {status} {ctype}')
                ext = '.jpg' if 'jpg' in ctype or 'jpeg' in ctype else '.png'
                out_dir = OUT / sid
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_card = re.sub(r'[^A-Za-z0-9_.-]+', '_', row['card_id'])
                local_path = out_dir / f'{safe_card}{ext}'
                local_path.write_bytes(data)
                nbytes = len(data)
                digest = sha256(data)
                downloaded[image_url] = (local_path, nbytes, digest)
        except Exception as e:
            misses.append(dict(row) | {'reason': f'{type(e).__name__}:{e}', 'asset_url': image_url})
            continue
        manifest.append({
            'language_code': 'en',
            'card_id': row['card_id'],
            'local_id': row['local_id'],
            'name': name,
            'image_url': image_url,
            'asset_url': image_url,
            'status': 'downloaded',
            'candidate_type': source['candidate_type'],
            'local_path': str(local_path),
            'bytes': nbytes,
            'core_set_id': sid,
            'resolved_set_id': sid,
            'source_set_id': sid,
            'source_card_id': source['source_card_id'],
            'source_api_url': source['source_api_url'],
            'sha256': digest,
        })

    report = REPORTS / f'en_final_tail_recovery_{dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")}.json'
    report.write_text(json.dumps({
        'generated_at': dt.datetime.now(dt.UTC).isoformat(),
        'manifest': manifest,
        'missed_entries': misses,
    }, indent=2, ensure_ascii=False))
    print(json.dumps({'report': str(report), 'downloaded_manifest_entries': len(manifest), 'misses': len(misses)}, indent=2))
    return 0 if manifest else 2


if __name__ == '__main__':
    raise SystemExit(main())
