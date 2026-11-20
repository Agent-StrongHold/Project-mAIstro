---
inventory-delta:
  packages/maistro-core/tests: +12
  packages/hive-conductor/backend/tests: +2
---
# Issue #57: shared Agent schema admission

New `test_tool_schema_boundary.py` exercises `Agent.handle()` with a custom
strategy, not ReAct's separate early validation. Five missing/non-object host
schema cases require refusal before Sentinel/backend dispatch and scoped audit
records. Unknown registered names must not get fabricated open schemas; rewriting
model exposures cannot forge or widen the host schema snapshot. Two invalid
Sentinel repair cases require validation of the actual materialized arguments,
including an empty repair. Three positive controls cover valid original/repaired
arguments and an explicit no-argument schema.

Two Hive tests prove the exposure adapter projects the existing canonical
contract schemas without mutable aliases and drive the composed boot Agent's
`handle()`/ReAct path into a completed, correlated tool Invocation. Only the
model/network are hermetic fixtures; authorization and persistence are real.

Existing positive Agent fixtures must register their synthetic lookup tools
explicitly. The generic-schema test is renamed to assert unknown exposure
refusal (one identity replacement, no net count change). Red/green evidence and
residual issue acceptance blockers are recorded in
`.cursor/context/repair-57-3a6a7088.md`. Salvage validation was independently
repeated in `.cursor/context/repair-57-18abbc04.md`: starting-HEAD Agent code
fails nine new cases; the repaired focused core/Hive suites pass 956/107 cases,
and the inventory gate confirms the +14 total delta.
