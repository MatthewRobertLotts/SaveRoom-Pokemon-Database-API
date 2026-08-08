#!/usr/bin/env python3
"""Deep recovery of remaining European TCGdex images that have images available."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

UA='Mozilla/5.0 (Hermes SaveRoom source-backed image recovery)'
ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
OUT_ROOT=ROOT/'recovered_images/euro_tcgdex_deep'
REPORTS=ROOT/'full_tcgdex/reports'
CANDIDATE_TYPE='exact_tcgdex_set_api_recovered_asset'

def get_json(url: str, timeout:int=10)->Any|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return json.loads(r.read().decode())
    except: return None

def get_img(url: str, timeout:int=12)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None
    return None

def dl_one(row:dict, c:dict, series:str, set_code:str, lang:str)->dict|None:
    asset=c['image']
    data=get_img(asset+'/high.webp') or get_img(asset)
    if not data: return None
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_', row['card_id'])
    out=OUT_ROOT/lang/row['resolved_set_id']
    out.mkdir(parents=True,exist_ok=True)
    path=out/f'{safe}.webp'; path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    return {
        'language_code':lang,'card_id':row['card_id'],'name':'','local_id':row['local_id'],
        'image_url':asset,'asset_url':asset,'local_path':str(path),'status':'downloaded',
        'candidate_type':CANDIDATE_TYPE,'core_set_id':row['resolved_set_id'],'resolved_set_id':row['resolved_set_id'],
        'source_set_id':set_code,'source_card_id':c.get('id') or f'{set_code}-{c.get("localId")}',
        'source_api_url':f'https://api.tcgdex.net/v2/{lang}/sets/{set_code}','sha256':sha}

def probe_set(lang:str, sid:str)->tuple[dict,str]|None:
    for probe in [sid.lower(),sid.upper(),sid]:
        data=get_json(f'https://api.tcgdex.net/v2/{lang}/sets/{probe}',timeout=8)
        if data and any(c.get('image') for c in (data.get('cards') or [])):
            return data, probe
    return None

def idx_from_api(data:dict)->dict[str,dict]:
    idx:dict={}
    for c in data.get('cards') or []:
        lid=str(c.get('localId') or c.get('id') or '').strip()
        if lid and c.get('image'):
            idx[lid]=c
            m=re.search(r'(\d+)',lid)
            if m:
                n=int(m.group(1)); idx[str(n)]=c; idx[f'{n:03d}']=c
    return idx

def main()->int:
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    for lang in ['fr','de','it','es','pt']:
        missing=conn.execute("SELECT resolved_set_id,resolved_set_name,count(*)n FROM v2_card_search WHERE language_code=? AND has_display_image=0 GROUP BY resolved_set_id ORDER BY n DESC",(lang,)).fetchall()
        for (sid,sname,_) in missing:
            result=probe_set(lang,sid)
            if not result: continue
            data,set_code=result
            series=data.get('serie',{}).get('id') or ''
            idx=idx_from_api(data)
            rows=conn.execute("SELECT card_id,local_id,resolved_set_id FROM v2_card_search WHERE language_code=? AND resolved_set_id=? AND has_display_image=0 ORDER BY local_id_sort,card_id",(lang,sid)).fetchall()
            jobs=[]
            for row in rows:
                lid=str(row['local_id'] or '').strip()
                c=None
                for k in [lid,re.sub(r'[^0-9]','',lid),str(re.sub(r'[^0-9]','',lid)).zfill(3)]:
                    c=idx.get(k)
                    if c: break
                if c: jobs.append((row,c))
            downloaded=0
            with ThreadPoolExecutor(max_workers=16) as ex:
                futs={ex.submit(dl_one,row,c,series,set_code,lang):row for row,c in jobs}
                for f in as_completed(futs):
                    item=f.result()
                    if item: manifest.append(item); downloaded+=1
            if downloaded: print(f'{lang} {sid}: {downloaded}/{len(rows)}')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    out=REPORTS/f'euro_tcgdex_deep_recovery_{stamp}.json'
    out.write_text(json.dumps({'generated_at':stamp,'source':'TCGdex','manifest':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'MANIFEST={out}\nENTRIES={len(manifest)}')
    conn.close()
    return 0
if __name__=='__main__': raise SystemExit(main())