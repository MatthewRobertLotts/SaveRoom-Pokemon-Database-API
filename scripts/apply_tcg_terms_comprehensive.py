#!/usr/bin/env python3
"""
Final translation pass using multiple strategies:
1. Batch translate remaining names using the translators library
2. For names that can't be translated, use best-effort matching
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REF_DIR = Path("/media/matt/Storage/Brain/Pokemon Card Database/references")

# Load Pokémon name mappings
with open(REF_DIR / "pokemon_names_en.json", encoding="utf-8") as f:
    en_names = json.load(f)

POKEAPI_MAPS = {}
for lang_file, lang_code in [
    ("pokemon_names_ja.json", "ja"),
    ("pokemon_names_ko.json", "ko"),
    ("pokemon_names_zh_hant.json", "zh-tw"),
    ("pokemon_names_zh_hans.json", "zh-cn"),
    ("pokemon_names_th.json", "th"),
]:
    with open(REF_DIR / lang_file, encoding="utf-8") as f:
        local_names = json.load(f)
    POKEAPI_MAPS[lang_code] = {local: en_names[i] for i, local in enumerate(local_names) if i < len(en_names)}

# Comprehensive TCG term dictionary for remaining items/trainers/energies
TCG_TERMS_COMPREHENSIVE = {
    "zh-tw": {
        # Items
        "傷藥": "Potion",
        "普通釣竿": "Old Rod",
        "能量輸送": "Energy Transfer",
        "能量轉移": "Energy Switch",
        "極光能量": "Aurora Energy",
        "高溫火能量": "Fire Energy",
        "先機球": "Quick Ball",
        "巢穴球": "Nest Ball",
        "寶可裝置3.0": "Pokégear 3.0",
        "寶可齒輪3.0": "Pokégear 3.0",
        "回收網": "Net Ball",
        "厲害釣竿": "Good Rod",
        "超級釣竿": "Super Rod",
        "建築": "Construction",
        # Trainers
        "竹蘭的霸氣": "Cynthia's Ambition",
        "老大的指令（坂木）": "Boss's Orders (Giovanni)",
        "奇樹": "Iono",
        "阿馴": "Alain",
        "老大的指令": "Boss's Orders",
        "博士的研究": "Professor's Research",
        # Locations
        "草路競技場": "Grass Court",
        "通頂雪道": "Snowpoint Temple",
        "隨風球": "Drifloon",
        "離洞繩": "Escape Rope",
        "進化薰香": "Evolution Incense",
        "足量"bytes": "Full Bucket",
        # Energy
        "強力無エネルギー": "Strong Energy",
        "基本【火】能量": "Basic Fire Energy",
        "基本【水】能量": "Basic Water Energy",
        "基本【草】能量": "Basic Grass Energy",
        "基本【雷】能量": "Basic Lightning Energy",
        "基本【超】能量": "Basic Psychic Energy",
        "基本【鬥】能量": "Basic Fighting Energy",
        "基本【惡】能量": "Basic Darkness Energy",
        "基本【鋼】能量": "Basic Metal Energy",
        "岩石鬥能量": "Fighting Energy",
        "清洗水エネルギー": "Water Energy",
        "芳香草エネルギー": "Grass Energy",
        # Pokemon names (Taiwan-specific translations)
        "光電傘蜥": "Wattrel",
        "圓絲蛛": "Spinarak",
        "熔蟻獸": "Centiskorch",
        "好啦魷": "Inkay",
        "赫拉克羅斯": "Heracross",
        "火神蛾": "Volcarona",
        "蜻蜻蜓": "Yanma",
        "遠古巨蜓": "Yanmega",
        "鴨嘴炎獸": "Magmortar",
        "爆炸頭水牛": "Bouffalant",
        "美蓉": "Eelektrik",
        "夜巡靈": "Duskull",
        "彷徨夜靈": "Dusclops",
        "幼基拉斯": "Larvitar",
        "沙基拉斯": "Pupitar",
        "泳圈鼬": "Buizel",
        "隨風球": "Drifloon",
        "離洞繩": "Escape Rope",
        "足量水桶": "Full Bucket",
        "進化薰香": "Evolution Incense",
        "強力無能量": "Strong Energy",
        "克拉拉": "Klara",
        "可爾妮の氣勢": "Korrina's Focus",
        "基本【超】能量": "Basic Psychic Energy",
        "帕底亞 烏波": "Paldean Wooper",
        "幼基拉斯": "Larvitar",
        "彷徨夜靈": "Dusclops",
        "恐怖超エネルギー": "Spooky Energy",
        "沙基拉斯": "Pupitar",
        "泳圈鼬": "Buizel",
        "潛行惡エネルギー": "Darkness Energy",
        "烈箭鷹": "Talonflame",
        "爆炸頭水牛": "Bouffalant",
        "美蓉": "Eelektrik",
        "能量回收": "Energy Retrieval",
        "能量回收器": "Energy Retrieval",
        "草路競技場": "Grass Court",
        "通頂雪道": "Snowpoint Temple",
        "雙重渦輪エネルギー": "Double Turbo Energy",
        "高速雷エネルギー": "Speed Lightning Energy",
        "鴨嘴炎獸": "Magmortar",
        "美納斯": "Milotic",
        "美蓉": "Eelektrik",
        "熔蟻獸": "Centiskorch",
        "阿馴": "Alain",
        "奇樹": "Iono",
        "好啦魷": "Inkay",
        "傷藥": "Potion",
        "普通釣竿": "Old Rod",
        "巢穴球": "Nest Ball",
        "帕底亞 肯泰羅": "Paldean Tauros",
        "能量輸送": "Energy Transfer",
        "能量轉移": "Energy Switch",
        "極光能量": "Aurora Energy",
        "高溫火能量": "Fire Energy",
        "先機球": "Quick Ball",
        "寶可裝置3.0": "Pokégear 3.0",
        "回收網": "Net Ball",
        "厲害釣竿": "Good Rod",
        "超級釣竿": "Super Rod",
        "竹蘭的霸氣": "Cynthia's Ambition",
        "老大的指令（坂木）": "Boss's Orders (Giovanni)",
        "老大的指令": "Boss's Orders",
        "博士的研究": "Professor's Research",
        "基本【火】能量": "Basic Fire Energy",
        "基本【水】能量": "Basic Water Energy",
        "基本【草】能量": "Basic Grass Energy",
        "基本【雷】能量": "Basic Lightning Energy",
        "基本【超】能量": "Basic Psychic Energy",
        "基本【鬥】能量": "Basic Fighting Energy",
        "基本【惡】能量": "Basic Darkness Energy",
        "基本【鋼】能量": "Basic Metal Energy",
        "岩石鬥能量": "Fighting Energy",
        "粉碎之錘": "Hammer",
        "火神蛾": "Volcarona",
        "蜻蜻蜓": "Yanma",
        "遠古巨蜓": "Yanmega",
        "鴨嘴炎獸": "Magmortar",
        "爆炸頭水牛": "Bouffalant",
        "美蓉": "Eelektrik",
        "夜巡靈": "Duskull",
        "彷徨夜靈": "Dusclops",
        "幼基拉斯": "Larvitar",
        "沙基拉斯": "Pupitar",
        "泳圈鼬": "Buizel",
        "潛行惡能量": "Darkness Energy",
        "烈箭鷹": "Talonflame",
        "能量回收": "Energy Retrieval",
        "草路競技場": "Grass Court",
        "通頂雪道": "Snowpoint Temple",
        "雙重渦輪能量": "Double Turbo Energy",
        "高速雷能量": "Speed Lightning Energy",
        "克拉拉": "Klara",
        "帕底亞 烏波": "Paldean Wooper",
        "恐怖超能量": "Spooky Energy",
        "隨風球": "Drifloon",
        "離洞繩": "Escape Rope",
        "足量水桶": "Full Bucket",
        "進化薰香": "Evolution Incense",
        "強力無能量": "Strong Energy",
        "基本惡能量": "Basic Darkness Energy",
        "基本雷能量": "Basic Lightning Energy",
        "基本鬥能量": "Basic Fighting Energy",
        "塗層鋼能量": "Coating Metal Energy",
        "雙子能量": "Twin Energy",
        "反擊能量": "Counter Energy",
        "反轉能量": "Reversal Energy",
        "幸運能量": "Lucky Energy",
        "懷舊能量": "Retro Energy",
        "戰吼能量": "Howl Energy",
        "捕獲能量": "Capture Energy",
        "反擊能量": "Counter Energy",
        "反擊增幅器": "Counter Catcher",
        "反擊捕捉器": "Counter Catcher",
    },
    "zh-cn": {
        "烈箭鹰": "Talonflame",
        "老大的指令": "Boss's Orders",
        "好啦鱿": "Inkay",
        "伤药": "Potion",
        "普通钓竿": "Old Rod",
        "能量输送": "Energy Transfer",
        "能量转移": "Energy Switch",
        "极光能量": "Aurora Energy",
        "高温火能量": "Fire Energy",
        "先机球": "Quick Ball",
        "巢穴球": "Nest Ball",
        "宝可梦装置3.0": "Pokégear 3.0",
        "回收网": "Net Ball",
        "厉害钓竿": "Good Rod",
        "超级钓竿": "Super Rod",
        "竹兰的霸气": "Cynthia's Ambition",
        "老大的指令（坂木）": "Boss's Orders (Giovanni)",
        "博士的研究": "Professor's Research",
        "基本【火】能量": "Basic Fire Energy",
        "基本【水】能量": "Basic Water Energy",
        "基本【草】能量": "Basic Grass Energy",
        "基本【雷】能量": "Basic Lightning Energy",
        "基本【超】能量": "Basic Psychic Energy",
        "基本【斗】能量": "Basic Fighting Energy",
        "基本【恶】能量": "Basic Darkness Energy",
        "基本【钢】能量": "Basic Metal Energy",
    },
    "ja": {
        "博士の研究（ナナカマド博士）": "Professor's Research (Professor Oak)",
        "博士の研究": "Professor's Research",
        "ナンジャモ": "Iono",
        "ネオラントV": "Neo Lantern V",
        "ミュウex": "Mew ex",
        "ポケモンキャッチャー": "Pokémon Catcher",
        "ボスの指令": "Boss's Orders",
        "ハイパーボール": "Hyper Ball",
        "ポケモンいれかえ": "Pokémon Switch",
    },
    "ko": {
        "포켓몬 캐처": "Pokémon Catcher",
        "보스의 지령": "Boss's Orders",
        "박사의 연구": "Professor's Research",
        "하이퍼볼": "Hyper Ball",
        "포켓몬 교체": "Pokémon Switch",
    },
    "th": {
        "Pokémon Catcher": "Pokémon Catcher",
        "สับเปลี่ยนโปเกมอน": "Pokémon Switch",
        "พัลเดีย อูปา": "Paldean Wooper",
        "เนสต์บอล": "Nest Ball",
        "โปเกเกีย 3.0": "Pokégear 3.0",
        "งานวิจัยของศาสตราจารย์": "Professor's Research",
        "แผนการของศาสตราจารย์ฟูทูร์": "Professor Futru's Plan",
        "จิตมุ่งมั่นของศาสตราจารย์โอลิม": "Professor Olim's Determination",
        "เนโม": "Nemona",
        "ผู้ตัดสิน": "Judge",
        "โบรโรโรมex": "Borororom ex",
    },
    "id": {
        "Kostum Pokémon": "Pokémon Costume",
        "Pokémon Catcher": "Pokémon Catcher",
        "Breeder Pokémon": "Pokémon Breeder",
        "Pengangkat Pokémon Super": "Super Pokémon Catcher",
        "Tukar Pokémon": "Pokémon Switch",
        "Bola Ultra": "Ultra Ball",
        "Bola Nest": "Nest Ball",
        "Pokégear 3.0": "Pokégear 3.0",
        "Tipe: Nol": "Type: Null",
        "Neutral Center": "Neutral Center",
        "Markas Utama Liga Pokémon": "Pokémon League Headquarters",
        "Moci Rantai": "Chain Mace",
        "Kristal Gemerlap": "Brilliant Crystal",
        "Obsesi Colress": "Colress's Obsession",
        "Pelatihan Breeder Pokémon": "Pokémon Breeder's Training",
        "Siklon Pengangkat Pokémon": "Pokémon Retrieval Cyclone",
        "Undangan Erika": "Erika's Invitation",
        "Karisma Giovanni": "Giovanni's Charisma",
        "Teknik Rahasia Janine": "Janine's Secret Technique",
    },
}


def apply_comprehensive_tcg_terms():
    """Apply comprehensive TCG term translations."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
        SELECT id, card_id, language_code, local_name
        FROM card_name_translations
        WHERE source = 'untranslated'
    ''')

    updates = []
    translated = 0
    still_untranslated = 0

    for row_id, card_id, lang, local_name in cur.fetchall():
        en_name = None
        source = None

        # Check comprehensive TCG terms
        if lang in TCG_TCG_TERMS_COMPREHENSIVE and local_name in TCG_TERMS_COMPREHENSIVE.get(lang, {}):
            en_name = TCG_TERMS_COMPREHENSIVE[lang][local_name]
            source = "tcg_comprehensive"

        if en_name:
            updates.append((en_name, source, row_id))
            translated += 1
        else:
            still_untranslated += 1

    cur.executemany('UPDATE card_name_translations SET en_name = ?, source = ? WHERE id = ?', updates)
    conn.commit()

    print(f"Comprehensive TCG terms pass:")
    print(f"  Translated: {translated}")
    print(f"  Still untranslated: {still_untranslated}")

    # Coverage
    print("\n=== Coverage by language ===")
    cur.execute('''
        SELECT language_code, 
               COUNT(*) as total,
               SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) as translated,
               ROUND(100.0 * SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM card_name_translations
        GROUP BY language_code
        ORDER BY COUNT(*) DESC
    ''')
    for lang, total, trans, pct in cur.fetchall():
        print(f"  {lang:10s}: {trans:>6,} / {total:>6,} ({pct}%)")

    # Remaining
    if still_untranslated > 0:
        print(f"\n=== Remaining untranslated ({still_untranslated}) ===")
        cur.execute('''
            SELECT language_code, local_name, COUNT(*) as n
            FROM card_name_translations
            WHERE source = 'untranslated'
            GROUP BY language_code, local_name
            ORDER BY n DESC
            LIMIT 30
        ''')
        for lang, name, n in cur.fetchall():
            print(f"  {lang:5s} {n:>4}x  {name!r}")

    conn.close()
    return still_untranslated


if __name__ == "__main__":
    remaining = apply_comprehensive_tcg_terms()
    if remaining == 0:
        print(f"\n✅ All non-English cards now have English names!")
    else:
        print(f"\n⚠️  {remaining} names still untranslated")
