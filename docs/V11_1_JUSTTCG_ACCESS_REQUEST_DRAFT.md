# v11.1 JustTCG Access Request Draft

Tags: #type/project #status/needs-review

Status: DRAFT
Date: 2026-06-27
Branch: v11.1-market-evidence-next

## Overview

Short draft Matthew can send to JustTCG to request access and terms clarification before SaveRoom builds a second-source pricing evidence integration. This draft does not include secrets or private contact details.

> **Strategy note (2026-06-28):** JustTCG is a **supporting/fallback provider** in the corrected UK-first external pricing strategy. It is **not** the core UK pricing source. UK-first pricing intelligence is anchored on UK sold/completed market evidence (eBay UK as the planned primary source). JustTCG's role is USD external market/current pricing, trend/sanity checks, thin-market support, and identifier mapping. See `docs/V12_PRICING_STRATEGY_CORRECTION.md` for the full correction.

## Message Draft

Subject: JustTCG API access and terms clarification for Pokémon pricing evidence project

Hi JustTCG team,

I'm Matthew, a UK-based small business owner/developer building SaveRoom, a Pokémon TCG inventory and pricing evidence platform.

I’m currently evaluating a second structured pricing source for a private/internal Pokémon card pricing tool, with the possibility of later using the same evidence layer in a paid product/API. The goal is provenance and confidence scoring: storing where a price came from, what kind of price it is, and how it compares with other sources. I am not trying to scrape your service, resell raw JustTCG data, or bypass your terms.

Before I build anything against the API, could you confirm whether JustTCG is suitable for this use case and what plan/key I should use for development?

The specific points I need to confirm are:

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

For development, I would like to test a small representative set of Pokémon cards covering modern, vintage, promo, English and non-English rows, holo/reverse/unknown finish, and high/low value cards. If fixture saving is allowed, I would use a small number of anonymized/sanitized JSON responses for private unit tests and would not include API keys, account details, or quota metadata.

Could you also point me to the right development key/plan for this kind of backend integration, including any pricing or credit details I should be aware of?

Thanks — I want to make sure SaveRoom uses JustTCG in a compliant way before writing the integration.

Best,
Matthew

## JustTCG Pricing Plans (observed 2026-06-28)

| Plan | Price | Monthly Requests | Daily Requests | Rate Limit | Cards/Request | Support |
|---|---|---|---|---|---|---|
| **Free Tier** | $0 | 1,000 | 100 | 10/min | 20 | Basic |
| **Starter** | $19/mo | 10,000 | 1,000 | 50/min | 100 | Basic |
| **Professional** | $49/mo | 50,000 | 5,000 | 100/min | 100 | Priority |
| **Enterprise** | $149/mo | 500,000 | 50,000 | 500/min | 200 | Highest priority |

### Plan notes
- Free tier is active but has no API key configured yet
- All plans support all TCGs (not just Pokémon)
- Starter ($19/mo) is likely the minimum viable plan for development + early production
- Professional ($49/mo) recommended if SaveRoom launches a paid product
- Enterprise has custom integration support and priority request routing

### Recommended plan for SaveRoom
**Starter ($19/mo)** for initial development and testing. Upgrade to Professional ($49/mo) if/when launching a customer-facing product with meaningful traffic.

## Notes for Matthew

- Do not include an API key in the message.
- Do not include phone number or private address details.
- If JustTCG replies with terms, save the response outside Git first and summarize the allowed/blocked points before asking Hermes to code.
- If they approve fixture saving, collect only the smallest representative payload set needed for adapter tests.
- The Free Tier (1K/mo) may be sufficient for initial development but will need upgrading for production use.
- Consider starting with Starter ($19/mo) for comfortable development headroom.

## Links

- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_1_PREFLIGHT.md`
