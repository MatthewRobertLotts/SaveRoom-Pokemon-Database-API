# v11.1 JustTCG Access Request Draft

Tags: #type/project #status/needs-review

Status: DRAFT
Date: 2026-06-27
Branch: v11.1-market-evidence-next

## Overview

Short draft Matthew can send to JustTCG to request access and terms clarification before SaveRoom builds a second-source pricing evidence integration. This draft does not include secrets or private contact details.

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

## Notes for Matthew

- Do not include an API key in the message.
- Do not include phone number or private address details.
- If JustTCG replies with terms, save the response outside Git first and summarize the allowed/blocked points before asking Hermes to code.
- If they approve fixture saving, collect only the smallest representative payload set needed for adapter tests.

## Links

- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_1_PREFLIGHT.md`
