#!/usr/bin/env python3
"""Recover TC/Pocket images from PTCG-database repo."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
REPORTS=ROOT/'full_tcgdex/reports'
UA='Mozilla/5.0 (Hermes SaveRoom source-backed image recovery)'

def get_img(url:str,timeout:int=15)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None

SOURCES=[
    ('zh-tw','ptcg_db_repo/data_tc','exact_asia_tw_scraped_asset'),
    ('en','ptcg_db_repo/data_pocket','exact_tcgdex_set_api_recovered_asset'),
]
# Also add pocket for pt-br (pocket has pt-br language option)
# And add JP ADV/Neo/eCard sets using tcgdex.com cloudfront source
# Let me also try the main pokemon-card.com with the jp_id from repo
# Check what JP sets remain missing after repo recovery

def main()->int:
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; total_dl=0
    
    for lang,data_path,candidate_type in SOURCES:
        data_dir=ROOT/data_path
        if not data_dir.exists(): continue
        print(f'Indexing {data_path} for {lang}...')
        
        # Build set index: for each repo set, build number->card index
        repo_sets:dict[str,dict[str,dict]]={}
        for d in data_dir.iterdir():
            if not d.is_dir(): continue
            idx:dict[str,dict]={}
            for jf in d.glob('*.json'):
                try:
                    c=json.loads(jf.read_text(encoding='utf-8'))
                    num=str(c.get('number','')).strip()
                    if num and c.get('img'):
                        idx[num]=c
                        m=re.search(r'(\d+)',num)
                        if m:
                            n=int(m.group(1))
                            idx[str(n)]=c; idx[f'{n:03d}']=c
                except: pass
            if idx: repo_sets[d.name]=idx
        print(f'  Indexed {len(repo_sets)} repo sets with {sum(len(v) for v in repo_sets.values())} images')
        
        missing=conn.execute("""
            select resolved_set_id, resolved_set_name, count(*) n
            from v2_card_search
            where language_code=? and has_display_image=0
            group by resolved_set_id order by n desc
        """, (lang,)).fetchall()
        if not missing: continue
        print(f'  {len(missing)} missing set buckets')
        
        for (sid,sname,cnt) in missing:
            cards=conn.execute("""
                select card_id, local_id, resolved_set_id
                from v2_card_search
                where language_code=? and resolved_set_id=? and has_display_image=0
                order by local_id_sort, card_id
            """, (lang,sid)).fetchall()
            if not cards: continue
            
            best_match=None; best_score=0
            sid_low=sid.lower()
            for rs_name,rs_idx in repo_sets.items():
                rs_low=rs_name.lower().replace('@4x.png','').replace('.png','').strip()
                score=0
                if sid_low==rs_low: score=100
                elif sid_low in rs_low or rs_low in sid_low: score=40
                if abs(len(rs_idx)-len(cards))<=5: score+=10
                if score>best_score: best_score=score; best_match=rs_name
            
            if best_match is None or best_score<40: continue
            rs_idx=repo_sets[best_match]
            downloaded=0
            OUT_ROOT=ROOT/f'recovered_images/{lang}_ptcg_repo'
            
            def dl(row,c):
                nonlocal downloaded
                data=get_img(c['img'])
                if not data: return None
                safe=re.sub(r'[^A-Za-z0-9_.-]+','_',row['card_id'])
                out=OUT_ROOT/best_match; out.mkdir(parents=True,exist_ok=True)
                path=out/f'{safe}.webp'; path.write_bytes(data)
                sha=hashlib.sha256(data).hexdigest()
                return {
                    'language_code':lang,'card_id':row['card_id'],'name':c.get('name',''),'local_id':row['local_id'],
                    'image_url':c['img'],'asset_url':c['img'],'local_path':str(path),'status':'downloaded',
                    'candidate_type':candidate_type,'core_set_id':row['resolved_set_id'],
                    'resolved_set_id':row['resolved_set_id'],'source_set_id':c.get('set_name',''),
                    'source_card_id':c.get('number',''),
                    'source_api_url':c.get('url',''),'sha256':sha,
                }
            
            jobs=[]
            for row in cards:
                lid=str(row['local_id'] or '').strip()
                c=None
                for k in [lid,re.sub(r'[^0-9]','',lid),str(re.sub(r'[^0-9]','',lid)).zfill(3)]:
                    c=rs_idx.get(k)
                    if c: break
                if c: jobs.append((row,c))
            
            with ThreadPoolExecutor(max_workers=8) as ex:
                futs={ex.submit(dl,row,c):row for row,c in jobs}
                for f in as_completed(futs):
                    item=f.result()
                    if item: manifest.append(item); downloaded+=1; total_dl+=1
            if downloaded: print(f'{lang} {sid} -> {best_match}: {downloaded}/{len(cards)}')
    
    if manifest:
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        out=REPORTS/f'tc_pocket_repo_recovery_{stamp}.json'
        out.write_text(json.dumps({'generated_at':stamp,'manifest':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'MANIFEST={out}\nENTRIES={len(manifest)}')
    else: print('No images recovered')
    conn.close()
    return 0
if __name__=='__main__': raise SystemExit(main())