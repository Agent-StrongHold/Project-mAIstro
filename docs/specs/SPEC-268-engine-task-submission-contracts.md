---
id: SPEC-268
title: "Engine task submission contracts and capability-admission helpers"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-226
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-268: Engine Task Submission Contracts

## Finding addressed

`EngineService.submit_task` mixes capability gating, optional program-context hydration, `TaskCreate` construction, backend submission, and logging.

## Design

1. Extract pure `admit_capability(capability, program_context)` behavior.
2. Extract program-context hydration behind a small injectable helper.
3. Extract `TaskCreate` construction to a pure mapper.
4. Add exact tests for gated capability rejected, gated capability confirmed, missing backend, missing context, and backend submit failure.
5. Keep logging after successful submit only.

## Acceptance criteria

- [ ] Capability admission is unit-tested independently of backend submission.
- [ ] Context hydration failure has a documented result and test.
- [ ] `TaskCreate` mapping has exact field assertions.
- [ ] Backend failures are not swallowed or misreported as successful submissions.
