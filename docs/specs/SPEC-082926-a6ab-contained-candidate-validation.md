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
  AC-1: contained_validation
  AC-2: contained_validation
  AC-3: local_loop
  AC-4: contained_validation
  AC-5: contained_validation
  AC-6: local_loop
  AC-7: local_loop
  AC-8: local_loop
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-a6ab: Contained candidate validation

Implements ADR-082926-a6ab.

## Acceptance criteria

### AC-1 — Under container isolation the vector runs in the container

**Given** a loop configured with `isolation="container"` and a test vector
**When** it validates a cycle
**Then** the vector runs inside a sandbox seeded from that cycle's directory
**And** no host process is started for it.

### AC-2 — The sandbox is built from the configured image, vector and timeout

**Given** a config naming an image and a timeout
**When** validation runs
**Then** the sandbox is created from that image, seeded from the cycle
directory, and the vector runs under that timeout
— a sandbox built from a different image is a different containment claim from
the one the configuration makes.

### AC-3 — Local isolation still runs on the host

**Given** a loop configured with `isolation="local"`
**When** it validates a cycle
**Then** the vector runs on the host, as an argument list, with no shell.

Present so that a loop which contained *everything* could not satisfy AC-1 by
breaking the operator's own machine.

### AC-4 — A verdict comes from the exit status, and only from a run

**Given** a contained run
**When** the command exits zero **Then** the verdict is a pass;
**when** it exits non-zero **Then** the verdict is a failure;
**when** the sandbox could not run it at all
**Then** `ContainmentUnavailable` is raised rather than a verdict returned.

### AC-5 — Containment that cannot be established is refused

**Given** container isolation
**When** the vector is empty, the container backend is unimportable, or the
sandbox raises
**Then** the caller receives `ContainmentUnavailable` naming the reason
**And** the command is never attempted on the host.

### AC-6 — Uncontainable signals are refused, not degraded

**Given** `isolation="container"` and `use_fitness=True`
**When** the run starts
**Then** it raises before any cycle, naming #614 and both ways out
(disable fitness, or run under local isolation).

### AC-7 — The builders agent is told which sandbox to build

**Given** an HTTP-initiated run resolved to container isolation
**When** the service constructs the apply function
**Then** it passes that isolation and image to the factory
— the factory defaults to `"local"`, and an injected apply function wins over
the one the loop would have built for itself.

### AC-8 — The review route uses the run's own repository

**Given** a review decision carrying a `repo_path`
**When** it is submitted
**Then** the request is refused with 400 before anything is recorded
**And** an approval without one applies the patch against the repository the
run was authorized for.
