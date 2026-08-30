---
id: ADR-083026-1cb1
title: "Correlation is ambient: one execution context, bound at the seams that hold the ids"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-081226-7248
implements: []
related:
  - maistro-engine#SPEC-083026-20b2
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/observability/test_execution_correlation.py
  - packages/maistro-core/tests/runs/test_execution_is_correlated.py
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-1cb1: Correlation is ambient: one execution context, bound at the seams that hold the ids

## Context

ADR-037 names the correlation taxonomy and ADR-081226-7248 gives the event
envelope the fields to carry it. Both were honoured on the *records*:
`EventEnvelope` declares `workspace_id`, `project_id`, `run_id`, `node_run_id`,
`attempt_id`, `invocation_id`, `session_id`, `correlation_id` and
`causation_id`, and the Run/NodeRun/Attempt stores persist their own.

Neither said how code *inside* an execution learns which execution it is in,
and nothing supplied an answer. Before this decision:

- `RequestIDMiddleware` bound one key, `request_id`, into structlog's
  contextvars. Those calls plus `merge_contextvars` were the complete set of
  `structlog.contextvars` usage in the workspace, and `ContextVar` appeared in
  no file under `packages/*/src` at all.
- Work that did not arrive over HTTP — a schedule firing, a task-queue
  dispatch, a recovery sweep — emitted log lines with no correlation of any
  kind. Work that did arrive over HTTP carried a `request_id` that appeared on
  no record, so it joined to nothing.
- `trace_agent`'s one production call site opened a span carrying
  `maistro.output_preview` and no id. A trace existed and could not be joined
  to the execution it traced.
- `RunExecutionService.retry_node` receives only a `node_run_id`, so a retry's
  output named a NodeRun and no Run while the first try named both.
- Every event producer filled the envelope by hand — `correlation_id` at five
  separate call sites, `invocation_id` at exactly one — with nothing checking
  that a producer set the ids it could have.

The shape of the gap matters: the ids were never *unavailable*. They were held
by a caller several frames above the code that needed to name them, and the
only way to pass them down was as arguments through every intervening
signature. That is the arrangement that loses one, because the frame deepest in
the stack is the one least likely to hold the outer ids.

## Decision

Correlation is **ambient**: a `ContextVar`-backed `ExecutionContext` in
`maistro.observability.correlation`, bound by the seams that already hold the
ids and read by anything that needs to name them — logs, spans and events
alike.

Three properties are load-bearing.

**Binding is additive.** `bind_execution_context(node_run_id=…)` inside a
Run-scoped context keeps the Run. Callers bind what they hold and inherit the
rest.

**A blank never erases.** A seam that cannot resolve an id passes nothing, and
passing an id it failed to resolve is no worse than passing none. An unknown
field name, by contrast, raises: a typo'd `noderun_id` accepted silently would
correlate nothing, which is the failure this decision exists to end.

**The scope is the lifetime.** Every binding is a context manager that resets
its own token. An unbound context reads as empty, never as whatever the last
execution on this task left behind.

The seams:

| Seam | Binds | Why there |
|------|-------|-----------|
| `RequestIDMiddleware` | `request_id` | The request is the outermost scope an HTTP-borne execution has |
| `RunExecutionService.execute_node` | `run_id` | Held as an argument; costs no store read |
| `RunExecutionService.retry_node` | `run_id` | Resolved from the NodeRun — the one read correlation costs, and the only way to get the id |
| `AttemptExecutionService.execute` | `node_run_id`, then `attempt_id` | The Attempt id is bound only once the Attempt is `RUNNING` |
| `EventEnvelope` `append` | the blank fields | Producers keep the fields; the store fills what they omitted |

`workspace_id` and `project_id` are deliberately left to whichever seam already
holds them rather than read back from the Run at `execute_node`: putting a query
on every node execution to decorate a log line is a cost correlation should not
impose, and an outer bind supplies them for free where they are known.

`workspace_id` is likewise not among the fields `correlated()` fills on an
envelope. The envelope's own invariant requires `workspace_id` or
`stream_scope` and forbids both, so a blank `workspace_id` is never an
omission — it is a producer that chose an explicit alternate stream, and
overwriting it would move the event to a different stream or raise outright.

**One vocabulary.** Direct use of `structlog.contextvars.bind_contextvars` in
production source is banned and guarded by an AST scan. An id bound there
reaches log lines and neither spans nor events — exactly the split this
decision closes — so a second place to put an id would reintroduce the defect
one file at a time.

## Consequences

### Positive
- A single trace joins request → Run → NodeRun → Attempt across logs, spans and
  events, for non-HTTP entry points as much as HTTP ones.
- A retry and the try before it carry the same Run, so the question a retry
  raises can be answered.
- A producer that forgets an envelope field emits a correlated event anyway;
  forgetting is no longer silent data loss.
- New seams cost one `with` statement, not a parameter threaded through every
  signature between them and the work.

### Negative / Trade-offs
- `retry_node` gains one store read per retry. Accepted: there is no other
  source for the id.
- `AttemptExecutionService.execute` is split into a wrapper owning the scope and
  an inner method receiving the `ExitStack`, because the Attempt id is not known
  until several awaits in. Passing a stack as a parameter is unusual and is
  documented at both ends.
- Ambient state is invisible at the call site. The mitigation is that it is
  *only* descriptive: nothing reads the context to decide behaviour, so a
  missing binding degrades a log line and never changes an outcome.

### Neutral
- `maistro.observability.proxy.TraceContext` is unaffected. It allocates the
  per-trace sequence numbers of the ADR-055 record/replay proxies and is passed
  by hand between two collaborators that must agree; this is ambient identity,
  which is a different thing that happens to share a word.
- The OTLP exporter stack, and attaching provider/model/token/cost metadata to
  the correct Invocation, remain #63's and #56's to settle.
