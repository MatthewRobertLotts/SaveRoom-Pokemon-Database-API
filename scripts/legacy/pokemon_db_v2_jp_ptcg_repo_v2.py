#!/usr/bin/env python3
"""Aggressively recover JP card images from PTCG-database repo with auto-mapping."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
REPO=ROOT/'ptcg_db_repo/data_jp'
OUT_ROOT=ROOT/'recovered_images/jp_ptcg_repo'
REPORTS=ROOT/'full_tcgdex/reports'
CANDIDATE_TYPE='exact_jp_official_scraped_asset'
UA='Mozilla/5.0 (Hermes SaveRoom source-backed image recovery)'

def get_img(url:str,timeout:int=15)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None
    return None

def main()->int:
    # Build repo index: set_name -> {number -> card_json}
    repo_sets:dict[str,dict[str,dict]]={}
    print('Indexing 315 repo directories...')
    for d in sorted(REPO.iterdir()):
        if not d.is_dir(): continue
        index:dict[str,dict]={}
        for jf in d.glob('*.json'):
            try:
                c=json.loads(jf.read_text(encoding='utf-8'))
                num=str(c.get('number','')).strip()
                if num and c.get('img'):
                    index[num]=c
                    m=re.search(r'(\d+)',num)
                    if m:
                        n=int(m.group(1))
                        index[str(n)]=c
                        index[f'{n:03d}']=c
            except: pass
        if index:
            repo_sets[d.name]=index
    print(f'Indexed {len(repo_sets)} repo sets with images')

    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; set_results:list=[]; total_dl=0
    OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)

    missing_sets=conn.execute("""
        select resolved_set_id, resolved_set_name, count(*) n
        from v2_card_search where language_code='ja' and has_display_image=0
        group by resolved_set_id order by n desc
    """).fetchall()
    print(f'Processing {len(missing_sets)} Japanese missing set buckets')

    for (sid,sname,cnt) in missing_sets:
        if cnt==0: continue
        # Get a sample of card data from this set
        sample_cards=conn.execute("""
            select card_id, local_id, resolved_set_id, card_name, local_id_sort
            from v2_card_search where language_code='ja' and resolved_set_id=? and has_display_image=0
            order by local_id_sort, card_id limit 200
        """, (sid,)).fetchall()
        if not sample_cards: continue

        # Try to find best matching repo set
        best_match=None; best_score=-1
        sid_low=sid.lower()
        card_count=len(sample_cards)

        for rs_name,rs_index in repo_sets.items():
            rs_low=rs_name.lower()
            score=0
            
            # Direct match (after normalization)
            if sid_low==rs_low: score=100
            elif sid_low==rs_low.replace('-',''): score=95
            elif sid_low==rs_low.replace('_',''): score=95
            # Substring matches
            elif sid_low in rs_low or rs_low in sid_low:
                score=50
                if len(sid_low)>=3 and sid_low[:3]==rs_low[:3]: score=60
            # SM era number matches
            elif sid_low.startswith('sm') and rs_low.startswith('sm'):
                snum=sid_low[2:].lstrip('0')
                rnum=rs_low[2:].lstrip('0')
                if snum==rnum: score=85
                elif snum and rnum and snum[:2]==rnum[:2]: score=70
            # XY era number matches
            elif sid_low.startswith('xy') and rs_low.startswith('xy'):
                snum=sid_low[2:].lstrip('0')
                rnum=rs_low[2:].lstrip('0')
                if snum==rnum: score=85
            # BW era
            elif sid_low.startswith('bw') and rs_low.startswith('bw'):
                snum=sid_low[2:].lstrip('0')
                rnum=rs_low[2:].lstrip('0')
                if snum==rnum: score=85
            # DP era
            elif sid_low.startswith('dp') and rs_low.startswith('dp'):
                snum=sid_low[2:].lstrip('0')
                rnum=rs_low[2:].lstrip('0')
                if snum==rnum: score=85
            
            # Card count proximity bonus
            rs_count=len(rs_index)
            if abs(rs_count-card_count)<=5: score+=10
            elif abs(rs_count-card_count)<=20: score+=5
            
            # Name match: check if any card in sample matches by name
            for crd in sample_cards[:5]:
                cn=str(crd['card_name'] or '').strip().lower()[:10]
                if not cn: continue
                for rc in rs_index.values():
                    rcn=str(rc.get('name','')).strip().lower()[:10]
                    if cn and cn==rcn:
                        score+=15; break

            if score>best_score:
                best_score=score; best_match=rs_name

        if best_match is None or best_score<40:
            set_results.append({'set':sid,'name':sname,'count':cnt,'repo':'no_match','best_score':best_score})
            continue

        rs_index=repo_sets[best_match]
        jobs=[]
        for row in sample_cards:
            lid=str(row['local_id'] or '').strip()
            c=None
            for k in [lid,re.sub(r'[^0-9]','',lid),str(re.sub(r'[^0-9]','',lid)).zfill(3),
                      re.sub(r'[^a-zA-Z0-9]','',lid),re.sub(r'[^a-zA-Z0-9]','',lid).upper(),
                      re.sub(r'[^a-zA-Z0-9]','',lid).lower()]:
                c=rs_index.get(k)
                if c: break
            if c: jobs.append((dict(row),c))

        downloaded=0
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs={ex.submit(_dl_one,row,c,best_match):row for row,c in jobs}
            for f in as_completed(futs):
                item=f.result()
                if item: manifest.append(item); downloaded+=1; total_dl+=1

        if downloaded:
            print(f'{sid} -> repo [{best_match}]: {downloaded}/{len(sample_cards)} (score={best_score})')
        elif best_score>=80:
            print(f'{sid} -> repo [{best_match}]: 0/{len(sample_cards)} (score={best_score})- mismatch?')
        set_results.append({'set':sid,'name':sname,'count':cnt,'repo':best_match,'score':best_score,
                          'matched':len(jobs),'downloaded':downloaded})

    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    out=REPORTS/f'jp_ptcg_repo_v2_{stamp}.json'
    out.write_text(json.dumps({'generated_at':stamp,'source':'PTCG-database/JP','manifest':manifest,
                               'set_results':set_results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'\nMANIFEST={out}\nENTRIES={len(manifest)}\nTotal JP cards: {total_dl}')
    conn.close()
    return 0

def _dl_one(row:dict,c:dict,set_name:str)->dict|None:
    data=get_img(c['img'],timeout=15)
    if not data: return None
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',row['card_id'])
    out=OUT_ROOT/set_name; out.mkdir(parents=True,exist_ok=True)
    path=out/f'{safe}.webp'; path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    return {
        'language_code':'ja','card_id':row['card_id'],'name':c.get('name',''),'local_id':row['local_id'],
        'image_url':c['img'],'asset_url':c['img'],'local_path':str(path),'status':'downloaded',
        'candidate_type':CANDIDATE_TYPE,'core_set_id':row['resolved_set_id'],
        'resolved_set_id':row['resolved_set_id'],
        'source_set_id':set_name,'source_card_id':c.get('jp_id'),
        'source_api_url':c.get('url',''),'sha256':sha,
    }

if __name__=='__main__': raise SystemExit(main())