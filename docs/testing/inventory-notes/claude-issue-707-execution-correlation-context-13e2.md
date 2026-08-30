---
inventory-delta:
  packages/maistro-core/tests: +68
---
# claude-issue-707-execution-correlation-context-13e2

All 68 are new; nothing was removed, renamed or merged, so the delta is the
addition. The last 15 answer a Codex review — see the final section.

**`tests/observability/test_execution_correlation.py` (+42, new).** The three
load-bearing properties of the context get eleven cases between them — additive
binding, blanks that never erase, and a scope that is the lifetime, including
two `asyncio` cases pinning that a task started before a binding never acquires
it and that a child task's binding does not escape to its parent. Five more
cover the structlog processor and the JSON line a reader actually sees; three
cover span attributes; ten cover the envelope fill and the two `append`
implementations that apply it. The last five are the AST guard against a second
correlation vocabulary, and two of those five test the guard rather than the
code: one that a non-call reference is not flagged, one that its corpus is not
empty. A guard whose corpus is empty guards nothing, and #700's `_outcomes`
guard was wrong twice before it was right.

**`tests/runs/test_execution_is_correlated.py` (+7, new).** The acceptance
cases: what an executor driven through the real `RunExecutionService` can say
about which execution it is in. The retry case is the one that could not have
passed before — a retry named its NodeRun and no Run — and the
attempt-id-before-the-Attempt case pins the ordering choice that binding
happens only once the Attempt is `RUNNING`.

**`tests/observability/test_middleware.py` (+3).** The existing two cases assert
the header round trip and say nothing about what a handler can read. The three
added ones cover the handler reading the request from the canonical context, the
context not outliving the request, and — the reason `clear_contextvars()` was
removed — a binding made outside the request surviving it.

**Answering the review (+15).** Four findings, all verified real against the
code, and each fix carries the case that fails without it.

`test_execution_correlation.py` gains 10: three for `detached_execution_context`
— the counterpart `bind_execution_context` cannot express, since it is additive
by design and can only ever add an id; three for `correlation_id` following the
event's *effective* run rather than the ambient one, so an event a producer
stamped with run B stops correlating to run A; three for the stdlib formatter,
including that wrapping twice does not double the suffix, because
`configure_logging` can be called more than once in a process.

`test_logging.py` gains 1, and it is the one that matters most: a mutation
removing `install_log_correlation()` from `configure_logging` survived every
other test here. The formatter worked and nothing proved it was installed —
the "wired but never read" shape #236 exists to catch.

`test_outbox.py` gains 2. The outbox splits producing an event from appending
it, so correlating only at append meant correlating in the publisher's context.
One case pins that the producer's ids are captured at staging; the other that a
publisher's own execution does not leak onto an event staged without one.

`test_durable_run_is_correlated.py` (+3, new) covers the P1. The durable graph
constructs `AttemptExecutionService` directly and never passes through
`RunExecutionService`, so it had to bind its own Run. The nested case is the one
that was actively wrong rather than merely missing: binding is additive, so a
child durable graph inherited the surrounding Attempt's `run_id` and attributed
its own nodes to the parent Run.
