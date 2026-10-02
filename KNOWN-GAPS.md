# Known Gaps

This document is the source for the v1.0.0 release notes' "Known
limitations" section. Each item below is shipped surface area whose current
behavior is intentionally limited or degraded. The entries are v1.1 tracking
inputs, not promises that the capability is complete in v1.

## Deferred To v1.1

### Task queue persistence

Updated by #91 (M3-B1): with a database configured, the queue is now durable
and recoverable. Admission commits a QUEUED canonical Run before the `202`,
lifespan startup rehydrates those Runs through `queue.recover` (announcing
each as `task_recovered`), RUNNING residue with no execution evidence is
failed visibly instead of stranding, terminal receipts the shutdown abandoned
are reconciled from the Run (#849), and a resubmission under the same
idempotency key replays the original admission through the durable claim
store (#1176). The product path across a forced (SIGKILL) restart — recover,
execute exactly once on the same Run, idempotent replay — is pinned by
`packages/maistro-server/tests/test_task_restart_recovery.py`.

What remains limited: the task *receipt* a fresh process serves is still the
living queue's answer (ADR-018 best-effort rows), so terminal state after a
restart is read through the canonical Run (`GET /v1/runs/{run_id}`) and
idempotent resubmission rather than rehydrating every historical receipt
into memory; and without a database the spine is in-process only, so
admitted tasks are still lost on restart (`run_store_in_process_only`).
Wave-level crash recovery (crash-loop quarantine, checkpoint version
gating) remains [ADR-056](docs/adr/ADR-056-task-crash-recovery.md)'s
orchestrator path.

### Canvas background job runner

Canvas jobs can be created, but they do not advance unless an external runner
is configured and operating. The shipped service does not provide a built-in
worker that consumes those jobs.

Tracking: add the runner described by SPEC-203 before treating canvas jobs as
self-progressing work.

### Canvas publish and export

Updated by #94 (M3-B4): the `/v2/canvas` product boundary now implements
publish/export as a governed capability (`design.export`) instead of a 501
stub. With `app.state.canvas_exporter` wired, `POST /designs/{id}/publish` and
`GET /designs/{id}/export/{format}` cross the Capability -> Provider ->
Binding -> Invocation seam, record a governed Invocation, and append an
immutable export version per accepted state (re-export after an edit yields a
new version with its own provenance). Supported formats: `png`, `webp`, `jpg`
(compositor), `html` (plugin-free fixed page), and `pptx` when python-pptx is
installed (absent dependency is a truthful failure, not fake bytes). `pdf` and
`svg` are deliberately unsupported and refused with a machine-readable 422 —
they are out of scope, not "temporarily unavailable". Without a configured
exporter the endpoints still return a truthful 501; the engine never falls
back to an ungoverned direct compositor call. Outbound delivery to external
destinations (print-on-demand, stores, media platforms) remains out of this
repository; #773 coordinates those connectors, which must consume accepted
versions through governed capabilities. The legacy `maistro_canvas` package
routes (mounted at `/api/canvas`) keep their direct encode path as a
declared-transitional compatibility surface per ADR-045 until the #95 cutover
retires them.

Tracking: close this entry fully when the supported paths pass product E2E
under #773 (Design Studio cutover #95 wires the exporter in deployed stacks).

### Conductor degraded modes

The Conductor can continue in a degraded state when optional services are
unavailable. Startup now makes optional-router failures observable, but the
degraded state is not yet a complete user-facing operating mode.

Tracking: finish the visible degraded-mode behavior in F3 (#302).

### Design Studio production availability and Canvas boundary

Design Studio is the parent creative-production surface; Canvas is one
visual/fixed-page/rendering capability it consumes, not the identity of the
Studio. The product information architecture is now cut over (#95): the
canonical deep link is `/design-studio`, the route is a first-class primary
navigation entry, and the implementation-era `/cli/canvas` path survives only
as a compatibility redirect that browser E2E asserts. Backend capability APIs
keep their `/v1/canvas/**` and `/v1/design/**` namespaces; product routing no
longer borrows the Canvas tool's name. The shipped Design Studio currently
supports resource discovery, artifact-mode selection, and prompt entry only.
Visual generation is disabled and server-side artifact publish/export are not
available; durable artifact state is browser-local rather than
server-persisted. The product does
not simulate those unavailable operations.

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

### Trace export is build- and config-gated, and the default stack sends none

The conductor agent path and the Conductor's chat path emit
OpenTelemetry spans, but export is deliberately opt-in at two doors: the
image must be built with `INSTALL_OBSERVABILITY=1` to carry the OTLP
exporter packages ([Dockerfile](packages/hive-conductor/Dockerfile), #668),
and the process must be given `OTEL_EXPORTER_OTLP_ENDPOINT`/`_HEADERS`. The
default compose stack runs a Langfuse service, but no service in it exports
traces there — the `LANGFUSE_*` variables configure the Langfuse service's
own UI/API, not trace export. With no endpoint configured, spans are emitted
to a no-op tracer at negligible cost and nothing leaves the process (#63's
doc audit; see `packages/hive-conductor/backend/adapters/telemetry_langfuse.py`).

Tracking: decide whether a compose profile should wire
`OTEL_EXPORTER_OTLP_ENDPOINT` to the bundled Langfuse/Phoenix services when
the image is built with the observability extra.

### Reliability signals declared without a producer

ADR-038 declares that circuit state changes also emit a `circuit.state_change`
event, and the resilience layer ships `context_probe`, `rate_coordination` and
`retry_policy` primitives. The `maistro_circuit_state` metric is emitted by the
real conductor circuit path, but the event and the three primitives have no
production call path — their intended producer is the Invocation/provider
effect path (#55/#56), which nothing constructs yet (see #63's audit and the
`resilience-unwired` reachability disposition).

Tracking: wire reliability signals when #55 makes the Invocation the real
effect path; do not invent a producer for them sooner.

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
> active tasks. Canvas jobs require an external runner; Canvas publish/export
> is governed at `/v2/canvas` (png/webp/jpg/html/pptx where configured; pdf/svg
> are explicitly unsupported), while print-on-demand and external destinations
> are not implemented. The mounted Canvas data routes are unconfigured in the
> default shipped service and return `503`. Design Studio can discover
> resources and select artifact modes, but visual generation and
> editing/preview still need wired providers. Conductor can run in degraded
> mode when optional services are unavailable, and API-wide HTTP content
> negotiation from ADR-076 is deferred to v1.1.
