#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
FIXED={
 'xya-24a':('M-Voltenso-EX','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/24a/','official_pokemon_de_card_archive'),
 'xya-28a':('Blitza-EX','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/28a/','official_pokemon_de_card_archive'),
 'xya-54a':('Zygarde-EX','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/54a/','official_pokemon_de_card_archive'),
 'xya-55a':('M-Lucario-EX','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/55a/','official_pokemon_de_card_archive'),
 'xya-92a':('Trainerpost','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/92a/','official_pokemon_de_card_archive'),
 'xya-107a':('Prof. Platan','https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/xya/107a/','official_pokemon_de_card_archive'),
 'xyp-XY150a':('Yveltal-EX','https://pokemonplug.com/de/products/yveltal-ex-xya-xy150a-alternate-art-promo','german_reference_card_page'),
 'xyp-XY177a':('Melanie','https://www.pokewiki.de/Melanie_(TCG)','pokewiki_de_card_page'),
 'xyp-XY198a':('M-Camerupt-EX','https://www.pokewiki.de/M-Camerupt-EX_(XY_Black_Star_Promos_XY198)','pokewiki_de_card_page'),
 'xyp-XY200a':('M-Tohaido-EX','https://www.pokewiki.de/M-Tohaido-EX_(XY_Black_Star_Promos_XY200)','pokewiki_de_card_page'),
}
# remove bad official archive provenance from bot-blocked bulk pass for rows restored by PokeAPI
POKEAPI_RESTORED=[f'sma-SV{i}' for i in [6,7,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45]]
def main():
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 fixed=[]
 for cid in POKEAPI_RESTORED:
  conn.execute("delete from card_source_provenance where language_code='de' and card_id=? and method='official_pokemon_de_card_archive'",(cid,))
 for cid,(name,url,method) in FIXED.items():
  row=conn.execute('select set_id,name from cards where language_code=? and card_id=?',('de',cid)).fetchone()
  if not row: continue
  old=row['name']
  conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'de',cid))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('de',row['set_id'],cid,url,method,f'German localized name sourced from card-specific German reference/archive page; old value={old!r}.',FETCHED_AT))
  fixed.append({'card_id':cid,'old':old,'new':name,'url':url,'method':method})
 conn.commit()
 by_set=[list(r) for r in conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='de' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc""")]
 suspicious=[list(r) for r in conn.execute("""select c.set_id,c.card_id,c.name,p.method,p.source_url from cards c left join card_source_provenance p on p.language_code=c.language_code and p.card_id=c.card_id where c.language_code='de' and (c.name='Pardon Our Interruption' or c.name like '{{%' or c.name like '[[%') order by c.set_id,c.card_id limit 200""")]
 report={'fetched_at':FETCHED_AT,'fixed_count':len(fixed),'fixed':fixed,'removed_bad_official_provenance_for':POKEAPI_RESTORED,'remaining_de':sum(x[1] for x in by_set),'remaining_by_set':by_set,'suspicious_bad_names':suspicious}
 out=REPORT_DIR/'german_final_fixed_sources_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
