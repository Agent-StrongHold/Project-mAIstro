---
id: SPEC-083026-14c3
title: Repairing an emptied Attempt output carries its accepted outcome, or reports why it cannot
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-14c3
implements:
  - maistro-engine#ADR-083026-14c3
related:
  - maistro-engine#SPEC-082926-2844
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_attempt_result_repair.py
source:
  - packages/maistro-core/src/maistro/runs/repair.py
  - packages/maistro-core/src/maistro/runs/store.py
ac-modules:
  AC-1: maistro.runs.repair
  AC-2: maistro.runs.repair
  AC-3: maistro.runs.repair
  AC-4: maistro.runs.store
  AC-5: maistro.runs.store
  AC-6: maistro.runs.store
  AC-7: maistro.runs.repair
  AC-8: maistro.runs.repair
  AC-9: maistro.runs.repair
  AC-10: maistro.cli._repair
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-14c3: Repairing an emptied Attempt output carries its accepted outcome, or reports why it cannot

## Context

ADR-083026-14c3 decides that an Attempt persisted with `output: {}` is repaired
only where a second copy proves the emptiness was loss, and that the two
recorded copies of one execution's evidence move together or not at all.

Two of the criteria below are regressions of the withdrawn repair's actual
defects rather than hypotheses. AC-1 is the false clean bill of health: the
survey ran over a store nothing writes, so it reported "nothing to repair"
against a deployment full of emptied Attempts. AC-8 is the unstated bound —
the same defect one level up, a partial sweep presented as a complete one.

AC-4 through AC-6 are the store method, held against every backend. AC-6 is the
invariant `validate_accepted_outcome_against_attempt()` enforces, and the reason
the method does both writes rather than offering two — in one transaction, since
two commits are two chances to stop between them and leave exactly the
disagreement the invariant refuses.

AC-9 and AC-10 are two more bounds the sweep has to state, both found in review
(Codex, #690). AC-9 is the scope it was *given*: `--workspace-id` chose which
store to wire and nothing more, so the sweep listed globally and naming one
Workspace surveyed — and with `--apply` rewrote — every other tenant's records
in the same database. AC-10 is the scope it cannot reach: once a terminal Run's
payload is offloaded, `PgRunStore.list_by_status` skips it, because it selects
`payload IS NOT NULL`. A cold record holding this very loss is therefore
invisible and no larger `--limit` reveals it. Both are reported rather than
tolerated, for AC-1's reason — a clean report over records the sweep could not
read is the withdrawn version's defect wearing different clothes.

## Acceptance Criteria

```gherkin
Feature: Repairing an emptied Attempt output

  @AC-1
  Scenario: The survey reads the store production writes
    Given a deployment whose Attempts hold an emptied output
    When the survey runs against the configured run store
    Then it reports those Attempts
    And it does not report the deployment as having nothing to repair

  @AC-2
  Scenario: An emptied output beside a logical record is repairable
    Given an accepted Attempt whose recorded output is empty
    And a NodeRun whose result carries the output that Attempt produced
    When the survey classifies it
    Then it is reported as repairable

  @AC-3
  Scenario: An emptied output with no second copy is reported, not guessed
    Given an Attempt with an empty output that no accepted outcome names
    When the survey classifies it
    Then it is reported as unrepairable with a reason
    And nothing is written for it

  @AC-4
  Scenario: A repair rewrites the Attempt's recorded result
    Given a repairable Attempt
    When the repair applies the recovered output
    Then the store returns that Attempt holding the recovered output

  @AC-5
  Scenario: A repair refuses an Attempt that has not finished
    Given an Attempt that is still running
    When a repair is attempted on it
    Then the store refuses and the Attempt is unchanged

  @AC-6
  Scenario: The accepted outcome moves with the Attempt it names
    Given a repairable Attempt whose NodeRun accepted it
    When the repair applies the recovered output
    Then the NodeRun's accepted outcome matches the repaired Attempt
    And validating the outcome against that Attempt raises nothing

  @AC-7
  Scenario: A survey writes nothing until it is told to
    Given a deployment with repairable Attempts
    When the survey runs without being asked to apply
    Then every Attempt holds what it held before

  @AC-8
  Scenario: A capped sweep says so rather than reading as complete
    Given more runs than one sweep examines
    When the survey runs
    Then it reports how many runs it examined
    And it states that it stopped at its limit

  @AC-9
  Scenario: A sweep confined to one Workspace touches no other
    Given damaged Attempts in two Workspaces of one database
    When the survey names one of them and the repair is applied
    Then only that Workspace's Attempt is rewritten
    And the other is still found by a sweep that asks for it

  @AC-10
  Scenario: The sweep states the records it could not read
    Given a deployment whose terminal payloads may be archived
    When the survey runs
    Then it states that archived runs were not examined
    And it states it on a clean sweep as well as a dirty one
```
