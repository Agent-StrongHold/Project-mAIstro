---
id: SPEC-205
title: "Test-suite fidelity — failure-mode coverage, deterministic time, multi-process invariants, project-wide gate"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-09
substrate:
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#SPEC-202
  - maistro-engine#SPEC-203
  - maistro-engine#SPEC-204
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-09
---

# SPEC-205: Test-Suite Fidelity

## Problem

The suite is large (199 files, ~2075 tests, 28-model Hypothesis property suite,
cosmic-ray mutation testing, per-PR 95% touched-file gate). But findings #1–#18
surfaced a consistent gap: **tests prove the happy path on the single-process
configuration; bugs live in failure modes and realistic configurations.**

Five concrete, measured weaknesses:

### 1. Project-wide coverage gate is `--fail-under=20`

Touched-file gate: 95% line+branch (excellent). Project-wide gate: 20%. Dead
features (#114: delegation, learning promotion, conduit crash) stayed green because
they lived in the ungated 80%.

### 2. Existence-only assertions

Tests assert `is not None` as the terminal check. A function returning `{}`, a wrong
timestamp, or empty-but-present passes. Clustered in `graph/test_protocol.py`,
canvas asset tests, e2e files.

### 3. Time-dependent logic barely time-controlled

77 source files use clock/TTL/decay/lockout. 3 test files control time. An
off-by-one in a TTL or a wrong-sign decay is invisible to tests using real
`datetime.now()`.

### 4. Multi-process invariants tested single-process

The formal suite proves strike escalation on one in-memory instance — the config
nobody ships. Now that strikes are Postgres-backed (#7), the proof must cover the
shared-store configuration.

### 5. Contract/scope marker axes defined but unused

`pyproject.toml` defines `contract` (boundary|behavioral|cross_service) and `scope`
(unit|integration|e2e|property). 2 files use each. The taxonomy is documentation,
not infrastructure.

## Design

### 1. Ratchet the project-wide gate

Replace `--fail-under=20` with a ratchet against a stored baseline in
`docs/QA-BASELINE.md`. Coverage only goes up. Set near-term target (60%) and
long-term floor. Touched-file 95% stays.

### 2. Failure-mode assertions

Audit existence-only terminal assertions; convert to value assertions. Standing
policy: every new feature lands with at least one failure-mode test.

### 3. Deterministic clock fixture

Add `frozen_clock` fixture. Required for any test exercising decay, TTL, lockout,
rate windows, leases, billing, canary timing. Backfill highest-risk paths first:
strike lockout, rate window, memory decay, lease reaping.

### 4. Distributed invariants in property suite

Extend `formal/models/test_strike_escalation.py` and `test_rate_limiter.py` to run
against 2+ tracker instances sharing one Postgres store. Assert the ladder holds
across instances.

### 5. Apply marker axes

Tag existing suite with `contract` and `scope` markers. Add fast pre-merge CI job
running `pytest -m "scope: unit or contract: boundary"`. Full suite on slower path.

## Acceptance criteria

- [ ] Project-wide gate is a ratchet against stored baseline; PR lowering coverage fails CI
- [ ] `docs/QA-BASELINE.md` records current coverage + near-term target; gate reads from it
- [ ] Existence-only terminal assertions in `graph/test_protocol.py` converted to value assertions (representative test now fails on wrong value)
- [ ] `frozen_clock` fixture exists and documented as required for time-dependent tests
- [ ] Strike lockout, rate window, memory decay each have frozen-clock boundary tests
- [ ] Property suite runs strike/rate-limit across ≥2 instances sharing one store
- [ ] Formal boundary contracts and e2e tests carry `contract`/`scope` markers; `pytest -m "contract: boundary"` selects correct subset
- [ ] Fast pre-merge CI job runs marker-selected subset
- [ ] `docs/WAYS-OF-WORKING.md` states failure-mode test policy
