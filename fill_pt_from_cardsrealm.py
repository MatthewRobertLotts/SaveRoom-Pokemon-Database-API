#!/usr/bin/env python3
"""Complete Portuguese fallback rows using CardsRealm Portuguese set pages.

CardsRealm exposes PT/BR set spoiler pages with card names and collector numbers.
This script maps unresolved Portuguese rows by set + collector number and records
source provenance. It is used only for language_code='pt'.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS = {'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8'}
SET_URLS = {
    'bw11': 'https://pokemon.cardsrealm.com/pt-br/sets/bw11-legendary-treasures',
    'g1': 'https://pokemon.cardsrealm.com/pt-br/sets/g1-gym-heroes',
    'sma': 'https://pokemon.cardsrealm.com/pt-br/sets/sma-hidden-fates-shiny-vault',
    'col1': 'https://pokemon.cardsrealm.com/pt-br/sets/col1-call-of-legends',
    'hgss1': 'https://pokemon.cardsrealm.com/pt-br/sets/hgss1-heartgold-soulsilver',
}


def fetch(url: str) -> str:
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=45) as r:
        return r.read().decode('utf-8','ignore')


def clean(s: str) -> str:
    return html.unescape(re.sub(r'\s+',' ',s)).strip()


def strip_code(name: str, number: str) -> str:
    n=clean(name)
    # CardsRealm names look like "Coroa Floral GEN RC26", "Elesa LTR RC20", "Litografia Alph HS ONE".
    # Remove the final collector number and set abbreviation token.
    toks=n.split()
    if toks and toks[-1].lower()==number.lower():
        toks=toks[:-1]
    if toks and re.fullmatch(r'[A-Z0-9]{2,5}', toks[-1]):
        toks=toks[:-1]
    out=' '.join(toks).strip()
    return out or n


def parse_cardsrealm(raw: str) -> dict[str, dict[str,str]]:
    out={}
    pat=re.compile(r'<a itemprop="url" href="([^"]+)" title="([^"]+)".*?<span itemprop="name">([^<]+)</span>\s*#([^<]+)<', re.S)
    for href,title,span,number in pat.findall(raw):
        number=clean(number)
        name=strip_code(span, number)
        out[number.upper()]={'name':name,'href':href,'title':clean(title)}
    return out


def unresolved(conn):
    return conn.execute("""
        SELECT p.set_id,p.card_id,c.local_id,c.name AS old_name
        FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
        ORDER BY p.set_id,c.local_id_sort,c.card_id
    """).fetchall()


def main():
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    maps={}
    parsed_counts={}
    for set_id,url in SET_URLS.items():
        raw=fetch(url)
        cards=parse_cardsrealm(raw)
        maps[set_id]=cards
        parsed_counts[set_id]=len(cards)
        print(set_id, 'parsed', len(cards))
    rows=unresolved(conn)
    updated=0; examples=[]; misses=[]
    for r in rows:
        set_id=r['set_id']; local=(r['local_id'] or '').upper()
        hit=maps.get(set_id,{}).get(local)
        if not hit:
            misses.append(dict(r)); continue
        name=hit['name']
        source_url=SET_URLS[set_id]
        if hit.get('href') and hit['href'].startswith('/'):
            source_url='https://pokemon.cardsrealm.com'+hit['href']
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?',(name,'pt',r['card_id']))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """,('pt',set_id,r['card_id'],source_url,'cardsrealm_pt_set_spoiler',f'Portuguese card name parsed from CardsRealm Portuguese set/card listing; old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated+=1
        if len(examples)<50: examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':name,'source':source_url})
    conn.commit()
    remaining=conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    """).fetchone()[0]
    by_set=list(conn.execute("""
        SELECT p.set_id, COUNT(*) FROM card_source_provenance p WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
        GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """).fetchall())
    report={'fetched_at':FETCHED_AT,'parsed_counts':parsed_counts,'input_unresolved':len(rows),'updated':updated,'remaining_pt':remaining,'remaining_by_set':[list(x) for x in by_set],'examples':examples,'misses':misses[:80]}
    out=REPORT_DIR/'cardsrealm_pt_completion.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:12000])
    print('Report:',out)
    conn.close()

if __name__=='__main__': main()
