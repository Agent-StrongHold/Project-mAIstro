---
id: SPEC-274
title: "Bootstrap install-plan golden contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
substrate:
  - maistro-engine#SPEC-180
  - maistro-engine#SPEC-205
related: []
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-274: Bootstrap Plan Golden Contracts

## Finding addressed

`build_install_plan` combines feature selection, compose-stack behavior, Podman/Docker hints, environment variables, warnings, and preview notes. Golden tests now protect root-compose/no-root behavior plus observability and gateway preview notes; remaining work is to keep adding fixtures whenever install-plan semantics expand.

## Design

1. Add golden fixtures for no features, Postgres, LiteLLM, Langfuse, root compose dry-run, root compose apply, Podman preference, and every deployment tier gate.
2. Assert exact commands, environment variables, warnings, notes, and compose files.
3. Split policy helpers only after golden tests show which branches are stable contracts.
4. Keep plan output deterministic so CLI and JSON output can share the same fixtures.
5. Update SPEC-180 references if install-plan semantics change.

## Acceptance criteria

- [x] Golden tests cover feature-only, root-compose, and deployment-tier plans.
- [x] Podman/Docker messaging is asserted exactly for current root-compose apply specs.
- [ ] Dry-run versus apply behavior is tested for command side effects.
- [ ] JSON plan output and interactive preview use the same plan object.
- [x] Current preview-note combinations added by this finding have exact golden coverage.
- [ ] Any new install feature must add or update a golden fixture.
