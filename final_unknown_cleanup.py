#!/usr/bin/env python3
"""Final targeted cleanup for remaining Unknown card rows."""
from __future__ import annotations
import re, sqlite3, urllib.request
from pathlib import Path

DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
FETCHED_AT='2026-06-11T17:40:00+00:00'
MAP={
    'EBB':'Legendary_Treasures_(TCG)',
    'SM10b':'Sky_Legend_(TCG)',
    'SM7a':'Thunderclap_Spark_(TCG)',
    'SM12':'Cosmic_Eclipse_(TCG)',
}

def fetch(title):
    url=f'https://bulbapedia.bulbagarden.net/w/index.php?title={title}&action=raw'
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SaveRoomKB/1.0'}),timeout=60).read().decode('utf-8','replace')

def split_args(s):
    out=[];buf=[];depth=0;i=0
    while i<len(s):
        if s[i:i+2]=='{{': depth+=1;buf.append('{{');i+=2;continue
        if s[i:i+2]=='}}' and depth: depth-=1;buf.append('}}');i+=2;continue
        if s[i]=='|' and depth==0: out.append(''.join(buf).strip());buf=[]
        else: buf.append(s[i])
        i+=1
    out.append(''.join(buf).strip());return out

def clean(s):
    s=re.sub(r'\{\{TCG ID\|[^|{}]+\|([^|{}]+)\|[^|{}]+\}\}',r'\1',s)
    s=re.sub(r'\[\[[^]|]+\|([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\[\[([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\{\{[^{}]+\}\}','',s)
    s=re.sub(r'<[^>]+>','',s)
    return re.sub(r'\s+',' ',s).strip()

def parse(title):
    txt=fetch(title)
    entries=[]
    for kind,args_s in re.findall(r'\{\{Setlist/(entry|nmentry)\|(.*?)\}\}',txt,re.S):
        args=split_args(args_s)
        if kind=='entry':
            if len(args)<3: continue
            local=args[0].split('/')[0]; card=args[2]; rarity=args[-1]
        else:
            if len(args)<2: continue
            local=args[0].split('/')[0]; card=args[1]; rarity=args[-1]
        name=clean(card); rarity=clean(rarity)
        if local and name: entries.append((local,name,rarity))
    # dedupe by local
    seen=set(); out=[]
    for e in entries:
        if e[0] in seen: continue
        seen.add(e[0]); out.append(e)
    return out

def sort_int(x):
    m=re.search(r'\d+',str(x)); return int(m.group(0)) if m else None

conn=sqlite3.connect(DB)
updated=0; deleted=0
# Delete Chinese csm2.5 placeholders beyond Cryst verified count (99)
for card_id, in conn.execute("""
select card_id from cards where language_code='zh-cn' and set_id='csm2.5' and name like 'Unknown card%' and local_id_sort>99
""").fetchall():
    conn.execute('delete from cards where language_code=? and card_id=?',('zh-cn',card_id))
    conn.execute('delete from card_source_provenance where language_code=? and card_id=? and method=?',('zh-cn',card_id,'official_count_placeholder'))
    deleted+=1

for set_id,title in MAP.items():
    entries=parse(title)
    print(set_id,title,'entries',len(entries))
    for lang in ['ja','ko']:
        rows=conn.execute("""
        select card_id, local_id_sort, name from cards
        where language_code=? and set_id=? and name like 'Unknown card%'
        order by local_id_sort
        """,(lang,set_id)).fetchall()
        if not rows: continue
        for (card_id,srt,old),(local,name,rarity) in zip(rows,entries):
            conn.execute('update cards set name=?, local_id=?, local_id_sort=? where language_code=? and card_id=?',(name,local,sort_int(local),lang,card_id))
            conn.execute('''insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                            values(?,?,?,?,?,?,?)''',(lang,set_id,card_id,f'https://bulbapedia.bulbagarden.net/wiki/{title}','bulbapedia_final_unknown_cleanup',f'Replaced remaining unknown {old!r} using {title}',FETCHED_AT))
            conn.execute('''insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,fetched_at)
                            values(?,?,?,?,?,?,?,?)''',(card_id,lang,set_id,local,sort_int(local),name,rarity,FETCHED_AT))
            updated+=1
        print(lang,set_id,'updated',len(rows))
conn.commit(); conn.close()
print('updated',updated,'deleted',deleted)
