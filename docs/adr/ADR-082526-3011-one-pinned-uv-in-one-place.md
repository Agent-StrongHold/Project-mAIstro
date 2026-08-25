---
id: ADR-082526-3011
title: "One exactly-pinned uv, declared in one place, and workflows may not call setup-uv directly"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-3011: One exactly-pinned uv, declared in one place, and workflows may not call setup-uv directly

## Context

`exact-debt-ledger` failed on #181 without running a single test:

```
Could not determine uv version from uv.toml or pyproject.toml. Falling back to latest.
Fetching version data from https://raw.githubusercontent.com/astral-sh/versions/main/v1/uv.ndjson ...
##[error]fetch failed
```

The commit under test removed a duplicated row from a markdown table. Nothing
about it can affect `astral-sh/setup-uv`'s ability to reach GitHub's raw CDN.
This is the same class as #204: an external fetch on the critical path of a job
that has nothing to do with the network, failing before any test body runs.

#213 raised two questions it could not answer from a workstation. Both are
answerable, and the answers change the fix.

**Does a glob pin avoid the fetch?** No. From `setup-uv`'s own
`src/version/resolve.ts`, `resolveVersion` walks `CONCRETE_VERSION_RESOLVERS`
in order. An exact version is served by the exact resolver, which returns the
parsed specifier without a network call. `latest` and semantic ranges fall
through to the latest and range resolvers, which call `getLatestVersion` and
`getAllVersions` — both of which fetch the manifest. `latest-known` is the one
other early return; it is baked into the action's own release.

So `quality.yml`'s `version: "0.5.x"` is **not protection**. It fetches exactly
like the unpinned jobs, and it is not even a documented input value: the action
documents exact versions, `latest`, `latest-known`, and empty.

**Which version is correct?** Measured against the live manifest: `0.5.x`
resolves to **uv 0.5.31**, and the unpinned jobs' `latest` resolves to **uv
0.12.5**. The repository has therefore been running two uv versions seven
minor releases apart, split across jobs, with nothing saying so.

The suspicion in #213 — that a 0.5-era uv reading a `revision = 3` lock is
wrong — does not hold up, and it is worth recording that it was checked rather
than assumed. uv 0.5.31 was downloaded and run against this repository's
`uv.lock`; `uv lock --check` resolves 239 packages and exits 0. The pin is not
broken. It is *ineffective*, which is worse in one specific way: it looks like
the fix for the flake it does not fix.

The inventory in #213 has also drifted. It records 11 unpinned of 13 usages;
the tree now has **17 unpinned of 20**.

## Decision

Every workflow gets uv through one local composite action,
`.github/actions/setup-uv`, which wraps `astral-sh/setup-uv@v7` at a single
**exact** version. No workflow references `astral-sh/setup-uv` directly, and a
gate enforces that.

- **Exact, not a range.** Proven above to be the only form that skips the
  fetch. `latest-known` also skips it, but ties the version to whichever
  `setup-uv` release is current, which is a version nobody in this repository
  chose.
- **uv 0.12.5**, because seventeen of twenty jobs already run it and are green.
  This moves only the three `quality.yml` jobs, and moves them onto what the
  rest of CI already uses rather than onto a number picked fresh.
- **One place**, because the acceptance criterion "the version every workflow
  installs is stated somewhere reviewable" is not met by the same literal
  copied twenty times. A composite action is the smallest construct that makes
  it exactly one line.
- **Enforced**, because a mix of routed and direct usages means the flake
  merely gets rarer and harder to attribute — which #213 names explicitly.
  Uniformity that is not checked is uniformity until the next PR.

`required-version` in `pyproject.toml` was considered and rejected. The action
does read it, and it would remove the fetch, but `required-version` is a uv
setting: pinning it exactly makes uv refuse to run for every contributor not on
that exact build. That is a real cost imposed on local development to fix a CI
problem.

Retrying the action is out of scope, per #213: a retry hides the dependency
instead of removing it.

## Consequences

### Positive
- No job can fail because `raw.githubusercontent.com` was briefly unreachable
  while installing uv. The request is not made.
- One line states the uv version for the whole repository, and a gate keeps it
  that way.
- The 0.5.31/0.12.5 split closes. Every job runs the same uv, so a result from
  one job means the same thing as a result from another.
- Twenty jobs stop making a network request they never needed, which is a small
  but real saving on every CI run.

### Negative / Trade-offs
- An exact pin goes stale by construction. Nothing here updates it, and
  updating uv becomes a deliberate one-line change with its own CI run. That is
  the intended trade: determinism over currency.
- A composite action is indirection. A reader of `ci.yml` no longer sees which
  uv is installed without opening one more file — mitigated by the gate's error
  message naming that file.
- The three `quality.yml` jobs change uv version (0.5.31 → 0.12.5). Their locks
  are consumed with `--locked`, so no resolution changes, but it is a real
  change to what those gates run.

### Neutral
- `setup-uv` is still pinned by major tag (`@v7`) rather than by commit sha.
  That is the repository's existing convention for actions and is a separate
  question from the version it installs.
- The manifest fetch remains for anyone running the action outside this
  repository; this record governs this repository's workflows only.
