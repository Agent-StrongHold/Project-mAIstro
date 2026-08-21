---
id: ADR-001
title: Branching strategy — integration as default PR base
repo: maistro-engine
kind: adr
status: Superseded
created: 2026-04-26
substrate: []
implements: []
related:
  - maistro-engine#ADR-095
supersedes: []
superseded-by:
  - maistro-engine#ADR-095
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Superseded
    date: 2026-04-26
---

# ADR-001: Branching strategy — integration as default PR base

> **Superseded by [ADR-095](ADR-095-four-tier-branch-model.md) (2026-05-29).** The model is now four-tier — `feat/* → develop → integration → main` — with enforced branch protection and CI gates. The `integration`-as-default-base and `research/<tranche>` staging below are historical.

**Status:** Accepted
**Date:** 2026-04-26
**Tranche:** T0
**Depends on:** —

---

## Context

`maistro-engine` previously had only a `main` branch. The CLAUDE.md engineering rule for this workspace states: never target `main` with PRs without explicit current-turn permission from the user. As porting work begins (Tranches 0–14, 99 ADRs), a stable staging line is needed so that incremental ports can be reviewed and integrated before being promoted to `main`.

## Decision

Create an `integration` branch as the default PR base for all porting work. `main` receives only periodic sync PRs from `integration` once a tranche is stable.

**Branch hierarchy:**
- `main` — production-grade; only receives merges from `integration` via explicit user permission
- `integration` — default PR target for all ADR implementation PRs
- `research/<tranche>` — optional staging branches for long tranches (T1, T2, T3, T9, T10) that land into `integration` as a single squash PR

CI runs on push/PR to both `main` and `integration`.

## Acceptance criteria

- [x] `integration` branch exists at remote origin
- [x] CI workflow triggers on push/PR to `integration`
- [ ] README documents branching strategy (not blocking — can be deferred to T14 CI hardening)

## Out of scope

Merge automation (dependabot, GitHub Actions auto-merge). Manual merge only.

## Source references

N/A — this is a process decision, not a code port.
