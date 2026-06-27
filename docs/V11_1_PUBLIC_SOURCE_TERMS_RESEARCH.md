# v11.1 Public Source Terms Research

Tags: #type/project #status/needs-review

Status: PUBLIC_RESEARCH_COMPLETE
Date: 2026-06-27
Branch: v11.1-market-evidence-next
Baseline commit: 056c419

## Overview

This document supplements the v11.1 source validation and procurement pack with public web/Tavily research. It answers as many source-access, pricing, terms, caching, commercial-use, and API-field questions as public documentation allows.

Research constraints followed:

- 50 Tavily/web searches were run across the candidate providers.
- Public docs, pricing pages, terms pages, official API docs, and reputable provider pages were used.
- No signup, paid credits, authenticated API calls, secret storage, or adapter implementation was performed.
- Unclear public information is not treated as permission.

Label meanings:

- **PUBLICLY CONFIRMED** — public docs explicitly state this point.
- **PUBLICLY UNCLEAR** — not found or not explicit enough in public docs.
- **BLOCKED / REQUIRES CONTACT** — source/key/permission/contact is needed before implementation.
- **NOT SUITABLE** — public docs make the source unsuitable for this v11.1 purpose.

## Sources consulted

Key URLs used:

- JustTCG docs: https://justtcg.com/docs
- JustTCG examples: https://justtcg.com/docs/examples
- JustTCG terms: https://justtcg.com/terms
- JustTCG product page: https://justtcg.com
- PokéWallet docs: https://www.pokewallet.io/api-docs
- PokéWallet terms: https://www.pokewallet.io/terms-conditions
- PokéWallet product page: https://pokewallet.io
- Cardmarket API help: https://help.cardmarket.com/en/cardmarket-api
- Cardmarket PriceGuide docs: https://api.cardmarket.com/ws/documentation/API_2.0:PriceGuide
- Cardmarket Article entity docs: https://api.cardmarket.com/ws/documentation/API_2.0:Entities:Article
- CardMarket API / TCGGO landing page: https://www.cardmarket-api.com
- RapidAPI CardMarket API TCG pricing: https://rapidapi.com/tcggopro/api/cardmarket-api-tcg/pricing
- RapidAPI Pokémon TCG API pricing: https://rapidapi.com/tcggopro/api/pokemon-tcg-api/pricing
- TCGplayer access help: https://help.tcgplayer.com/hc/en-us/articles/201577976-How-can-I-get-access-to-your-card-pricing-data
- TCGplayer API pricing docs: https://docs.tcgplayer.com/reference/pricing
- TCGplayer welcome/API docs: https://docs.tcgplayer.com/docs/welcome
- TCGplayer API terms search result: https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions
- eBay Browse search docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
- eBay API license page: https://developer.ebay.com/join/api-license-agreement
- eBay get-started guide: https://developer.ebay.com/develop/guides-v2/get-started-with-ebay-apis
- Apify eBay sold listings: https://apify.com/caffein.dev/ebay-sold-listings
- Apify eBay sold listings API: https://apify.com/caffein.dev/ebay-sold-listings/api
- SoldComps: https://sold-comps.com
- RapidAPI eBay completed docs: https://github.com/colindaniels/eBay-sold-items-documentation
- RapidAPI eBay average selling price: https://rapidapi.com/ecommet/api/ebay-average-selling-price

## Provider research

### 1. JustTCG

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — docs, examples, product page, and terms are reachable (`justtcg.com/docs`, `/docs/examples`, `/terms`). |
| 2. API key required? | **PUBLICLY CONFIRMED** — all API requests require an API key in `x-api-key`; SDK reads `JUSTTCG_API_KEY`. Source: https://justtcg.com/docs |
| 3. Free tier? | **PUBLICLY CONFIRMED** — product page advertises a free tier/no credit card. Terms restrict free tier to personal, non-commercial use. Sources: https://justtcg.com and https://justtcg.com/terms |
| 4. Paid/subscription/credit based? | **PUBLICLY CONFIRMED** — terms mention subscription tiers, fees, rate limits by tier, and possible additional charges when limits are exceeded. Source: https://justtcg.com/terms |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED / PARTIAL** — terms say rate limits depend on subscription tier; examples show `api_calls_used` and `api_calls_remaining`; exact current tier quotas were not fully captured in public docs. Sources: `/terms`, `/docs/examples`, product page. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED / BLOCKED FOR FREE TIER** — data may be used for personal or business purposes according to subscription tier; free tier commercial/business/scraping/reselling use is prohibited. Source: https://justtcg.com/terms |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — terms discuss data licensing and restrictions but no explicit raw-response caching/retention permission was found. Requires provider confirmation. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR** — business use is tier-dependent, but permanent normalized storage/aggregate retention is not explicit. Requires provider confirmation. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED** — product page lists Pokémon TCG support and docs describe Pokémon among supported games. Sources: https://justtcg.com, https://justtcg.com/docs |
| 10. Condition-specific pricing? | **PUBLICLY CONFIRMED** — product page and examples show condition-specific requests such as `Near Mint` and `Lightly Played`. Sources: product page, `/docs/examples`. |
| 11. Finish/variant-specific pricing? | **PUBLICLY CONFIRMED** — examples include `printing` such as `Normal` and `1st Edition`; product page says printing variant tracking. Sources: `/docs/examples`, product page. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY UNCLEAR** — public docs call it pricing/current prices and variants, but do not clearly label sold vs active listing vs market vs guide in the extracted material. |
| 13. Currencies/regions? | **PUBLICLY UNCLEAR** — public examples show dollar pricing but provider coverage/currency set was not clearly specified. |
| 14. Graded prices? | **PUBLICLY UNCLEAR** — no clear public confirmation in extracted JustTCG docs. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / PARTIAL** — sample payloads include `id`, `set`, `number`, `tcgplayerId`; likely useful for set/collector/TCGplayer matching, but Pokémon-specific payloads still need sample confirmation. Sources: product page, `/docs/examples`. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED** — examples show response shapes and request patterns. Full Pokémon samples still need authenticated sample confirmation. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY UNCLEAR** — examples are public, but saving actual authenticated responses as fixtures is not explicitly allowed. |
| 18. Development risk | Medium. Structured API and examples are good; auth/plan/credits/caching and exact Pokémon field behavior still need confirmation. |
| 19. Commercial/legal risk | Medium. Paid tier may permit business use, but caching/fixture/storage and customer-facing display need confirmation. Free tier is not suitable for commercial/business use. |
| 20. Recommendation | **BLOCKED / REQUIRES CONTACT** before adapter. JustTCG remains preferred target, but direct confirmation is still needed for caching, normalized retention, fixtures, source-derived display, and correct plan. |

### 2. PokéWallet

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — docs, product page, and terms are reachable. |
| 2. API key required? | **PUBLICLY CONFIRMED** — all endpoints except `/health` require an API key; supports `X-API-Key` and bearer token. Source: https://www.pokewallet.io/api-docs |
| 3. Free tier? | **PUBLICLY CONFIRMED** — Free plan: 100/hour, 1,000/day, $0/month. Source: API docs. |
| 4. Paid/subscription/credit based? | **PUBLICLY CONFIRMED** — Pro plan listed at €20/month; Business custom; Coffee tier. Source: API docs. |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED** — plan limits and rate-limit headers are public. Source: API docs. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED** — terms grant limited, non-exclusive, non-transferable, revocable license for personal or commercial purposes subject to terms. Source: https://www.pokewallet.io/terms-conditions |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — docs mention internal cache health but do not clearly permit users to store raw API responses. Requires confirmation. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR** — commercial use is allowed generally, but permanent derived storage/aggregate retention is not explicit. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED** — API is specifically Pokémon TCG with real-time pricing from TCGPlayer and CardMarket. |
| 10. Condition-specific pricing? | **PUBLICLY UNCLEAR / PARTIAL** — docs expose variant systems but extracted public docs do not clearly show condition-specific price ladders. |
| 11. Finish/variant-specific pricing? | **PUBLICLY CONFIRMED** — docs document TCGPlayer `sub_type_name` values and CardMarket `variant_type` normal/holo. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY UNCLEAR** — docs say real-time pricing from TCGPlayer/CardMarket; not clearly bucketed as sold vs active vs guide. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED / PARTIAL** — TCGPlayer and CardMarket imply USD/EUR and US/EU; health region example uses FRA. Exact currency fields need sample payload confirmation. |
| 14. Graded prices? | **PUBLICLY UNCLEAR** — no clear confirmation in extracted docs. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / PARTIAL** — docs explain `pk_` IDs, CardMarket-only hashes, and variant IDs; still need payload samples for set code + collector number. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED / PARTIAL** — docs show auth/rate/error examples and ID formats; useful card payload samples may need authenticated calls. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY UNCLEAR** — no explicit permission for saving authenticated fixtures. |
| 18. Development risk | Medium. Strong docs/rate limits and clearer commercial-use wording than several candidates; mapping and caching remain open. |
| 19. Commercial/legal risk | Medium. Commercial use is public, but caching/raw payload retention and derived-data terms need confirmation. |
| 20. Recommendation | **C. Need account/key before coding** plus caching/fixture clarification. Best fallback structured candidate if JustTCG stalls. |

### 3. Cardmarket direct API

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — official help and API docs are reachable. |
| 2. API key required? | **PUBLICLY CONFIRMED** — PriceGuide requires authentication and is restricted to selected users. Source: PriceGuide docs. |
| 3. Free tier? | **PUBLICLY UNCLEAR / BLOCKED** — public help says applications for API access are currently not accepted. |
| 4. Paid/subscription/credit based? | **PUBLICLY UNCLEAR** — access is restricted; no open public plan suitable for this work found. |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED / PARTIAL** — PriceGuide updated daily; docs warn 429 if requested more frequently. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED / RESTRICTIVE** — search result from Cardmarket GTC states API may only be used for managing own contents and presentation of trading cards/prices requires prior written agreement. Public help warns credentials can manipulate account/stock. |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — no clear caching permission found. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR / BLOCKED** — prior written agreement appears needed for presenting prices; derived storage not explicit. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED** — Article entity has Pokémon-specific fields; PriceGuide has `idGame`; Cardmarket is a TCG marketplace. |
| 10. Condition-specific pricing? | **PUBLICLY CONFIRMED / PARTIAL** — Article entity has `condition`; PriceGuide includes `Low Price Ex+`, but not a full condition ladder in the priceguide fields. |
| 11. Finish/variant-specific pricing? | **PUBLICLY CONFIRMED** — Article entity includes `isFoil`, `isReverseHolo`, `isFirstEd` for Pokémon; PriceGuide has foil fields. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY CONFIRMED / PARTIAL** — PriceGuide has average sell, low, trend, AVG1/7/30 fields; Article is marketplace listing data. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED** — Article entity price uses EUR by default and includes currency fields. Region is Cardmarket/Europe. |
| 14. Graded prices? | **PUBLICLY UNCLEAR** — no clear direct API graded pricing support found. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / PARTIAL** — `idProduct`, expansion abbreviation, product number fields exist, but v10 mapping would require product-ID/set-number mapping. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED** — docs include entity examples and PriceGuide CSV fields. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY CONFIRMED for docs examples only / UNCLEAR for live data**. |
| 18. Development risk | High due restricted access, OAuth/signing, product mapping, and permission constraints. |
| 19. Commercial/legal risk | High. Public terms/help indicate restricted use and prior written agreement for presenting prices. |
| 20. Recommendation | **D. Not suitable now / BLOCKED**. Do not implement without direct Cardmarket permission. |

### 4. RapidAPI CardMarket / Pokémon card pricing APIs

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — RapidAPI listings and provider landing pages are reachable; some RapidAPI pricing pages failed extraction but search summaries returned pricing info. |
| 2. API key required? | **PUBLICLY CONFIRMED** — RapidAPI APIs require RapidAPI key/subscription. |
| 3. Free tier? | **PUBLICLY CONFIRMED / PROVIDER-SPECIFIC** — examples include Basic $0 with 100/day for `tcggopro` Pokémon TCG API; other APIs show different free limits. |
| 4. Paid/subscription/credit based? | **PUBLICLY CONFIRMED** — plans such as Pro/Ultra/Mega are public; overage/limits vary by API. |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED / PARTIAL** — RapidAPI pricing search summaries expose daily/monthly and per-minute limits for some listings. |
| 6. Commercial use mentioned? | **PUBLICLY UNCLEAR** — provider landing pages advertise developer/business use, but exact terms for SaveRoom use and redistribution are not clear from public extracts. |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — no explicit cache/raw retention permission found. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR** — no explicit permission found. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED** — provider pages list Pokémon TCG pricing from Cardmarket/TCGPlayer and sometimes eBay graded sold prices. |
| 10. Condition-specific pricing? | **PUBLICLY CONFIRMED / PARTIAL** — landing page sample includes near-mint fields; full condition matrix unclear. |
| 11. Finish/variant-specific pricing? | **PUBLICLY UNCLEAR / PARTIAL** — sample has card fields but finish handling is not clearly documented in extracted content. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY CONFIRMED / PARTIAL** — provider advertises Cardmarket, TCGPlayer, and eBay sold graded medians; exact bucket semantics require sample docs. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED** — EUR from Cardmarket, USD from TCGPlayer/eBay; country-specific DE/FR/ES/IT fields advertised. |
| 14. Graded prices? | **PUBLICLY CONFIRMED for provider landing page** — eBay sold graded prices for PSA/BGS/CGC are advertised. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / PARTIAL** — sample has provider `id`, `name_numbered`, `card_number`, set code; needs actual docs/sample coverage. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED / PARTIAL** — landing page includes sample response excerpts. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY UNCLEAR** — public examples can be cited, but saving authenticated responses needs provider/RapidAPI term review. |
| 18. Development risk | Medium/high. Rich data but provider/RapidAPI terms, overlap, and exact endpoint docs need careful review. |
| 19. Commercial/legal risk | Medium/high. API aggregates multiple marketplaces; caching/redistribution not clear. |
| 20. Recommendation | **B/C. Need provider/RapidAPI term review and key before coding**. Not safe to implement from public docs alone. |

### 5. TCGplayer direct API

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — help and docs pages are reachable. |
| 2. API key required? | **PUBLICLY CONFIRMED** — docs require authorization/application access. |
| 3. Free tier? | **PUBLICLY UNCLEAR** — no open free tier suitable for this use was confirmed. |
| 4. Paid/subscription/credit based? | **PUBLICLY UNCLEAR / PARTNER-BASED** — help frames API access as partner/affiliate/custom API. |
| 5. Rate limits/quotas public? | **PUBLICLY UNCLEAR** — not captured in public docs. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED / RESTRICTIVE** — help says APIs can be used in website/app and affiliate program; search result for API Terms says combining TCGplayer pricing data with own/third-party pricing data is a restricted/prohibited item. Needs legal review/contact. |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — no clear caching permission found. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR / POSSIBLY RESTRICTED** — API Terms search result mentions restrictions around combining/rebranding TCG content. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED** — TCGplayer marketplace covers Pokémon; pricing endpoints return market/low/mid/high/buylist. |
| 10. Condition-specific pricing? | **PUBLICLY UNCLEAR / LIKELY via product/SKU APIs** — not enough public extracted detail for this decision. |
| 11. Finish/variant-specific pricing? | **PUBLICLY UNCLEAR / LIKELY via product/SKU APIs** — not enough public extracted detail. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY CONFIRMED / PARTIAL** — pricing docs mention market, low/mid/high, Buylist; not sold comps. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED / PARTIAL** — US marketplace; USD implied. |
| 14. Graded prices? | **PUBLICLY UNCLEAR**. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / PARTIAL** — product/SKU IDs exist; v10 external refs may help, but mapping needs implementation analysis. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED / PARTIAL** — docs/reference exists, but login may hide endpoint detail. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY UNCLEAR**. |
| 18. Development risk | Medium/high due partner access and restrictive terms. |
| 19. Commercial/legal risk | High until terms/contact confirm combining, caching, and display rights. |
| 20. Recommendation | **BLOCKED / REQUIRES CONTACT**. Also less distinct from TCGdex because TCGdex already exposes TCGPlayer-backed pricing. |

### 6. eBay Browse API

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — Browse search docs are reachable. |
| 2. API key required? | **PUBLICLY CONFIRMED** — OAuth bearer token required. |
| 3. Free tier? | **PUBLICLY UNCLEAR** — developer account/API access exists, but limits/terms require app registration. |
| 4. Paid/subscription/credit based? | **PUBLICLY UNCLEAR** — no paid plan confirmed in extracted docs. |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED / PARTIAL** — eBay publishes call-limit concepts; exact application limits depend on API/app. Search endpoint has result/limit/offset restrictions. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED / TERMS-GATED** — API use is subject to eBay API License Agreement. |
| 7. Caching/raw response storage mentioned? | **PUBLICLY CONFIRMED / PARTIAL** — eBay get-started guide search result says to cache locally to avoid duplicate retrieval; exact retention/display restrictions require API license review. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR** — not explicit in extracted docs. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED / INDIRECT** — eBay listings include Pokémon cards, but API is general marketplace search. |
| 10. Condition-specific pricing? | **PUBLICLY CONFIRMED / PARTIAL** — supports condition filters/fields. |
| 11. Finish/variant-specific pricing? | **PUBLICLY UNCLEAR** — finish would be title/aspect inference, not reliable structured Pokémon finish. |
| 12. Sold/active/market/guide distinction? | **NOT SUITABLE for sold comps** — Browse search returns item summaries and defaults to fixed-price active listings. It is not a sold/completed pricing source. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED** — marketplace header determines marketplace; listings carry marketplace-specific prices. |
| 14. Graded prices? | **PUBLICLY UNCLEAR / title-inferred only**. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY CONFIRMED / WEAK** — supports ePID/GTIN/category/keyword, but Pokémon set+collector matching would mostly be title/aspect parsing. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED** — docs describe fields and examples. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY UNCLEAR** for live responses; docs examples can be cited. |
| 18. Development risk | High for v11.1 confidence because data is active listings and matching is noisy. |
| 19. Commercial/legal risk | Medium/high until API license display/cache terms are reviewed. |
| 20. Recommendation | **D. Not suitable as v11.1 second-source pricing evidence**. Useful later for active-listing market context, not sold-comps confidence. |

### 7. eBay sold/completed pricing providers

Providers found include Apify `caffein.dev/ebay-sold-listings`, SoldComps, and RapidAPI `eBay Average Selling Price`.

| Question | Answer |
|---|---|
| 1. Public documentation reachable? | **PUBLICLY CONFIRMED** — provider pages and docs are reachable. |
| 2. API key required? | **PUBLICLY CONFIRMED** — Apify requires account/token; SoldComps requires API key; RapidAPI provider requires RapidAPI key. |
| 3. Free tier? | **PUBLICLY CONFIRMED / PROVIDER-SPECIFIC** — SoldComps advertises free 25 requests/month; Apify is paid by result; RapidAPI plan unknown from extraction. |
| 4. Paid/subscription/credit based? | **PUBLICLY CONFIRMED** — Apify from $4/1,000 results; SoldComps paid monthly tiers; RapidAPI subscription/key. |
| 5. Rate limits/quotas public? | **PUBLICLY CONFIRMED / PROVIDER-SPECIFIC** — SoldComps publishes requests/month and req/min; Apify pricing by result; RapidAPI provider docs show result limits. |
| 6. Commercial use mentioned? | **PUBLICLY CONFIRMED / PARTIAL** — providers market toward developers/resale tools/pricing intelligence, but exact commercial/cache rights require terms review. |
| 7. Caching/raw response storage mentioned? | **PUBLICLY UNCLEAR** — no explicit raw-response retention permission found in extracted docs. |
| 8. Normalized derived prices/aggregates allowed? | **PUBLICLY UNCLEAR** — no explicit permission found. |
| 9. Pokémon prices available? | **PUBLICLY CONFIRMED / INDIRECT** — these are generic eBay sold listing providers; Pokémon can be queried by keyword/category but not Pokémon-specific structured IDs. |
| 10. Condition-specific pricing? | **PUBLICLY CONFIRMED / PARTIAL** — sold listings include eBay condition labels/IDs; not TCG grading conditions. |
| 11. Finish/variant-specific pricing? | **PUBLICLY UNCLEAR / WEAK** — finish must be inferred from title/aspects. |
| 12. Sold/active/market/guide distinction? | **PUBLICLY CONFIRMED** — these providers return sold/completed prices, not active listings. |
| 13. Currencies/regions? | **PUBLICLY CONFIRMED** — SoldComps/Apify support multiple eBay marketplaces; outputs include currency. |
| 14. Graded prices? | **PUBLICLY CONFIRMED / TITLE-INFERRED** — graded cards appear in sold listings; not necessarily normalized by PSA/BGS/CGC unless provider-specific parsing exists. |
| 15. Stable identifiers for v10 matching? | **PUBLICLY UNCLEAR / WEAK** — eBay item IDs are stable for listings, but no set+collector identity. Matching would be title/category/parser based. |
| 16. Public sample payloads? | **PUBLICLY CONFIRMED** — Apify, SoldComps, and GitHub docs show response examples. |
| 17. Unit-test fixtures from public examples? | **PUBLICLY CONFIRMED for public example snippets / UNCLEAR for live responses**. |
| 18. Development risk | High for first v11.1 adapter because title matching/outlier filtering are non-trivial and source is not Pokémon-structured. |
| 19. Commercial/legal risk | Medium/high due scraping/provider terms, paid quota, and cache ambiguity. |
| 20. Recommendation | **B/C. Need provider terms/key before coding**. Valuable later for sold-comps evidence, but not the first structured second-source adapter. |

## Decision table

| Provider | Access now? | Useful distinct data? | Caching clear? | Commercial use clear? | Safe to implement now? | Reason |
|---|---|---|---|---|---|---|
| JustTCG | No — API key/subscription required | Yes, likely condition/variant structured pricing distinct from TCGdex | No | Partly; business use tier-dependent, free tier not commercial | No | Best target, but caching/fixtures/plan/display and price-bucket semantics need confirmation. |
| PokéWallet | No — key required for useful endpoints | Maybe; structured TCGPlayer/CardMarket data, but overlaps TCGdex | No | Yes, terms allow personal/commercial subject to terms | No | Good fallback, but cache/fixtures, exact payloads, and independence need confirmation. |
| Cardmarket direct | No — restricted, applications not accepted | Yes, direct EU marketplace | No | No; prior written agreement appears needed to present prices | No | Blocked by restricted access and legal/commercial constraints. |
| RapidAPI CardMarket/Pokémon APIs | No — RapidAPI key/subscription required | Yes, includes country pricing and some graded eBay data | No | Unclear | No | Rich but provider/RapidAPI terms and cache rights unclear. |
| TCGplayer direct | No — partner/API access required | Limited; overlaps TCGdex TCGPlayer feed | No | Unclear/restrictive | No | API terms and combining/caching/display rights require contact. |
| eBay Browse API | No — OAuth/app required | Low for v11.1; active listings only | Partial/local caching mentioned, retention unclear | Terms-gated | No | Not sold-comps; title matching weak; license review needed. |
| eBay sold providers | No — key/token/paid plan required | Yes, actual sold comps | No | Partly marketed for commercial use, terms unclear | No | Useful later, but not structured identity; cache/terms and noisy matching need work. |

## Public research decision

Strict decision: **B. Need provider contact before coding** for JustTCG, and **C. Need account/key before coding** for any authenticated source.

No candidate meets the “safe to implement now” bar from public docs alone.

Why none qualify as safe now:

- No candidate is both accessible now and clearly approved for SaveRoom's intended caching/provenance/commercial use.
- JustTCG has the best public technical fit, but free-tier commercial use is prohibited and raw-response caching/fixture retention is unclear.
- PokéWallet has clearer public commercial-use language, but useful endpoints require a key and caching/fixture terms remain unclear.
- Cardmarket direct is explicitly blocked/restricted for new access and needs prior written agreement for price presentation.
- eBay Browse is not a sold-price source.
- eBay sold providers provide distinct sold data but are provider/scrape products with paid access, cache ambiguity, and weak Pokémon identity matching.

## Best next step

Send the JustTCG access request draft, now updated by public research priorities:

1. Ask what paid tier permits SaveRoom's intended business use.
2. Ask explicitly about raw-response caching and fixture storage.
3. Ask whether normalized observations/aggregates may be stored permanently.
4. Ask whether source-derived prices can be shown in internal and future customer-facing UI.
5. Ask for documentation of price type semantics: sold vs active vs market vs guide.

If JustTCG cannot confirm these, next fallback is PokéWallet because its public terms explicitly allow personal or commercial use subject to terms, but it still needs cache/fixture and sample-payload confirmation.

## Links

- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_1_JUSTTCG_ACCESS_REQUEST_DRAFT.md`
- Related: `docs/V11_1_PREFLIGHT.md`
