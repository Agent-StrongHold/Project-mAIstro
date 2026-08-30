---
id: ADR-082526-3011
title: "The setup-uv release is the flake fix; the uv pin is determinism. Both live in one wrapper"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_check_uv_setup.py
ac-modules:
  AC-1: '@tool/check-uv-setup'
  AC-2: '@tool/check-uv-setup'
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-3011: The setup-uv release is the flake fix; the uv pin is determinism. Both live in one wrapper

## Context

`exact-debt-ledger` failed on #181 without running a single test:

```
Could not determine uv version from uv.toml or pyproject.toml. Falling back to latest.
Fetching version data from https://raw.githubusercontent.com/astral-sh/versions/main/v1/uv.ndjson ...
##[error]fetch failed
```

The commit under test removed a duplicated row from a markdown table. Nothing
about it can affect `astral-sh/setup-uv`'s ability to reach GitHub's raw CDN.

#213 asked whether pinning the uv version avoids that fetch, and could not
test it from a workstation. **It does not, and this record exists partly to
stop that assumption being made a third time.** The first version of this
change asserted it — from a summarised reading of the action's resolver rather
than from behaviour — and the PR's own CI disproved it within minutes.

Three measurements, all on PR #264 against this repository:

| action | `version` | result |
|---|---|---|
| `@v7` | `0.12.5` (exact) | `Fetching version data from raw.githubusercontent.com …`, installs |
| `@v7` | `latest-known` | fetches, then `##[error]No version found for latest-known` |
| `@v10.0.1` | `0.12.5` (exact) | `Fetching manifest data from raw.githubusercontent.com …`, installs |

The manifest request is **unconditional**. No value of `version` avoids it, in
any release tested. What differs between releases is whether a transient
failure of it is fatal: `v10.0.1` ships as *"Tolerate transient manifest
timeouts"*. `v7` — where this repository sat — has no such tolerance, and that
is precisely what killed #181.

Two further measured facts, both of which #213 got wrong or could not check:

- **`0.5.x` resolved to uv 0.5.31** while every unpinned job resolved `latest`
  to **uv 0.12.5**. Three gate jobs ran a uv seven minor releases behind the
  other seventeen, and nothing said so.
- **#213's suspicion that a 0.5-era uv cannot read a `revision = 3` lock does
  not hold.** uv 0.5.31 was downloaded and run against this repository's
  `uv.lock`: `uv lock --check` resolves 239 packages and exits 0. The `0.5.x`
  pin was not broken. It was *ineffective*, which is worse in one way — it
  looked like the fix for the flake it did not fix.
- **The action has no floating major above `v7`.** `git ls-remote --tags`
  shows point releases through v10.0.1 but floating majors stopping at v7, so
  `@v10` does not resolve; the newest must be pinned by full tag.

#213's inventory had also drifted: it records 11 unpinned of 13 usages; the
tree had **17 unpinned of 20**.

## Decision

Every workflow gets uv through one local composite action,
`.github/actions/setup-uv`, which pins **two** things for **two different
reasons**. No workflow references `astral-sh/setup-uv` directly, and a gate
enforces all of it.

**1. The action release — `astral-sh/setup-uv@v10.0.1`. This is the #213 fix.**
It is the release that tolerates a transient manifest outage. Since the fetch
cannot be avoided, tolerating its failure is the only lever available. Pinned
by full tag because no floating major above v7 exists to track.

**2. The uv version — exactly `0.12.5`. This is not the #213 fix and must not
be presented as one.** It buys determinism: one uv for the whole repository
instead of the 0.5.31/0.12.5 split. 0.12.5 is what seventeen of twenty jobs
already ran green, so only the three `quality.yml` jobs move.

**One place**, because "the version every workflow installs is stated somewhere
reviewable" is not met by the same literal copied twenty times. **Enforced**,
because #213 says a mix of pinned and floating usages means the flake merely
gets rarer and harder to attribute.

`required-version` in `pyproject.toml` was considered and rejected: it is a uv
*setting*, so pinning it exactly makes uv refuse to run for every contributor
not on that exact build — a real cost on local development to fix a CI problem.
Retrying the action is out of scope per #213, and would in any case be the
thing v10.0.1 already does internally.

## Consequences

### Positive
- A transient `raw.githubusercontent.com` outage is tolerated by the action
  rather than failing the job, on all twenty usages at once.
- One line states the uv version for the whole repository, and one states the
  action release; a gate keeps both true.
- The 0.5.31/0.12.5 split closes, so a result from one job means the same thing
  as a result from another.

### Negative / Trade-offs
- **The central claim is weaker than it looks, and is recorded as such.** That
  v10.0.1 tolerates the outage is its release's stated purpose, not something
  measured here — simulating a CDN outage in CI is not available. What *is*
  measured is that the fetch still happens. Anyone revisiting this should treat
  the tolerance as documented-but-unverified.
- Three major releases of the action are skipped at once (v7 → v10.0.1),
  including v10.0.0's "Disable automatic caching for sensitive events". CI
  exercises all twenty usages, but this is a real jump.
- Both pins go stale by construction, and nothing here updates them.
- A composite action is indirection: a reader of `ci.yml` no longer sees which
  uv is installed without opening one more file.

### Neutral
- The three `quality.yml` jobs change uv version (0.5.31 → 0.12.5). Their locks
  are consumed with `--locked`, so no resolution changes.
- The manifest fetch itself remains, for every job. Removing it would mean not
  using `setup-uv` at all, which trades the flake for hand-rolled installation
  and the loss of its caching. Not judged worth it, but it is the lever left if
  the tolerance proves insufficient.

## Acceptance criteria

- [x] **AC-1** The wrapper pins the action release that tolerates a transient
  manifest outage, and pins an **exact** uv version. Dropping to an older
  release, to a floating major that does not resolve, or to a non-exact uv
  version all fail the build. These are two guards, not one: the release is the
  flake fix, the exact version is determinism, and the manifest is fetched
  either way.
- [x] **AC-2** No workflow calls `astral-sh/setup-uv` directly. Every step that
  installs uv goes through `.github/actions/setup-uv`, so both pins are stated
  once for the whole repository and a later PR cannot quietly reintroduce a
  direct, unpinned call for one job.
