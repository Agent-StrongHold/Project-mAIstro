---
id: SPEC-091226-1341
title: "Gates Ran path-scoped execution evidence"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-12
accepted: 2026-09-12
history:
  - status: Proposed
    date: 2026-09-12
    reason: "The Gates Ran path-scope behavior needs a measurable contract."
  - status: Accepted
    date: 2026-09-12
    reason: "The path-scope evaluator behavior is implemented and regression-tested in PR #1341."
  - status: AC Defined
    date: 2026-09-12
    reason: "Three acceptance scenarios mirror the existing path-scope regression tests."
substrate:
  - maistro-engine#ADR-091226-1341
implements:
  - maistro-engine#ADR-091226-1341
related:
  - maistro-engine#ADR-082526-9fa2
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_check_gates_ran.py
source:
  - scripts/check-gates-ran.py
  - scripts/ci_merge_group_scope.py
ac-modules:
  AC-1: '@tool/check-gates-ran'
  AC-2: '@tool/check-gates-ran'
  AC-3: '@tool/check-gates-ran'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-091226-1341: Gates Ran path-scoped execution evidence

## Scope

This specification defines the pull-request path-scope behavior of
`scripts/check-gates-ran.py`. The publisher uses the changed-file envelope and
`scripts/ci_merge_group_scope.py` to determine whether a skipped specialized
check was outside the candidate's affected scope. It does not change the
required-check contract, make DevSkim required, or replace the quality gate's
handling of a failed check.

## Acceptance criteria

```gherkin
Feature: Gates Ran path-scoped execution evidence

  @AC-1
  Scenario: An out-of-scope skipped specialized check is excused, but another skipped check is not
    Given a measured changed-file scope that proves the postgres leg is unreachable
    And the postgres check is skipped while an always-required check is also skipped
    When Gates Ran evaluates the required set
    Then the postgres check is not reported as non-executed
    And the always-required check is reported as non-executed

  @AC-2
  Scenario: A completed specialized check remains execution evidence even when its leg is out of scope
    Given a measured changed-file scope that proves the postgres leg is unreachable
    And the postgres check completed with a failure conclusion
    When Gates Ran evaluates the required set
    Then the check is reported as ran
    And the scope exemption does not erase or convert the failure evidence

  @AC-3
  Scenario: An unmeasured scope keeps a skipped specialized check pending
    Given a skipped postgres check
    And changed-file scope is missing or was not measured
    When Gates Ran evaluates the required set
    Then the check is reported as unfinished
    And the publisher returns pending rather than green
```

The scenarios are exercised by `TestPathScopedRequiredChecks` in
[`tests/test_check_gates_ran.py`](../../tests/test_check_gates_ran.py).
