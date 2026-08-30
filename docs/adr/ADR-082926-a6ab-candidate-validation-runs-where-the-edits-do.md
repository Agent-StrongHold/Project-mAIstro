---
id: ADR-082926-a6ab
title: "Candidate validation runs where the edits do, or it does not run"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-rsi/tests/test_contained_validation.py
  - packages/maistro-rsi/tests/test_no_host_shell_execution.py
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-a6ab: Candidate validation runs where the edits do, or it does not run

## Context

`isolation="container"` was applied to one half of an RSI cycle. The builders
agent wrote inside a container, its edits were synced back to the host
worktree, and then `LocalRsiLoop._run_tests` ran the test vector on the host
with `subprocess.run(argv, cwd=cycle_dir)`.

The reasoning that made this look safe was that the vector is policy-resolved
and runs without a shell. That is true and insufficient. **An argument vector
is not an isolation boundary.** `shell=False` decides how the first command is
parsed; it says nothing about whose code runs afterwards, and every realistic
validation profile — `python -m pytest` above all — imports the candidate's
test modules, its `conftest.py`, and any plugin its configuration declares.

So a candidate authored inside a container executed as the loop's own process,
on the host, from an HTTP-initiated run, under the one setting whose purpose
was to prevent exactly that. Found in review on #496.

The same shape recurs in the fitness path. `candidate_fitness.evaluate_candidate`
composes its Scorecard from a test run, a coverage run, a red/green replay and
several static tools, each with `cwd` at the candidate worktree — six call
sites with the property this decision is about, rather than one.

## Decision

**A validation signal executes inside the isolation the run was configured
for, or it is refused. There is no host-side fallback.**

Concretely:

1. `maistro_rsi.contained_validation` is the seam. Under container isolation
   the loop runs the candidate's vector through a `ContainerBuilderSandbox`
   seeded from the cycle directory and reads back the exit status.
2. Every condition that prevents containment raises `ContainmentUnavailable`
   rather than returning a verdict — an absent vector (there is no shell inside
   the sandbox to hand a command string to), a missing backend, a sandbox that
   cannot run.
3. Signals that cannot yet be contained are **refused, not silently
   downgraded**. `use_fitness` under container isolation raises, naming #614.
4. The decision about which sandbox the builders agent gets is made at the one
   call site that injects an apply function. An injected function wins over the
   one the loop would have built, so `isolation` and `image` are load-bearing
   arguments there rather than defaults.

"Refused" is the load-bearing word. A refused run is a run that did not happen,
which an operator can see and act on. A host-side fallback is a containment
failure that reports success.

## Consequences

### Positive
- The claim `isolation="container"` makes is now true of the whole cycle rather
  than of its editing half.
- "The tests failed" and "the tests could not be run safely" stay distinct, so
  a broken sandbox cannot read as a candidate that did not pass.
- One seam, shared by both halves, so the two cannot drift apart again.

### Negative / Trade-offs
- **Fitness scoring is unavailable on the Conductor's HTTP path** until #614
  lands, because that path requires container isolation. This is a real
  capability loss, taken deliberately over scoring a candidate on signals that
  ran outside its containment.
- A container per validation costs startup time on every cycle. Scoping
  `coverage_pytest_args` matters more inside a container than outside.
- The contained path cannot be executed in an environment without Docker, so
  its integration coverage is docker-gated; the routing decision is tested
  host-side instead.

### Neutral
- Local CLI runs are unchanged: an operator who chose `isolation="local"` on
  their own machine still gets host execution, and a test asserts that half so
  a loop that contained everything could not pass by containing too much.
