#!/usr/bin/env python3
"""
Second-pass translation: handle remaining untranslated names.

Categories:
1. Latin-script names that ARE already English (Magikarp, Pikachu, etc.)
2. Local-script names needing translation (皮卡丘 → Pikachu)
3. TCG terms (高級球 → Hyper Ball, 寶可夢交替 → Pokémon Switch)
4. Indonesian TCG terms (Tukar Pokémon → Pokémon Switch)
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
DICT_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/references/pokemon_name_dictionary.json")

# Load existing dictionary
with open(DICT_PATH, encoding="utf-8") as f:
    dictionary = json.load(f)

# Comprehensive Pokémon name mappings for names that appear in the DB
# but weren't caught by the first pass (Latin-script names used in non-EN cards)
POKEMON_NAMES_LATIN = {
    # These are Pokémon names that appear as-is in non-English cards
    # Japanese cards often use English/Latin Pokémon names
    "Magikarp": "Magikarp",
    "Paldean Tauros": "Paldean Tauros",
    "Pyroar": "Pyroar",
    "Dendra": "Dendra",
    "Fuecoco": "Fuecoco",
    "Paldean Wooper": "Paldean Wooper",
    "Quaxly": "Quaxly",
    "Sprigatito": "Sprigatito",
    "Sableye": "Sableye",
    "Tropius": "Tropius",
    "Salandit": "Salandit",
    "Salazzle": "Salazzle",
    "Dugtrio": "Dugtrio",
    "Mismagius": "Mismagius",
    "Clavell": "Clavell",
    "Crocalor": "Crocalor",
    "Falkner": "Falkner",
    "Floragato": "Floragato",
    "Oricorio": "Oricorio",
    "Rockruff": "Rockruff",
    "Charmander": "Charmander",
    "Bronzor": "Bronzor",
    "Mawile": "Mawile",
    "Scyther": "Scyther",
    "Shaymin": "Shaymin",
    "Shinx": "Shinx",
    "Snorlax": "Snorlax",
    "Bronzong": "Bronzong",
    "Pikachu": "Pikachu",
    "Eevee": "Eevee",
    "Boss's Orders": "Boss's Orders",
    "Boss’s Orders": "Boss's Orders",
}

# Chinese (Traditional) TCG term translations
ZH_TW_TERMS = {
    "寶可夢交替": "Pokémon Switch",
    "高級球": "Hyper Ball",
    "皮卡丘": "Pikachu",
    "伊布": "Eevee",
    "寶可夢捕捉器": "Poké Ball",
    "卡比獸": "Snorlax",
    "超級球": "Super Ball",
    "大師球": "Master Ball",
    "精靈球": "Poké Ball",
    "神奇糖果": "Rare Candy",
    "博士的研究": "Professor's Research",
    "道館館主": "Gym Leader",
    "冠軍": "Champion",
    "四天王": "Elite Four",
    "裁判": "Judge",
    "大鉗蟹": "Kingler",
    "可達鴨": "Psyduck",
    "拉普拉斯": "Lapras",
    "暴鯉龍": "Gyarados",
    "海星星": "Staryu",
    "寶石海星": "Starmie",
    "小磁怪": "Magnemite",
    "三合一磁怪": "Magneton",
    "利歐路": "Riolu",
    "路卡利歐": "Lucario",
    "謎擬丘": "Mimikyu",
    "智揮猩": "Oranguru",
    "岩狗狗": "Rockruff",
    "洛托姆": "Rotom",
    "咚咚鼠": "Dedenne",
    "大嘴娃": "Mawile",
    "蛋蛋": "Exeggcute",
    "烏賊王": "Inkay",
    "青綿鸟": "Swablu",
    "銀伴戰獸": "Type: Null",
    "顫弦蠑螈": "Toxtricity",
    "燒火蚣": "Sizzlipede",
    "咩利羊": "Mareep",
    "茸茸羊": "Flaaffy",
    "電龍": "Ampharos",
    "莫魯貝可": "Morpeko",
    "毒電嬰": "Toxel",
    "小霞的": "Misty's",
    "小剛的": "Brock's",
    "小智的": "Ash's",
}

# Chinese (Simplified) TCG term translations
ZH_CN_TERMS = {
    "伊布": "Eevee",
    "岩狗狗": "Rockruff",
    "洛托姆": "Rotom",
    "谜拟丘": "Mimikyu",
    "智挥猩": "Oranguru",
    "皮卡丘": "Pikachu",
    "小磁怪": "Magnemite",
    "利欧路": "Riolu",
    "路卡利欧": "Lucario",
    "乌贼王": "Inkay",
    "咚咚鼠": "Dedenne",
    "大嘴娃": "Mawile",
    "蛋蛋": "Exeggcute",
    "三合一磁怪": "Magneton",
    "四颚针龙GX": "Naganadel GX",
    "宝可梦交替": "Pokémon Switch",
    "高级球": "Hyper Ball",
    "超级球": "Super Ball",
    "大师球": "Master Ball",
    "精灵球": "Poké Ball",
    "神奇糖果": "Rare Candy",
    "博士的研究": "Professor's Research",
    "道馆馆主": "Gym Leader",
    "冠军": "Champion",
    "四天王": "Elite Four",
    "裁判": "Judge",
}

# Korean TCG term translations
KO_TERMS = {
    "팔데아 켄타로스": "Paldean Tauros",
    "보스 오더": "Boss's Orders",
    "덴드라": "Dendra",
    "뜨아거": "Fuecoco",
    "팔데아 우파": "Paldean Wooper",
    "꾸왁스": "Quaxly",
    "나오하": "Sprigatito",
    "깜까미": "Sableye",
    "트로피우스": "Tropius",
    "야도뇽": "Psyduck",
    "야도란": "Golduck",
    "마자용": "Munchlax",
    "잠만보": "Snorlax",
    "이브이": "Eevee",
    "피카츄": "Pikachu",
    "리오르": "Riolu",
    "루카리오": "Lucario",
    "파이리": "Charmander",
    "리자드": "Charmeleon",
    "리자몽": "Charizard",
    "꼬부기": "Squirtle",
    "어니부기": "Wartortle",
    "거북왕": "Blastoise",
    "캐터피": "Caterpie",
    "단데기": "Metapod",
    "버터플": "Butterfree",
    "뿔충이": "Weedle",
    "딱충이": "Kakuna",
    "독침붕": "Beedrill",
    "구구": "Pidgey",
    "피죤": "Pidgeotto",
    "피죤투": "Pidgeot",
    "꼬렛": "Rattata",
    "레트라": "Raticate",
    "깨비참": "Pikachu",
    "코일": "Magnemite",
    "레어코일": "Magneton",
    "찌리리공": "Voltorb",
    "붐볼": "Electrode",
    "아라리": "Exeggcute",
    "나시": "Exeggutor",
    "탕구리": "Cubone",
    "텅구리": "Marowak",
    "시라소몽": "Lickitung",
    "홍수몽": "Lickilicky",
    "내루미": "Weezing",
    "또가스": "Koffing",
    "또도가스": "Weezing",
    "고오스": "Gastly",
    "고우스트": "Haunter",
    "팬텀": "Gengar",
    "롱스톤": "Onix",
    "슬리프": "Drowzee",
    "슬리퍼": "Hypno",
    "크랩": "Krabby",
    "킹크랩": "Kingler",
    "리자몽 ex": "Charizard ex",
    "포켓몬 교체": "Pokémon Switch",
    "포켓몬 교환": "Pokémon Exchange",
    "포켓몬센터": "Pokémon Center",
    "이상한사탕": "Rare Candy",
    "하이퍼볼": "Hyper Ball",
    "슈퍼볼": "Super Ball",
    "마스터볼": "Master Ball",
    "몬스터볼": "Poké Ball",
    "상처약": "Potion",
    "해독제": "Antidote",
    "화상치료제": "Burn Heal",
    "동상치료제": "Ice Heal",
    "잠깨는약": "Awakening",
    "마비치료제": "Paralyze Heal",
    "회복약": "Full Heal",
    "풀회복약": "Full Restore",
    "기력의조각": "Revive",
    "기력의덩어리": "Max Revive",
    "좋은상처약": "Super Potion",
    "고급상처약": "Hyper Potion",
    "박사의 연구": "Professor's Research",
    "체육관 관장": "Gym Leader",
    "챔피언": "Champion",
    "사천왕": "Elite Four",
    "TV 리포터": "TV Reporter",
    "U턴 보드": "U-Turn Board",
    "V가드 에너지": "V Guard Energy",
    "가득찬 양동이": "Full Bucket",
    "N의 각오": "N's Resolve",
    "춤추새": "Oricorio",
    "화강돌": "Falinks",
}

# Thai TCG term translations
TH_TERMS = {
    "อีวุย": "Eevee",
    "พิคาชู": "Pikachu",
    "พัลเดีย เคนเทารอส": "Paldean Tauros",
    "คาร์โบ": "Charbo",
    "โบรรอน": "Bronzor",
    "กูร์ตง": "Greedent",
    "ไคเด็น": "Kaiden",
    "โมรุเปโกะ": "Morpeko",
    "อุมิดิกดา": "Umidigda",
    "ลิซาร์ดอนex": "Lizardon ex",
    "คานุจัง": "Kanuchan",
    "ไฮเปอร์บอล": "Hyper Ball",
    "ซูเปอร์บอล": "Super Ball",
    "มาสเตอร์บอล": "Master Ball",
    "โปเกมอนบอล": "Poké Ball",
    "ยารักษา": "Potion",
    "ยาแก้พิษ": "Antidote",
    "ยาแก้ไฟไหม้": "Burn Heal",
    "ยาแก้ตัวเย็น": "Ice Heal",
    "ยาปลุก": "Awakening",
    "ยาแก้อัมพาต": "Paralyze Heal",
    "ยารักษาทั้งหมด": "Full Heal",
    "ยาฟื้นฟูทั้งหมด": "Full Restore",
    "ส่วนฟื้นฟู": "Revive",
    "ส่วนฟื้นฟูสูงสุด": "Max Revive",
    "ยารักษาดี": "Super Potion",
    "ยารักษาเยอะ": "Hyper Potion",
    "ลูกอมประหลาด": "Rare Candy",
    "โปเกมอนสมุด": "Pokédex",
    "การ์ดโปเกมอน": "Pokémon Card",
    "ท่าต่อสู้": "Attack",
    "ความสามารถ": "Ability",
    "วิวัฒนาการ": "Evolution",
    "พื้นฐาน": "Basic",
    "กระดิ่งช่วยเหลือ": "Help Bell",
    "กระเป๋าของฮ็อป": "Hop's Bag",
    "กราดอน": "Groudon",
    "กราวิตีเมาน์เทน์": "Gravitite Mountain",
    "กราเซีย": "Glacia",
    "โนโนะคุราเกะ": "Nonokurage",
    "เดเด็นเนะ": "Dedenne",
    "ฮิราฮินะ": "Hirahina",
    "บอสคำสั่ง": "Boss's Orders",
}

# Indonesian TCG term translations
ID_TERMS = {
    "Tukar Pokémon": "Pokémon Switch",
    "Bola Ultra": "Ultra Ball",
    "Bola Master": "Master Ball",
    "Bola Super": "Super Ball",
    "Bola Pokémon": "Poké Ball",
    "Obat Luka": "Potion",
    "Obat Antiracun": "Antidote",
    "Obat Luka Bakar": "Burn Heal",
    "Obat Beku": "Ice Heal",
    "Obat Tidur": "Awakening",
    "Obat Kelumpuhan": "Paralyze Heal",
    "Obat Penyembuh": "Full Heal",
    "Obat Penyembuh Penuh": "Full Restore",
    "Sari Buah": "Berry",
    "Permen Langka": "Rare Candy",
    "Kamus Pokémon": "Pokédex",
    "Kartu Pokémon": "Pokémon Card",
    "Serangan": "Attack",
    "Kemampuan": "Ability",
    "Evolusi": "Evolution",
    "Dasar": "Basic",
    "Tahap 1": "Stage 1",
    "Tahap 2": "Stage 2",
    "Pelatih Pokémon": "Pokémon Trainer",
    "Pemimpin Gym": "Gym Leader",
    "Juara": "Champion",
    "Elit Empat": "Elite Four",
    "Wasit": "Judge",
}


def is_latin_only(name: str) -> bool:
    """Check if a name contains only Latin characters (ASCII + extended)."""
    return bool(re.match(r"^[A-Za-z0-9\s\-'.()]+$", name))


def apply_second_pass():
    """Apply second-pass translations to remaining untranslated names."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all untranslated entries
    cur.execute('''
        SELECT id, card_id, language_code, local_name
        FROM card_name_translations
        WHERE source = 'untranslated'
    ''')

    updates = []
    still_untranslated = 0
    translated_this_pass = 0

    for row_id, card_id, lang, local_name in cur.fetchall():
        en_name = None
        source = None

        # Category 1: Latin-only names that are already English
        if is_latin_only(local_name):
            # Check if it's in our Latin name mapping
            if local_name in POKEMON_NAMES_LATIN:
                en_name = POKEMON_NAMES_LATIN[local_name]
                source = "latin_recognized"
            else:
                # Assume it's already an English name (Indonesian cards use Latin script)
                en_name = local_name
                source = "latin_passthrough"

        # Category 2-4: Language-specific term dictionaries
        if not en_name:
            term_dict = None
            if lang == "zh-tw":
                term_dict = ZH_TW_TERMS
            elif lang == "zh-cn":
                term_dict = ZH_CN_TERMS
            elif lang == "ko":
                term_dict = KO_TERMS
            elif lang == "th":
                term_dict = TH_TERMS
            elif lang == "id":
                term_dict = ID_TERMS

            if term_dict and local_name in term_dict:
                en_name = term_dict[local_name]
                source = "tcg_terms"

        if en_name:
            updates.append((en_name, source, row_id))
            translated_this_pass += 1
        else:
            still_untranslated += 1

    # Apply updates
    cur.executemany('UPDATE card_name_translations SET en_name = ?, source = ? WHERE id = ?', updates)
    conn.commit()

    print(f"Second pass results:")
    print(f"  Translated: {translated_this_pass}")
    print(f"  Still untranslated: {still_untranslated}")

    # Report updated coverage
    print("\n=== Updated translation coverage by language ===")
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

    # Report by source
    print("\n=== Source breakdown ===")
    cur.execute('SELECT source, COUNT(*) FROM card_name_translations GROUP BY source ORDER BY COUNT(*) DESC')
    for source, count in cur.fetchall():
        print(f"  {source:25s}: {count:>6,}")

    # Remaining untranslated
    print("\n=== Remaining untranslated (sample) ===")
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


if __name__ == "__main__":
    apply_second_pass()
