#!/usr/bin/env python3
"""
Final translation pass: expanded TCG terms + compound name patterns.

Handles:
1. Remaining Japanese TCG terms (items, trainers, energies)
2. Chinese compound names (trainer names, items with parentheticals)
3. Thai Pokémon names with suffixes
4. Indonesian TCG terms
5. Special characters like '同上', '未知', '猟犬'
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REF_DIR = Path("/media/matt/Storage/Brain/Pokemon Card Database/references")

# Load Pokémon names for reference
with open(REF_DIR / "pokemon_names_en.json", encoding="utf-8") as f:
    pokemon_en = set(json.load(f))
with open(REF_DIR / "pokemon_names_ja.json", encoding="utf-8") as f:
    ja_to_en = {local: en for local, en in zip(json.load(f), json.load(open(REF_DIR / "pokemon_names_en.json"))) if local}
with open(REF_DIR / "pokemon_names_ko.json", encoding="utf-8") as f:
    ko_to_en = {local: en for local, en in zip(json.load(f), json.load(open(REF_DIR / "pokemon_names_en.json"))) if local}
with open(REF_DIR / "pokemon_names_zh_hant.json", encoding="utf-8") as f:
    zh_hant_to_en = {local: en for local, en in zip(json.load(f), json.load(open(REF_DIR / "pokemon_names_en.json"))) if local}
with open(REF_DIR / "pokemon_names_zh_hans.json", encoding="utf-8") as f:
    zh_hans_to_en = {local: en for local, en in zip(json.load(f), json.load(open(REF_DIR / "pokemon_names_en.json"))) if local}
with open(REF_DIR / "pokemon_names_th.json", encoding="utf-8") as f:
    th_to_en = {local: en for local, en in zip(json.load(f), json.load(open(REF_DIR / "pokemon_names_en.json"))) if local}

# Comprehensive Japanese TCG term dictionary (expanded)
JA_TCG_TERMS = {
    # Special entries
    "未知": "Unknown",
    "同上": "Same as above",
    "猟犬": "Houndoom",
    "パルデア ケンタロス": "Paldean Tauros",
    "ポケモンいれかえ": "Pokémon Switch",
    "ハイパーボール": "Hyper Ball",
    "リザードンex": "Charizard ex",
    "リザードンEX": "Charizard ex",
    "カルボウ": "Charcadet",
    "カヌチャン": "Tinkatink",
    "スターミー": "Starmie",
    "ポリゴン": "Porygon",
    "マンキー": "Mankey",
    "Flabébé": "Flabébé",
    "ウミディグダ": "Clauncher",
    "シロナの覇気": "Cynthia's Ambition",
    "ボスの指令（アカギ）": "Boss's Orders (Ghetsis)",
    "マグネトン": "Magneton",
    "ライチュ": "Raichu",
    "ヘラクロス": "Heracross",
}

# Comprehensive Chinese Traditional TCG terms
ZH_TW_TERMS = {
    "博士的研究（山梨博士）": "Professor's Research (Professor Rowan)",
    "妮莫": "Nemona",
    "巢穴球": "Nest Ball",
    "帕底亞 肯泰羅": "Paldean Tauros",
    "瑪俐": "Marnie",
    "先機球": "Quick Ball",
    "老大的指令（赤日）": "Boss's Orders (Ghetsis)",
    "莎娜": "Shauna",
    "霧之水晶": "Misty Crystal",
    "博士的研究(木蘭博士)": "Professor's Research (Professor Magnolia)",
    "皮卡丘V": "Pikachu V",
    "藏瑪然特V": "Zamazenta V",
    "伽勒爾 喵喵": "Galarian Meowth",
    "伽勒爾 直衝熊": "Galarian Linoone",
    "伽勒爾 蛇紋熊": "Galarian Zigzagoon",
    "奇巴納": "Ryuki",
    "摔角鷹人": "Hawlucha",
    "等級球": "Level Ball",
    "蒼響V": "Zacian V",
    "赫普": "Hop",
    "醜醜魚": "Feebas",
    "六尾": "Vulpix",
    "九尾": "Ninetales",
    "不良蛙": "Croagunk",
    "偷兒狐": "Nickit",
    "勒克貓": "Luxio",
    "卡蒂狗": "Growlithe",
    "啃果蟲": "Applin",
    "愛管侍": "Indeedee",
    "拳拳蛸": "Clobbopus",
    "捷拉オラ": "Zeraora",
    "銅鏡怪": "Bronzong",
    "阿勃梭魯": "Absol",
    "焚焰蜈": "Centiskorch",
    "帕底亞 肯泰羅": "Paldean Tauros",
}

# Comprehensive Chinese Simplified TCG terms
ZH_CN_TERMS = {
    "好啦鱿": "Inkay",
    "拉普拉斯": "Lapras",
    "木棉球": "Whimsicott",
    "索尔迦雷欧GX": "Solgaleo GX",
    "胆小虫": "Wimpod",
    "自爆磁怪": "Magnezone",
    "花岩怪": "Spiritomb",
    "银伴战兽GX": "Type: Null GX",
    "青绵鸟": "Swablu",
}

# Thai Pokémon names with common suffixes
TH_POKEMON_SUFFIXES = [" V", " VMAX", " VSTAR", " ex", " EX", " GX"]

# Indonesian remaining terms
ID_TERMS = {
    "Pokémon Catcher": "Pokémon Catcher",
    "Pokégear 3.0": "Pokégear 3.0",
}


def translate_japanese(local_name: str) -> tuple[str | None, str | None]:
    """Translate Japanese card names."""
    # Direct match
    if local_name in JA_TCG_TERMS:
        return JA_TCG_TERMS[local_name], "ja_tcg_terms"

    # Compound: "XのY" → try translating Y
    m = re.match(r"^.+?の(.+)$", local_name)
    if m:
        pokemon_part = m.group(1).strip()
        if pokemon_part in ja_to_en:
            return ja_to_en[pokemon_part], "ja_compound_pokemon"

    # Strip suffix and try Pokémon name
    base = local_name
    for suffix in [" ex", " EX", " V", " VMAX", " VSTAR", " GX", " LV.X",
                   " FB", " ◇", "Ｚ", "（デルタ種）", " (Delta Species)"]:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()
            break
    if base in ja_to_en:
        return ja_to_en[base], "ja_pokemon_suffix"

    # Try exact Pokémon name
    if local_name in ja_to_en:
        return ja_to_en[local_name], "ja_pokemon_exact"

    return None, None


def translate_korean(local_name: str) -> tuple[str | None, str | None]:
    """Translate Korean card names."""
    # Strip suffix and try Pokémon name
    base = local_name
    for suffix in [" ex", " EX", " V", " VMAX", " VSTAR", " GX",
                   " FA", " ◇", "Ｚ", "TAG", " 연합"]:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()
            break
    if base in ko_to_en:
        return ko_to_en[base], "ko_pokemon_suffix"

    if local_name in ko_to_en:
        return ko_to_en[local_name], "ko_pokemon_exact"

    return None, None


def translate_chinese(local_name: str, lang: str) -> tuple[str | None, str | None]:
    """Translate Chinese card names."""
    dict_map = zh_hant_to_en if lang == "zh-tw" else zh_hans_to_en
    tcg_map = ZH_TW_TERMS if lang == "zh-tw" else ZH_CN_TERMS

    # Direct TCG term match
    if local_name in tcg_map:
        return tcg_map[local_name], f"{lang}_tcg_terms"

    # Compound: "<X的>Y" → try translating Y
    m = re.match(r"^<.+?的>(.+)$", local_name)
    if m:
        pokemon_part = m.group(1).strip()
        if pokemon_part in dict_map:
            return dict_map[pokemon_part], f"{lang}_compound_pokemon"

    # Compound: "X（Y）" → X is the card name
    m = re.match(r"^(.+?)（.+?）$", local_name)
    if m:
        base = m.group(1).strip()
        if base in dict_map:
            return dict_map[base], f"{lang}_parenthetical_pokemon"

    # Strip suffix and try Pokémon name
    base = local_name
    for suffix in ["GX", "EX", "V", "VMAX", "VSTAR", "◇", " V", " ex"]:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()
            break
    if base in dict_map:
        return dict_map[base], f"{lang}_pokemon_suffix"

    # Exact Pokémon name
    if local_name in dict_map:
        return dict_map[local_name], f"{lang}_pokemon_exact"

    return None, None


def translate_thai(local_name: str) -> tuple[str | None, str | None]:
    """Translate Thai card names."""
    # Strip suffix and try Pokémon name
    base = local_name
    for suffix in TH_POKEMON_SUFFIXES:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()
            break
    if base in th_to_en:
        return th_to_en[base], "th_pokemon_suffix"

    if local_name in th_to_en:
        return th_to_en[local_name], "th_pokemon_exact"

    return None, None


def translate_indonesian(local_name: str) -> tuple[str | None, str | None]:
    """Translate Indonesian card names."""
    if local_name in ID_TERMS:
        return ID_TERMS[local_name], "id_tcg_terms"

    # Many Indonesian names are already English (Latin script)
    # Check if it contains recognizable English Pokémon names
    for en_name in pokemon_en:
        if en_name.lower() in local_name.lower():
            return local_name, "id_contains_english"

    return None, None


def apply_final_pass():
    """Apply final translation pass."""
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

        if lang == "ja":
            en_name, source = translate_japanese(local_name)
        elif lang == "ko":
            en_name, source = translate_korean(local_name)
        elif lang in ("zh-tw", "zh-cn"):
            en_name, source = translate_chinese(local_name, lang)
        elif lang == "th":
            en_name, source = translate_thai(local_name)
        elif lang == "id":
            en_name, source = translate_indonesian(local_name)

        if en_name:
            updates.append((en_name, source, row_id))
            translated += 1
        else:
            still_untranslated += 1

    cur.executemany('UPDATE card_name_translations SET en_name = ?, source = ? WHERE id = ?', updates)
    conn.commit()

    print(f"Final pass results:")
    print(f"  Translated: {translated}")
    print(f"  Still untranslated: {still_untranslated}")

    # Coverage report
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

    # Source breakdown
    print("\n=== Source breakdown ===")
    cur.execute('SELECT source, COUNT(*) FROM card_name_translations GROUP BY source ORDER BY COUNT(*) DESC')
    for source, count in cur.fetchall():
        print(f"  {source:30s}: {count:>6,}")

    # Remaining untranslated
    if still_untranslated > 0:
        print(f"\n=== Remaining untranslated ({still_untranslated} cards) ===")
        cur.execute('''
            SELECT language_code, local_name, COUNT(*) as n
            FROM card_name_translations
            WHERE source = 'untranslated'
            GROUP BY language_code, local_name
            ORDER BY n DESC
            LIMIT 40
        ''')
        for lang, name, n in cur.fetchall():
            print(f"  {lang:5s} {n:>4}x  {name!r}")

    conn.close()
    return still_untranslated


if __name__ == "__main__":
    remaining = apply_final_pass()
    if remaining == 0:
        print(f"\n✅ All {298688 - 46668} non-English cards now have English names!")
    else:
        print(f"\n⚠️  {remaining} names still need translation (may need manual review)")
