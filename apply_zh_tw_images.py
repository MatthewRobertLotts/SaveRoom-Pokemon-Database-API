#!/usr/bin/env python3
"""Apply downloaded ZH-TW images to the DB.

Reads the manifest file and applies images to the v2 display layer.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')


def apply_zh_tw_images():
    """Apply ZH-TW images from the manifest to the DB."""
    
    # Find the latest manifest
    manifests = sorted(REPORTS.glob('zh_tw_asia_scrape_*.json'))
    if not manifests:
        print('No manifest found')
        return
    
    manifest_path = manifests[-1]
    print(f'Using manifest: {manifest_path}')
    
    manifest = json.loads(manifest_path.read_text())
    
    # Filter to downloaded images
    downloaded = [m for m in manifest if m.get('status') == 'downloaded']
    print(f'Downloaded images in manifest: {len(downloaded)}')
    
    if not downloaded:
        print('No downloaded images to apply')
        return
    
    # Apply to DB
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    # First, ensure the candidate type is recognized
    # Insert into card_image_candidates
    applied = 0
    skipped = 0
    
    for entry in downloaded:
        card_id = entry['card_id']
        set_id = entry['set_id']
        image_url = entry['image_url']
        local_path = entry.get('local_path', '')
        
        # Check if this card already has a display image
        existing = cur.execute('''
            SELECT has_display_image FROM v2_card_search 
            WHERE language_code='zh-tw' AND card_id=?
        ''', (card_id,)).fetchone()
        
        if not existing:
            skipped += 1
            continue
        
        if existing[0] == 1:
            # Already has display image
            skipped += 1
            continue
        
        # Insert into card_image_candidates
        cur.execute('''
            INSERT OR REPLACE INTO card_image_candidates 
            (language_code, card_id, candidate_type, source_name, source_url, 
             asset_url, local_path, verification_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('zh-tw', card_id, 'exact_asia_tw_scraped_asset', 'asia_pokemon_card_tw',
              f'https://asia.pokemon-card.com/tw/card-search/detail/{entry.get("detail_id", "")}/',
              image_url, local_path, 'asia_tw_search_results', time.strftime('%Y-%m-%dT%H:%M:%S+00:00')))
        
        applied += 1
    
    conn.commit()
    
    # Now refresh the v2 views to pick up the new candidates
    # Rebuild v2_card_image_best
    cur.execute('''
        INSERT OR REPLACE INTO v2_card_image_best 
        (language_code, card_id, best_image_url, best_image_source_type, best_image_source_language_code)
        SELECT 
            c.language_code,
            c.card_id,
            c.asset_url,
            c.candidate_type,
            'zh-tw'
        FROM card_image_candidates c
        WHERE c.candidate_type = 'exact_asia_tw_scraped_asset'
        AND c.card_id NOT IN (
            SELECT card_id FROM v2_card_image_best 
            WHERE language_code = 'zh-tw'
        )
    ''')
    
    # Update v2_card_search display_image_url from v2_card_image_best
    cur.execute('''
        UPDATE v2_card_search 
        SET display_image_url = (
            SELECT best_image_url FROM v2_card_image_best b 
            WHERE b.language_code = v2_card_search.language_code 
            AND b.card_id = v2_card_search.card_id
        ),
        display_image_source_type = (
            SELECT best_image_source_type FROM v2_card_image_best b 
            WHERE b.language_code = v2_card_search.language_code 
            AND b.card_id = v2_card_search.card_id
        ),
        has_display_image = 1
        WHERE language_code = 'zh-tw' 
        AND has_display_image = 0
        AND card_id IN (SELECT card_id FROM v2_card_image_best WHERE language_code = 'zh-tw')
    ''')
    
    conn.commit()
    
    # Count results
    total_missing = cur.execute('SELECT COUNT(*) FROM v2_card_search WHERE language_code="zh-tw" AND has_display_image=0').fetchone()[0]
    total_with = cur.execute('SELECT COUNT(*) FROM v2_card_search WHERE language_code="zh-tw" AND has_display_image=1').fetchone()[0]
    
    print(f'\nApplied: {applied}')
    print(f'Skipped: {skipped}')
    print(f'ZH-TW with display image: {total_with:,}')
    print(f'ZH-TW missing: {total_missing:,}')
    
    conn.close()


if __name__ == '__main__':
    apply_zh_tw_images()
