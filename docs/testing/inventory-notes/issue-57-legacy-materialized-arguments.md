---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# Issue #57: validate legacy tool arguments against the shared host schemas

Five parametrized regressions execute the production legacy node adapter through
its canonical Binding/Invocation service. Invalid URL/task types, mixed-type
clarification questions, an invalid search limit, and a malformed parent-derived
search query must fail before any raw provider dispatch. The multi-query case
places a valid query first: all materialized inputs must validate before the
first effect, not only immediately before each individual call.

Assertions cover no backend calls, a failed node result, and one failed canonical
Invocation. A sixth test proves that an identically typed error raised by the
backend after valid admission retains UNKNOWN outcome, not EffectNotApplied:
only the pure pre-effect validation stage may establish safe failure.

Schemas come from the existing Hive ToolContractRegistry; no second
authorization route or schema definitions are introduced. This repairs argument
validation only, not the remaining legacy reversibility/effective-envelope gap.

Before/after evidence and commands are recorded in
`.cursor/context/repair-57-f3864421.md` and the assigned job's repair logs.
