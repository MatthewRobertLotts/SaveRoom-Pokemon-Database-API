<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=rect&color=gradient&customColorList=0,2,3,4,6,8&height=5&section=header" width="100%" />
</p>

<div align="center">
  <h1>🃏 SaveRoom Pokémon Card Database API</h1>
  <p><strong>Reusable backend brain for Pokémon TCG products</strong><br/>multilingual card data · pricing intelligence · inventory workflows · app-ready APIs</p>
</div>

<p align="center">
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/releases">
    <img src="https://img.shields.io/github/v/release/MatthewRobertLotts/SaveRoom-Pokemon-Database-API?style=for-the-badge&label=Release&color=22498e"></a>
  <a href="#">
    <img src="https://img.shields.io/badge/Tests-937%20passing-2ea44f?style=for-the-badge&logo=pytest&logoColor=white"></a>
  <a href="#">
    <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white"></a>
  <a href="#">
    <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"></a>
  <a href="#">
    <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white"></a>
  <a href="#">
    <img src="https://img.shields.io/badge/OpenAPI%203.1-6DB33F?style=for-the-badge&logo=swagger&logoColor=white"></a>
</p>

---

## 📌 Overview

SaveRoom Pokémon Card Database API is the **core backend platform** for SaveRoom's Pokémon TCG ecosystem — a structured, API-first data platform with:

- 🔍 **Multi-language card data** — 18 languages, canonical printings, commercial variants
- 💰 **Pricing intelligence** — Evidence chain, chart-ready history, market analysis
- 📦 **Inventory workflows** — Physical items, locations, status tracking
- 🏪 **Listing assistant** — Deterministic output, workflow-ready endpoints
- 📊 **Sales aggregation** — Typed local summaries, analytics
- 🧪 **Test suite** — 937 passing tests, comprehensive coverage

**Current stable release:** [`v12.2.0`](https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/releases/tag/v12.2.0)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                  SaveRoom Pokémon DB API (v12+)       │
│  FastAPI · SQLite · OpenAPI 3.1 · Auth               │
├─────────────────────────────────────────────────────┤
│  Cards · Sets · Printings · SKUs · Pricing            │
│  Images · Inventory · Listings · Sales · Reports       │
│  Multi-language · Fixtures · Health                    │
└────────────────────────┬────────────────────────────┘
                         │ HTTP/REST
                         ▼
              ┌──────────────────────┐
              │   Scanner / Client   │
              │   (consumer apps)     │
              └──────────────────────┘
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API.git
cd SaveRoom-Pokemon-Database-API
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 pokemon_db_v2_fastapi.py
```

Browse interactive docs at **`http://localhost:8765/docs`**

---

## 📐 API Scope

| Domain | Endpoints | Purpose |
|--------|-----------|---------|
| 🔍 Cards | Search, detail, variants, printings | Canonical card data across 18 languages |
| 📚 Sets | Set listing, detail, card-by-set | Release/set metadata |
| 💰 Pricing | Market prices, history, evidence | Pricing intelligence pipeline |
| 📦 Inventory | Items, locations, status | Physical stock management |
| 🖼️ Images | Asset lookup, content delivery | Image cache & delivery |
| 🧪 Fixtures | Test/development data | App dev & QA |
| ❤️ Health | Status, metrics, diagnostics | Monitoring & operations |

---

## 🔗 Related

| Project | Purpose |
|---------|---------|
| [`SaveRoom-Scanner-App`](https://github.com/MatthewRobertLotts/SaveRoom-Scanner-App) | Flutter scanner & collection frontend |
| **This repo** | 👈 Backend brain / API / data platform |

---

## 📄 License

Copyright © 2026 Matthew Lotts. Licensed under the **Apache License, Version 2.0**. See [`LICENSE`](LICENSE) for details.

---

<p align="center">
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/stargazers"><img src="https://img.shields.io/github/stars/MatthewRobertLotts/SaveRoom-Pokemon-Database-API?style=social&label=Stars"></a>
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/network"><img src="https://img.shields.io/github/forks/MatthewRobertLotts/SaveRoom-Pokemon-Database-API?style=social&label=Forks"></a>
  <a href="https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/releases"><img src="https://img.shields.io/github/downloads/MatthewRobertLotts/SaveRoom-Pokemon-Database-API/total?style=social&label=Downloads"></a>
</p>