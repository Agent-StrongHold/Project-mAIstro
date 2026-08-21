---
id: ADR-002
title: Per-port spec-first workflow
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-001
implements: []
related:
  - maistro-engine#ADR-000
supersedes: []
blocks: []
blocked-by: []
contracts: [behavioral]
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-002: Per-port spec-first workflow

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T0  
**Depends on:** ADR-001

---

## Context

maistro-engine is receiving improvements ported from two adjacent repos: `stronghold` (production multi-agent platform) and `Project_mAIstro` (Python conductor + TypeScript app layer). Each port must be specced, tested, and implemented in a repeatable, auditable way per the `~/.claude/CLAUDE.md` 12-step engineering workflow.

## Decision

Every port follows this sequence without collapsing steps:

1. **ADR drafted** — sections: Context, Decision, Interface (spec), Acceptance criteria, Test plan, Dependencies, Out of scope, Source references.
2. **ADR-only PR opened** to `integration` for review.
3. **Failing happy-path test** written after ADR merged.
4. **Edge cases enumerated** in ADR test-plan section.
5. **Failing edge-case tests** written.
6. **Implementation** written to make all tests pass.
7. **`pytest tests/`** — full suite green.
8. **Coverage check** — new code must have test coverage (judgment call per port; threshold gate formalized in T14).
9. **Assertion-strength audit** — tests must pin meaningful behavior, not just "doesn't crash."
10. **Code-smell audit** — duplication, dead code, half-finished abstractions.
11. **`ruff check src/ tests/ && ruff format --check src/ tests/ && mypy --strict src/ && pip-audit --strict`** — all must pass.
12. **Implementation PR** opened to `integration`; links back to ADR; ADR Status updated to Implemented.

Trivial typo/rename fixes exempt from the full workflow.

## Spec format

ADR-style at `docs/adr/ADR-XXX-name.md`. Template at `docs/adr/ADR-000-template.md`. Numbering begins at ADR-001 (this file). ADRs combine the architecture decision and the per-port specification.

## Acceptance criteria

- [x] ADR template exists at `docs/adr/ADR-000-template.md`
- [x] This ADR documents the workflow
- [ ] Future ADRs reference this document in their "workflow" section (living check)

## Out of scope

Automated ADR status tracking, ADR linting CI gate. Manual process only.
