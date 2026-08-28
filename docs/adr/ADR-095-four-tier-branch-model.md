---
id: ADR-095
title: Protected develop-to-main promotion model
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
  - status: Accepted
    date: 2026-08-27
---

# ADR-095: Protected develop-to-main promotion model

## Context

The original decision introduced an `integration` stabilization tier between
`develop` and `main`. The live repository no longer has that branch, and the
actual operating model has converged on one active integration branch plus a
release/promotion branch. M0 #162 also moved the enforcement mechanism from a
planned classic-protection application to live GitHub repository Rulesets.

The decision must describe the merge boundary that actually exists rather than
preserve a historical tier that nobody uses.

## Decision

Work flows:

```text
topic branches -> develop -> main
```

- **Topic branches** branch from `develop` and return by pull request.
- **`develop`** is the canonical active integration branch. It requires a pull
  request, zero approvals, strict required checks, conversation resolution,
  stale-review dismissal, no deletion or non-fast-forward update, restricted
  creation, and linear history. Squash/rebase are the normal merge methods.
- **`main`** is the release/promotion ledger. Ordinary releases are a single
  `develop -> main` pull request. It requires one approval, strict required
  checks including the main-only CodeQL/container checks, conversation
  resolution, stale-review dismissal, no deletion or non-fast-forward update,
  and restricted creation.
- **`main` intentionally permits merge commits and does not require linear
  history.** The merge commit is an explicit release/promotion marker. Detailed
  development history remains linear on `develop` because feature work was
  already squash/rebase integrated there.
- **`integration` is retired.** Reintroducing a stabilization tier is a new
  governance decision, not an implicit resurrection of this ADR's old shape.

## Live enforcement

Repository Rulesets are the merge boundary. The reviewable source of truth is
`.github/branch-protection.json`; its `ruleset` sections record Ruleset-only
semantics such as targets, allowed merge methods, `gates-ran`, and bypass mode.

Both live branches require the ordinary PR gate set plus:

- `autonomous-merge-admissibility` — base-trusted policy that prevents an
  ordinary PR-authoring agent from weakening the judge that decides whether the
  same candidate may merge;
- `gates-ran` — verifies that required workflow families actually ran for the
  PR head rather than treating absence as success.

`main` additionally requires the three CodeQL analysis checks and
`Container scan + SBOM + cosign`.

### Bypass policy

- `develop`: organization administrators / repository admin role may use the
  administrative bypass. This is the independent/manual path for trusted-policy
  and other deliberately non-autonomous changes.
- `main`: administrator bypass is **pull-request-only**. There is no ordinary
  direct-update path; releases still travel through a PR even when an
  administrator must exercise emergency authority.

Repository auto-merge may remain enabled because the live required checks are
now load-bearing.

## Acceptance criteria

- [x] `develop` and `main` exist and are covered by active repository Rulesets.
- [x] `integration` is absent and explicitly retired from the active topology.
- [x] `develop` requires strict checks, zero approvals, conversation resolution,
      stale-review dismissal, linear history, and blocks deletion/non-fast-forward updates.
- [x] `main` requires strict checks, one approval, conversation resolution,
      stale-review dismissal, and blocks deletion/non-fast-forward updates.
- [x] `main` permits release merge commits and intentionally omits linear-history enforcement.
- [x] `autonomous-merge-admissibility` and `gates-ran` are required live.
- [x] Main-only CodeQL/container checks are required on `main`, not `develop`.
- [x] The live rules can be reconstructed from the checked-in policy artifact.

## Consequences

- There is one canonical development integration point: `develop`.
- `main` history is a sequence of explicit promotions, while detailed change
  history remains on `develop`.
- A trusted-policy change may deliberately fail the autonomous judge and still
  be merged through the administrator/manual path; that is separation of
  authority, not a gate failure to baseline away.
- Adding another persistent promotion branch requires an explicit ADR change and
  matching merge-boundary rules.
