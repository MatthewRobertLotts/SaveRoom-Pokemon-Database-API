# v12.0.0 Post-Release State

## Release identity

- Release name: v12.0.0 app readiness API foundation
- Release tag: `v12.0.0`
- Merge commit: `aee25bb793676f445d2b3b8e3f9a62212a989588`
- Merge commit summary: `aee25bb Merge v12 app readiness release candidate`
- Current stable branch: `main`

## Verification checkpoint

- Full suite after merge: `875 passed, 1 skipped, 19 warnings in 407.02s`
- `origin/main` after release: `aee25bb793676f445d2b3b8e3f9a62212a989588`
- Tag pushed: `origin/v12.0.0`

## What v12.0.0 contains

v12.0.0 is the stable app-readiness API foundation. It includes:

- canonical card detail
- batch app-ready detail
- chart-ready price history
- UK-primary pricing recommendation
- deterministic listing assistant
- local listing drafts
- inventory-to-draft bridge
- draft ready/reservation workflow
- explicit local sale completion
- local sales read/list API
- JustTCG exposure policy guard
- release-candidate audit

## Safety boundaries

These boundaries remain active after the release:

- Do not run live provider calls without explicit approval.
- Do not spend API credits.
- Do not call `_get_justtcg_price_data()` without explicit approval for a live provider test.
- Do not call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs during planning-only work.
- Do not publish listings.
- Do not ask for, print, or commit API keys.
- Do not commit `.env`, `.env.local`, `private_provider_payloads/`, raw provider JSON, sanitized candidates, API keys, headers, or account metadata.

## Intentionally untracked files

The following unrelated files were intentionally left untracked after the v12.0.0 release and should not be committed unless Matthew explicitly asks:

```text
docs/SAVEROOM_POKEMON_CARD_DATABASE_PROJECT_REPORT_V1130.md
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.drawio
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.url.txt
```

## Recommended versioning policy

- Use `v12.0.1` only for bugfixes, documentation fixes, and polish on the released v12.0.0 foundation.
- Use `v12.1` for the next approved feature batch.
- Do not create or start v13 unless Matthew explicitly approves it.
- Do not add more features directly to `v12.0.0` or `main`.
- Use `v12.1-next` only as a planning branch until Matthew approves the first v12.1 implementation milestone.
