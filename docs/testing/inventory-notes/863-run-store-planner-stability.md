---
inventory-delta:
  tests/: +28
---

# 863-run-store-planner-stability

Issue #863 — make Run-store retention and queue indexes planner-stable at
scale. The +28 are two new files under `tests/migrations/`; the change to
`test_capability_invocation_effect_index_migration.py` moves the chain-tip
sentinel from `051` to `053` without moving any count.

## `test_status_domain_lockstep.py` (8, no server)

The status columns of `canonical_runs`, `canonical_node_runs`,
`canonical_attempts` and `graph_continuations` were unconstrained `text`, and
every correctness-critical scan of them rides a partial index whose predicate
names constant statuses (012 live, 013 retention, 017 archive). An
unconstrained column plus constant predicates means a status added to the
model — a terminal one especially — silently escapes the sweeps: no error, no
log line, just a table that grows while every sweeper reports an empty
backlog. Migration 053 CHECK-constrains each column to its model enum so the
failure is loud at write time; these tests hold the pairing shut statically:

- 053's domain lists equal `RunStatus`/`AttemptStatus` in *declaration* order,
  and the CHECK DDL strings spell exactly those values (a reordered or
  half-copied domain fails).
- The three partial-index predicates name exactly the model's
  `TERMINAL_RUN_STATUSES` — the set a new terminal status would otherwise
  fall out of.
- The store's `_TERMINAL_RUN_STATUS_VALUES` still derives from the model, so
  the interpolated literals in the sweep SQL cannot drift from the indexes.
- Every `sa.Column("status", sa.Text)` in the chain belongs either to the four
  constrained spine tables or to the enumerated non-spine set (memory,
  durable events, handler invocations, capability invocations) — a new
  status-bearing table must be declared here, with an owner and a domain,
  rather than silently joining the class of columns this issue is about.

Repair note (this branch): 053's constraint adds ride a guarded
`_add_check_constraint_if_absent` helper so re-applying the revision over its
own schema is adoption, not `DuplicateObject` — the lockstep greps were
updated to that spelling with the enforced property unchanged, and test
counts are unmoved (`test_migration_chain.py`'s re-application test now
covers the guarded revision).

CI-repair note: that helper originally spelled the guarded ``ADD`` as an
f-string, which the run-id reference-inventory scan refuses — a DDL-shaped
f-string whose interpolations (the helper's parameters) it cannot resolve
statically must be rejected, not assumed run-id-free
(`test_retention_reference_inventory.py::test_every_run_id_table_is_in_the_purge_inventory`
and `::test_scan_sees_the_known_reference_shapes` failed on exactly that
refusal in the coverage/test jobs at 9e5ed653). The DDL is now one
module-level format-template constant: the scan reads its literal skeleton
as SQL text as it does every constant in the chain, the placeholders are
filled only from this module's own constants, and the enforced properties —
adoption-safe guarded add, lockstep-grepped call shape, exact CHECK domain
strings — are unchanged. No test added, removed or renamed; the recorded
suite inventory is untouched.

## `test_run_store_planner_stability.py` (20: 5 static + 15 live)

The planner half. Postgres switches long-lived prepared statements (sweepers,
tickers) to *generic* plans, and a partial index's predicate can only be
proven from a clause naming the same constants — so `status = ANY($2::text[])`
degraded the retention/archive sweeps to a sequential scan of every Run kept,
and the queue cursor's unindexed `ORDER BY payload->>'created_at'` made
fairness O(every Run) per tick under any plan mode.

The static five pin the shipped SQL shapes as importable objects: literal
terminal statuses and no `ANY($` in the three sweeps; caller input still
parameterized; the status listing's order matching 053's index expression; the
continuation listing's two literal statement shapes (an `OR ... IS NULL` arm
can never become an index condition); and 053 declaring no partial index at
all.

The live fifteen apply the whole chain to an empty scratch database, seed a
representative distribution (40k Runs across all nine statuses with due/
far-future/nil retention deadlines, 3k continuations, both anti-join arms
populated), and `EXPLAIN` the *imported* queries under
`plan_cache_mode = force_generic_plan` and `force_custom_plan`. Shapes are
asserted, never costs: the sweeps hit `ix_canonical_runs_retention` /
`ix_canonical_runs_archive_candidates` with `canonical_runs` never
seq-scanned; the queue and continuation cursors hit their
`(status, created_at, run_id)` indexes with no `Sort` node — under both modes.
The negative control re-runs the pre-fix parameterized shape and asserts it
*cannot* use the retention index generically, which is the regression this
issue closed kept assertable. Two domain tests write an out-of-domain status
to each spine table (refused) and every model status (accepted), and the
catalog test asserts the replaced `ix_graph_continuations_status` is actually
gone — the write-cost side of the acceptance: one index on the table, not two.
