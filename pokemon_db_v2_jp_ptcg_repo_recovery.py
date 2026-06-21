#!/usr/bin/env python3
"""Recover Japanese card images from PTCG-database repo official Japan site URLs."""
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

# DB resolved_set_id -> REPO directory name mapping
DIRECT_MAP = {
    # SV era
    'sv1s':'SV1S','sv1v':'SV1V','sv1a':'SV1A','sv2d':'SV2D','sv2p':'SV2P','sv2a':'SV2A',
    'sv3':'SV3','sv3a':'SV3A','sv4k':'SV4K','sv4m':'SV4M','sv4a':'SV4A',
    'sv5k':'SV5K','sv5m':'SV5M','sv5a':'SV5A','sv6':'SV6','sv6a':'SV6A',
    'sv7':'SV7','sv7a':'SV7A','sv8':'SV8','sv8a':'SV8A','sv9':'SV9','sv9a':'SV9A',
    'sv10':'SV10','sv11b':'SV11B','sv11w':'SV11W',
    # S series
    's1h':'S1H','s1w':'S1W','s1a':'S1A','s2':'S2','s2a':'S2A',
    's3':'S3','s3a':'S3A','s4':'S4','s4a':'S4A',
    's5i':'S5I','s5r':'S5R','s5a':'S5A',
    's6h':'S6H','s6k':'S6K','s6a':'S6A',
    's7d':'S7D','s7r':'S7R',
    's8':'S8','s8a':'S8A','s8b':'S8B',
    's9':'S9','s9a':'S9A',
    's10d':'S10D','s10p':'S10P','s10a':'S10A','s10b':'S10B',
    's11':'S11','s11a':'S11A','s12':'S12','s12a':'S12A',
    # SM era
    'sm0':'SM0','sm1s':'SM1S','sm1m':'SM1M','sm1p':'SM1p',
    'sm2k':'SM2K','sm2l':'SM2L','sm2p':'SM2p','sm3h':'SM3H','sm3n':'SM3N','sm3p':'SM3p',
    'sm4s':'SM4S','sm4a':'SM4A','sm4p':'SM4p',
    'sm5s':'SM5S','sm5m':'SM5M','sm5p':'SM5p',
    'sm6':'SM6','sm6a':'SM6A','sm6b':'SM6B',
    'sm7':'SM7','sm7a':'SM7A','sm7b':'SM7B',
    'sm8':'SM8','sm8a':'SM8A','sm8b':'SM8B',
    'sm9':'SM9','sm9a':'SM9A','sm9b':'SM9B',
    'sm10':'SM10','sm10a':'SM10A','sm10b':'SM10B',
    'sm11':'SM11','sm11a':'SM11A','sm11b':'SM11B',
    'sm12':'SM12','sm12a':'SM12A',
    'sma':'SMA','smb':'SMB','smc':'SMC','smd':'SMD','sme':'SME',
    'smf':'SMF','smg':'SMG','smh':'SMH','smi':'SMI','smj':'SMJ',
    'smk':'SMK','sml':'SML','smm':'SMM','smn':'SMN','smp':'SMP','smp1':'SMP1','smp2':'SMP2',
    # XY era  
    'xy':'XY','xy1a':'XY1-Bx','xy1b':'XY1-By','xy2':'XY2','xy3':'XY3','xy4':'XY4',
    'xy5b':'XY5-Bt','xy5a':'XY5-Bg','xy6':'XY6','xy6':'XY6','xy6b':'XY6-B',
    'xy7':'XY7','xy7':'XY7','xy7b':'XY7-B','xy8b':'XY8-Bb','xy8a':'XY8-Br',
    'xy9':'XY9-B','xy10':'XY10-B','xy11b':'XY11-Bb','xy11a':'XY11-Br',
    'xya':'XYA','xyb':'XYB','xyc':'XYC','xyd':'XYD','xye':'XYE','xyf':'XYF','xyg':'XYG','xyh':'XYH',
    'xyp':'XYP',
    # BW era
    'bw':'BW','bw1a':'BW1-Bb','bw1b':'BW1-Bw','bw2':'BW2-B',
    'bw3a':'BW3-Bh','bw3b':'BW3-Bp','bw4':'BW4-B',
    'bw5a':'BW5-Brz','bw5b':'BW5-Brn','bw6a':'BW6-Bc','bw6b':'BW6-Bf',
    'bw7':'BW7-B','bw8a':'BW8-Brf','bw8b':'BW8-Brn',
    'bw9':'BW9-B','bw10':'BW10-B','bwp':'BWP',
    # DP era
    'dp1':'DP1','dp1a':'DP1','dp1b':'DP1',
    'dp2':'DP2','dp2':'DP2','dp3':'DP3','dp4':'DP4','dp4a':'DP4','dp4b':'DP4',
    'dp5':'DP5','dp5a':'DP5','dp5b':'DP5',
    'dp6':'DPP','dp7':'DPt1-B',
    # Promo/Other
    's-p':'S-P','sv-p':'SV-P','svp':'SVP1',
    'll':'LL','sk':'SK','sn':'SN','sll':'SLL','spz':'SPZ','spd':'SPD',
    'sld':'SLD','sc':'SC','scs':'SCS','sp6':'SP6','ds':'DS',
    'sm-x-y':'SM-XY',
    'm1l':'M1L','m1s':'M1S',
    'l1':'L1-Bhg','l2':'L2-B','l3':'L3-B',
}

def get_img(url: str, timeout:int=15)->bytes|None:
    try:
        req=urllib.request.Request(url, headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            ctype=(r.headers.get('content-type') or '').lower()
            if r.status==200 and 'image' in ctype:
                return r.read()
    except: return None
    return None

def main()->int:
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; set_results:list=[]; total_dl=0
    OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    
    missing_sets=conn.execute("""
        select resolved_set_id, resolved_set_name, count(*) n
        from v2_card_search
        where language_code='ja' and has_display_image=0
        group by resolved_set_id
        order by n desc
    """).fetchall()
    
    print(f'Processing {len(missing_sets)} Japanese missing set buckets')
    for (sid,sname,cnt) in missing_sets:
        repo_code=DIRECT_MAP.get(sid.lower()) or DIRECT_MAP.get(sid)
        if not repo_code:
            set_results.append({'lang':'ja','set':sid,'name':sname,'count':cnt,'repo':'no_mapping'})
            continue
        repo_dir=REPO/repo_code
        if not repo_dir.exists():
            set_results.append({'lang':'ja','set':sid,'name':sname,'count':cnt,'repo':repo_code,'repo':'dir_not_found'})
            continue
        # Build card index from repo JSONs
        index:dict[str,dict]={}
        for jf in repo_dir.glob('*.json'):
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
        
        if not index:
            set_results.append({'lang':'ja','set':sid,'name':sname,'count':cnt,'repo':repo_code,'cards':len(list(repo_dir.glob('*.json'))),'with_img':0})
            continue
        
        cards=conn.execute("""
            select card_id, local_id, resolved_set_id from v2_card_search
            where language_code='ja' and resolved_set_id=? and has_display_image=0
            order by local_id_sort, card_id
        """, (sid,)).fetchall()
        if not cards: continue
        
        jobs=[]
        for row in cards:
            lid=str(row['local_id'] or '').strip()
            c=None
            for k in [lid,re.sub(r'[^0-9]','',lid),str(re.sub(r'[^0-9]','',lid)).zfill(3)]:
                c=index.get(k)
                if c: break
            if c: jobs.append((dict(row), c))
        
        downloaded=0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs={}
            for row,c in jobs:
                future=ex.submit(_dl_one,row,c)
                futs[future]=row
            for f in as_completed(futs):
                item=f.result()
                if item:
                    manifest.append(item); downloaded+=1; total_dl+=1
        
        print(f'{sid} ({sname}): mapped={repo_code}, {downloaded}/{len(cards)} downloaded')
        set_results.append({'lang':'ja','set':sid,'name':sname,'count':cnt,'repo':repo_code,'matched':len(jobs),'downloaded':downloaded})
    
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    out=REPORTS/f'jp_ptcg_repo_recovery_{stamp}.json'
    out.write_text(json.dumps({'generated_at':stamp,'source':'PTCG-database/JP','manifest':manifest,'set_results':set_results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'\nMANIFEST={out}')
    print(f'ENTRIES={len(manifest)}')
    print(f'Total JP cards recovered: {total_dl}')
    conn.close()
    return 0

def _dl_one(row:dict, c:dict)->dict|None:
    data=get_img(c['img'],timeout=15)
    if not data: return None
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_', row['card_id'])
    out=OUT_ROOT/(c.get('set_name','unknown'))
    out.mkdir(parents=True,exist_ok=True)
    path=out/f'{safe}.webp'
    path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    return {
        'language_code':'ja','card_id':row['card_id'],'name':c.get('name',''),'local_id':row['local_id'],
        'image_url':c['img'],'asset_url':c['img'],'local_path':str(path),'status':'downloaded',
        'candidate_type':CANDIDATE_TYPE,'core_set_id':row['resolved_set_id'],'resolved_set_id':row['resolved_set_id'],
        'source_set_id':c.get('set_name'),'source_card_id':c.get('jp_id'),'source_api_url':c.get('url',''),
        'sha256':sha,
    }

if __name__=='__main__': raise SystemExit(main())