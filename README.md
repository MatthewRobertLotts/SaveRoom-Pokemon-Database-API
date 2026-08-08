<div align="center">
  <h1>SaveRoom Pokémon Card Database API</h1>
  <p><strong>FastAPI backend for Pokémon TCG search, pricing, inventory, and app workflows.</strong></p>
</div>

<p align="center">
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/actions/workflows/ci.yml"><img src="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/releases/tag/v12.2.0"><img src="https://img.shields.io/badge/release-v12.2.0-22498e" alt="v12.2.0"></a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
</p>

## What this is

SaveRoom Pokémon Card Database API is the backend platform behind SaveRoom's Pokémon TCG tools. It exposes card search, card detail, images, pricing, inventory, listing, sales, fixture, and health endpoints through a FastAPI/OpenAPI service.

**Current stable release:** [`v12.2.0`](https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/releases/tag/v12.2.0)

## Why it matters

- **App-ready API:** built for scanner, collection, inventory, and seller workflows.
- **Multilingual card data:** supports 18 languages, canonical cards, printings, variants, and set metadata.
- **Pricing intelligence:** stores market price, history, evidence, and source guardrails.
- **Operational shape:** auth, quotas, health checks, image delivery, fixtures, tests, and docs.

## Architecture

```text
Flutter / client apps
        │ HTTP / REST
        ▼
FastAPI service ── OpenAPI 3.1 docs
        │
        ├── Cards / Sets / Printings
        ├── Images / Fixtures / Health
        ├── Pricing / Sales / Listings
        └── Inventory / Locations / Reports
        │
        ▼
SQLite data store + local image cache
```

## Quick start

```bash
git clone https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API.git
cd SaveRoom-Pokemon-Database-API
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 pokemon_db_v2_fastapi.py
```

Open: `http://localhost:8765/docs`

## API scope

| Domain | Purpose |
|---|---|
| Cards | Search, detail, variants, printings, multilingual metadata |
| Sets | Set listing, set detail, card-by-set workflows |
| Pricing | Market price, history, evidence chain, source adapters |
| Inventory | Physical stock, locations, status, workflow fields |
| Listings | Listing assistant endpoints and deterministic listing output |
| Images | Asset lookup and signed/local delivery paths |
| Fixtures | Stable app-development and QA payloads |
| Health | Runtime status, diagnostics, and monitoring endpoints |

## Repo notes

Runtime/API entrypoints stay at the repository root. Historical import, scraper, recovery, and one-off data build scripts live in `scripts/legacy/` so the public root stays readable without deleting project history.

## Related

| Project | Purpose |
|---|---|
| [SaveRoom Scanner App](https://github.com/MatthewRobertLotts/SaveRoom-Scanner-App) | Flutter frontend consuming this API |
| This repo | Backend API and data platform |

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
