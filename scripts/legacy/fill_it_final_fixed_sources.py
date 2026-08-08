#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
DP_SOURCE='https://bulbapedia.bulbagarden.net/wiki/Diamond_%26_Pearl_Trainer_Kit_(TCG)'
MAP={
 # EX Trainer Kit (Latias/Latios) - Cardmarket Italian product pages/search results
 'tk-ex-latia-8':('Pozione','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Potion-TK1Latias-8'),
 'tk-ex-latia-9':('Ricerca di Energia','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Energy-Search-TK1Latias-9'),
 'tk-ex-latia-10':('Energia Fuoco','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Fire-Energy-TK1Latias-10'),
 'tk-ex-latio-8':('Pozione','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Potion-TK1Latios-8'),
 'tk-ex-latio-9':('Ricerca di Energia','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Energy-Search-TK1Latios-9'),
 'tk-ex-latio-10':('Energia Lampo','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit/Lightning-Energy-TK1Latios-10'),
 # EX Trainer Kit 2 (Plusle/Minun)
 'tk-ex-p-8':('Ricerca di Energia','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Energy-Search-TK2red-8'),
 'tk-ex-p-9':('Pozione','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Potion-TK2red-9'),
 'tk-ex-p-10':('Scoperta del Professor Cosmi','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Professor-Cozmos-Discovery-TK2red-10'),
 'tk-ex-p-11':('Energia Lampo','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Lightning-Energy-TK2red-11'),
 'tk-ex-p-12':('Energia Psiche','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Psychic-Energy-TK2red-12'),
 'tk-ex-m-8':('Rete di Celio','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Celios-Network-TK2blue-8'),
 'tk-ex-m-9':('Ricerca di Energia','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Energy-Search-TK2blue-9'),
 'tk-ex-m-10':('Pozione','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Potion-TK2blue-10'),
 'tk-ex-m-11':('Energia Fuoco','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Fire-Energy-TK2blue-11'),
 'tk-ex-m-12':('Energia Lampo','https://www.cardmarket.com/it/Pokemon/Products/Singles/EX-Trainer-Kit-2/Lightning-Energy-TK2blue-12'),
 # XY alternate/promos
 'xya-24a':('M Manectric-EX','https://www.pokemon.com/it/gcc/archivio-carte/series/xya/24a/'),
 'xya-28a':('Jolteon-EX','https://www.pokemon.com/it/gcc/archivio-carte/series/xya/28a/'),
 'xya-54a':('Zygarde-EX','https://www.pokemon.com/it/gcc/archivio-carte/series/xya/54a/'),
 'xya-55a':('M Lucario-EX','https://www.pokemon.com/it/gcc/archivio-carte/series/xya/55a/'),
 'xya-92a':('Posta Allenatori','https://limitlesstcg.com/cards/it/ROS/92a'),
 'xya-107a':('Professor Platan','https://oakly-tcg.app/italian-cards/xy9/professor-platan-107a'),
 'xyp-XY150a':('Yveltal-EX','https://pokemonplug.com/it/products/yveltal-ex-xya-xy150a-alternate-art-promo'),
 'xyp-XY177a':('Karen','https://bulbapedia.bulbagarden.net/wiki/Karen_(XY_Promo_177)'),
 'xyp-XY198a':('M Camerupt-EX','https://pokemonplug.com/products/m-camerupt-ex-xy198a-alternate-art-promo'),
 'xyp-XY200a':('M Sharpedo-EX','https://pokemonplug.com/products/m-sharpedo-ex-xya-xy200a-alternate-art-promo'),
}
def main():
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 updated=[]; missing=[]
 for cid,(name,url) in MAP.items():
  row=conn.execute("""select p.set_id,c.name from card_source_provenance p join cards c on c.language_code=p.language_code and c.card_id=p.card_id where p.language_code='it' and p.card_id=? and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""",(cid,)).fetchone()
  if not row:
   missing.append(cid); continue
  method='italian_cardmarket_product_page' if 'cardmarket.com' in url else ('official_pokemon_it_card_archive' if 'pokemon.com' in url else 'italian_reference_card_page')
  conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'it',cid))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('it',row['set_id'],cid,url,method,f'Italian localized name sourced from card-specific Italian reference page; old fallback={row["name"]!r}.',FETCHED_AT))
  updated.append({'card_id':cid,'old':row['name'],'new':name,'url':url})
 # Delete DP Trainer Kits in Italian: Bulbapedia states released in English/German/French only.
 deleted=[]
 for setid in ['tk-dp-l','tk-dp-m']:
  rows=[dict(r) for r in conn.execute('select card_id,local_id,name from cards where language_code=? and set_id=? order by local_id_sort',('it',setid))]
  if rows:
   conn.execute('delete from card_details where language_code=? and set_id=?',('it',setid))
   conn.execute('delete from card_source_provenance where language_code=? and set_id=?',('it',setid))
   conn.execute('delete from cards where language_code=? and set_id=?',('it',setid))
   conn.execute('delete from sets where language_code=? and set_id=?',('it',setid))
   deleted.append({'set_id':setid,'deleted_rows':len(rows),'source':DP_SOURCE,'rows':rows})
 conn.commit()
 remaining=conn.execute("""select count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
 by_set=list(conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc"""))
 report={'fetched_at':FETCHED_AT,'updated':updated,'missing_mapping_targets':missing,'deleted_unreleased_sets':deleted,'remaining_it':remaining,'remaining_by_set':[list(x) for x in by_set]}
 out=REPORT_DIR/'italian_final_fixed_sources_and_unreleased_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:16000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
