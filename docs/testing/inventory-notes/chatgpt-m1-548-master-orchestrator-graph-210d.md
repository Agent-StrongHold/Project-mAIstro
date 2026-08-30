---
inventory-delta:
  packages/maistro-core/tests: +21
---
# chatgpt-m1-548-master-orchestrator-graph-210d

All twenty-one are in `packages/maistro-core/tests/orchestrator/test_master_canonical.py`.
Purely additive; nothing renamed or removed, so the +21 is the whole delta.

One, `test_security_gate_exception_is_projected_as_domain_failure`, covers the
seam this convergence turns on. A security gate that *raises* — rather than
returning a refusal — is an exception escaping into the canonical frontier, and
the question #548 has to answer is what a Graph does with it. The answer this
branch implements is that it stays a **domain** outcome: the WorkItem projects
`FAILED` carrying `"Security gate: gate unavailable"`, rather than the
exception aborting the Run or being retried as a transport fault. That
distinction is the same one #573 settled for retries — physical failure versus
logical failure — applied to the gate.

The other twenty close the diff-coverage gap the rewrite itself left: `master.py`
went from 87% to 100% line and branch coverage. They fall into three groups.

**Constructor and `load_plan` validation** (six tests): the three `ValueError`s
in `__init__` (non-positive wave concurrency, negative retry budget, an
injected `run_store` without matching scope), the three in `load_plan` (blank
task_id, duplicate task_id, the reserved root id), plus the unknown-dependency
`ValueError` `_dependency_edges` raises during `execute()`. None of these had
ever been exercised — a validation branch nobody triggers is a validation
branch nobody can trust.

**The scope-injection path** (three tests): a `run_store` supplied with
`workspace_id`/`project_id` skips the constructor's default-construction
branch entirely — `_project_store` stays `None`, and `_scope_project_id`
returns the caller's id without ever touching a project store. The
`RuntimeError` guard for the reverse case (`_project_id` and `_project_store`
both unset) is unreachable through the public constructor — passing a
`run_store` without a `project_id` is rejected there — so that one test drives
the private method directly, which is the accepted way in this file to prove a
defensive invariant actually holds rather than being untested dead code.

**Projection logic** (eleven tests, mostly direct calls on `_projection_payload`,
`_project_one`, `_project_xp`, `_project_waves`): a security gate that accepts
rather than refuses (proving `_apply_security_gate` returns the handler's own
status, not the gate's); three shapes `_projection_payload` must reject
(non-dict result, absent outcome key, wrong-typed status/message/metadata);
`_project_one` for a NodeRun that never ran (`SKIPPED`), a `COMPLETED` run with
no parseable payload (falls back to `PASSED`), each terminal failure status,
and each in-flight/unstarted status; `_project_xp` skipping a non-integer XP
award; `_project_waves` leaving both timestamps unset when nothing in the wave
ever started; and an empty plan completing with nothing to do, which is what
exercises `_wave_edges`' early return when there are no waves to fan out to.
