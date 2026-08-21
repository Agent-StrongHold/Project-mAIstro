---
id: SPEC-231
title: "Four-tier branch model: develop / integration / main with CI wiring"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-095
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests:
  - .github/workflows/ci.yml
  - .github/workflows/registry.yml
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-231: Four-tier branch model

## Context

ADR-095 establishes `feat/* -> develop -> integration -> main` with GitHub branch
protection enforced (not just conventional) and `main` requiring one approval. This
SPEC documents how that decision is actually realized in the repo's process docs and
CI wiring. Branch protection itself is configured in GitHub settings (not code), so
"implemented" here means: documented, and the CI workflows are wired to the three
branch names as the model requires.

## Goals

- Document where the branch model is written down for contributors.
- Document the concrete CI trigger wiring tied to `main`/`integration`/`develop`.
- Flag the one broken cross-reference found during this audit.

## Non-goals

- Re-implementing or automating branch-protection setup via the GitHub API (no such
  tooling exists today; see Open questions).
- Verifying GitHub's live branch-protection settings (those are configured outside
  this repo's source and were not independently re-verified by this SPEC).

## Decision

`CONTRIBUTING.md` (lines 8-23) documents the model explicitly: topic branches
(`feat/*`, `bug/*`, `idea/*`, `doc/*`, `chore/*`, `fix/*`) base off and PR into
`develop`; `develop` PRs into `integration`; `integration` PRs into `main`; the
protection table (PR required, approvals, linear history, no force-push, no deletion)
matches ADR-095's decision section.

CI wiring confirms the three-branch model is live infrastructure, not just
documentation:

- `.github/workflows/ci.yml` triggers on
  `branches: [main, integration, develop, merge/main-into-integration]`.
- `.github/workflows/registry.yml` triggers on `integration`.

Linear history (squash/rebase merges only) is the enforced merge strategy per the
ADR; no merge-commit workflow remains in the documented process.

## Acceptance criteria

- [x] `develop`, `integration`, `main` tier structure is documented in `CONTRIBUTING.md`
- [x] Branch protection table (PR required, approvals, linear history, no force-push/deletion) is documented matching ADR-095
- [x] CI (`ci.yml`) triggers on all three tier branches
- [x] CI (`registry.yml`) triggers on `integration`
- [ ] `develop` and `integration` branches were independently confirmed to exist at origin during this audit (only `main` and the current working branch were visible in the local clone's `git branch -a`; this may be a shallow-clone artifact rather than a real absence — needs confirming against the GitHub remote directly)
- [ ] `CONTRIBUTING.md`'s ADR link is corrected (`docs/adr/ADR-060-four-tier-branch-model.md` is a broken/stale reference — that path is actually `ADR-060-persona-as-seed-and-eval-protocol.md`; the real branch-model ADR is `docs/adr/ADR-095-four-tier-branch-model.md`)
- [ ] No tooling automates branch-protection configuration via the GitHub API — currently manual

## Testing

Not applicable in the unit/integration-test sense — this is process/CI-config
documentation. Verification is via the CI trigger configuration itself
(`.github/workflows/ci.yml`, `.github/workflows/registry.yml`) and `CONTRIBUTING.md`.

## Open questions

- Should `CONTRIBUTING.md:23`'s broken link to `ADR-060-four-tier-branch-model.md` be
  fixed to point at `ADR-095-four-tier-branch-model.md`? (Flagged here; fix is a
  one-line doc change outside this SPEC's no-code-changes scope.)
- Should branch-protection configuration be codified (e.g. via `gh api` in a setup
  script under `tools/` or `scripts/`) so it's reproducible/auditable rather than
  manual?
- Required status checks (`lint-and-type-check`, `test`) are called out in ADR-095 as
  "added incrementally" — track separately whether they have since been added as
  required gates on each branch.

## References

- `CONTRIBUTING.md`
- `.github/workflows/ci.yml`
- `.github/workflows/registry.yml`
- `docs/adr/ADR-095-four-tier-branch-model.md`
- `docs/adr/ADR-001` (superseded)
