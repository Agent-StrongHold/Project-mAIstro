---
id: SPEC-204
title: "Partial-feature hardening — connector demo-data honesty, canary stage automation, base-node contract"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-09
substrate:
  - maistro-engine#ADR-039
implements: []
related:
  - maistro-engine#SPEC-005
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-09
---

# SPEC-204: Partial-Feature Hardening

## Problem

Several features in `maistro-core` are wired far enough to look complete but carry a
half-built seam that fails in the "claims more than it enforces" pattern.

### 1. Marketplace connectors: catch-all-then-demo masks every failure

`skills/connectors.py` attempts a real `httpx` GET, then on **any** exception falls
back to hardcoded demo data. Three problems compound:

- `except (httpx.RequestError, Exception)` swallows programming errors as "API
  unreachable," logging at `debug` and silently serving canned results.
- The fallback is **silent to the caller** — live results and demo fixtures are
  indistinguishable.
- Demo fixtures include adversarial names (`admin-override`, `credential-helper`,
  `code-executor-unlimited`, `unlimited-agent`) that surface to any caller on an API
  hiccup — a social-engineering footgun.

### 2. Canary `PARTIAL` stage is defined but promotion may not be automated

`skills/canary.py` defines `CANARY 5% → PARTIAL 25% → MAJORITY 75% → FULL 100%`
with traffic fractions and `_STAGE_ORDER`. Advancement between stages needs
confirmation that it's driven by a scheduler/metric trigger. If nothing advances
stages on a health signal, it's a fixed 5% split that never graduates.

### 3. `GraphNode._execute` base raises `NotImplementedError` at execution time

A node subclass missing `_execute` fails deep in a DAG run rather than at
registration/validation time.

## Design

### Connectors

- Catch only `httpx.RequestError` / `httpx.HTTPStatusError` for demo fallback. Let
  everything else propagate.
- Return `source ∈ {"live", "demo"}` in the result envelope.
- Move adversarial fixtures to test-only; shipped demo data uses benign names.
- Gate demo fallback behind `allow_demo_fallback: bool` (default True in dev, False
  in production).

### Canary

- Confirm/implement advancement driver: `CanaryController.tick()` reads metrics and
  advances or rolls back.
- If intentionally manual, docstring says so explicitly.

### Base node

- Registration-time check: graph validation asserts each node type overrides
  `_execute`. Runtime `NotImplementedError` stays as backstop.

## Acceptance criteria

- [ ] Connector catches only `httpx`-family errors for fallback; parse `KeyError` propagates (tested)
- [ ] Connector results indicate `source ∈ {"live", "demo"}` (tested)
- [ ] Demo fallback fires at `warning` level, only when `allow_demo_fallback=True`; raises when False (tested both)
- [ ] Adversarial fixture names removed from shipped core data; demo data is benign (tested)
- [ ] Canary advancement driven by metric tick (or docstring states manual); test runs deployment through all stages
- [ ] Canary auto-rollback fires on failing metric threshold (tested)
- [ ] Node missing `_execute` fails graph validation at registration time (tested)
