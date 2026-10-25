---
id: SPEC-082926-a6ab
title: "Contained candidate validation"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
substrate: []
implements:
  - maistro-engine#ADR-082926-a6ab
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-rsi/tests/test_contained_validation.py
  - packages/maistro-rsi/tests/test_no_host_shell_execution.py
  - packages/hive-conductor/backend/tests/test_rsi_execution_containment.py
source:
  - packages/maistro-rsi/src/maistro_rsi/contained_validation.py
  - packages/maistro-rsi/src/maistro_rsi/local_loop.py
ac-modules:
  AC-1: maistro_rsi.contained_validation
  AC-2: maistro_rsi.contained_validation
  AC-3: maistro_rsi.local_loop
  AC-4: maistro_rsi.contained_validation
  AC-5: maistro_rsi.contained_validation
  AC-6: maistro_rsi.local_loop
  AC-7: maistro_rsi.local_loop
  AC-8: maistro_rsi.local_loop
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-a6ab: Contained candidate validation

Implements ADR-082926-a6ab.

## Acceptance criteria

```gherkin
Feature: Contained candidate validation

  @AC-1
  Scenario: Under container isolation the vector runs in the container
    Given a loop configured with container isolation and a test vector
    When it validates a cycle
    Then the vector runs inside a sandbox seeded from that cycle's directory
    And no host process is started for it

  @AC-2
  Scenario: The sandbox is built from the configured image, vector and timeout
    Given a config naming an image and a timeout
    When validation runs
    Then the sandbox is created from that image, seeded from the cycle directory
    And the vector runs under that timeout

  @AC-3
  Scenario: Local isolation still runs on the host
    Given a loop configured with local isolation
    When it validates a cycle
    Then the vector runs on the host, as an argument list, with no shell

  @AC-4
  Scenario: A zero exit is a pass and a non-zero exit is a failure
    Given a contained run
    When the command exits zero
    Then the verdict is a pass
    And when it exits non-zero the verdict is a failure, not an error

  @AC-5
  Scenario: Containment that cannot be established is refused
    Given container isolation
    When the vector is empty, the container backend is unimportable, or the sandbox raises
    Then the caller receives ContainmentUnavailable naming the reason
    And the command is never attempted on the host

  @AC-6
  Scenario: Uncontainable signals are refused, not degraded
    Given container isolation and fitness scoring enabled
    When the run starts
    Then it raises before any cycle, naming #614 and both ways out

  @AC-7
  Scenario: The builders agent is told which sandbox to build
    Given an HTTP-initiated run resolved to container isolation
    When the service constructs the apply function
    Then it passes that isolation and image to the factory

  @AC-8
  Scenario: The review route uses the run's own repository
    Given a review decision carrying a repo_path
    When it is submitted
    Then the request is refused with 400 before anything is recorded
    And an approval without one applies the patch against the authorized repository
```

### Why each is worded that way

- **AC-3** is present so that a loop which contained *everything* could not
  satisfy AC-1 by breaking the operator's own machine.
- **AC-4**'s second clause is the distinction that matters: "the tests failed"
  and "the tests could not be run safely" are different facts, and collapsing
  them lets a broken sandbox read as a candidate that did not pass.
- **AC-6** costs a capability on purpose. Silently downgrading to the bare test
  gate was the alternative, and a run scored on fewer signals than the operator
  asked for — saying so nowhere — is how a promotion decision changes meaning
  without anyone deciding.
