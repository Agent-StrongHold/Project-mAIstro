---
date: 2026-06-28
tester: Claude (agent)
area: packages/maistro-core/src/maistro/tasks/status.py — can_transition()
charter: Poke can_transition() with type-violating and unrecognized inputs to see whether the freshly-landed 8x8 state matrix (test_status.py, Phase 1) missed any failure-mode behavior the matrix's well-typed inputs couldn't reach.
---

## Observations

The matrix test (`test_status.py`) parametrizes over `itertools.product(TaskStatus, TaskStatus)` —
every pair is a real, valid `TaskStatus` enum member. That proves the transition table is correct
for well-typed callers, but says nothing about what happens if a caller hands `can_transition`
something that *isn't* a `TaskStatus` member (a plain string from a deserialized request body, a
stale value from an older enum version, etc.). Ran a quick interactive probe:

```python
from maistro.tasks.models import TaskStatus
from maistro.tasks.status import can_transition

can_transition(TaskStatus.QUEUED, "planning")        # -> True
can_transition(TaskStatus.QUEUED, "not-a-real-status") # -> False
can_transition("not-a-real-status", TaskStatus.PLANNING) # -> False
can_transition(TaskStatus.QUEUED, None)               # -> False
can_transition(None, TaskStatus.PLANNING)             # -> False
```

No crash on any of these. `target in TRANSITIONS.get(current, set())` is defensive by
construction: `.get(current, set())` silently treats any `current` not present as a key in
`TRANSITIONS` as having zero valid outgoing transitions, rather than raising `KeyError`. Today
that branch is dead code in practice — every one of `TaskStatus`'s 8 members has a `TRANSITIONS`
entry, confirmed by re-reading `status.py` and `models.py` side by side. But it's dead *by
coincidence of current enum membership*, not by an assertion anywhere that guarantees it stays
that way. A future status added to the enum without a matching `TRANSITIONS` entry would silently
fail closed (no transition ever allowed from/to it) instead of erroring loudly at the point of the
omission — the kind of thing that's easy to miss in review since it's a missing dict entry, not a
visibly wrong one.

Also notable (not a bug): passing a raw string equal to an enum member's value (`"planning"`)
works identically to passing `TaskStatus.PLANNING`, because `TaskStatus` is a `StrEnum`. This is
intentional `StrEnum` design, not a flaw — but it means `can_transition`'s type signature
(`current: TaskStatus, target: TaskStatus`) is not actually enforced at runtime, only by mypy at
call sites. Worth knowing if a future caller is tempted to pass loosely-typed strings on purpose.

## Findings

| # | Kind | Description | Escalated to | Follow-up test |
|---|------|-------------|---------------|----------------|
| 1 | gap | `can_transition`'s defensive `.get(current, set())` fallback for a `current` absent from `TRANSITIONS` had no regression lock — a future refactor to `TRANSITIONS[current]` (raising `KeyError`) or a new enum member without a matching entry could silently change behavior with no test catching it. | none (fixed directly, no BACKLOG item needed) | `packages/maistro-core/tests/tasks/test_status.py::TestUnrecognizedCurrentDefaultsClosed::test_value_not_in_transitions_table_has_no_valid_targets` |
| 2 | nit | `StrEnum` membership means raw strings are runtime-interchangeable with `TaskStatus` members; type safety here is mypy-only, not enforced at the function boundary. | none | none — documented here for awareness, not a defect |
