#!/usr/bin/env python3
"""Replace Simplified Chinese placeholders using Cryst's Cards Database API.

Source: https://tcg.mik.moe/api/v3/card/product-list and product-detail.
This provides real Simplified Chinese card names and set lists.
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
CACHE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/cryst_mik_moe')
BASE='https://tcg.mik.moe'
FETCHED_AT='2026-06-11T17:05:00+00:00'
UA='Mozilla/5.0 SaveRoomPokemonKB/1.0'


def post(path,payload,cache_name=None):
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    if cache_name:
        cp=CACHE_DIR/cache_name
        if cp.exists() and cp.stat().st_size>20:
            return json.loads(cp.read_text(encoding='utf-8'))
    req=urllib.request.Request(BASE+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':UA},method='POST')
    data=json.loads(urllib.request.urlopen(req,timeout=60).read().decode())
    if cache_name:
        (CACHE_DIR/cache_name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data


def sort_int(x):
    m=re.search(r'\d+',str(x)); return int(m.group(0)) if m else None


def update_set(conn,set_id,product):
    detail=post('/api/v3/card/product-detail',{'setId':product['setId']},f"product_{product['setId']}.json")
    if detail.get('code')!=200 or not detail.get('data'):
        return {'set_id':set_id,'product_setId':product['setId'],'status':'detail_failed','updated':0,'inserted':0,'cards':0}
    d=detail['data']; cards=d.get('cards') or []
    updated=inserted=0
    # Ensure set official count reflects real source if larger.
    if cards:
        conn.execute('update sets set official_count=?, total_count=coalesce(total_count,?) where language_code=? and set_id=?',(len(cards),len(cards),'zh-cn',set_id))
    for c in cards:
        local=str(c.get('cardIndex') or '').strip()
        name=str(c.get('cardName') or '').strip()
        if not local or not name: continue
        card_id=f'{set_id}-{local}'
        srt=sort_int(local)
        existing=conn.execute('select card_id from cards where language_code=? and set_id=? and local_id_sort=?',('zh-cn',set_id,srt)).fetchone()
        if existing:
            card_id=existing[0]
            conn.execute('update cards set name=?, local_id=?, local_id_sort=? where language_code=? and card_id=?',(name,local,srt,'zh-cn',card_id))
            updated+=1
        else:
            conn.execute('insert into cards(language_code,set_id,card_id,local_id,local_id_sort,name,image_url) values(?,?,?,?,?,?,?)',('zh-cn',set_id,card_id,local,srt,name,f'https://tcg.mik.moe/static/img/{d.get("setCode")}/{local}.png'))
            inserted+=1
        conn.execute('''insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                        values(?,?,?,?,?,?,?)''',('zh-cn',set_id,card_id,f'https://tcg.mik.moe/cards/{product["setId"]}/{local}','cryst_mik_moe_api',f'Real Simplified Chinese card name from Cryst API product-detail setId={product["setId"]}; source setCode={d.get("setCode")}',FETCHED_AT))
        conn.execute('''insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,category,fetched_at)
                        values(?,?,?,?,?,?,?,?,?)''',(card_id,'zh-cn',set_id,local,srt,name,c.get('rarity'),c.get('cardType'),FETCHED_AT))
    return {'set_id':set_id,'product_setId':product['setId'],'product_name':product.get('name'),'status':'ok','updated':updated,'inserted':inserted,'cards':len(cards)}


def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH)
    plist=post('/api/v3/card/product-list',{},'product_list.json')['data']['list']
    by_lower={p['setId'].lower():p for p in plist}
    by_name={p['name']:p for p in plist}
    alias = {
        'csm1a': 'CSM1aC',
        'csm1b': 'CSM1bC',
        'csm1c': 'CSM1cC',
        'csm1.5': 'CSM1.5C',
        'csm2a': 'CSM2aC',
        'csm2b': 'CSM2bC',
        'csm2c': 'CSM2cC',
        'csm2.5': 'CSM2.5C',
    }
    targets=conn.execute("""
        select distinct s.set_id,s.name
        from sets s
        where s.language_code='zh-cn'
          and exists (
            select 1 from card_source_provenance p
            where p.language_code='zh-cn' and p.set_id=s.set_id
              and p.method in ('official_count_placeholder','cross_language_template')
              and not exists (
                select 1 from card_source_provenance r
                where r.language_code=p.language_code and r.card_id=p.card_id
                  and r.method in ('cryst_mik_moe_api')
              )
          )
        order by s.set_id
    """).fetchall()
    print('targets',len(targets))
    report=[]
    for set_id,name in targets:
        p=by_lower.get(set_id.lower()) or by_lower.get(alias.get(set_id, '').lower()) or by_name.get(name)
        # TCGdex has lowercase aliases csm1a/csm1b/csm1c that map to Cryst CSM1aC/bC/cC.
        if not p:
            alt=set_id.upper()
            p=by_lower.get(alt.lower())
        if not p:
            report.append({'set_id':set_id,'name':name,'status':'no_product_match'})
            continue
        res=update_set(conn,set_id,p)
        report.append(res)
        conn.commit()
        print(set_id,name,'->',p['setId'],res['status'],'cards',res.get('cards'),'updated',res.get('updated'),'inserted',res.get('inserted'))
    (REPORT_DIR/'cryst_mik_moe_zh_cn_replacement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    conn.close()

if __name__=='__main__':
    main()
