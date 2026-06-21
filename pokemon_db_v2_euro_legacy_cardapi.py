#!/usr/bin/env python3
"""Recover European legacy images via TCGdex card API (not set API).
The card API returns image URLs that the bundled set API card list doesn't."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
OUT_ROOT=ROOT/'recovered_images/euro_legacy_cardapi'
REPORTS=ROOT/'full_tcgdex/reports'
UA='Mozilla/5.0 (Hermes SaveRoom TCGdex card API)'
CANDIDATE_TYPE='exact_tcgdex_set_api_recovered_asset'
LANG_MAP={'pt-br':'pt'}  # pt-br uses pt TCGdex for legacy

def get_json(url:str)->dict|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=12) as r:
            if r.status==200: return json.loads(r.read().decode())
    except: return None

def get_img(url:str)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=15) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None

def main()->int:
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; set_results:list=[]; total_dl=0
    OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    
    # For European languages, find cards with no image but where TCGdex might have images
    # We'll query each card individually via the card API
    langs=['fr','de','it','es','pt']
    
    for lang in langs:
        lang_api = LANG_MAP.get(lang, lang).replace('-br','')
        # Get all missing cards for this language
        cards=conn.execute("""
            select c.card_id, c.local_id, c.name, c.set_id
            from cards c
            where c.language_code=? and (c.image_url is null or trim(c.image_url)='')
            order by c.card_id
        """, (lang,)).fetchall()
        if not cards: continue
        print(f'{lang}: {len(cards)} missing cards to try card API')
        
        dl_count=0
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs={ex.submit(_try_card,card_id,name,set_id,lang,lang_api):(card_id,set_id)
                  for card_id,name,local_id,set_id in cards}
            for f in as_completed(futs):
                item=f.result()
                if item:
                    manifest.append(item); dl_count+=1; total_dl+=1
        print(f'  {lang}: {dl_count} recovered')
    
    if manifest:
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        out=REPORTS/f'euro_legacy_cardapi_{stamp}.json'
        out.write_text(json.dumps({'generated_at':stamp,'source':'TCGdex card API','manifest':manifest,
                                   'set_results':set_results},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'\nMANIFEST={out}\nENTRIES={len(manifest)}')
    else: print('No legacy images recovered')
    conn.close()
    return 0

def _try_card(card_id:str, name:str, set_id:str, lang:str, lang_api:str)->dict|None:
    # Try TCGdex card API with the card ID
    data=get_json(f'https://api.tcgdex.net/v2/{lang_api}/cards/{card_id}')
    if not data:
        # Try with different format - just the local_id
        m=re.match(r'^[A-Za-z0-9.-]+-(\d+)$', card_id)
        if m:
            lid=m.group(1)
            data=get_json(f'https://api.tcgdex.net/v2/{lang_api}/cards/{set_id}-{lid}')
        if not data: return None
    
    img_url=data.get('image')
    if not img_url: return None
    
    # Download the actual image
    dl_url=img_url
    data_bytes=get_img(dl_url)
    if not data_bytes and 'tcgdex.net' in img_url and not img_url.endswith(('.webp','.png','.jpg')):
        data_bytes=get_img(img_url+'/high.webp')
    if not data_bytes: return None
    
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',card_id)
    out=OUT_ROOT/lang; out.mkdir(parents=True,exist_ok=True)
    path=out/f'{safe}.webp'; path.write_bytes(data_bytes)
    sha=hashlib.sha256(data_bytes).hexdigest()
    return {
        'language_code':lang,'card_id':card_id,'name':name,'local_id':'','local_path':str(path),
        'image_url':img_url,'asset_url':img_url,'status':'downloaded',
        'candidate_type':CANDIDATE_TYPE,'core_set_id':set_id,'resolved_set_id':set_id,
        'source_set_id':set_id,'source_card_id':data.get('id',card_id),
        'source_api_url':f'https://api.tcgdex.net/v2/{lang_api}/cards/{card_id}','sha256':sha,
    }

if __name__=='__main__': raise SystemExit(main())