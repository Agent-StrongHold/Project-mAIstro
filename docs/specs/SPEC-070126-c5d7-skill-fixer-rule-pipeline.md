---
id: SPEC-070126-c5d7
title: "Skill fixer rule pipeline and public API ownership"
repo: maistro-engine
kind: spec
status: Superseded
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related: []
implements: []
supersedes: []
superseded-by:
  - maistro-engine#SPEC-062126-7853
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-21
  - status: Superseded
    date: 2026-07-29
---

# SPEC-261: Skill Fixer Rule Pipeline

> **Superseded by [SPEC-062126-7853](SPEC-062126-7853-skill-fixer-rule-pipeline.md).**
> This file is a stale duplicate: the date-based-ID rename (ADR-062026-9b30)
> renamed the original `SPEC-261` to `SPEC-062126-7853`, and a later, unrelated
> commit accidentally reintroduced the pre-rename content verbatim under this
> ID. Content is otherwise identical — see the canonical file for the live spec.

## Finding addressed

The deep dive identified `fix_content` as a long sequence of independent repair passes with hidden ordering coupling. Vulture also reported `fix_content` and `is_deeply_flawed` as unused, requiring an explicit public API/dead-code decision.

## Problem

A long repair function is hard to extend safely. Rule intent, rule order, and rule interactions are implicit in the function body. Broad before/after tests will not identify which repair regressed.

## Design

1. Introduce a `RepairRule` dataclass or protocol with `name`, `reason`, and `apply(content) -> RepairResult`.
2. Store rules in an ordered tuple so rule order is explicit and reviewable.
3. Keep `fix_content` as the public orchestrator over the ordered rule list if the API is still supported.
4. Add exact-output parametrized tests for every rule.
5. Add at least one ordering regression test where two rules can interact.
6. Decide whether `is_deeply_flawed` is public API, internal helper, or dead code.
7. Add vulture allowlist entries only for confirmed public/dynamic APIs.

## Acceptance criteria

- [ ] `fix_content` delegates to named `RepairRule` instances.
- [ ] Every rule has a test with exact `fixed_content`, `fixes_applied`, and `unfixable_issues` expectations.
- [ ] Interacting rules have at least one ordering test.
- [ ] `is_deeply_flawed` has direct tests or is removed.
- [ ] Vulture output for this module is either clean or allowlisted with ownership rationale.
