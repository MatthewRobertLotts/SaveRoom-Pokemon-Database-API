# v11.1 Quality Report — Source-Neutral Comparison Foundation

Tags: #type/project #status/release-candidate

Status: RELEASE_CANDIDATE
Date: 2026-06-28
Branch: v11.1-market-evidence-next
Latest commit: 9053adf

## Overview

v11.1 adds **source-neutral comparison infrastructure** on top of the v11.0 Market Evidence Foundation. It does **not** add a live second provider. Real cross-source pricing value remains blocked until approved second-source access is available.

## What v11.1 Adds

1. **Source-neutral comparison module** (`pricing_sources/comparison.py`)
   - Provider-agnostic bucket comparison
   - Agreement/disagreement bands: AGREE (0–15%), MINOR_DISAGREEMENT (>15–35%), MAJOR_DISAGREEMENT (>35%)
   - Confidence impact calculation
   - Strict bucket compatibility guards (currency, listing_type, finish, condition)

2. **Read-only comparison API** (`GET /api/v1/prices/comparison/{target_type}/{target_id}`)
   - Reads existing stored observations
   - Computes per-source aggregate buckets
   - Returns INSUFFICIENT_EVIDENCE when only one source exists
   - Never fetches from external providers

3. **Minimal comparison UI panel** (browser admin UI)
   - Reuses existing evidence target input
   - Displays summary and comparison rows
   - Conservative messaging, no pricing certainty claims

4. **Source validation and procurement docs**
   - Candidate validation matrix
   - Public web/Tavily research on terms/access
   - Procurement checklist and JustTCG access request draft

5. **Image fallback fix included on branch** (from `97f7bde`)

## What v11.1 Does NOT Add

- No live second-source adapter (JustTCG, PokéWallet, Cardmarket, eBay)
- No real multi-source pricing
- No FX conversion
- No pricing certainty or sale price recommendations
- No marketplace sync, POS, scanner, or billing work
- No changes to v10 canonical identity

## Test Results

| Suite | Tests | Status |
|---|---|---|
| `test_v11_1_cross_source_comparison.py` | 52 | PASS |
| `test_v11_1_price_comparison_api.py` | 10 | PASS |
| `test_v11_1_comparison_ui_smoke.py` | 14 | PASS |
| `test_v11_image_ui_smoke.py` | 25 | PASS |
| `test_v11_admin_ui_smoke.py` | 12 | PASS |
| `test_v11_price_api.py` | 12 | PASS |
| `test_v11_market_evidence_migrations.py` | 14 | PASS |
| `test_v11_price_adapter_framework.py` | 28 | PASS |
| `test_v11_tcgdex_adapter.py` | 22 | PASS |
| `test_v11_price_matching_confidence.py` | 18 | PASS |
| `test_v11_price_aggregation.py` | 24 | PASS |
| **Total v11.x** | **~231** | **PASS** |
| `compileall -q .` | — | PASS |
| `git diff --check` | — | PASS |
| Duplicate script tag check | — | PASS (exactly one `app.js` tag) |

## Known Limitations

- **Single source in production**: Until a second approved provider's observations are stored, the comparison endpoint returns INSUFFICIENT_EVIDENCE for all targets.
- **No FX conversion**: Cross-currency comparison is not performed.
- **No condition-specific matching**: v11.0/11.1 observations do not include TCG grading conditions.
- **No sold-comps data**: Current TCGdex-backed observations are market/active-listing estimates.
- **UI treats all targets as canonical_printing**: No variant/SKU target resolution in the comparison UI yet.

## Provider-Access Blockers

| Provider | Status | Reason |
|---|---|---|
| JustTCG | BLOCKED | API key + terms/caching/commercial-use confirmation required |
| PokéWallet | BLOCKED | API key + caching/fixture permission required |
| Cardmarket direct | BLOCKED | Not accepting API access applications |
| eBay Browse | NOT SUITABLE | Active-listing only, not sold comps |
| eBay sold providers | BLOCKED | Paid access + terms review required |

## Image Fallback Status

Image loading regression was fixed on this branch (`97f7bde`) and verified. No duplicate `app.js` script tags exist.

## Endpoint Status

| Endpoint | Status |
|---|---|
| `GET /api/v1/prices/sources` | IMPLEMENTED (from v11.0) |
| `GET /api/v1/prices/sources/{code}/health` | IMPLEMENTED (from v11.0) |
| `GET /api/v1/prices/observations` | IMPLEMENTED (from v11.0) |
| `GET /api/v1/prices/observations/{id}` | IMPLEMENTED (from v11.0) |
| `GET /api/v1/prices/aggregate/{type}/{id}` | IMPLEMENTED (from v11.0) |
| `POST /api/v1/prices/refresh/{type}/{id}` | IMPLEMENTED (from v11.0) |
| `GET /api/v1/prices/comparison/{type}/{id}` | **NEW in v11.1** |

## Recommendation

v11.1 can be treated as a **comparison-foundation release candidate**. The infrastructure is complete and tested. However, **it is not real multi-source pricing** — that remains blocked until approved second-source access is available.

Do not merge to main until explicit approval. Do not tag until merge is confirmed.

## Links

- Related: `docs/V11_1_RELEASE.md`
- Related: `docs/V11_1_PREFLIGHT.md`
- Related: `docs/V11_1_CROSS_SOURCE_COMPARISON_MODEL.md`
- Related: `docs/V11_1_PUBLIC_SOURCE_TERMS_RESEARCH.md`
- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_1_PRICE_API.md`
