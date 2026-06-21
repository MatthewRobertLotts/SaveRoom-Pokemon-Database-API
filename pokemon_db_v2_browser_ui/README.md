# SaveRoom Pokémon DB Browser UI

Lightweight browser UI over the local FastAPI service.

## Run

```bash
cd '/media/matt/Storage/Brain/Pokemon Card Database'
python3 pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/ui/
```

Or open `index.html` directly in a browser and keep the API base set to `http://127.0.0.1:8765`.

## Features

- Search box backed by `/search`.
- Language filter.
- Core set filter.
- "Has image only" toggle.
- Result count and API timing.
- Card grid with thumbnail, name, language, set, collector number, rarity, image status.
- Detail modal backed by `/cards/{language_code}/{card_id}`.
- Copy result JSON.
- Copy card JSON.
- Copy product title.
- Copy Shopify draft fields.

## Verification

Latest smoke report:

```text
/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports/v2_browser_ui_smoke_test_2026-06-14.json
```
