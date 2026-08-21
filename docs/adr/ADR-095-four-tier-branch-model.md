---
id: ADR-095
title: Four-tier branch model with protected, CI-gated merges
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-29
substrate: []
implements: []
related:
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
supersedes:
  - maistro-engine#ADR-001
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Accepted
    date: 2026-05-29
---

# ADR-095: Four-tier branch model with protected, CI-gated merges

## Context

ADR-001 established `main < integration` with `integration` as the default PR base and `main` taking periodic sync PRs. As the repo consolidated into a single monorepo (see `docs/archive/CONSOLIDATION-PLAN.md`) and shifted to high-volume AI-assisted change, we want a clearer separation between *active feature integration* and *stabilized QA*, plus enforced (not just conventional) protection so nothing reaches `main` un-reviewed or un-tested.

## Decision

Adopt a **four-tier** branch hierarchy. Work flows **upward**; each promotion is a pull request, never a direct push:

```
feat/* bug/* idea/* doc/* chore/*   →  develop  →  integration  →  main
        (topic branches)               (active     (stabilized    (release-
                                         dev tier)   QA tier)       grade)
```

- **Topic branches** (`feat/*`, `bug/*`, `idea/*`, `doc/*`, `chore/*`, `fix/*`) — branch off `develop`; PR into `develop`.
- **`develop`** — active integration of feature work. PR-gated, 0 required approvals.
- **`integration`** — stabilized QA tier; receives PRs from `develop`. PR-gated, 0 required approvals.
- **`main`** — release-grade; receives PRs from `integration` only. PR-gated, **1 required approval**.

### Branch protection (enforced via GitHub, not convention)

| Branch | PR required | Approvals | Linear history | Force-push | Deletion | Required CI checks |
|--------|:-----------:|:---------:|:--------------:|:----------:|:--------:|--------------------|
| `main` | yes | **1** | yes | no | no | added per-check as CI goes green |
| `integration` | yes | 0 | yes | no | no | added per-check as CI goes green |
| `develop` | yes | 0 | yes | no | no | added per-check as CI goes green |

- **Linear history** is required on all three → merges are **squash or rebase**, not merge commits.
- **Admins are not enforced** (`enforce_admins=false`) so a solo maintainer/agent isn't deadlocked, but the gates still block accidental direct pushes and unreviewed `main` merges.
- **Required status checks** are added incrementally: a CI job becomes a required gate only once it is reliably green (the repo is mid-cleanup toward green `lint-and-type-check` + `test`). This avoids a deadlock where a red pre-existing check blocks all merges.

## Acceptance criteria

- [x] `develop`, `integration`, `main` exist at origin.
- [x] All three are protected: PR required, no force-push, no deletion, linear history.
- [x] `main` requires 1 approving review; `develop`/`integration` require 0.
- [ ] Required status checks (`lint-and-type-check`, `test`) added to each branch once green.
      *(Verifiable only in GitHub branch-protection settings, not from the tree — left unchecked
      until confirmed there. C3/#288.)*
- [x] CONTRIBUTING documents the flow; topic branches base off `develop`.
      ([`CONTRIBUTING.md` §Branch model](../../CONTRIBUTING.md#branch-model) — the four-tier
      diagram, the "branch off `develop`, PR into `develop`" rule for every topic prefix, the
      per-branch approval counts, and the squash/rebase consequence of linear history.)

### Workflow branch-filter coverage (audited C3/#288, 2026-08-01)

Every workflow that filters by branch includes `integration`; the rest are not branch-triggered.
`registry.yml`'s `develop` gap noted in the v1 plan is already closed, and the stale
`research/pm-fleet-poc` filter it mentioned is gone.

| Workflow | `push` branches | `pull_request` branches | `integration` covered |
|---|---|---|:--:|
| `ci.yml` | `main, integration, develop, merge/main-into-integration` | `main, integration, develop` | yes |
| `quality.yml` | `main, integration, develop, feat/*` | `main, integration, develop` | yes |
| `security.yml` | `main, integration, develop, feat/*` (+ nightly) | `main, integration, develop` | yes |
| `registry.yml` | `main, integration, develop` | *(unfiltered, path-scoped)* | yes |
| `formal-conformance.yml` | `main, integration, develop` | *(unfiltered)* | yes |
| `mutation.yml` | — | `main, integration, develop` (path-scoped, + nightly) | yes |
| `cage-guard.yml` | — | *(unfiltered, path-scoped)* | yes |
| `formal-conformance-nightly.yml` | — | — | n/a (schedule) |
| `release-installer.yml` | tags `v*` | — | n/a (tag/dispatch) |
| `rsi-harvest.yml` | — | — | n/a (dispatch) |

## Consequences

- Feature work no longer bases off `integration` directly (the ADR-001 default) — it bases off `develop`.
- Because linear history is enforced, PRs merge via squash/rebase; the merge-commit workflow used during the consolidation is retired.
- `research/<tranche>` staging branches (ADR-001) are superseded by `develop` as the single active-integration tier.

## Source references

- Supersedes ADR-001 (integration-as-default-base).
- `docs/archive/CONSOLIDATION-PLAN.md` — monorepo consolidation context.
- ADR-031 (front-matter/registry), ADR-032 (contracts as acceptance criteria) — CI gates that will become required checks.
