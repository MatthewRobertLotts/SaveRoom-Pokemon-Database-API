#!/usr/bin/env python3
"""Replace placeholder/cross-language rows with real Bulbapedia setlist data.

Improves prior scraper by parsing both {{Setlist/entry}} and {{Setlist/nmentry}},
following redirects, and searching Bulbapedia titles by set names.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
CACHE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/bulbapedia_v2')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = '2026-06-11T16:35:00+00:00'
UA = 'SaveRoomPokemonKB/1.0'
API='https://bulbapedia.bulbagarden.net/w/api.php'
RAW='https://bulbapedia.bulbagarden.net/w/index.php?title={title}&action=raw&redirect=no'
WIKI='https://bulbapedia.bulbagarden.net/wiki/'

KNOWN = {
    'SM12a': 'Tag All Stars (TCG)',
    'SM8b': 'Hidden Fates (TCG)',
    'SM4+': 'GX Battle Boost (TCG)',
    'CP4': 'Premium Champion Pack (TCG)',
    'CP6': 'Evolutions (TCG)',
    'XY1a': 'XY (TCG)',
    'XY1b': 'XY (TCG)',
    'XY2': 'Flashfire (TCG)',
    'XY3': 'Furious Fists (TCG)',
    'XY4': 'Phantom Forces (TCG)',
    'XY5a': 'Primal Clash (TCG)',
    'XY5b': 'Primal Clash (TCG)',
    'XY6': 'Roaring Skies (TCG)',
    'XY7': 'Ancient Origins (TCG)',
    'XY8a': 'BREAKthrough (TCG)',
    'XY8b': 'BREAKthrough (TCG)',
    'XY9': 'BREAKpoint (TCG)',
    'XY10': 'Fates Collide (TCG)',
    'XY11a': 'Steam Siege (TCG)',
    'XY11b': 'Steam Siege (TCG)',
    'CP3': 'PokéKyun Collection (TCG)',
    'CP2': 'Legendary Shine Collection (TCG)',
    'CP1': 'Double Crisis (TCG)',
    # Regional aliases in the current TCGdex layer that are Triplet Beat-derived buckets.
    'CS1.5': 'Triplet Beat (TCG)',
    'CS1a': 'Triplet Beat (TCG)',
    'CS1b': 'Triplet Beat (TCG)',
    'CS2.5': 'Triplet Beat (TCG)',
    'CS2a': 'Triplet Beat (TCG)',
    'CS2b': 'Triplet Beat (TCG)',
    'CS3.5': 'Triplet Beat (TCG)',
    'sv1a': 'Triplet Beat (TCG)',
    'csm1.5': 'Storming Emergence (ATCG)',
    'CSM1aC': 'Storming Emergence (ATCG)',
    'CSM1bC': 'Storming Emergence (ATCG)',
    'CSM1cC': 'Storming Emergence (ATCG)',
    'csm2.5': 'Shining Synergy (ATCG)',
    'CSM2aC': 'Shining Synergy (ATCG)',
    'CSM2bC': 'Shining Synergy (ATCG)',
    'CSM2cC': 'Shining Synergy (ATCG)',
}


def fetch(url: str, timeout=45) -> str | None:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return r.read().decode('utf-8','replace')
    except Exception:
        return None


def raw_title(title: str) -> tuple[str|None,str|None]:
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',title)[:180]
    path=CACHE_DIR/(safe+'.wiki')
    if path.exists() and path.stat().st_size>50:
        text=path.read_text(encoding='utf-8',errors='replace')
    else:
        text=fetch(RAW.format(title=urllib.parse.quote(title.replace(' ','_'),safe='')))
        if not text:
            return None,None
        path.write_text(text,encoding='utf-8')
        time.sleep(0.12)
    # follow raw redirect
    m=re.match(r'#REDIRECT\s*\[\[([^\]]+)\]\]',text,re.I)
    if m:
        target=m.group(1)
        if target!=title:
            return raw_title(target)
    if len(text)<50 or 'There is currently no text' in text:
        return None,None
    return text,title


def search_titles(q: str, limit=5) -> list[str]:
    url=API+'?'+urllib.parse.urlencode({'action':'query','list':'search','srsearch':q,'format':'json','srlimit':limit})
    data=fetch(url)
    if not data: return []
    try: js=json.loads(data)
    except Exception: return []
    time.sleep(0.12)
    return [h['title'] for h in js.get('query',{}).get('search',[]) if h.get('title')]


def split_args(s: str) -> list[str]:
    out=[]; buf=[]; depth=0; i=0
    while i<len(s):
        if s[i:i+2]=='{{': depth+=1; buf.append('{{'); i+=2; continue
        if s[i:i+2]=='}}' and depth: depth-=1; buf.append('}}'); i+=2; continue
        if s[i]=='|' and depth==0:
            out.append(''.join(buf).strip()); buf=[]
        else: buf.append(s[i])
        i+=1
    out.append(''.join(buf).strip())
    return out


def strip_markup(s: str) -> str:
    s=html.unescape(s)
    s=re.sub(r'\{\{(?:Mega|GX|EX|VSTAR|VMAX|Red TT GX|Blue TT GX|Green TT GX|e|TCG\|)(?:\|[^{}]*)?\}\}','',s)
    s=re.sub(r'\{\{TCG ID\|([^|{}]+)\|([^|{}]+)\|([^|{}]+)\}\}',r'\2',s)
    s=re.sub(r'\[\[[^]|]+\|([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\[\[([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\{\{[^{}]+\}\}','',s)
    s=re.sub(r'<[^>]+>','',s)
    return re.sub(r'\s+',' ',s).strip()


def extract_name(card_arg: str) -> str | None:
    m=re.search(r'\{\{TCG ID\|[^|{}]+\|([^|{}]+)\|[^|{}]+\}\}',card_arg)
    if m: return strip_markup(m.group(1))
    m=re.search(r'\[\[[^]|]+\|([^]]+)\]\]',card_arg)
    if m: return strip_markup(m.group(1))
    name=strip_markup(card_arg)
    return name or None


def parse_entries(text: str, wanted_count: int|None=None) -> list[dict]:
    entries=[]
    # Generic template capture for Setlist/entry and Setlist/nmentry; each entry line is one template in Bulba raw.
    for kind,args_s in re.findall(r'\{\{Setlist/(entry|nmentry)\|(.*?)\}\}',text,re.S):
        args=split_args(args_s)
        if kind=='entry':
            if len(args)<3: continue
            num=args[0]; card_arg=args[2]; rarity=args[-1] if args else None
        else:
            if len(args)<2: continue
            num=args[0]; card_arg=args[1]; rarity=args[-1] if args else None
        num_clean=strip_markup(num)
        den=None; local=num_clean
        if '/' in num_clean:
            local,den_s=num_clean.split('/',1)
            dm=re.search(r'\d+',den_s); den=int(dm.group(0)) if dm else None
        if wanted_count and den and den!=wanted_count:
            continue
        name=extract_name(card_arg)
        if not name: continue
        entries.append({'local_id':local.strip(),'name':name,'rarity':strip_markup(rarity or ''),'denominator':den})
    seen=set(); out=[]
    for e in entries:
        k=e['local_id']
        if k in seen: continue
        seen.add(k); out.append(e)
    return out


def find_page(set_id: str, set_name: str, count: int|None) -> tuple[str|None,list[dict],str]:
    titles=[]
    if set_id in KNOWN: titles.append(KNOWN[set_id])
    for q in [f'"{set_name}" TCG', f'{set_name} TCG', f'{set_name} ATCG', f'{set_id} TCG']:
        titles += search_titles(q,5)
    seen=[]
    for t in titles:
        if t in seen: continue
        seen.append(t)
        if not (t.endswith('(TCG)') or t.endswith('(ATCG)') or 'cards (TCG)' in t):
            continue
        text,final=raw_title(t)
        if not text: continue
        entries=parse_entries(text,count)
        if entries:
            # accept exact count or sizeable useful list if count absent; exact preferred
            if count is None or len(entries)==count or len(entries)>=min(count or 1,50):
                return final or t, entries, 'exact_or_sizeable'
    return None, [], 'not_found'


def sort_int(local_id: str) -> int|None:
    m=re.search(r'\d+',local_id); return int(m.group(0)) if m else None


def replace_set(conn, lang, set_id, entries, title):
    updated=0
    for e in entries:
        srt=sort_int(e['local_id'])
        if srt is None: continue
        # Prefer matching local_id_sort, because placeholder width may differ.
        row=conn.execute('select card_id,name from cards where language_code=? and set_id=? and local_id_sort=?',(lang,set_id,srt)).fetchone()
        if not row: continue
        card_id,old=row
        # Only overwrite placeholders or cross-language/fallback rows with provenance methods we are replacing.
        prov=conn.execute("select method from card_source_provenance where language_code=? and card_id=? and method in ('official_count_placeholder','cross_language_template')",(lang,card_id)).fetchone()
        if not prov: continue
        conn.execute('update cards set name=?, local_id=? where language_code=? and card_id=?',(e['name'],e['local_id'],lang,card_id))
        conn.execute('''insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                        values(?,?,?,?,?,?,?)''',(lang,set_id,card_id,WIKI+urllib.parse.quote(title.replace(' ','_'),safe='()_'),'bulbapedia_v2_setlist',f'Replaced {prov[0]} name {old!r} using Bulbapedia {title}',FETCHED_AT))
        conn.execute('''insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,fetched_at)
                        values(?,?,?,?,?,?,?,?)''',(card_id,lang,set_id,e['local_id'],srt,e['name'],e.get('rarity'),FETCHED_AT))
        updated+=1
    return updated


def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH)
    targets=conn.execute('''
    select p.language_code,p.set_id,s.name,s.official_count,count(*) cnt
    from card_source_provenance p join sets s on s.language_code=p.language_code and s.set_id=p.set_id
    where p.method in ('official_count_placeholder','cross_language_template')
      and not exists (
          select 1 from card_source_provenance done
          where done.language_code=p.language_code
            and done.set_id=p.set_id
            and done.method='bulbapedia_v2_setlist'
      )
    group by p.language_code,p.set_id
    order by cnt desc
    ''').fetchall()
    print('targets',len(targets))
    report=[]; total=0
    page_cache={}
    for i,(lang,set_id,name,count,cnt) in enumerate(targets,1):
        key=(set_id,name,count)
        if key in page_cache:
            title,entries,status=page_cache[key]
        else:
            title,entries,status=find_page(set_id,name,count)
            page_cache[key]=(title,entries,status)
        updated=0
        if entries and title:
            updated=replace_set(conn,lang,set_id,entries,title)
            conn.commit()
        total+=updated
        if updated or i%50==0:
            print(f'{i}/{len(targets)} {lang} {set_id} {name}: entries={len(entries)} updated={updated} title={title}')
        report.append({'lang':lang,'set_id':set_id,'name':name,'count':count,'placeholder_rows':cnt,'title':title,'entries':len(entries),'updated':updated,'status':status})
    (REPORT_DIR/'bulbapedia_v2_placeholder_replacement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('total_updated',total)
    conn.close()

if __name__=='__main__':
    main()
