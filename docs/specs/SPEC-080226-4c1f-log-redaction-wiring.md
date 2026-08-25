---
id: SPEC-080226-4c1f
title: "Installing secret redaction on the log pipelines — closing ADR-064's integration half"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-08-02
substrate:
  - maistro-engine#ADR-064
implements:
  - maistro-engine#ADR-064
related:
  - maistro-engine#SPEC-223
  - maistro-engine#SPEC-080126-9e42
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_log_redaction.py
  - packages/hive-conductor/backend/tests/test_log_redaction.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-02
  - status: Implemented
    date: 2026-08-02
---

# SPEC-080226-4c1f: Installing secret redaction on the log pipelines

## Context

ADR-064 opens by calling unredacted secrets in log output **"the single highest-impact
security gap in the platform"**, and requires redaction *"applied to all log output, error
messages, and trajectory recordings."*

[SPEC-223](SPEC-223-secret-redaction.md) shipped `maistro/security/redact.py` — a correct,
tested, 30+-pattern redactor with an entropy fallback — and explicitly listed the wiring as a
**Non-goal**, noting the integration points were *"tracked separately per ADR-064."* No such
artifact was ever created. `redact()` therefore had **zero production callers** for its entire
life: every log line the platform ever emitted went out verbatim.

Meanwhile `SECURITY.md` told readers it *"scrubs API keys, JWTs, private-key blocks,
connection strings, etc. from logs/errors/trajectories"*, and `COMPLIANCE.md` cited it as an
operative control under EU AI Act Art. 10, SOC 2 CC1–CC9, and SOC 2 Confidentiality. This is
the same defect class as #344 (inert memory decay), #346 (five unwired controls), and #347
(the skills-scan stub): **a correct module, fully tested, with no call path, behind a document
that says it runs.** It was found by the reachability sweep in #357, not by any test.

## Problem

Grepping for `redact` finds the module, the tests, and the docs — everything except a caller.
Nothing in the running system was protected.

## Goals

- `redact()` runs on every log line both deployed services emit.
- Coverage includes `%`-style arguments and exception tracebacks, not just the format string.
- Whether it is installed is *observable*, not inferred from source.
- `SECURITY.md` and `COMPLIANCE.md` describe what is actually covered — and, equally, what is
  not.

## Non-goals

- Redacting anything outside the log pipelines. HTTP response bodies, `print()`, and direct
  file writes are untouched; the docs now say so rather than implying blanket coverage.
- Trajectory recordings. ADR-064 named them as a third sink, written when the conductor-router
  persisted every intermediate result to disk. That code does not exist in this repo —
  `maistro-evolve`'s "trajectory" is OPRO prompt-optimization history that reaches disk only
  through logging, and is therefore already covered. The claim was narrowed rather than a sink
  invented to satisfy it.
- Changing the pattern catalogue or the entropy threshold. SPEC-223 owns those.
- A runtime on/off toggle. SPEC-223 deliberately shipped none, and adding one here would create
  a supported way to turn a security control off.

## Decision

`maistro/security/log_redaction.py`, installed from both `configure_logging()` functions.

### Handler formatters, not a logger filter

The obvious implementation — a `logging.Filter` on the root logger — is quietly almost
useless. A `Filter` attached to a `Logger` is consulted only for records logged *through that
logger*; records propagating up from child loggers never see it. Since essentially all
application logging goes through child loggers, a root filter would have covered nearly
nothing while looking comprehensive.

Handler-level formatting is the one point every emitted record passes through.
`RedactingFormatter` wraps whatever formatter a handler already has and redacts the rendered
string. Formatting first is what makes `%`-args and exception tracebacks covered — and
tracebacks are where credentials most often surface, since a connection string usually reaches
the log inside an exception's repr rather than a deliberate log call.

`install_log_redaction()` also wraps `uvicorn`, `uvicorn.error`, and `uvicorn.access`: uvicorn
configures those with `propagate = False`, so wrapping root alone would leave request logs and
startup tracebacks — the highest-risk lines — unredacted.

A handler with no explicit formatter still formats, via a default `Formatter()` created inside
`logging.Handler.format`. The wrapper materialises that default, so the least-configured
handler in the app is not the one that leaks.

### structlog gets a processor

`maistro-server` renders through structlog, which bypasses stdlib formatting.
`structlog_redact_processor` redacts every string in the event dict and is placed **last before
the renderer**, so it also sees the traceback string `format_exc_info` has just produced.
Third-party libraries still log through stdlib, so `configure_logging()` installs the handler
wrapping as well — the two mechanisms cover disjoint traffic.

### Degraded loudly, per the F3 precedent

If the wiring cannot be installed, every subsequent log line carries secrets verbatim — the
exact condition `SECURITY.md` says does not occur. A silent `except: pass` would reproduce the
gap this closes. The Conductor warns, and `/health` publishes `log_redaction_active` with
`degraded: true`, matching the treatment `ALLOW_STUB_LLM` and `MEMORY_DECAY_INTERVAL_S` get.

## Acceptance criteria

- [x] A secret in a log message, in a `%`-arg, and inside an exception traceback is redacted on
      the Conductor's stdlib pipeline.
- [x] The same holds for `maistro-server`'s structlog pipeline, including the rendered
      traceback.
- [x] Non-secret text passes through unchanged.
- [x] Installation is idempotent — `configure_logging()` runs more than once per process, and
      double-wrapping would make the handler chain unreadable.
- [x] Installed/not-installed is visible on `/health` and feeds `degraded`.
- [x] `SECURITY.md` and `COMPLIANCE.md` state the log-only scope; the SOC 2 PI1 row that cited
      the (unreachable) builders pipeline is downgraded to 🟡 in the same pass.

## Testing

Every assertion drives a real logging call or the real `configure_logging()`. **No test in
either file calls `redact()` directly** — SPEC-223's tests already do, and that coverage is
exactly what let the gap survive for months. Both suites were sabotage-verified: removing the
install call makes the wiring tests fail and leaves the unit tests passing, which is the
signature of the bug this SPEC fixes.

## References

- ADR-064 — the decision; its integration half
- [SPEC-223](SPEC-223-secret-redaction.md) — ships `redact()`; declared this wiring a Non-goal
- #357 — the reachability sweep that found it
- #344 / #346 / #347 / #350 — the same defect class elsewhere
