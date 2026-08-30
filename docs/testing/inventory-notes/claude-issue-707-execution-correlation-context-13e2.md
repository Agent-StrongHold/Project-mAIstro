---
inventory-delta:
  packages/maistro-core/tests: +53
---
# claude-issue-707-execution-correlation-context-13e2

All 52 are new; nothing was removed, renamed or merged, so the delta is the
addition.

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
