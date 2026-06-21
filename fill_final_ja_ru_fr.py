#!/usr/bin/env python3
"""Complete final ja/ru/fr unresolved fallback rows with sourced localized names."""
from __future__ import annotations
import json,sqlite3,time,urllib.parse,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
API='https://api.daldagury.com'
HEAD={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Origin':'https://daldagury.com','Referer':'https://daldagury.com/'}

def get_json(path,params=None):
    url=API+path+('?' + urllib.parse.urlencode(params) if params else '')
    return json.load(urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=60))

def unresolved(conn, lang):
    return conn.execute("""
    SELECT p.language_code,p.set_id,p.card_id,c.local_id,c.name old_name
    FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
    WHERE p.language_code=? AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    ORDER BY p.set_id,c.local_id_sort,c.card_id
    """,(lang,)).fetchall()

def set_card_map(setid):
    data=get_json('/tcg/cards/search',{'gameCode':'pokemon','setIds':setid,'limit':500})['resultData']['data']
    return {(c.get('cardNumber') or '').upper(): c for c in data if c.get('cardNumber')}, data

def fill_ja(conn):
    # Daldagury set ids for JP region rows: S10b Pokémon GO, S11 Lost Abyss, S8a 25th Anniversary Collection.
    jp_set_ids={'S10b':'2031','S11':'2029','S8a':'2039'}
    maps={}; rows_by_set={}
    for code,sid in jp_set_ids.items():
        maps[code], data=set_card_map(sid)
        rows_by_set[code]={'daldagury_set_id':sid,'api_rows':len(data),'mapped_locals':len(maps[code])}
    updated=[]; misses=[]
    for r in unresolved(conn,'ja'):
        hit=maps.get(r['set_id'],{}).get((r['local_id'] or '').upper())
        if not hit:
            misses.append(dict(r)); continue
        name=hit['nameKo']  # For JP-region Daldagury rows this field contains the Japanese printed name.
        url=f'https://daldagury.com/tcg/pokemon/card/{hit["cardId"]}'
        conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'ja',r['card_id']))
        conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('ja',r['set_id'],r['card_id'],url,'daldagury_jp_card_api',f'Japanese name sourced from Daldagury JP-region Pokémon TCG API/card page; local={r["local_id"]!r}; old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated.append({'card_id':r['card_id'],'old':r['old_name'],'new':name,'url':url})
    return {'input':len(updated)+len(misses),'updated':len(updated),'miss_count':len(misses),'misses':misses,'set_meta':rows_by_set,'examples':updated[:80]}

RU_FIXES={
 'xy2-88a': ('Кузнец', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%9E%D0%B3%D0%BD%D0%B5%D0%BD%D0%BD%D0%B0%D1%8F_%D0%92%D1%81%D0%BF%D1%8B%D1%88%D0%BA%D0%B0', 'Pokeru/ShoutWiki Russian XY—Fire Flash set checklist lists 88/106 as Кузнец.'),
 'xy3-55a': ('М Лукарио-EX', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%AF%D1%80%D0%BE%D1%81%D1%82%D0%BD%D1%8B%D0%B9_%D0%9A%D1%83%D0%BB%D0%B0%D0%BA', 'Russian XY—Furious Fists set checklist entry for 55/111; Mega Pokémon card name normalized to Russian TCG printed style.'),
 'xy4-24a': ('М Манектрик-EX', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%9F%D1%80%D0%B8%D0%B7%D1%80%D0%B0%D1%87%D0%BD%D1%8B%D0%B5_%D0%A1%D0%B8%D0%BB%D1%8B', 'Russian XY—Phantom Forces set checklist entry for 24/119; Mega Pokémon card name normalized to Russian TCG printed style.'),
 'xy4-65a': ('Эгислэш-EX', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%9F%D1%80%D0%B8%D0%B7%D1%80%D0%B0%D1%87%D0%BD%D1%8B%D0%B5_%D0%A1%D0%B8%D0%BB%D1%8B', 'Russian XY—Phantom Forces set checklist entry for 65/119.'),
 'xy6-77a': ('Шеймин-EX', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%93%D1%80%D0%BE%D1%85%D0%BE%D1%87%D1%83%D1%89%D0%B8%D0%B5_%D0%9D%D0%B5%D0%B1%D0%B5%D1%81%D0%B0', 'Russian XY—Roaring Skies set checklist entry for 77/108.'),
 'xy6-92a': ('Тренерская почта', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%93%D1%80%D0%BE%D1%85%D0%BE%D1%87%D1%83%D1%89%D0%B8%D0%B5_%D0%9D%D0%B5%D0%B1%D0%B5%D1%81%D0%B0', 'Russian XY—Roaring Skies set checklist entry for Trainers’ Mail 92/108.'),
 'xy7-75a': ('Оккультистка', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%94%D1%80%D0%B5%D0%B2%D0%BD%D0%B8%D0%B5_%D0%98%D1%81%D1%82%D0%BE%D0%BA%D0%B8', 'Russian XY—Ancient Origins set checklist entry for Hex Maniac 75/98.'),
 'xy8-146a': ('Письмо профессора', 'https://pokeru.shoutwiki.com/wiki/%D0%9A%D0%9A%D0%98:%D0%A2%D1%83%D1%80%D0%B1%D0%BE_%D0%98%D0%BC%D0%BF%D1%83%D0%BB%D1%8C%D1%81', 'Russian XY—BREAKthrough set checklist entry for Professor’s Letter 146/162.'),
}

def fill_static(conn, lang, fixes, method):
    updated=[]; misses=[]
    for r in unresolved(conn,lang):
        fix=fixes.get(r['card_id'])
        if not fix:
            misses.append(dict(r)); continue
        name,url,note=fix
        conn.execute('update cards set name=? where language_code=? and card_id=?',(name,lang,r['card_id']))
        conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",(lang,r['set_id'],r['card_id'],url,method,note+f' Old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated.append({'card_id':r['card_id'],'old':r['old_name'],'new':name,'url':url})
    return {'input':len(updated)+len(misses),'updated':len(updated),'miss_count':len(misses),'misses':misses,'examples':updated}

def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    before={lang:len(unresolved(conn,lang)) for lang in ['ja','ru','fr']}
    report={'fetched_at':FETCHED_AT,'before':before}
    report['ja']=fill_ja(conn)
    report['ru']=fill_static(conn,'ru',RU_FIXES,'pokeru_ru_set_checklist_manual')
    report['fr']=fill_static(conn,'fr',{'B1-283':('Tauros-ex','https://www.pokepedia.fr/Tauros-ex_(M%C3%A9ga-Ascension_283)','Poképédia page for Tauros-ex (Méga-Ascension 283) lists French name Tauros-ex and numbering 283/226.')},'pokepedia_fr_pocket_card_page')
    conn.commit()
    after={lang:len(unresolved(conn,lang)) for lang in ['ja','ru','fr']}
    total=conn.execute("""select count(*) from card_source_provenance p where p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
    report['after']=after; report['global_remaining_unresolved']=total
    report['unknown_names']=conn.execute("select count(*) from cards where name like 'Unknown card%' or name like 'Unresolved promo%'").fetchone()[0]
    report['missing_language_set_rows']=conn.execute("select count(*) from sets s where not exists (select 1 from cards c where c.language_code=s.language_code and c.set_id=s.set_id)").fetchone()[0]
    out=REPORT_DIR/'final_ja_ru_fr_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:30000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
