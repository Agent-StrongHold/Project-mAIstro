---
id: ADR-082926-0b72
title: "Conductor settings are durable, or the write fails"
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
implements: []
related:
  - maistro-engine#SPEC-010
  - maistro-engine#SPEC-011
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_settings_durability.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-0b72: Conductor settings are durable, or the write fails

## Context

`stores.settings` is a module-level `SettingsModel` instance. Nothing writes it
anywhere. `PUT /api/settings`, `PATCH /api/settings`, the capability toggle in
`routes/capabilities.py`, and the Setup wizard's default-model choice in
`routes/setup.py` all rebind or mutate that object and return `200` with the new
value in the body. The next restart discards every one of them.

The response is not merely optimistic — it is *shaped like* a durable write. A
caller has no way to distinguish it from one, so the failure surfaces later, as
lost configuration, attributed to something else.

Two mechanisms downstream of the route make an optimistic ack unsafe even once
a store is wired:

1. `PersistedStore.put` is asynchronous. It calls `State.submit`, which enqueues
   a closure for the writer thread and returns. The route returns before any row
   exists.
2. `State._writer_loop` catches every exception from that closure, logs it, and
   continues. A write that fails is invisible to the caller by construction.

So "wire settings into `PersistedStore`" would move the problem rather than
close it: the ack would still precede — and survive — the failure.

There is a second, quieter defect in the same surface.
`routes/setup.py` assigns `stores.settings.default_model = ...`, mutating the
model in place. A write-through setter on the module attribute would not even
see it. Any design that keeps `stores.settings` assignable keeps that class of
silent loss available.

## Decision

**A settings write is acknowledged only after the value has been read back from
the authoritative durable store.**

1. **One durable record, versioned.** Settings persist as a single
   `DurableSettings` envelope — `schema_version`, `revision`, `updated_at`, and
   the `SettingsModel` payload — under one key. The envelope is what migrates;
   the payload is what callers see.

2. **Write, drain, read back, compare.** `SettingsStore.save` submits the write,
   drains the writer queue, opens a *reader* connection, and compares what came
   back to what it sent. A mismatch, a missing row, or a drain timeout raises
   `SettingsPersistenceError`, which the route returns as `503`. The response
   body is the value the store holds, never the value the caller sent.

3. **`stores.settings` stops being assignable.** The module-level name is
   removed in favour of `stores.current_settings()` and
   `stores.save_settings(...)`. A missed call site becomes an `AttributeError`
   at import time rather than a write that quietly does not land. In-place
   mutation of the returned model is defused by returning a copy.

4. **Optimistic concurrency, explicit conflict.** Every read carries the
   record's `revision`. A write may pass `expected_revision`; if the stored
   revision has moved, the write is refused with `409` and the current value.
   Omitting it is a deliberate last-writer-wins, not an accident — the field is
   required to be *absent*, not merely unset.

5. **Settings hold references, never secret material.** Values are scanned with
   `maistro.security.sentinel.pii_filter` before they are stored; a value
   carrying an API key, an AWS key or a private key block is refused with `400`
   and the rejection names the field, never the value. Secrets belong in the
   SPEC-011 vault, and settings may name a vault key.

6. **Volatile values are a separate, labelled surface.** Preview overrides live
   in an explicitly in-process overlay, exposed under a `volatile` key with a
   `durable: false` marker. They cannot reach the durable record, and the
   durable record is never inferred from them.

**Rollback is refused, not attempted.** A record whose `schema_version` exceeds
the version this build knows is not readable by this build. Startup refuses it
rather than coercing it, because a forward-version envelope's unknown fields
would be silently dropped by the first write — turning a downgrade into data
loss. Older versions migrate forward on read.

## Consequences

### Positive
- A `200` on a settings write means the value is on disk. The failure mode moves
  from "silent loss discovered at restart" to "an error at the moment of writing".
- The Setup wizard's default model, capability toggles and settings edits all
  survive service recreation, which is what #331's volume work is for.
- Removing the assignable module attribute makes the remaining volatility
  *reachable by a type checker* rather than by inspection.

### Negative / Trade-offs
- Every settings write now costs a queue drain and a read. Settings writes are
  rare and operator-driven, so the latency is paid where it is affordable — but
  it is a real cost, and it is paid on the request path.
- Refusing a forward-version record turns a downgrade into a startup failure.
  That is louder than silent field loss and is the intended trade, but it means
  a rollback needs the record restored from backup, not merely an older image.
- The secret scan can refuse a legitimate value that looks like a key. The
  rejection names the field so the operator can move it to the vault; there is
  no override, deliberately.

### Neutral
- The durable record is stored through the same `PersistedStore`/`State` spine
  as every other Conductor store, so #331's data-directory work covers it with
  no additional inventory entry.
- `SettingsModel` itself is unchanged. The envelope wraps it rather than
  extending it, so nothing downstream reads a new field by accident.
