# Alternative Image Sources Research Results
# ============================================

## Sources That WORK (Confirmed)

### 1. pokemontcg.io (Scrydex) — English only
- URL: `https://images.pokemontcg.io/<set_id>/<card_number>_hires.png`
- API: `https://api.pokemontcg.io/v2/cards/<set_id>-<number>`
- Languages: English only
- Coverage: 173 sets, all English
- Status: ✅ Tested and working
- Can recover: ~1,716 English cards (with set ID mapping)

### 2. tcg.mik.moe — Chinese Simplified only
- URL: `https://tcg.mik.moe/static/img/<set_id>/<number>.png`
- Languages: Chinese Simplified only
- Coverage: ~17 of 42 ZH-CN sets mapped so far
- Status: ✅ Tested and working
- Can recover: ~1,727 ZH-CN cards (more with better set ID mapping)

### 3. Asia Pokemon Card sites — ID, ZH-TW, TH
- URL: `https://asia.pokemon-card.com/<site>/card-img/...`
- Languages: Indonesian, Traditional Chinese, Thai
- Status: ✅ Fully scraped
- Recovered: 6,030 ID + 5,367 ZH-TW + 2,223 TH

### 4. TCGdex — SV-Japanese only
- URL: `https://assets.tcgdex.net/ja/<series>/<set>/<number>`
- Languages: SV-Japanese only (images empty for other languages)
- Status: ✅ Used for 204 SV-Japanese cards

## Sources That PARTIALLY Work

### 5. Japanese Official Site CDN
- URL: `https://www.pokemon-card.com/assets/images/card_images/large/<SET>/<CARD_ID>_<ROMAJI_NAME>.jpg`
- Languages: Japanese
- Coverage: All Japanese sets
- Status: ⚠️ CDN accessible but requires numeric card ID + romaji name
- Challenge: Need to map DB card_id → numeric ID and Japanese name → romaji
- Can recover: Up to 11,931 Japanese cards (if mapping solved)

### 6. pokellector.com — Multi-language (English + Japanese)
- URL: `https://den-cards.pokellector.com/<set_id>/<card_name>.<rarity>.<number>.thumb.png`
- Languages: English, Japanese (claimed)
- Coverage: Unknown
- Status: ⚠️ Images exist but URL format is complex (requires card name, rarity)
- Challenge: Need to map DB card_id → pokellector URL format

## Sources That DON'T Work

### 7. TCGdex API (full) — All languages
- Status: ❌ Has card data but image URLs are empty for all except SV-Japanese

### 8. Official Korean site (pokemoncard.co.kr)
- Status: ❌ Returns 410 Gone

### 9. CardTrader API
- Status: ❌ Requires authentication (API key needed)

### 10. PokemonTCG GitHub repo
- Status: ❌ English only

### 11. pokemon-tcg-pocket-database
- Status: ❌ Pocket game only, not main TCG

## Untested Sources (Potential)

### 12. PokéWallet API (pokewallet.io)
- Claims multi-language support
- Status: ❓ Not tested

### 13. Ximilar API (ximilar.com)
- Card recognition API, might have images
- Status: ❓ Not tested

### 14. RyuuPlay (GitHub: keeshii/ryuu-play)
- Open source TCG simulator with card images
- Status: ❓ Not tested

### 15. ptcg-assets (GitHub: 1niceroli/ptcg-assets)
- Collection of Pokémon TCG assets
- Status: ❓ Not tested

## Summary of Recoverable Cards

| Source | Language | Cards | Status |
|--------|----------|-------|--------|
| pokemontcg.io | English | ~1,716 | ✅ Ready to implement |
| tcg.mik.moe | Chinese Simplified | ~1,727 | ✅ Ready to implement |
| Japanese CDN | Japanese | ~11,931 | ⚠️ Needs ID mapping |
| pokellector.com | Japanese/English | Unknown | ❓ Needs investigation |
| **Total recoverable** | | **~15,374** | |

## Recommended Next Steps

1. **Implement English recovery via pokemontcg.io** (~1,716 cards)
2. **Implement Chinese Simplified recovery via tcg.mik.moe** (~1,727 cards)
3. **Investigate Japanese CDN** — solve the numeric ID mapping problem
4. **Test pokellector.com** for Japanese/English cards
5. **Test untried sources** (PokéWallet, ptcg-assets, RyuuPlay)
