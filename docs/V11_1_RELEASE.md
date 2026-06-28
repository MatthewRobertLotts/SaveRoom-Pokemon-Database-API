# v11.1.0-rc — Source-Neutral Comparison Foundation

Tags: #type/project #status/release-candidate

Status: RELEASE_CANDIDATE (not merged, not tagged)
Date: 2026-06-28
Branch: v11.1-market-evidence-next
Previous release: v11.0.0 (tag `v11.0.0`, commit `384426c`)

## Summary

v11.1 adds the **infrastructure** to compare multiple pricing evidence sources, plus a read-only comparison API and a minimal admin UI panel. It does **not** add a live second provider — real cross-source pricing awaits approved second-source access.

## What's New

### Source-Neutral Comparison Module

**File:** `pricing_sources/comparison.py`

Provider-agnostic comparison of aggregate evidence buckets. Compares medians across sources with conservative bands:
- **AGREE**: medians within 15%
- **MINOR_DISAGREEMENT**: medians differ by >15–35%
- **MAJOR_DISAGREEMENT**: medians differ by >35%

Strict guards prevent comparing incompatible buckets (different currencies, listing types, finishes, conditions). Confidence is never raised from a single source.

### Read-Only Comparison API

**Endpoint:** `GET /api/v1/prices/comparison/{target_type}/{target_id}`

Reads existing `v11_price_observations`, computes per-source aggregate buckets, and returns comparison results. Returns `INSUFFICIENT_EVIDENCE` when only one source exists. Never fetches from external providers.

### Minimal Comparison UI Panel

**Files:** `pokemon_db_v2_browser_ui/index.html`, `app.js`, `styles.css`

A small section under the existing v11 Pricing Evidence panel. Users enter a target ID and click "Compare sources" to view cross-source agreement/disagreement. Conservative messaging throughout — no pricing certainty claims.

### Source Access Research

- `docs/V11_1_PUBLIC_SOURCE_TERMS_RESEARCH.md` — Public web research on JustTCG, PokéWallet, Cardmarket, TCGplayer, eBay terms
- `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md` — Procurement checklist and JustTCG access request draft
- `docs/V11_1_SECOND_SOURCE_VALIDATION.md` — Candidate validation matrix

### Image Fallback Fix (included on branch)

Commit `97f7bde` repaired browser card image loading fallbacks. This fix is included in the v11.1 branch.

## What's Not Included

- No live second-source adapter (JustTCG, PokéWallet, Cardmarket, eBay)
- No real multi-source pricing
- No FX conversion
- No condition-specific pricing
- No sold-comps integration
- No marketplace sync, POS, scanner, or billing work

## Tests

| Suite | Tests |
|---|---|
| `test_v11_1_cross_source_comparison.py` | 52 |
| `test_v11_1_price_comparison_api.py` | 10 |
| `test_v11_1_comparison_ui_smoke.py` | 14 |
| Existing v11.0 suites | ~155 |
| **Total** | **~231** |

All passing. `compileall` clean. `git diff --check` clean.

## Known Blockers

Real cross-source value requires approved second-source access:
- **JustTCG**: preferred target, awaiting key/terms/caching confirmation
- **PokéWallet**: fallback structured candidate, awaiting cache/fixture permission
- **Cardmarket direct**: not accepting API applications
- **eBay sold comps**: paid/third-party providers, terms review needed

Until a second source's observations are stored, the comparison endpoint returns `INSUFFICIENT_EVIDENCE` for all targets.

## Release Recommendation

v11.1 is ready as a **comparison-foundation release candidate**. The infrastructure is complete and tested. Real multi-source pricing remains blocked by provider access.

**Do not merge to main yet.** Hold until explicit approval to merge/tag.

## Commits in v11.1 (not in v11.0)

```
9053adf ui: add v11.1 source comparison panel
a128816 api: expose v11.1 source comparison endpoint
724e14c pricing: add v11.1 source-neutral comparison logic
32418f0 docs: research public source access terms for v11.1
056c419 docs: prepare v11.1 source access procurement pack
44ac638 docs: add v11.1 second-source validation
97f7bde ui: repair browser card image loading fallbacks
8a85438 fix: prioritize card_key gateway path for image display
```

## Links

- Related: `docs/V11_1_QUALITY_REPORT.md`
- Related: `docs/V11_1_PREFLIGHT.md`
- Related: `docs/V11_1_CROSS_SOURCE_COMPARISON_MODEL.md`
- Related: `docs/V11_1_PRICE_API.md`
- Previous release: `docs/V11_RELEASE.md`
