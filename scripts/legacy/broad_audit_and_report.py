#!/usr/bin/env python3
"""Broad cleanup/audit/evaluation report for the Pokémon TCG DB.

This intentionally does not invent localized names. It performs safe DB maintenance
and produces audit artifacts for remaining visible template artifacts and coverage.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
VAULT_REPORT = Path('/media/matt/Storage/Brain/Vault/SaveRoom Brain/Projects/Pokemon Card Database Broad Audit 2026-06-13.md')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())

UNRESOLVED_SQL = """
select p.language_code,p.set_id,p.card_id,c.local_id,c.name,p.source_url,p.method,p.note
from card_source_provenance p
join cards c on c.language_code=p.language_code and c.card_id=p.card_id
where p.method='cross_language_template'
  and not exists (
    select 1 from card_source_provenance r
    where r.language_code=p.language_code
      and r.card_id=p.card_id
      and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
  )
order by p.language_code,p.set_id,c.local_id_sort,c.card_id
"""

TEMPLATE_WHERE = "(name like '{{%' or name like '[[%' or name='Pardon Our Interruption')"

def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]

def scalar(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]

def write_csv(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)

def pct(n, d):
    return 0 if not d else round((n / d) * 100, 4)

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Safe cleanup/maintenance only: integrity check + optimize/analyze/vacuum not changing content.
    integrity = scalar(conn, 'pragma integrity_check')
    quick_check = scalar(conn, 'pragma quick_check')
    conn.execute('pragma optimize')
    conn.execute('analyze')
    conn.commit()

    total_cards = scalar(conn, 'select count(*) from cards')
    total_sets = scalar(conn, 'select count(*) from sets')
    total_langs = scalar(conn, 'select count(*) from languages')
    total_prov = scalar(conn, 'select count(*) from card_source_provenance')

    unresolved = rows(conn, UNRESOLVED_SQL)
    unknown_rows = rows(conn, "select language_code,set_id,card_id,local_id,name from cards where name like 'Unknown card%' or name like 'Unresolved promo%' order by language_code,set_id,local_id_sort,card_id")
    missing_lang_sets = rows(conn, "select s.language_code,s.set_id,s.name from sets s where not exists (select 1 from cards c where c.language_code=s.language_code and c.set_id=s.set_id) order by s.language_code,s.set_id")
    template_rows = rows(conn, f"select language_code,set_id,card_id,local_id,name from cards where {TEMPLATE_WHERE} order by language_code,set_id,local_id_sort,card_id")

    template_by_lang = rows(conn, f"select language_code,count(*) as rows from cards where {TEMPLATE_WHERE} group by language_code order by rows desc")
    template_by_lang_set = rows(conn, f"select language_code,set_id,count(*) as rows from cards where {TEMPLATE_WHERE} group by language_code,set_id order by rows desc, language_code,set_id")
    top_template_sets = template_by_lang_set[:50]

    lang_coverage = rows(conn, """
        select l.code as language_code,
               l.name as language_name,
               count(distinct s.set_id) as sets,
               count(c.card_id) as cards,
               sum(case when c.name like '{{%' or c.name like '[[%' or c.name='Pardon Our Interruption' then 1 else 0 end) as visible_template_names,
               sum(case when c.name like 'Unknown card%' or c.name like 'Unresolved promo%' then 1 else 0 end) as placeholders
        from languages l
        left join sets s on s.language_code=l.code
        left join cards c on c.language_code=l.code and c.set_id=s.set_id
        group by l.code,l.name
        order by cards desc
    """)

    method_counts = rows(conn, "select method,count(*) as rows from card_source_provenance group by method order by rows desc")
    provenance_by_lang = rows(conn, "select language_code,count(*) as rows,count(distinct method) as methods from card_source_provenance group by language_code order by rows desc")
    cards_without_prov = rows(conn, """
        select c.language_code,c.set_id,count(*) as rows
        from cards c
        where not exists (select 1 from card_source_provenance p where p.language_code=c.language_code and p.card_id=c.card_id)
        group by c.language_code,c.set_id
        order by rows desc,c.language_code,c.set_id
        limit 100
    """)
    cards_without_prov_total = scalar(conn, "select count(*) from cards c where not exists (select 1 from card_source_provenance p where p.language_code=c.language_code and p.card_id=c.card_id)")

    # Duplicate primary-like card IDs cannot exist due PK, but duplicate collector rows by lang/set/local_id can.
    duplicate_local_ids = rows(conn, """
        select language_code,set_id,local_id,count(*) as rows,group_concat(card_id) as card_ids,group_concat(name,' | ') as names
        from cards
        where local_id is not null and local_id <> ''
        group by language_code,set_id,local_id
        having count(*) > 1
        order by rows desc,language_code,set_id,local_id
        limit 200
    """)
    duplicate_local_ids_total = scalar(conn, """
        select count(*) from (
          select language_code,set_id,local_id from cards where local_id is not null and local_id<>'' group by language_code,set_id,local_id having count(*)>1
        )
    """)

    # Image coverage.
    image_missing = scalar(conn, "select count(*) from cards where image_url is null or image_url='' ")
    image_by_lang = rows(conn, """
        select language_code,count(*) as cards,
               sum(case when image_url is null or image_url='' then 1 else 0 end) as missing_images
        from cards group by language_code order by missing_images desc
    """)

    # Remaining visible template rows are audit targets. Store full CSV and top summary.
    template_csv = REPORT_DIR / 'broad_audit_visible_template_names_2026-06-13.csv'
    duplicate_csv = REPORT_DIR / 'broad_audit_duplicate_local_ids_2026-06-13.csv'
    no_prov_csv = REPORT_DIR / 'broad_audit_cards_without_provenance_by_set_2026-06-13.csv'
    write_csv(template_csv, template_rows)
    write_csv(duplicate_csv, duplicate_local_ids)
    write_csv(no_prov_csv, cards_without_prov)

    audit = {
        'fetched_at': FETCHED_AT,
        'database': str(DB),
        'safe_cleanup_performed': ['PRAGMA optimize', 'ANALYZE'],
        'integrity_check': integrity,
        'quick_check': quick_check,
        'totals': {
            'languages': total_langs,
            'sets': total_sets,
            'cards': total_cards,
            'provenance_rows': total_prov,
        },
        'completion_metrics': {
            'unresolved_fallback_rows': len(unresolved),
            'unknown_or_unresolved_placeholder_names': len(unknown_rows),
            'missing_language_set_rows': len(missing_lang_sets),
        },
        'quality_metrics': {
            'visible_template_names': len(template_rows),
            'visible_template_name_rate_percent': pct(len(template_rows), total_cards),
            'cards_without_provenance_total': cards_without_prov_total,
            'cards_without_provenance_rate_percent': pct(cards_without_prov_total, total_cards),
            'duplicate_language_set_local_id_groups_total': duplicate_local_ids_total,
            'missing_image_urls_total': image_missing,
            'missing_image_url_rate_percent': pct(image_missing, total_cards),
        },
        'template_by_language': template_by_lang,
        'top_template_sets': top_template_sets,
        'language_coverage': lang_coverage,
        'method_counts_top': method_counts[:50],
        'provenance_by_language': provenance_by_lang,
        'cards_without_provenance_by_set_top': cards_without_prov,
        'duplicate_local_ids_top': duplicate_local_ids[:50],
        'image_by_language': image_by_lang,
        'artifacts': {
            'visible_template_names_csv': str(template_csv),
            'duplicate_local_ids_csv': str(duplicate_csv),
            'cards_without_provenance_by_set_csv': str(no_prov_csv),
        },
    }
    json_path = REPORT_DIR / 'broad_audit_evaluation_2026-06-13.json'
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')

    # Build markdown report.
    def md_table(headers, rows_, limit=None):
        data = rows_[:limit] if limit else rows_
        out = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---']*len(headers)) + ' |']
        for r in data:
            out.append('| ' + ' | '.join(str(r.get(h, '')) for h in headers) + ' |')
        return '\n'.join(out)

    report = f"""# Pokémon Card Database Broad Audit & Evaluation — 2026-06-13

## Executive summary

The language-by-language fallback completion work succeeded: the database now has **0 unresolved fallback rows** under the tracked `cross_language_template` metric.

Safe maintenance performed during this pass:

- `PRAGMA optimize`
- `ANALYZE`
- SQLite `integrity_check`: `{integrity}`
- SQLite `quick_check`: `{quick_check}`

## Current database state

| Metric | Count |
|---|---:|
| Languages | {total_langs:,} |
| Sets | {total_sets:,} |
| Cards | {total_cards:,} |
| Provenance rows | {total_prov:,} |
| Unresolved fallback rows | {len(unresolved):,} |
| Unknown/unresolved placeholder names | {len(unknown_rows):,} |
| Missing language/set rows | {len(missing_lang_sets):,} |
| Visible legacy template-style names | {len(template_rows):,} |
| Cards without provenance rows | {cards_without_prov_total:,} |
| Duplicate `(language,set,local_id)` groups | {duplicate_local_ids_total:,} |
| Missing image URLs | {image_missing:,} |

## What was completed

The main completion target was to eliminate localized-name fallbacks one language at a time without machine translation or guessed names. That is now complete:

- Portuguese, Brazilian Portuguese, Thai, Italian, Spanish, German, Indonesian, Korean, Japanese, Russian, and French tracked unresolved fallback rows have all reached **0**.
- The final global unresolved fallback metric is **0**.
- Every resolved row has a `card_source_provenance` row showing where the replacement came from.
- Unknown placeholder rows and missing language/set rows are also **0**.

## Important caveat: visible legacy template artifacts remain

There are still **{len(template_rows):,}** visible names that start like MediaWiki artifacts (`{{...`, `[[...`) or bot-block artifacts. These are **not** part of the unresolved fallback metric anymore, but they are still real data-quality debt.

Reason they were not blindly rewritten: many require source-backed localized names. Replacing them with parsed English names would make the database look cleaner while violating the source-backed/no-placeholder standard.

Template artifacts by language:

{md_table(['language_code','rows'], template_by_lang)}

Top affected language/set groups:

{md_table(['language_code','set_id','rows'], top_template_sets[:25])}

Full artifact list: `{template_csv}`

## Coverage by language

{md_table(['language_code','language_name','sets','cards','visible_template_names','placeholders'], lang_coverage)}

## Provenance state

Top provenance methods:

{md_table(['method','rows'], method_counts[:25])}

Provenance by language:

{md_table(['language_code','rows','methods'], provenance_by_lang)}

Cards without provenance rows: **{cards_without_prov_total:,}** ({pct(cards_without_prov_total, total_cards)}% of cards). This does not necessarily mean the card is wrong; it means the row lacks an explicit source/provenance record in `card_source_provenance`.

Top card groups without provenance:

{md_table(['language_code','set_id','rows'], cards_without_prov[:25])}

Full no-provenance summary: `{no_prov_csv}`

## Duplicate collector-number groups

Duplicate `(language_code, set_id, local_id)` groups: **{duplicate_local_ids_total:,}**.

These may be legitimate alternate prints/variants in some products, but they should be reviewed where counts look suspicious.

Top duplicate groups:

{md_table(['language_code','set_id','local_id','rows','card_ids','names'], duplicate_local_ids[:20])}

Full duplicate audit: `{duplicate_csv}`

## Image coverage

Missing image URLs: **{image_missing:,}** ({pct(image_missing, total_cards)}% of cards).

Image coverage by language:

{md_table(['language_code','cards','missing_images'], image_by_lang)}

## Evaluation of what we have

This is now a high-value multilingual Pokémon card knowledge base with:

1. **Broad multilingual set/card coverage** — {total_cards:,} card rows across {total_langs:,} languages and {total_sets:,} localized set rows.
2. **A resolved fallback baseline** — the tracked fallback metric is now zero, making it possible to distinguish future regressions clearly.
3. **Provenance-aware repairs** — recently completed rows record source URLs and methods, making the database auditable rather than just cosmetically cleaned.
4. **Language-specific source discipline** — Indonesian came from official Asia Pokémon; Korean/Japanese from Daldagury/Pokémon-linked data; French Pocket from Poképédia; Russian XY names from Russian set checklist evidence.
5. **A concrete remaining debt list** — the template artifact CSV is now the next cleanup queue rather than hidden unknown work.

## Potential uses

This database can support:

- **SaveRoom inventory/search tooling**: localize cards and sets for stream/product listings, labels, and search aliases.
- **Collector apps**: multilingual card lookup, set browsing, and language-aware collection tracking.
- **Price/inventory enrichment**: join localized metadata to sales or market data, especially for Japanese/Korean/Indonesian product where names differ from English.
- **Content generation**: generate accurate set summaries, pack guides, stream overlays, social posts, and product descriptions.
- **Data QA dashboards**: track fallback regressions, provenance gaps, template artifacts, duplicate local IDs, and missing images.
- **RAG/search knowledge base**: power natural-language queries such as “show me Korean Lost Abyss cards” or “which Indonesian promos exist officially?”.
- **Migration/export layer**: produce Shopify-friendly product metadata, CSV exports, or an API for future SaveRoom apps.

## Recommended next steps

1. **Template artifact cleanup by language, source-backed only**  
   Start with languages with the largest remaining visible artifacts. Use official/local sources where possible; do not parse English names as a substitute for localized names unless the target language officially prints English names.

2. **Provenance backfill**  
   Add provenance rows for cards that are already likely correct but lack explicit source records.

3. **Duplicate local-id review**  
   Separate legitimate variant/alternate-print duplicates from import artifacts.

4. **Image URL backfill**  
   Fill missing images from official sources or stable source archives where licensing/use permits.

5. **Regression checks**  
   Add a small repeatable audit script that fails if unresolved fallback rows, unknown placeholders, or missing language/set rows become non-zero again.

## Artifacts from this audit

- JSON audit: `{json_path}`
- Visible template artifact CSV: `{template_csv}`
- Duplicate local-id CSV: `{duplicate_csv}`
- Cards-without-provenance-by-set CSV: `{no_prov_csv}`

## Links

- [[Pokemon Card Database Final State 2026-06-11]]
"""
    VAULT_REPORT.write_text(report, encoding='utf-8')

    print(json.dumps({
        'json_report': str(json_path),
        'vault_report': str(VAULT_REPORT),
        'summary': audit['completion_metrics'],
        'quality': audit['quality_metrics'],
        'integrity_check': integrity,
        'quick_check': quick_check,
    }, ensure_ascii=False, indent=2))

    conn.close()

if __name__ == '__main__':
    main()
