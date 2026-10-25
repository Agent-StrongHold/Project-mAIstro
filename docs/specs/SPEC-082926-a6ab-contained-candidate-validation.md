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
  - packages/maistro-rsi/tests/test_contained_fitness.py
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
  Scenario: Fitness scoring is contained, not refused and not degraded
    Given container isolation and fitness scoring enabled
    When the evaluation runs
    Then every executing signal — the test vector, the coverage run, the red/green
    And replay, the mutation probe's reruns, per-file collection and the static tools
    And — runs inside the ONE sandbox seeded from the candidate directory (#614)
    And results cross the boundary as data: exit statuses, parsed reports, file contents
    And a sandbox that cannot be established or executed raises ContainmentUnavailable
    And no Scorecard is produced from signals that could not run safely

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
- **AC-6** named #614 as the owner of the fitness escape. #496 refused the
  configuration because the signals ran on the host; #614 removes the refusal
  by containing them — one sandbox per evaluation, every executing signal
  inside it, results back as data. The fail-closed rule is unchanged: the
  ADR's "a validation signal executes inside the isolation the run was
  configured for, or it is refused" now holds for the whole Scorecard, so a
  sandbox that cannot run still raises instead of degrading the evidence.

### Backend authority note (#614 dependency clarification)

The clarification on #614 asks the implementation to consume the canonical
sandbox authority (#18/#76) and its ADR-093 mode floors. #76 is REOPENED: its
selector registers no backend that meets the standard untrusted policies yet
(bubblewrap/fake only), and production builders/RSI containment ships through
`ContainerBuilderSandbox` — the same backend the editing half of a cycle uses
under `isolation="container"`, hardened per #77/#78/#811 (no network, dropped
caps, unprivileged uid, credential-filtered seed). This change therefore
routes the fitness signals through THAT established backend via the shared
`contained_validation` seam rather than inventing a second selector or a
weaker Docker-only path, and it does not treat the container label as
attestation: the sandbox must actually open, seed, and execute — every other
failure raises `ContainmentUnavailable` (fail closed, ADR-093 decision 5).
When #76 names its supported backend, this seam is the single integration
point: swap the factory, keep the contract.

### Closeout evidence (#614)

The issue's closeout clause demands real-backend evidence for every signal in
its AC-1 — "a locally skipped Docker test is not proof of the supported
production path" — so the proof is executable, not prose:

- `test_real_evaluation_scores_every_signal_inside_one_container`
  (`packages/maistro-rsi/tests/test_contained_fitness.py`, docker-gated) runs
  `evaluate_candidate` end-to-end under a real `ContainerBuilderSandbox` and
  asserts per signal that it crossed the sandbox channel: the vector
  (`python -m pytest -q <args>`), the coverage run and its report
  (`python -m coverage run|json`), the red/green replay and the probe reruns
  (`python -m pytest -q -p no:cacheprovider`), per-file collection
  (`--collect-only`) and a static tool (`python -m ruff`). It also asserts
  the closeout's data rule on the real backend — the coverage number came
  back as data and drove an ENFORCED gate decision — and the mutation probe's
  containment: the mutant is written inside the sandbox and the host worktree
  is never the tree it ran against. Executed against a live daemon with a
  `maistro-builders:latest` carrying the fitness toolchain: every gate green,
  a Scorecard produced (the #496 refusal gone), host tree untouched.
- The supported image must carry the fitness toolchain — the same list
  `Dockerfile.rsi-runner` installs for the in-container loop (pytest,
  coverage, ruff, mypy, bandit, radon, interrogate, vulture, pylint). Since
  #304 landed, a tool missing from the image is a blocking ``not_run`` gate
  naming its cause — in BOTH isolation modes, so containment cannot silently
  narrow the evidence ("a missing analyzer blocks promotion rather than
  narrowing the evidence"); the non-required quality measures instead drop
  from the composite by renormalised weights, and an image lacking one of
  those is never a false pass either. The end-to-end test names the
  toolchain requirement in its skip reason instead of weakening its
  assertions.
