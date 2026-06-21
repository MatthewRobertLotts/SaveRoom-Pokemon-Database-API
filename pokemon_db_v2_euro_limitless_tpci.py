#!/usr/bin/env python3
"""Recover European language images from Limitless tpci CDN bucket."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
DB=ROOT/'full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite'
OUT_ROOT=ROOT/'recovered_images/euro_limitless'
REPORTS=ROOT/'full_tcgdex/reports'
UA='Mozilla/5.0'
CDN='https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpci'

# DB set_id -> Limitless set code (uppercase)
SET_MAP = {
    # Promo sets (codes confirmed work)
    'smp': 'SMP', 'bwp': 'BWP', 'xyp': 'XYP', 'svp': 'SVP',
    'swshp': 'SSH', 'sve': 'SVE',
    # SM promos / special
    'sma': 'HIF',  # Hidden Fates Shiny Vault
    'sm7.5': 'DRM',  # Dragon Majesty
    'sm3.5': 'SLG',  # Shining Legends
    'sm115': 'DRM',  # Dragon Majesty actually
    'sm35': 'SLG',   # Shining Legends
    'g1': 'G1',  # Generations (already on list)
    'g2': 'G2',  # Gym Heroes 2
    # XY promos
    'xya': 'KSS', 'xyb': 'KSS', 'xyc': 'KSS',
    'xyd': 'KSS', 'xye': 'KSS', 'xyf': 'KSS',
    'xyg': 'KSS', 'xyh': 'KSS',
    # BW promos
    'bwp': 'BWP',
    # DP promos
    'dpp': 'DPP',
    # Neo
    'neo1': 'N1', 'neo2': 'N2', 'neo3': 'N3', 'neo4': 'N4',
    # DP
    'dp1': 'DP', 'dp2': 'MT', 'dp3': 'GE', 'dp4': 'LA', 
    'dp5': 'MD', 'dp6': 'SW', 'dp7': 'SF',
    # Platinum
    'pl1': 'PL', 'pl2': 'RR', 'pl3': 'SF', 'pl4': 'SV',
    # EX
    'ex1': 'RS', 'ex2': 'SS', 'ex3': 'DR', 'ex4': 'DR',
    'ex5': 'TM', 'ex6': 'LM', 'ex7': 'HP', 'ex8': 'DX',
    'ex9': 'EM', 'ex10': 'UF', 'ex11': 'CG', 'ex12': 'LM',
    'ex13': 'HP', 'ex14': 'CG', 'ex15': 'DF', 'ex16': 'PK',
    # HGSS
    'hgss1': 'HS', 'hgss2': 'UL', 'hgss3': 'UD', 'hgss4': 'TM',
    # League / Rocket
    'base1': 'BS', 'base2': 'BS2', 'base3': 'FO', 'base5': 'JU',
    # Gym
    'g1': 'G1', 'g2': 'G2',
    # e-Card
    'ecard1': 'EX', 'ecard2': 'AQ', 'ecard3': 'SK',
    # Other
    'col1': 'CL', 'det1': 'DET',
    'b1': 'BS', 'b2': 'BS2', 'b1a': 'BS',
    'wp': 'WP', 'sp': 'SP',
    'dc1': 'DC', 'dc': 'DC',
}

# Also check all Limitless codes from the website
LIMITLESS_CODES = [
    'AOR','AR','ASC','ASR','BCR','BG','BKP','BKT','BLK','BLW','BRS','BS','BS2','BST','BUS',
    'BWP','CEC','CEL','CES','CG','CIN','CL','CPA','CRE','CRI','CRZ','DAA','DCR','DET','DEX',
    'DF','DP','DPP','DR','DRI','DRM','DRV','DRX','DS','DX','E1','E2','E3','EM','EPO','EVO',
    'EVS','FCO','FFI','FLF','FLI','FO','FST','G1','G2','GE','GEN','GRI','HIF','HL','HP','HS',
    'HSP','JTG','JU','KSS','LA','LC','LM','LOR','LOT','LTR','MA','MD','MEE','MEG','MEP','MEW',
    'MT','N1','N2','N3','N4','NP','NVI','NXD','OBF','P1','P2','P3','P4','P5','P6','P7','P8','P9',
    'PAF','PAL','PAR','PFL','PGO','PHF','PK','PL','PLB','PLF','PLS','POR','PRC','PRE','RCL','RG',
    'RM','ROS','RR','RS','SCR','SF','SFA','SHF','SI','SIT','SLG','SMP','SP','SS','SSH','SSP','STS',
    'SUM','SV','SVE','SVI','SVP','SW','TEF','TEU','TM','TR','TRR','TWM','UD','UF','UL','UNB','UNM',
    'UPR','VIV','WHT','WP','XY','XYP',
]

def get_img(url:str)->bytes|None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=8) as r:
            if r.status==200 and 'image' in (r.headers.get('content-type') or '').lower():
                return r.read()
    except: return None

def main()->int:
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    manifest:list=[]; total_dl=0
    OUT_ROOT.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    
    for lang in ['fr','de','it','es','pt']:
        cards=conn.execute("""
            select card_id, local_id, name, set_id from cards
            where language_code=? and (image_url is null or trim(image_url)='')
        """, (lang,)).fetchall()
        if not cards: continue
        
        # For each card, try Limitless CDN with different set codes
        dl_count=0
        def dl(card_id, local_id, name, set_id):
            # Try direct mapping first
            ls=SET_MAP.get(set_id.lower())
            if ls:
                for num in [local_id, re.sub(r'[^0-9]','',local_id or ''),
                           f'{int(re.sub(r"[^0-9]","",local_id or "0") or 0):03d}',
                           str(int(re.sub(r'[^0-9]','',local_id or '0') or 0))]:
                    url=f'{CDN}/{ls}/{ls}_{num}_R_{lang.upper()}_LG.png'
                    d=get_img(url)
                    if d: return (d,url)
                    d=get_img(url.replace('_LG.png','.png'))
                    if d: return (d,url.replace('_LG.png','.png'))
            
            # Try all Limitless codes (slow but exhaustive)
            for lc in LIMITLESS_CODES:
                for num in [local_id, re.sub(r'[^0-9]','',local_id or '')]:
                    url=f'{CDN}/{lc}/{lc}_{num}_R_{lang.upper()}_LG.png'
                    d=get_img(url)
                    if d: return (d,url)
            return None
        
        with ThreadPoolExecutor(max_workers=32) as ex:
            futs={ex.submit(dl,c['card_id'],c['local_id'],c['name'],c['set_id']):c for c in cards}
            for f in as_completed(futs):
                c=futs[f]; item=f.result()
                if item:
                    data,url=item
                    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',c['card_id'])
                    out=OUT_ROOT/lang; out.mkdir(parents=True,exist_ok=True)
                    path=out/f'{safe}.webp'; path.write_bytes(data)
                    sha=hashlib.sha256(data).hexdigest()
                    manifest.append({
                        'language_code':lang,'card_id':c['card_id'],'name':c['name'],'local_id':c['local_id'],
                        'local_path':str(path),'image_url':url,'asset_url':url,'status':'downloaded',
                        'candidate_type':'exact_limitless_euro_asset','core_set_id':c['set_id'],
                        'resolved_set_id':c['set_id'],'source_set_id':c['set_id'],'sha256':sha})
                    dl_count+=1; total_dl+=1
        print(f'{lang}: {dl_count}')
    
    if manifest:
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        out=REPORTS/f'euro_limitless_tpci_{stamp}.json'
        out.write_text(json.dumps({'generated_at':stamp,'source':'Limitless tpci','manifest':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'MANIFEST={out}\nENTRIES={len(manifest)}')
    conn.close()
    return 0
if __name__=='__main__': raise SystemExit(main())