---
inventory-delta:
  packages/maistro-core/tests: +39
---
# chatgpt-m1-837-durable-resume-wakeup-a722

Durable Graph recovery for timed resume (#837). The continuation stores gained
an indexed due-deadline query (conformance, sqlite index pinning, due-candidate
semantics), the canonical store gained `reconcile_persistence` and `list_due`
(orphan purge, stepwise RUNNING->WAITING repair, bounded scans, due projection),
and `resume_due_graph_runs`/`recover_queued_graph_runs` gained their race and
budget edges (live-Attempt yield, vanished-record races, bootstrap claim
failure, zero-limit no-ops). Later repair pass added the admission-guard
conformance for pinned runs, the timed-pause redispatch predicate, the
cross-backend `delete()` contract (memory/sqlite/PG), and mypy strictness fixes
in `pg_continuation`/`attempt_executor`. All additions are in
`packages/maistro-core/tests/graph/durable_runs/`; no suite shrank.
