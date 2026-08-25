---
id: SPEC-070226-af02
title: "P1 Resilience: depth/compaction/retry enforcement with control-scope steering"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-07-02
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-062
  - maistro-engine#ADR-066
implements:
  - maistro-engine#ADR-066
related:
  - maistro-engine#ADR-071
  - maistro-engine#SPEC-248
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/resilience/test_p1.py
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-af02: P1 Resilience — depth/compaction/retry enforcement with control-scope steering

## Context

ADR-066 specifies P1 (Phase 1) resilience: depth limits on task retries, compaction (merging similar
retry attempts into one cohesive signal), and a control-scope enforcement mechanism to steer
remediation choices (escalate vs. retry vs. fail-fast). ADR-038's reliability taxonomy provides
the classification (Shallow, P1, P2, P3); this SPEC realizes the P1 enforcement.

Primitives already exist (retry/backoff primitives in maistro.resilience); this SPEC wires them into
the graph executor, conduit, and observability pipeline.

## Goals

- Enforce retry depth limits per task (configurable: default 3 retries max).
- Compact similar retry attempts (same error type/code, within time window) into one `CompactedRetry`
  signal rather than spamming the log.
- Control-scope gating: on each retry decision, consult a `ResiliencePolicy` (per-agent, per-layer,
  per-error-type) to decide escalate (to parent/super-planner) vs. retry vs. fail-fast.
- Emit P1 resilience events (retry.attempted, retry.succeeded, retry.exhausted, retry.compacted)
  per ADR-037.

## Non-goals

- P2/P3 resilience (deeper learning loops, jailbreak recovery) — Phase 2+.
- Auto-tuning resilience policy (operator-set, not learned in P1).
- Circuit breaker (ADR-038 Shallow; separate from P1 control).

## Decision (as implemented)

All new policy/compaction code lives in `maistro/resilience/p1.py`, reusing the
ADR-038 primitives (`maistro.resilience.classifier.classify_error`, deterministic
backoff helpers). The executor integration lives in `maistro/graph/executor.py`
as `execute_with_resilience`, which wraps any async operation (e.g. a
`NodeRun.execute` call) rather than replacing `NodeRun`'s internal loop.

### Error codes

`classify_error_code(error: Exception) -> str` maps exceptions to the four P1
codes via the ADR-038 classifier: `RATE_LIMIT → "rate_limit"`,
`TIMEOUT → "timeout"`, `CONTENT_FILTER → "llm_refusal"`, everything else
`"unknown"`.

### Depth enforcement: RetryBudget + execute_with_resilience

```python
# maistro/resilience/p1.py
@dataclass
class RetryBudget:
    max_retries: int = 3            # total failed attempts allowed (no off-by-one)
    compaction_window_ms: int = 5000
    attempts: list[RetryAttempt] = field(default_factory=list)
    # properties: current_attempt, exhausted, remaining; record(error, ...)

# maistro/graph/executor.py
async def execute_with_resilience(
    operation: Callable[[], Awaitable[T]],
    *,
    run_id: str = "", node_id: str = "", role: str = "",
    agent_id: str = "*", layer: str = "*",
    budget: RetryBudget | None = None,
    policy_store: ResiliencePolicyStore | None = None,
    emit: Callable[[GraphEvent], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T: ...
```

The loop: on each failure it records the attempt on the budget, consults the
policy store (every attempt), then either escalates (emit `node.escalated`,
re-raise), retries (emit `node.retry_attempted`, sleep the policy's backoff),
or stops (emit `node.retry_attempted` + `node.retry_exhausted` with the
compacted history, re-raise). A node with `max_retries=3` executes exactly
3 times.

### ResiliencePolicy and control-scope gating

```python
@dataclass(frozen=True)
class ResiliencePolicy:
    agent_id: str = "*"
    layer: str = "*"                 # Layer StrEnum values or free-form string
    error_code: str = "*"
    max_p1_retries: int = 3
    backoff_strategy: Literal["exponential", "linear"] = "exponential"
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0
    escalate_on: frozenset[str] = frozenset()

    def decide(self, attempt: int, error: Exception | str) -> Literal["retry", "escalate", "fail"]: ...
    def backoff_for(self, attempt: int) -> float: ...   # 2s, 4s, 8s… exponential

class ResiliencePolicyStore(Protocol):
    async def get(self, agent_id: str, layer: str, error_code: str) -> ResiliencePolicy: ...
```

`InMemoryResiliencePolicyStore` resolves with wildcard fallback (exact →
`(agent, layer, *)` → `(agent, *, code)` → `(*, layer, code)` → … →
`(*, *, *)` → `DEFAULT_POLICY`). Operator defaults (`default_policies()`):
escalate `llm_refusal` everywhere; tools-layer `rate_limit` retries up to 5.

### Compaction: merge similar retry attempts

```python
@dataclass(frozen=True)
class CompactedRetry:
    error_code: str
    count: int                # always >= 2
    first_timestamp: float
    last_timestamp: float
    common_cause: str         # first attempt's message (heuristic, no LLM in P1)

def compact_attempts(
    attempts: list[RetryAttempt], window_ms: int
) -> list[CompactedRetry | RetryAttempt]: ...
```

Consecutive attempts with the same error code within `window_ms` of the
group's first attempt merge into one `CompactedRetry`; groups of size 1 are
returned as the original `RetryAttempt` (single attempts are never compacted).

### Observability (ADR-037)

```python
# Events emitted:
emit("node.retry_attempted", {
    "node_id": "...",
    "attempt": 2,
    "error_code": "rate_limit",
    "backoff_seconds": 4
})

emit("node.retry_exhausted", {
    "node_id": "...",
    "total_attempts": 3,
    "compacted": CompactedRetry(...)
})

emit("node.escalated", {
    "node_id": "...",
    "reason": "llm_refusal",
    "escalate_to": "orchestrator"  # or parent node
})
```

Events are tagged with `source: "resilience.p1"` for filtering.

### Integration points

- **Graph executor** (`maistro/graph/executor.py`): `execute_with_resilience(operation, ...)`
  wraps any node-level async operation with `RetryBudget` + policy gating; events are delivered
  through an injected `emit` callable (compatible with the executor's existing
  `GraphEvent` callbacks). `NodeRun`'s existing ADR-038 retry loop is untouched.
- **Conduit / Container**: deliberately NOT wired in this batch (see deviations); callers
  construct an `InMemoryResiliencePolicyStore` (or their own store) and pass it in.
- **Observability**: no direct dependency; events flow through the injected emit callable
  and carry `detail.source = "resilience.p1"`.

### Deviations from the original sketch

- `compact_attempts` returns a **list** of `CompactedRetry | RetryAttempt` (grouped runs),
  not a single optional `CompactedRetry` — this is what "singles are never compacted"
  requires.
- `ResiliencePolicy.decide` accepts `Exception | str` (a pre-classified code avoids
  re-classifying on the hot path); `layer` is a plain string (values from the `Layer`
  StrEnum) rather than a hard enum, to keep policies open to product-defined layers.
- `node.retry_attempted` is emitted for **every** failed attempt (including the final one),
  so 3 failed attempts produce 3 `retry_attempted` + 1 `retry_exhausted` = 4 events while
  still executing exactly `max_retries` times. There is no separate `node.retry_failed`
  event; a policy `"fail"` decision emits `node.retry_exhausted` with
  `reason="policy_fail"`.
- `common_cause` is the first attempt's error message (heuristic); no LLM summarization
  in P1. No `retry.succeeded`/`retry.compacted` events — success is already covered by
  the executor's `node_completed`, and compaction data rides on `node.retry_exhausted`.
- Container/conduit wiring and the formal/ Hypothesis property + load tests are follow-up
  work (container.py/conduit.py were out of scope for this batch).

## Acceptance criteria

- [x] A `NodeRun` with `max_retries=3` fails after exactly 3 failed attempts (property: no
      off-by-one on retry count).
- [x] Two retries of the same error code within the compaction window (5s default) are merged into
      one `CompactedRetry` with `count=2`; retries after the window are separate.
- [x] `ResiliencePolicyStore.get(agent, layer, error_code)` returns a policy; unknown combinations
      fall back to a default policy (exponential backoff, no escalation).
- [x] On a rate-limit error with a retry policy that allows retries, the node pauses with
      exponential backoff (2s, 4s, 8s) and retries automatically.
- [x] On an LLM refusal error with an escalate policy, the node emits `node.escalated` and
      propagates the exception to the parent/orchestrator (not retried locally).
- [x] Every retry attempt emits a `node.retry_attempted` event; exhaustion emits
      `node.retry_exhausted` (property: exactly 4 events total for 3 retries + 1 exhaustion).
- [x] A compacted retry has `count >= 2`; single attempts are never compacted.
- [x] Control-scope policy is consulted for every retry decision (not just first/last attempt).

## Testing

- Unit: `RetryBudget` enforcement (no retries after max), `compact_attempts` (same code within
  window, different codes separate).
- Unit: `ResiliencePolicy.decide()` per error code (escalate, retry, fail branches).
- Integration: a graph node that throws rate-limit errors up to 5 times, retries automatically
  per policy, and succeeds on the 4th attempt.
- Integration: a graph node that throws llm_refusal, policy escalates, parent catches the
  escalation and routes to a different sub-agent.
- Property (formal/): "retry count never exceeds max_retries regardless of error type" (use
  Hypothesis to generate error sequences).
- Load test: 100 concurrent nodes with mixed retry policies; verify no thread-safety issues.

## Open questions

- Should P1 retry decisions be logged (machine-readable audit) or just emitted as events? (Leaning:
  events only, audit trail is in the event log per ADR-037.)
- Default compaction window (5s) — tunable per-agent or global? (Global for Phase 1, per-agent
  policy in Phase 2.)
- Should escalation to a parent/orchestrator automatically trigger re-routing to a different
  sub-agent, or does the parent decide that? (Parent decides; escalation just signals the issue.)

## References

- [ADR-066: P1 Resilience and Control](../adr/ADR-066-p1-resilience-and-control.md)
- [ADR-038: Reliability Taxonomy](../adr/ADR-038-reliability-taxonomy.md)
- [ADR-062: Graph Execution Protocol](../adr/ADR-062-graph-execution-protocol.md)
- [ADR-037: Observability](../adr/ADR-037-observability-taxonomy.md)
