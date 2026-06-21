#!/usr/bin/env python3
"""Recover missing images by finding identically-named cards that already have images in other sets.
Trainer kit cards, sample cards, and legacy reprints often share exact names with main set cards."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
OUT_ROOT=ROOT/'recovered_images/name_match'
REPORTS=ROOT/'full_tcgdex/reports'
UA='Mozilla/5.0 (Hermes SaveRoom name-match recovery)'

def get_img(url:str)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=12) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None

def main()->int:
    conn=sqlite3.connect(DB)
    manifest:list=[]; total_dl=0
    OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    
    # Process each language
    for lang in ['en','ja','fr','de','it','es','pt','pt-br','ko','th','zh-cn','zh-tw','id']:
        # Get all cards in this language that are missing images
        missing=conn.execute("""
            select c.card_id, c.name, c.set_id, c.language_code
            from cards c
            where c.language_code=? and (c.image_url is null or trim(c.image_url)='')
        """, (lang,)).fetchall()
        if not missing: continue
        print(f'{lang}: {len(missing)} missing cards to cross-reference')
        
        # Build lookup: normalised card name -> existing image URL in SAME language
        name_to_url:dict[str,tuple[str,str]]={}  # name_lower -> (card_id, image_url)
        existing=conn.execute("""
            select card_id, name, image_url from cards
            where language_code=? and image_url is not null and trim(image_url)!=''
        """, (lang,)).fetchall()
        for cid, cname, curl in existing:
            key=re.sub(r'[^a-z0-9]','',(cname or '').lower().strip())
            if key and len(key)>=3:
                name_to_url[key]=((cid, curl))
        
        jobs=[]
        for card_id, name, set_id, _ in missing:
            key=re.sub(r'[^a-z0-9]','',(name or '').lower().strip())
            if key and key in name_to_url:
                existing_cid, existing_url = name_to_url[key]
                if existing_url:
                    jobs.append((card_id, name, set_id, lang, existing_url, existing_cid))
        
        print(f'  Found {len(jobs)} name matches')
        
        dl_count=0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs={ex.submit(_dl,card_id, name, existing_url, lang):(card_id, name, set_id, lang) 
                  for card_id, name, set_id, lang, existing_url, _ in jobs}
            for f in as_completed(futs):
                item=f.result()
                if item:
                    manifest.append(item); dl_count+=1; total_dl+=1
        print(f'  Downloaded {dl_count}')
    
    if manifest:
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        out=REPORTS/f'name_match_recovery_{stamp}.json'
        out.write_text(json.dumps({'generated_at':stamp,'source':'name_cross_reference','manifest':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'\nMANIFEST={out}\nENTRIES={len(manifest)}')
    else: print('No name matches found')
    conn.close()
    return 0

def _dl(card_id:str, name:str, existing_url:str, lang:str)->dict|None:
    # Check if the URL actually works
    data=get_img(existing_url)
    if not data:
        # Try appending /high.webp for TCGdex-style URLs
        if 'tcgdex.net' in existing_url and not existing_url.endswith(('.webp','.png','.jpg')):
            data=get_img(existing_url+'/high.webp')
    if not data: return None
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_', card_id)
    out=OUT_ROOT/lang; out.mkdir(parents=True,exist_ok=True)
    path=out/f'{safe}.webp'; path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    return {
        'language_code':lang,'card_id':card_id,'name':name,'local_id':'','local_path':str(path),
        'image_url':existing_url,'asset_url':existing_url,'status':'downloaded',
        'candidate_type':'exact_name_cross_ref','core_set_id':'','resolved_set_id':'',
        'source_set_id':'','source_card_id':'','source_api_url':'','sha256':sha,
    }

if __name__=='__main__': raise SystemExit(main())