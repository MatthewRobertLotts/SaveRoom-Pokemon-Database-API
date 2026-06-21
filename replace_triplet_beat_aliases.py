#!/usr/bin/env python3
"""Replace Triplet Beat regional alias placeholder rows using Bulbapedia Triplet Beat list."""
from __future__ import annotations
import re, sqlite3, urllib.request, urllib.parse
from pathlib import Path

DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
FETCHED_AT='2026-06-11T17:25:00+00:00'
TITLE='Triplet Beat (TCG)'
URL='https://bulbapedia.bulbagarden.net/w/index.php?title=Triplet_Beat_(TCG)&action=raw'
SOURCE='https://bulbapedia.bulbagarden.net/wiki/Triplet_Beat_(TCG)'
ALIASES=['CS1.5','CS1a','CS1b','CS2.5','CS2a','CS2b','CS3.5','sv1a']
LANGS=['id','ja','ko','th','zh-tw']

def split_args(s):
    out=[];buf=[];depth=0;i=0
    while i<len(s):
        if s[i:i+2]=='{{': depth+=1;buf.append('{{');i+=2;continue
        if s[i:i+2]=='}}' and depth: depth-=1;buf.append('}}');i+=2;continue
        if s[i]=='|' and depth==0: out.append(''.join(buf).strip());buf=[]
        else: buf.append(s[i])
        i+=1
    out.append(''.join(buf).strip()); return out

def clean(s):
    s=re.sub(r'\{\{TCG ID\|[^|{}]+\|([^|{}]+)\|[^|{}]+\}\}',r'\1',s)
    s=re.sub(r'\[\[[^]|]+\|([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\[\[([^]]+)\]\]',r'\1',s)
    s=re.sub(r'\{\{[^{}]+\}\}','',s)
    s=re.sub(r'<[^>]+>','',s)
    return re.sub(r'\s+',' ',s).strip()

def sort_int(x):
    m=re.search(r'\d+',str(x)); return int(m.group(0)) if m else None

txt=urllib.request.urlopen(urllib.request.Request(URL,headers={'User-Agent':'SaveRoomKB/1.0'}),timeout=60).read().decode()
entries=[]
for args_s in re.findall(r'\{\{Setlist/entry\|(.*?)\}\}',txt,re.S):
    args=split_args(args_s)
    if len(args)<3: continue
    local=args[0].split('/')[0]
    name=clean(args[2])
    rarity=clean(args[-1]) if args else None
    if local and name: entries.append((local,name,rarity))
print('entries',len(entries))
conn=sqlite3.connect(DB)
updated=0
for lang in LANGS:
  for set_id in ALIASES:
    rows=conn.execute("""
    select card_id, local_id_sort, name from cards where language_code=? and set_id=? and (name like 'Unknown card%' or card_id in (
      select card_id from card_source_provenance where language_code=? and set_id=? and method='official_count_placeholder'
    )) order by local_id_sort limit ?
    """,(lang,set_id,lang,set_id,len(entries))).fetchall()
    if not rows: continue
    for (card_id,srt,old), (local,name,rarity) in zip(rows,entries):
        conn.execute('update cards set name=?, local_id=?, local_id_sort=? where language_code=? and card_id=?',(name,local,sort_int(local),lang,card_id))
        conn.execute('''insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                        values(?,?,?,?,?,?,?)''',(lang,set_id,card_id,SOURCE,'bulbapedia_triplet_beat_alias',f'Replaced regional Triplet Beat alias placeholder {old!r} using {TITLE}; localized names unavailable, English card names used.',FETCHED_AT))
        conn.execute('''insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,fetched_at)
                        values(?,?,?,?,?,?,?,?)''',(card_id,lang,set_id,local,sort_int(local),name,rarity,FETCHED_AT))
        updated+=1
    print(lang,set_id,'updated',len(rows))
conn.commit(); conn.close()
print('total_updated',updated)
