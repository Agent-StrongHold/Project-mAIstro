---
id: ADR-082926-87bb
title: "Ephemeral Conductor state is chosen, never caught"
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
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-082226-5104
  - maistro-engine#ADR-082926-0b72
implements: []
related:
  - maistro-engine#SPEC-010
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_state_durability_mode.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-87bb: Ephemeral Conductor state is chosen, never caught

## Context

`Foundation._init_state` opens the SQLite state database, wires every mutable
store to it, and — on **any** exception from any step in that block — logs a
warning and falls through to `stores.initialize_stores()` with no persistence
attached:

```python
except Exception as exc:
    logger.warning("State unavailable (%s) — using in-memory stores", exc)
```

The process then reports healthy. `/health` shows `state_enabled: false`, which
nothing consumes as a failure, and `/health/ready` is keyed on `"api"` alone, so
readiness is unconditionally true. Accounts, sessions, settings and every other
durable store accept writes and answer reads for as long as the process lives,
and lose all of it on restart. Users keep working; the loss arrives later,
detached from its cause.

Three properties make this worse than a plain outage:

1. **The trigger is an unexpected exception.** An unwritable data directory, a
   failed migration, a missing import and a corrupt database file all land in
   the same handler and produce the same success-shaped behaviour. Nothing
   distinguishes "this deployment wants ephemeral state" from "this deployment
   wanted durable state and did not get it", because nobody ever expressed the
   first.
2. **Initialization is not atomic.** `stores.configure_persistence` attaches the
   store to every `ModelStore` and `JsonStore`, then `initialize_stores()` loads
   each one. A failure partway through leaves some stores populated from disk
   and some empty, with writes going to both — two authorities for one dataset,
   and no record that it happened.
3. **Recovery would make it permanent.** If durability were restored later while
   in-memory writes existed, flushing them would overwrite the durable rows the
   database still holds with whatever the degraded process accumulated.

ADR-082926-0b72 closed the same shape one level down for settings — a write that
is acknowledged but not stored. This is the shape at the level of the store
itself.

## Decision

**Durability is a declared mode. Ephemeral state is entered by configuration, or
not at all.**

1. **`CONDUCTOR_DURABILITY` is `durable` (default) or `ephemeral`.** The value is
   read once at startup and recorded. `ephemeral` is a legitimate deployment —
   a demo, a test, a throwaway container — and it is *stated*, so nothing has to
   infer it from a stack trace.

2. **In `durable` mode, a state failure is a degraded state, not a substitution.**
   The exception is caught to be *recorded*, never to be recovered from with an
   in-memory stand-in wearing the same interface. The Foundation records what
   was requested, what was obtained, and the exception; readiness goes false and
   the affected stores refuse writes.

3. **A store that was promised durability and did not get it refuses writes.**
   `ModelStore.__setitem__`, `pop` and `JsonStore.__setitem__` raise
   `StoreUnavailableError`, which the API returns as `503`. Reads still answer —
   seeded and read-only data is still useful, and a reader that gets a 503 tells
   an operator nothing a failed write has not already told them.

4. **Initialization is all-or-nothing.** Every store loads inside one attempt; a
   failure part-way marks the whole set degraded rather than leaving a subset
   authoritative. Two authorities for one dataset is the state this refuses to
   be in, so it is never briefly in it either.

5. **Health says what is actually true.** `/health` gains a `state` block naming
   the requested mode, the backend in use, whether it is durable, the
   initialization error if any, and whether writes are refused. `/health/ready`
   is no longer keyed on `"api"` alone: a `durable` deployment that did not get
   durable state is not ready.

**Recovery is out of scope, and that is the point.** There is no path that
promotes a degraded process back to durable, because the only safe promotion is
one that has nothing to flush — and rule 3 is what guarantees that. A restart
against a repaired database is the recovery, and it starts from the durable rows.

## Consequences

### Positive
- A deployment that wanted durable state and did not get it fails visibly, at
  startup, instead of silently at the next restart.
- The four causes the issue names — unwritable path, bad migration, import
  failure, database outage — stop being indistinguishable from each other and
  from a deliberate choice.
- `ephemeral` becomes a supported, labelled mode rather than an accident, which
  is what makes tests and demos honest instead of exceptional.

### Negative / Trade-offs
- A Conductor that used to keep serving through a state failure now refuses
  writes and reports not-ready. That is the intended trade — the old behaviour
  was availability bought with silent data loss — but it will take deployments
  down that were previously "up".
- Every write path can now raise where it could not before. The exception is
  translated centrally, so no route enumerates it, but a caller that ignored
  errors will see new 503s.
- `CONDUCTOR_DURABILITY` is a new configuration surface, and a wrong value there
  is a new way to be misconfigured. It is validated at load: an unrecognised
  value refuses startup rather than defaulting.

### Neutral
- Nothing changes for a deployment whose state database opens normally, which is
  every healthy one.
- The settings record (ADR-082926-0b72) already reports its own `durable` flag;
  this makes the flag it reports derive from a declared mode rather than from
  which branch of a `try` ran.
