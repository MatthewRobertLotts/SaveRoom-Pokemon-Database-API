#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, hashlib, json, re, sqlite3, urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
ROOT=Path('/media/matt/Storage/Brain/Pokemon Card Database')
REPORTS=DB.parent/'reports'
OUT=ROOT/'recovered_images'/dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')/'en_manual'
UA={'User-Agent':'Hermes SaveRoom exact English remaining recovery/1.0'}

def get(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r:
        return r.status,r.read(),r.headers.get('content-type','')

def text(url):
    return get(url)[1].decode('utf-8','replace')

def sha(b): return hashlib.sha256(b).hexdigest()
def slug(s):
    return re.sub(r'[^a-z0-9]+','-',s.lower().replace('’','').replace("'",'').replace('&','and')).strip('-')

def pricecharting_page(set_id, local, name):
    n=str(local).strip().upper()
    lname=name.lower().replace('basic ','')
    if set_id=='mee':
        energy={'Grass':'grass','Fire':'fire','Water':'water','Lightning':'lightning','Psychic':'psychic','Fighting':'fighting','Darkness':'darkness','Metal':'metal'}
        typ=name.replace(' Energy','').replace('Basic ','')
        if typ in energy: return f'https://www.pricecharting.com/game/pokemon-mega-evolution-energy/basic-{energy[typ]}-energy-{int(n)}'
    if set_id=='2024sv': return 'https://www.pricecharting.com/game/pokemon-mcdonalds-2024/roaring-moon-11'
    if set_id=='2023sv': return 'https://www.pricecharting.com/game/pokemon-mcdonalds-2023/kilowattrel-8'
    if set_id=='ecard3': return 'https://www.pricecharting.com/game/pokemon-skyridge/flareon-h7'
    if set_id in {'tk-dp-l','tk-dp-m'}:
        base='https://www.pricecharting.com/game/pokemon-manaphy-lucario/'
        maps={('tk-dp-m','1'):'buizel-1',('tk-dp-m','9'):'dusk-ball-9',('tk-dp-l','10'):'quick-ball-10'}
        key=(set_id,str(int(n)) if n.isdigit() else n)
        if key in maps: return base+maps[key]
    return None

XYA_PAGES={
 '24A':'https://pkmncards.com/card/m-manectric-ex-phantom-forces-phf-24a/',
 '55A':'https://pkmncards.com/card/m-lucario-ex-furious-fists-ffi-55a/',
 '92A':'https://pkmncards.com/card/trainers-mail-roaring-skies-ros-92a/',
 '107A':'https://pkmncards.com/card/professor-sycamore-breakpoint-bkp-107a/',
}

def pkmn_image(page, local, name):
    html=text(page)
    if f'#{local}' not in html and f'#{local.upper()}' not in html: return None
    if re.sub(r'[^a-z0-9]+','',name.lower()) not in re.sub(r'[^a-z0-9]+','',html[:25000].lower()): return None
    imgs=re.findall(r'https://pkmncards.com/wp-content/uploads/[^"\'<> ]+?\.(?:jpg|png|jpeg|webp)',html)
    return next((u for u in imgs if 'clefairy' not in u and 'favicon' not in u), None)

def price_image(page):
    try:
        html=text(page)
    except Exception:
        return None
    imgs=re.findall(r'https://storage.googleapis.com/images.pricecharting.com/[^"\'<> ]+/1600.jpg',html)
    return imgs[0] if imgs else None

def main():
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    rows=conn.execute("select resolved_set_id,card_id,local_id,card_name from v2_card_search where language_code='en' and has_display_image=0 order by resolved_set_id,local_id_sort,card_id").fetchall(); conn.close()
    manifest=[]; misses=[]; cache={}
    for r in rows:
        sid,card_id,local,name=r['resolved_set_id'],r['card_id'],r['local_id'],r['card_name']
        url=src=None; ctype='exact_pricecharting_asset'
        if sid=='xya' and local.upper() in XYA_PAGES:
            src=XYA_PAGES[local.upper()]; url=pkmn_image(src, local, name); ctype='exact_pkmncards_asset'
        else:
            src=pricecharting_page(sid,local,name)
            if src: url=price_image(src)
        if not url:
            misses.append(dict(r)|{'reason':'no_manual_source'}); continue
        try:
            if url in cache: path,nbytes,h=cache[url]
            else:
                status,data,mime=get(url)
                if status!=200 or 'image' not in mime: raise RuntimeError(f'bad {status} {mime}')
                outdir=OUT/sid; outdir.mkdir(parents=True,exist_ok=True)
                ext='.jpg' if 'jpg' in mime or 'jpeg' in mime else '.png'
                path=outdir/(re.sub(r'[^A-Za-z0-9_.-]+','_',card_id)+ext)
                path.write_bytes(data); nbytes=len(data); h=sha(data); cache[url]=(path,nbytes,h)
            manifest.append({'set_id':sid,'card_id':card_id,'local_id':local,'name':name,'image_url':url,'asset_url':url,'status':'downloaded','candidate_type':ctype,'language_code':'en','local_path':str(path),'bytes':nbytes,'core_set_id':sid,'resolved_set_id':sid,'source_set_id':sid,'source_card_id':card_id,'source_api_url':src,'sha256':h})
        except Exception as e: misses.append(dict(r)|{'reason':str(e),'asset_url':url})
    out=REPORTS/f'en_manual_remaining_recovery_{dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")}.json'
    out.write_text(json.dumps({'generated_at':dt.datetime.now(dt.UTC).isoformat(),'manifest':manifest,'missed_entries':misses},indent=2,ensure_ascii=False))
    print(json.dumps({'report':str(out),'downloaded':len(manifest),'misses':len(misses)},indent=2))
    return 0 if manifest else 2
if __name__=='__main__': raise SystemExit(main())
