# v11.1 Source Access Procurement Pack

Tags: #type/project #status/needs-review

Status: PROCUREMENT_READY
Date: 2026-06-27
Branch: v11.1-market-evidence-next
Baseline commit: 44ac638

## Overview

This pack is the pre-implementation procurement checklist for v11.1 Second-Source Comparison & Cross-Source Confidence. It is written for Matthew to use before any Hermes implementation work begins.

Current decision: no second source is safe to implement yet. JustTCG is the preferred procurement target, but SaveRoom needs access, terms, credits/quota, caching, commercial-use, and sample-payload confirmation first.

## A. Why v11.1 needs source access

v11.0 already has a working market-evidence foundation using TCGdex. That gives SaveRoom a real end-to-end path:

```text
TCGdex -> raw cache -> observations -> v10 identity match -> aggregates -> API/UI
```

The limit is that v11.0 is still single-source. v11.1 should improve confidence by comparing another source against existing TCGdex-backed observations.

Before coding, SaveRoom needs source access because a second-source adapter must be built against real source rules, not guesses:

- authentication method and plan/credit behavior;
- source terms and commercial-use permission;
- whether raw responses can be cached for audit/provenance;
- whether normalized observations and aggregates can be stored permanently;
- exact payload shape for Pokémon cards;
- set/collector/variant/condition fields needed to match v10 identity;
- supported price buckets: sold, active listing, guide, market estimate;
- rate limits and monthly quotas.

## B. Preferred target: JustTCG

JustTCG is the preferred first procurement target because public docs and marketing indicate it is a structured TCG-focused pricing API with Pokémon support, condition-specific pricing, printing/variant awareness, and REST/JSON payloads.

> **Strategy note (2026-06-28):** JustTCG remains the preferred **second-source comparison target** for cross-source confidence scoring, but it is **not** the core UK pricing source. The corrected strategy is **UK-first external pricing intelligence** anchored on UK sold/completed market evidence (eBay UK as planned primary source). JustTCG's role is USD external market/current pricing, trend/sanity checks, thin-market support, and identifier mapping. USD-only JustTCG data requires explicit FX conversion before contributing to a GBP fallback estimate. See `docs/V12_PRICING_STRATEGY_CORRECTION.md` for the full correction.

### JustTCG Pricing Plans (observed 2026-06-28)

| Plan | Price | Monthly Requests | Daily Requests | Rate Limit | Cards/Request | Support |
|---|---|---|---|---|---|---|
| **Free Tier** | $0 | 1,000 | 100 | 10/min | 20 | Basic |
| **Starter** | $19/mo | 10,000 | 1,000 | 50/min | 100 | Basic |
| **Professional** | $49/mo | 50,000 | 5,000 | 100/min | 100 | Priority |
| **Enterprise** | $149/mo | 500,000 | 50,000 | 500/min | 200 | Highest priority + custom integration |

### Recommended plan
**Starter ($19/mo)** for development and early production. Upgrade to Professional ($49/mo) for customer-facing launch. The Free Tier (1K/mo) is available for initial evaluation but too limited for production.

Why it is preferred over the other candidates:

- It appears more structured than eBay sold-comps title search.
- It appears more accessible than Cardmarket direct API, whose official help currently says applications are not being accepted.
- It appears more directly pricing-focused than PokéWallet, but needs confirmation.
- It may provide better condition/variant information than current TCGdex data.
- It is likely a better first cross-source confidence target than a scraping/provider sold-comps integration.

Procurement goal: confirm JustTCG can be used legally and practically before any adapter is written.

## C. Questions that must be answered before implementation

These are the required JustTCG questions to send or ask before coding:

1. Can SaveRoom use the API for backend development of a Pokémon card pricing/evidence platform?
2. Is commercial use allowed for a private/internal pricing tool and later paid API/product?
3. Are raw API responses allowed to be cached for audit/provenance?
4. If caching is allowed, for how long?
5. Are normalized observations/aggregates allowed to be stored permanently?
6. Do requests consume paid credits during development/testing?
7. What are the rate limits and monthly quotas?
8. Does the API provide Pokémon TCG card pricing by condition?
9. Does the API separate finish/variant, such as normal, holo, reverse holo, first edition, promo, etc.?
10. Does the API distinguish sold prices, active listings, market price, or guide price?
11. Which currencies and regions are supported?
12. Are graded prices included or only raw/ungraded?
13. Is there a stable card identifier that can map to set code + collector number?
14. Can representative fixture responses be saved locally for unit tests?
15. Are there restrictions on showing source-derived prices in an internal admin UI?
16. Are there restrictions on showing source-derived prices in a future customer-facing product?

## D. Required API/key/plan details

Before implementation, Matthew should obtain and record:

- account owner and allowed developer/operator;
- plan name and whether it is free, trial, paid, or usage-based;
- whether a development key is available separately from production;
- authentication header name and expected key format;
- whether SDK use is required or plain REST calls are supported;
- base URL and API version;
- endpoint list relevant to Pokémon card lookup and pricing;
- pagination/bulk lookup support;
- monthly quota;
- per-minute/per-hour rate limit;
- whether failed requests consume quota;
- whether unit-test fixture capture consumes credits;
- whether local/offline fixtures are allowed for CI/unit tests;
- contact/support path for quota/terms questions.

Do not put the actual key in Git, docs, chat, test fixtures, logs, or screenshots. Store any approved key only in the project's secret mechanism after Matthew explicitly approves implementation.

## E. Required terms/caching/commercial-use confirmation

SaveRoom needs written or documented confirmation for:

- backend use in a private/internal pricing evidence tool;
- future commercial customer-facing product use;
- whether source-derived prices may be displayed in an internal admin UI;
- whether source-derived prices may be displayed in a future paid product;
- whether raw responses can be cached for provenance/audit;
- maximum raw-response retention period;
- whether normalized observations can be stored permanently;
- whether derived aggregates can be stored permanently;
- whether source attribution must be shown;
- whether data can be used for confidence scoring alongside another source;
- whether cached fixtures can be committed to a private repo for unit tests;
- whether prices can be exported or shared with users/customers;
- whether there are geographic restrictions relevant to UK/EU operation.

Recommended conservative interpretation until confirmed:

```text
No authenticated API calls, no adapter, no committed fixture payloads, no source-derived UI display.
```

## F. Required sample payloads

Before coding, capture approved sample payloads only after JustTCG confirms fixture saving is allowed.

Required payload types:

- single-card lookup by stable source ID;
- lookup by TCGplayer ID if supported;
- lookup/search by name + set + collector number if supported;
- bulk lookup, if supported;
- card with normal and reverse-holo data;
- card with holo or premium finish data;
- card with first edition or vintage variant data, if supported;
- promo card;
- non-English/language-specific card;
- raw/ungraded price only;
- graded price if supported;
- case with no price data;
- rate-limit metadata or response headers;
- error response for not found/invalid ID.

Each saved fixture should be named by source, lookup type, and local target, for example:

```text
justtcg_card_swsh9_017_charizard_v.json
justtcg_card_base1_4_charizard.json
justtcg_error_not_found.json
```

Do not save secrets, auth headers, account IDs, or quota/account metadata in fixtures.

## G. Representative card fixture list

The following fixture candidates were selected from the local v10 SQLite database (`full_tcgdex/staging_v9_baseline.sqlite`) without making paid or external API calls. In the local DB, `v10_canonical_printings.set_code` is mostly null, so this table uses `core_set_id`/`set_id` as the practical set-code field for source matching.

| # | canonical_printing_id | canonical_name | set_code | collector_number | language_code | finish | sellable_sku_id | Why included |
|---:|---|---|---|---|---|---|---|---|
| 1 | `cp-501e65fd75e0` | Exeggcute | `swsh9` | `001` | `en` | reverse | `sku-63126e2e0b25` | English modern low-value/bulk reverse variant; tests finish mapping. |
| 2 | `cp-de1acdc7c146` | Exeggutor | `swsh9` | `002` | `en` | reverse | `sku-564a3030ac47` | English modern uncommon-style reverse case; adjacent collector-number sanity. |
| 3 | `cp-882f0ea207e7` | Charizard V | `swsh9` | `017` | `en` | holo | `sku-c6d7a9545ea8` | English modern chase/popular card with holo finish. |
| 4 | `cp-b0761736454f` | Charizard VSTAR | `swsh9` | `018` | `en` | holo | `sku-128b4ed0c85e` | English modern high-demand VSTAR; validates V/VSTAR names and holo handling. |
| 5 | `cp-635e7e967fe7` | Umbreon VMAX | `swsh9` | `TG23` | `en` | holo | `sku-3ea0f7b3d89f` | English high-value/chase-style trainer gallery card; non-numeric collector number. |
| 6 | `cp-b3e724efb862` | Charizard V | `swshp` | `SWSH050` | `en` | holo | `sku-3945c2e8b896` | English promo-style card; promo numbering and holo. |
| 7 | `cp-13103a594bd6` | Special Delivery Charizard | `swshp` | `SWSH075` | `en` | unknown | `sku-ac64bf0a38fd` | High-value promo with ambiguous/unknown finish; tests conservative confidence. |
| 8 | `cp-4674cb8ed28a` | Charizard | `base1` | `4` | `en` | unknown | `sku-7c6f81b3c66d` | Older high-value Base Set Charizard; tests vintage identity and missing finish. |
| 9 | `cp-f9b525fab63f` | Charizard | `ex3` | `100` | `en` | unknown | `sku-ae2f35e89c69` | Older EX-era high-interest card; also historically useful for image/path regressions. |
| 10 | `cp-0186f1dcc830` | Xerneas EX | `xyp` | `XY07` | `en` | unknown | `sku-4808f9f1b479` | English promo/EX card; validates promo set and unknown finish. |
| 11 | `cp-cf3332b6efc2` | Marisson | `xyp` | `XY01` | `fr` | unknown | `sku-2a3601a25550` | French localized card; tests language-specific lookup and source matching. |
| 12 | `cp-87102b272c5e` | Chespin | `xyp` | `XY01` | `de` | unknown | `sku-df28ed6ed5e3` | German localized/product row; tests DE/EU-region behavior. |
| 13 | `cp-87102b272c5e` | Chespin | `xyp` | `XY01` | `es` | unknown | `sku-dcdf31995906` | Spanish localized variant sharing the same canonical print; tests language variant separation. |
| 14 | `cp-33ba30d265c2` | マリル | `web1` | `010` | `ja` | unknown | `sku-7f6047a685f5` | Japanese card with English name present (`Marill`); tests JP support and Unicode names. |
| 15 | `cp-2529b2e9b540` | チャームレオン | `web1` | `007` | `ja` | unknown | `sku-25ddec61b27f` | Japanese older card with no English name in the row; tests source language handling. |
| 16 | `cp-2c893919013c` | Unown | `ecard3` | `!` | `en` | unknown | `sku-dacde745b704` | Known local-image-missing/edge collector-number case; tests punctuation collector number and missing image independence. |

Fixture request notes:

- Ask JustTCG whether these can be queried by set code + collector number, source ID, TCGplayer ID, or name search.
- For each fixture, save raw JSON only after fixture retention is approved.
- If JustTCG cannot return localized French/German/Spanish/Japanese rows, record that explicitly instead of translating or falling back silently.
- If finish/condition are absent, mark the source as useful for canonical-level confidence only, not exact SKU confidence.

## H. Acceptance criteria before coding

Hermes may start a fixture-only adapter spike only after all of the following are true:

- Matthew confirms which source/key/plan may be used.
- Terms allow SaveRoom's intended use case.
- Raw-response caching/retention is either allowed or a non-raw alternative is defined.
- Normalized observations and aggregates are allowed to be stored permanently.
- Unit-test fixture payloads may be saved locally in the private repo or an approved local-only fixture directory.
- Rate limits and monthly quotas are known.
- Development/testing credit consumption is known and acceptable.
- Sample payloads confirm stable identity fields for set + collector number or equivalent v10 mapping.
- Payloads distinguish at least some of: condition, finish/variant, price type, currency, region, timestamp.
- Source overlap with TCGdex is understood well enough to decide whether the source contributes independent confidence or only enriched metadata.

If any acceptance criterion is unresolved, do not implement the adapter.

## I. Fallback plan if JustTCG is blocked

### Cardmarket direct API

- Access needed: official Cardmarket API credentials and permission for the priceguide/product endpoints.
- Why lower priority: official help currently says applications are not being accepted; credentials can affect account/stock; endpoint access is restricted.
- What would unblock it: written confirmation that SaveRoom has approved API access and may cache/store priceguide-derived observations for the intended use.

### PokéWallet

- Access needed: API key and plan terms for backend usage, caching, commercial/internal display, and fixture storage.
- Why lower priority: source identity, cache rights, and independence from TCGdex need validation; custom IDs may require mapping work.
- What would unblock it: approved key/plan plus 10-20 representative sample payloads matching v10 set/collector/language/variant fields.

### RapidAPI CardMarket/Pokemon API

- Access needed: RapidAPI subscription/key, provider terms, quota/credit rules, cache permissions, and sample payloads.
- Why lower priority: provider may repackage Cardmarket/TCGPlayer/eBay data with terms and credit risk; source independence from TCGdex is uncertain.
- What would unblock it: free/test quota confirmation, fixture permission, and clear mapping fields for v10 identity.

### eBay sold-comps provider

- Access needed: approved provider plan/key, sold-only endpoint, cache terms, and a controlled query budget.
- Why lower priority: sold comps are valuable but title matching is noisy and higher-risk than structured set/collector APIs.
- What would unblock it: provider permission plus a small reviewed pilot with strict category filters, title parser rules, outlier handling, and manual match review.

### TCGplayer direct

- Access needed: TCGplayer API/partner credentials, terms, cache rights, and product/SKU mapping documentation.
- Why lower priority: likely overlaps with TCGdex's TCGPlayer-backed market evidence; commercial licensing/caching needs care.
- What would unblock it: confirmed rights and evidence that direct product/SKU IDs improve matching or confidence beyond current TCGdex data.

## J. What Hermes must not do yet

Until Matthew confirms source access and terms, Hermes must not:

- build a JustTCG adapter;
- add Cardmarket, eBay, PokéWallet, RapidAPI, or TCGplayer source code;
- make authenticated source calls;
- use paid credits;
- store API secrets;
- commit raw external API payloads;
- fake sample responses;
- broaden UI beyond the existing evidence panel;
- change image loading again unless regression tests fail;
- start scanner, POS, marketplace sync, billing, or customer-facing product work.


## Public web/Tavily research update — 2026-06-27

A public research supplement now exists at `docs/V11_1_PUBLIC_SOURCE_TERMS_RESEARCH.md`. Fifty Tavily/web searches were run across JustTCG, PokéWallet, Cardmarket direct API, RapidAPI CardMarket/Pokémon pricing APIs, TCGplayer direct API, eBay Browse API, and eBay sold/completed providers.

Public research confirmed:

- JustTCG has public docs, examples, API key auth, Pokémon support, condition/printing examples, subscription-tier terms, and explicit free-tier non-commercial restrictions.
- PokéWallet has public docs, public rate limits/plans, API key auth, Pokémon pricing from TCGPlayer/CardMarket, variant models, and terms allowing personal or commercial use subject to its terms.
- Cardmarket direct API is publicly documented but currently not accepting API access applications; PriceGuide access is restricted, and public terms/search results indicate prior written agreement is needed to present trading-card prices.
- RapidAPI/provider APIs advertise Pokémon/Cardmarket/TCGPlayer/eBay graded pricing and public price tiers, but provider/RapidAPI cache and redistribution rights remain unclear.
- TCGplayer direct API has public docs/help for pricing data, but access is partner/API gated and terms around combining/rebranding/caching require direct review.
- eBay Browse API is documented and supports active listing search with OAuth, but it is not a sold/completed price source.
- eBay sold providers publicly offer sold-comps data, but require provider keys/tokens or paid plans and rely on title/category matching rather than Pokémon set+collector identity.

What remains unclear:

- Raw-response caching and retention permission for every viable provider.
- Permanent normalized observation/aggregate storage rights.
- Whether authenticated sample payloads can be saved as unit-test fixtures.
- Customer-facing display permission for source-derived prices.
- Exact price-bucket semantics for JustTCG: sold vs active listing vs market vs guide.
- Whether JustTCG/PokéWallet localized Pokémon payloads can map cleanly to v10 identity without fallback.

JustTCG contact is still needed. Public docs make JustTCG the best procurement target but do not prove safe implementation. In particular, public terms prohibit commercial/business use of the free tier and do not clearly authorize raw-response caching, fixture saving, or permanent derived aggregate storage.

Best next step: send the JustTCG access request now, emphasizing paid-tier business use, caching/fixture permission, derived aggregate retention, display rights, and price-type semantics. If JustTCG cannot confirm those points, repeat procurement with PokéWallet as the next structured-source fallback.

## Links

- Related: `docs/V11_1_PREFLIGHT.md`
- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Related: `docs/V11_RELEASE.md`
- Related: `docs/V11_QUALITY_REPORT.md`
- Draft request: `docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md`
