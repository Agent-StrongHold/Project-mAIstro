# Known Gaps

This document is the source for the v1.0.0 release notes' "Known
limitations" section. Each item below is shipped surface area whose current
behavior is intentionally limited or degraded. The entries are v1.1 tracking
inputs, not promises that the capability is complete in v1.

## Deferred To v1.1

### Task queue persistence

The live task queue is in memory. When a database is configured, every
submit and status change now upserts a `TaskRecord` row per
[ADR-018](docs/adr/ADR-018-task-record-persistence.md) (best-effort,
fire-and-forget), so task history survives a restart — but the queue does
not yet *recover* from those rows: queued and active tasks are still
discarded on restart, and no requeue/fail-over policy for interrupted tasks
has been decided.

Tracking: decide and implement the recovery policy (requeue vs. fail
interrupted tasks; relationship to
[ADR-056](docs/adr/ADR-056-task-crash-recovery.md)'s checkpoint-based
design).

### Canvas background job runner

Canvas jobs can be created, but they do not advance unless an external runner
is configured and operating. The shipped service does not provide a built-in
worker that consumes those jobs.

Tracking: add the runner described by SPEC-203 before treating canvas jobs as
self-progressing work.

### Canvas publish and export

The Canvas publish endpoint returns `501` because print-on-demand integration
lives outside this repository. PDF and SVG export also return `501`; PNG
export requires a configured compositor and otherwise returns `501`.

Tracking: implement publish and export integrations as a v1.1 capability.

### Conductor degraded modes

The Conductor can continue in a degraded state when optional services are
unavailable. Startup now makes optional-router failures observable, but the
degraded state is not yet a complete user-facing operating mode.

Tracking: finish the visible degraded-mode behavior in F3 (#302).

### Design Studio production availability and Canvas boundary

Design Studio is the parent creative-production surface; Canvas is one
visual/fixed-page/rendering capability it consumes, not the identity of the
Studio. The shipped Design Studio currently supports resource discovery,
artifact-mode selection, and prompt entry only. Visual generation is disabled,
fixed-page editing and preview are not yet available, Deck editing remains
contained, and publish/export are not available. The product does not simulate
those unavailable operations.

The repository contains and mounts Canvas capability routes, but the default
shipped `maistro-server` does not inject the required Canvas store into that
router. The mounted Canvas data routes therefore return `503` in the shipped
configuration. This is a separate limitation from Design Studio's product
cutover: neither the currently mounted route surface nor the current Studio UI
is yet the complete end-to-end production boundary.

Tracking: complete #95 under the continuing #286 Design Studio product lane,
with #93 supplying the supported built-in worker after the canonical Canvas
execution dependency lands. [SPEC-070226-8239](docs/specs/SPEC-070226-8239-canvas-studio-cutover.md)
remains the Proposed `maistro-server` Canvas capability boundary; its historical
filename and legacy migration notes must not be read as a separate current
product identity.

### HTTP API content negotiation

[ADR-076](docs/adr/ADR-076-http-api-versioning.md) is not implemented across
the business API. Canvas has a narrow `/v2` response-format mechanism, but
the business routes remain mounted under `/v1` and do not provide the ADR's
general content-negotiation scheme.

Tracking: implement ADR-076's API-wide version negotiation in v1.1.

### Recurring schedules created through the API do not survive a restart

Recurrence itself is now correct and durable-capable:
[ADR-082126-f69c](docs/adr/ADR-082126-f69c-recurrence-produces-runs.md)
replaced the two disagreeing cron matchers with one verified POSIX dialect,
gave schedules a timezone with explicit DST rules, added catchup and overlap
policies, and shipped a schedule store with in-memory and SQLite
implementations held to the same tests. A fired schedule produces a canonical
Run.

What is **not** closed: Hive's `/v1/schedules` routes still write
`stores.schedules`, which is in memory. A schedule created through the live
API is therefore still lost on restart, with no error and no indication to
the user who created it. The durable store it needs already exists; the
remaining work is migrating the CRUD path behind the unchanged HTTP contract.

Two smaller follow-ups from the same ADR: the Hive schedule row has no
timezone column, so recurrence there is evaluated in UTC until one is added,
and `maistro_schedule_fires_total` / the `schedule.fire` span are not emitted
yet (Run identity is in the audit trail today).

Tracking: the "not yet" rows in
[ADR-082126-f69c](docs/adr/ADR-082126-f69c-recurrence-produces-runs.md)'s
implementation-status table. ADR-046 and SPEC-080126-3a7c are superseded.

### Security controls specified but not reachable

Three controls have modules, tests, and specs, but no production call path.
`COMPLIANCE.md` and `SECURITY.md` have been corrected to say so rather than
citing the module paths as evidence the controls operate (#346):

- **Signed code registry** (`code_registry/verify.py`) — `CodeRegistry.register()`
  is never called; no code is signature-checked at load.
- **Plan-approval gates** (`tools/approval/gate.py`) — the `ApprovalGate`
  Protocol has no implementations.
- **Elevation grants** — the store is wired into the container (#347), but no
  surface issues grants, so no elevation can be requested or cleared.

Tracking: each needs a wiring design, not just a call site — see #346.

## Release-Notes Text

The following text is intended to be copied verbatim into the release notes.

> v1.0.0 ships with an in-memory task queue, so a restart loses queued and
> active tasks. Canvas jobs require an external runner; Canvas publish and
> some export formats are not implemented. The mounted Canvas data routes are
> unconfigured in the default shipped service and return `503`. Design Studio
> can discover resources and select artifact modes, but visual generation,
> editing/preview, and publish/export are not available. Conductor can run in
> degraded mode when optional services are unavailable, and API-wide HTTP
> content negotiation from ADR-076 is deferred to v1.1.
