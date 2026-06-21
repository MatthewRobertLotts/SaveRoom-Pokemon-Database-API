#!/usr/bin/env python3
from __future__ import annotations
import html,json,re,sqlite3,time,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'es,en;q=0.8'}
UNRELEASED_SOURCES={
 'tk-ex-latia':'https://bulbapedia.bulbagarden.net/wiki/EX_Trainer_Kit_(TCG)',
 'tk-ex-latio':'https://bulbapedia.bulbagarden.net/wiki/EX_Trainer_Kit_(TCG)',
 'tk-ex-p':'https://bulbapedia.bulbagarden.net/wiki/EX_Trainer_Kit_2_(TCG)',
 'tk-ex-m':'https://bulbapedia.bulbagarden.net/wiki/EX_Trainer_Kit_2_(TCG)',
 'tk-dp-l':'https://bulbapedia.bulbagarden.net/wiki/Diamond_%26_Pearl_Trainer_Kit_(TCG)',
 'tk-dp-m':'https://bulbapedia.bulbagarden.net/wiki/Diamond_%26_Pearl_Trainer_Kit_(TCG)',
}
FIXED={
 # correct CardsRealm noisy parses with official Pokémon Spanish archive
 'sma-SV82':('Cintia','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/sma/SV82/','official_pokemon_es_card_archive'),
 'sma-SV88':('Colina Saltagua','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/sma/SV88/','official_pokemon_es_card_archive'),
 'sma-SV90':('Santuario del Castigo','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/sma/SV90/','official_pokemon_es_card_archive'),
 # XY alternate cards
 'xya-24a':('M Manectric-EX','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/xya/24a/','official_pokemon_es_card_archive'),
 'xya-28a':('Jolteon-EX','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/xya/28a/','official_pokemon_es_card_archive'),
 'xya-54a':('Zygarde-EX','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/xya/54a/','official_pokemon_es_card_archive'),
 'xya-55a':('M Lucario-EX','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/xya/55a/','official_pokemon_es_card_archive'),
 'xya-92a':('Correo de Entrenadores','https://pokemon.cardsrealm.com/es-hn/card/trainers-mail-ros-92a','spanish_reference_card_page'),
 'xya-107a':('Profesor Ciprés','https://www.pokemon.com/es/jcc-pokemon/cartas-pokemon/series/xya/107a/','official_pokemon_es_card_archive'),
 # XY alternate promo rows
 'xyp-XY150a':('Yveltal-EX','https://www.pricecharting.com/es/game/pokemon-promo/yveltal-ex-xy150a','spanish_reference_card_page'),
 'xyp-XY177a':('Karen','https://bulbapedia.bulbagarden.net/wiki/Karen_(XY_Promo_177)','bulbapedia_card_language_table'),
 'xyp-XY198a':('M Camerupt-EX','https://pokemonplug.com/products/m-camerupt-ex-xy198a-alternate-art-promo','spanish_reference_card_page'),
 'xyp-XY200a':('M Sharpedo-EX','https://pokemonplug.com/products/m-sharpedo-ex-xya-xy200a-alternate-art-promo','spanish_reference_card_page'),
 # Pocket rows that timed out in the bulk pass / title-case normalization from the same Spanish pages
 'B1a-086':('Mega Steelix ex','https://pokemontcgpocket.app/es/card/B1a-086','pokemontcgpocket_app_es_card_page'),
 'B1a-103':('Extracto de crecimiento rápido','https://pokemontcgpocket.app/es/card/B1a-103','pokemontcgpocket_app_es_card_page'),
 'B1a-069':('Serena','https://pokemontcgpocket.app/es/card/B1a-069','pokemontcgpocket_app_es_card_page'),
 'B1a-082':('Serena','https://pokemontcgpocket.app/es/card/B1a-082','pokemontcgpocket_app_es_card_page'),
}
def main():
 REPORT_DIR.mkdir(parents=True,exist_ok=True)
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 fixed=[]
 for cid,(name,url,method) in FIXED.items():
  row=conn.execute('select set_id,name from cards where language_code=? and card_id=?',('es',cid)).fetchone()
  if not row: continue
  old=row['name']
  conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'es',cid))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('es',row['set_id'],cid,url,method,f'Spanish localized name sourced from card-specific Spanish reference/archive page; old value={old!r}.',FETCHED_AT))
  fixed.append({'card_id':cid,'old':old,'new':name,'url':url,'method':method})
 deleted=[]
 for setid,src in UNRELEASED_SOURCES.items():
  rows=[dict(r) for r in conn.execute('select card_id,local_id,name from cards where language_code=? and set_id=? order by local_id_sort',('es',setid))]
  if not rows: continue
  conn.execute('delete from card_details where language_code=? and set_id=?',('es',setid))
  conn.execute('delete from card_source_provenance where language_code=? and set_id=?',('es',setid))
  conn.execute('delete from cards where language_code=? and set_id=?',('es',setid))
  conn.execute('delete from sets where language_code=? and set_id=?',('es',setid))
  deleted.append({'set_id':setid,'deleted_rows':len(rows),'source':src,'rows':rows})
 conn.commit()
 by_set=[list(r) for r in conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='es' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc""")]
 remaining=sum(x[1] for x in by_set)
 suspicious=[list(r) for r in conn.execute("""select c.card_id,c.name,p.method,p.source_url from cards c join card_source_provenance p on p.language_code=c.language_code and p.card_id=c.card_id where c.language_code='es' and p.method like '%es%' and (c.name like '%.%' or c.name like '% sma %' or c.name like '% SM %' or c.name like '% -%' or length(c.name)>45) order by c.card_id limit 50""")]
 report={'fetched_at':FETCHED_AT,'fixed_count':len(fixed),'fixed':fixed,'deleted_unreleased_sets':deleted,'remaining_es':remaining,'remaining_by_set':by_set,'suspicious_after_cleanup':suspicious}
 out=REPORT_DIR/'spanish_final_fixed_sources_and_unreleased_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
