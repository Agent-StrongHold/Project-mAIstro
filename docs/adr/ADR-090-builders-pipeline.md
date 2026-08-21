---
id: ADR-090
title: "Builders Pipeline — the spec to tests to code to audit stage machine"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-032
  - maistro-engine#ADR-070
implements: []
related:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-049
  - maistro-engine#ADR-075
  - maistro-engine#ADR-071
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-090: Builders Pipeline

**Status:** Proposed
**Date:** 2026-05-30

---

## Context

The Builders 2.0 pipeline exists in code (`maistro.builders`) but has no ADR. It is the
engineering-specific workflow — turn an issue into a verified, tested, reviewed change — and is
distinct from the *general* task planner (ADR-071). ADR-032 (contracts as acceptance criteria)
covers its contract layer, but nothing pins the stage machine, the worker roles, or the
runtime-version lifecycle. This ADR formalises the pipeline **as it is built**.

## Decision

Adopt the existing Builders 2.0 design as the canonical engineering pipeline.

### Stage machine (core-owned)

Core owns the workflow state; the Builders runtime only returns results. The run advances through
explicit, allowed transitions:

```
queued -> issue_analyzed -> acceptance_defined -> tests_written
  -> implementation_started -> implementation_ready -> quality_checks_passed -> completed
```

with `blocked` and `failed` as terminal states, and rework loops (`implementation_ready` back to
`implementation_started`/`acceptance_defined`; `quality_checks_passed` back to `acceptance_defined`).
Each transition is a durable `StageEvent`; the run carries `RunState` (artifacts, retries, status).

### Worker roles

Three runtime roles, each handling specific stages, dispatched by a stateless `BuildersRuntime`
(per-`(worker, stage, version)` prompts + allowed-tools):

- **Frank** — analysis + acceptance + tests: issue -> machine-checkable Spec (Quartermaster, below)
  -> property tests.
- **Mason** — implementation: writes the code against the Spec in a shadow-git workspace (ADR-049).
- **Auditor** — quality gate: checks invariant coverage and gates the PR candidate (spec-coverage).

### Contract-driven (ADR-032)

- **Quartermaster** (`spec_emitter`) converts issue metadata into a machine-checkable `Spec`
  (acceptance criteria -> invariants -> protocols), reusing verified prior specs as templates
  (`SpecTemplateStore`): a verified Spec that merges becomes a reusable template, so future similar
  issues are matched-and-adapted instead of reasoned from scratch.
- **property_gen** derives Hypothesis property tests from the Spec invariants.
- **verifier** (`InvariantVerifier`) asserts every invariant has a covering property test.
- **spec_coverage** produces review findings for uncovered invariants; the Auditor gates on them.

### Runtime-version lifecycle

A Builders runtime version is `ready | draining | retired` — versions are registered and drained
for hot-swap, governed by the universal versioning model (ADR-075).

### It is a Repertoire instance (ADR-070)

The pipeline is the engineering-domain realisation of the Repertoire pattern: **Perform** = match a
verified spec template (Quartermaster); **Improvise** = author a new Spec via the LLM on a template
miss; **Rehearse** = verify invariant coverage + the Auditor gate; **Compose** = a verified, merged
Spec becomes a new reusable template. This is *not* the general planner (ADR-071) — it borrows the
same reuse-first cascade for code work.

## Acceptance criteria

- [ ] The run advances only through the allowed transitions; an illegal transition is rejected.
- [ ] Core holds the workflow state (`RunState`/`StageEvent`); the runtime returns only `RunResult`.
- [ ] Frank/Mason/Auditor are dispatched per `(worker, stage)`; an unsupported pair fails the run.
- [ ] Quartermaster emits a Spec whose invariants each gain a property test (verifier passes);
      uncovered invariants block at the Auditor.
- [ ] A verified, merged Spec is stored as a reusable template (SpecTemplateStore).
- [ ] Runtime versions move ready -> draining -> retired for hot-swap (ADR-075).
- [ ] Implementation happens in a shadow-git workspace and returns a PR candidate (ADR-049).

## Consequences

- The engineering pipeline gets a canonical contract distinct from the general planner.
- Builders, the planner, and the Repertoire pattern are explicitly related (instances of one idea).

## Out of scope

- The worker prompts / model choices (tuning detail).
- The general task planner (ADR-071) and non-engineering workflows.
- Multi-repo / cross-service builds.
