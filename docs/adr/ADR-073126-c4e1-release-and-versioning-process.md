---
id: ADR-073126-c4e1
title: "Release and versioning process: lockstep tags, single publish path"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-07-31
created: 2026-07-31
substrate: []
implements: []
related:
  - maistro-engine#ADR-095
  - maistro-engine#ADR-076
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-31
  - status: Accepted
    date: 2026-07-31
---

# ADR-073126-c4e1: Release and versioning process

**Status:** Accepted
**Date:** 2026-07-31

Extends [ADR-095](ADR-095-four-tier-branch-model.md) past `main`. ADR-095 defines
how code *reaches* `main`; it says nothing about how a release is cut from it,
versioned, tagged, or published. This fills that gap.

## Context

At the time of writing the repository has **zero git tags**, no release
workflow, and no publish path. `deploy.sh` pushes images by git SHA. Installers
clone a branch. Nothing has ever been published to PyPI. "Install v1.0.0" is not
an expressible request.

That is the gap this decision closes. It is a decision record, not a completion
record — see **Implementation status** below for what actually exists today.

## Decision

### 1. Versioning is lockstep across the monorepo

Every published package carries the **same** version, sourced from the root
`VERSION` file. There are no independent per-package version lines.

The cost is real and accepted: a package with no changes still gets a version
bump when a sibling changes. The benefit is that `maistro-rsi==1.0.0` resolves
`maistro-core`/`maistro-evolve`/`maistro-bootstrap` at exactly `1.0.0`, with no
compatibility matrix for anyone — maintainer or consumer — to reason about.
For a monorepo released as a unit by a single maintainer, that trade is worth it.

Inter-package dependency bounds are `>=X.0.0,<X+1` and are maintained by the
version-bump tooling, not by hand.

### 2. Tags are annotated, `vX.Y.Z`, and live on `main` only

- A **final** release tag `vX.Y.Z` may only point at a commit on `main`.
- A **release candidate** tag `vX.Y.Z-rcN` is the sole exception: it may point
  at a commit on `integration`, so a candidate can be soaked before promotion.
- Tags are **annotated** (`git tag -a`), never lightweight — the tag object
  carries the tagger and date that release provenance depends on.
- Tags are immutable. A bad release is superseded by a higher version, never by
  moving or deleting a tag.

**Package versions do not carry the rc suffix.** At `v1.0.0-rc1`, every package
reads `1.0.0`; the candidate-ness lives only in the tag. This keeps rc artifacts
byte-comparable with the final ones they become.

### 3. `release.yml` is the only publish path

Publishing — to PyPI or to the container registry — happens **only** via the
tag-triggered `release.yml` workflow. No local `twine upload`, no manual
`docker push`, no `deploy.sh` publishing to a release tag.

The workflow guards before it builds: the tag's commit must be an ancestor of
`main` (or `integration` for an rc), and the tag version must equal the root
`VERSION` and every package version exactly — with the rc suffix stripped for
comparison.

Publication to PyPI uses **trusted publishing (OIDC)**, not a long-lived API
token. Registering the trusted publisher on PyPI is one-time maintainer setup
and cannot be automated from inside this repository.

### 4. The `release` environment approval is the publish gate

The publish jobs run in a GitHub `release` environment carrying a required
reviewer. Everything before that point — guard, build, `twine check`, clean-venv
install smoke test — runs unattended. The human decision is *"publish these
verified artifacts"*, not *"is the build OK"*.

This is the one gate deliberately not automated. Publishing to PyPI is
irreversible: a version number, once taken, can never be reused even after
yanking.

### 5. Hotfix path

1. Branch from the **tag**, not from `main` (`git switch -c hotfix/x.y.z+1 vX.Y.Z`).
2. Fix, with a regression test.
3. PR into `main`.
4. Tag `vX.Y.Z+1` on `main`; `release.yml` publishes.
5. **Back-merge `main` into `develop`** so the fix is not lost on the next
   release cut.

Step 5 is the one that gets skipped under pressure and silently reintroduces the
bug in the next minor. It is part of the hotfix, not follow-up work.

### 6. Release-candidate conventions

- `rcN` starts at `rc1` and increments; no `rc0`.
- An rc is cut from `integration` and soaked. Any fix goes to `develop` →
  `integration` and gets a **new** rc number; an rc tag is never moved.
- Promotion to final is a merge of `integration` into `main` plus a `vX.Y.Z`
  tag. The final release ships the artifacts the last rc already validated.

## Consequences

- Cutting a release requires no local credentials — the workflow holds them.
- Provenance is answerable from the tag alone.
- A single-maintainer repo can still enforce a two-step publish, because the
  environment approval is a distinct action from the merge.
- **The lockstep cost is real:** unchanged packages get version bumps. Accepted
  deliberately over per-package versioning.
- **`main` becomes load-bearing for releases.** Its protection rules are now a
  release control, not just a code-review control.

## Implementation status (2026-07-31)

This ADR is `Accepted` as a **decision**. Most of the mechanism does not exist
yet, and this section is the honest inventory:

| Element | State |
|---|---|
| Lockstep versioning from root `VERSION` | Exists (E1, #317) |
| Inter-package bounds `>=X.0.0,<X+1` | **Not yet** — every package is at `0.9.0`, so a `>=1.0.0` floor is unsatisfiable today. Lands with the E1 bump (see #295) |
| Third-party dependency caps | Exists (#334) |
| `release.yml` | Exists (E3, #296) — **never executed**: no tag has been pushed, so it is statically verified only |
| PyPI trusted publisher | **Not registered** — maintainer-only setup (#296) |
| `release` environment + reviewer | **Not configured** (#296). Until it is, `release.yml`'s publish jobs run *ungated* |
| Annotated tags on `main` | **No tags exist at all** (the guard rejects lightweight tags when they do) |
| Installers pinned to tags | Exists (E5, #298). With no release published, the default install warns and falls back to `main` |

## Relationship to `main`'s protection

§2 makes `main` the only branch a final release tag may point at, and §3 makes
`release.yml` the only publisher. Together those move `main`'s branch protection
from a code-review control to a **release** control: the 1-approval requirement
ADR-095 places on `main` is now also what stands between a change and a
published artifact.

That is the intended design — the `release` environment approval in §4 is a
second, independent gate, not a substitute for the first. Anything that weakens
`main`'s protection weakens the release process by the same amount, and should
be evaluated on those terms.

## References

- [ADR-095: Four-tier branch model](ADR-095-four-tier-branch-model.md) — supersedes
  ADR-001 and is the branch model this extends
- [ADR-076: HTTP API versioning](ADR-076-http-api-versioning.md) — the API
  version axis is independent of the package version axis defined here
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — the topic-branch → `develop` →
  `integration` → `main` flow in operational terms
