#!/usr/bin/env bash
set -u
cd '/media/matt/Storage/Brain/Pokemon Card Database' || exit 1
LOG="full_tcgdex/reports/bulk_image_cache_resume_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "[$(date -u --iso-8601=seconds)] Starting bulk local image cache resume" | tee -a "$LOG"

remaining_for() {
  local source="$1"
  python3 - "$source" <<'PY'
import sqlite3, sys
source=sys.argv[1]
conn=sqlite3.connect('full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
cur=conn.cursor()
print(cur.execute("""
SELECT COUNT(*)
FROM v2_card_search s
WHERE s.has_display_image=1
  AND s.display_image_source_type=?
  AND NOT EXISTS (
    SELECT 1 FROM card_image_local_cache lc
    WHERE lc.language_code=s.language_code AND lc.card_id=s.card_id AND lc.cache_profile='webp_q72_512'
  )
""", (source,)).fetchone()[0])
PY
}

total_remaining() {
  python3 - <<'PY'
import sqlite3
conn=sqlite3.connect('full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
cur=conn.cursor()
print(cur.execute("""
SELECT COUNT(*)
FROM v2_card_search s
WHERE s.has_display_image=1
  AND NOT EXISTS (
    SELECT 1 FROM card_image_local_cache lc
    WHERE lc.language_code=s.language_code AND lc.card_id=s.card_id AND lc.cache_profile='webp_q72_512'
  )
""").fetchone()[0])
PY
}

for source in exact_existing_image same_card_id_existing_image same_core_local_id_existing_image; do
  while true; do
    rem=$(remaining_for "$source")
    echo "[$(date -u --iso-8601=seconds)] Remaining for $source: $rem" | tee -a "$LOG"
    if [[ "$rem" -le 0 ]]; then
      break
    fi
    python3 pokemon_db_v2_bulk_local_image_downloader.py \
      --limit 5000 \
      --source-types "$source" \
      --workers 12 \
      --timeout 20 \
      --retries 1 \
      --commit-interval 100 2>&1 | tee -a "$LOG"
    rc=${PIPESTATUS[0]}
    echo "[$(date -u --iso-8601=seconds)] Batch exit for $source: $rc" | tee -a "$LOG"
    # If a whole batch cannot cache anything, avoid an infinite loop and move on.
    if [[ "$rc" -ne 0 ]]; then
      echo "[$(date -u --iso-8601=seconds)] Non-zero batch exit; continuing to next source type after short pause" | tee -a "$LOG"
      sleep 5
      break
    fi
    sleep 2
  done
done

echo "[$(date -u --iso-8601=seconds)] Remaining total before API refresh: $(total_remaining)" | tee -a "$LOG"
echo "[$(date -u --iso-8601=seconds)] Refreshing FTS/API cache" | tee -a "$LOG"
python3 pokemon_db_v2_search_api.py setup-fts 2>&1 | tee -a "$LOG"
echo "[$(date -u --iso-8601=seconds)] Done. Remaining total after API refresh: $(total_remaining)" | tee -a "$LOG"
