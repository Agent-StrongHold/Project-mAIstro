---
inventory-delta:
  packages/maistro-core/tests: +473 -76
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# auto-42 develop merge reconciliation (L42 repair)

Reconciled the in-progress (crashed) merge of develop ba2f1f077 into auto-42.
The branch had implemented #1169/#1170 in parallel with develop's #1320/#1219;
the merge resolution makes develop's upstream-closed implementations canonical
where they supersede this branch's parallel attempt, and keeps this branch's
#1194 replay-effect enforcement (still open upstream) everywhere else.

Resolution policy per file family (details in the merge commit message):

- theirs: runs/service.py, runs/execution.py, runtime/execution.py, graph node
  human_* files, agent_delegate_remote.py, dag_run_inspection.py.
- union: runs/store.py + sqlite/pg stores (effect-claim API kept for
  server api/a2a.py + core tests; delegation receipt/occurrence API kept),
  capabilities invocation/approval stores (revision CAS + effect_scope column,
  migration and logical effect identity), a2a delegate/guest_peers
  (idempotency_key wire field matching the merged server receiver, both
  receipt dedupe identities).
- Post-merge semantic fixes found by tests/mypy: restored effect_scope on the
  Invocation create path (cross-NodeRun replay dedupe), aligned
  PgInvocationStore with the effect_scope contract (DDL, ALTER, INSERT,
  scoped list_effect), added effect_scope to Alembic 035, removed the
  superseded delegation effect-key helpers
  (find_child_run_by_effect, update_run_provenance, DelegationMessages) once
  they had zero remaining callers, and re-threaded the duplicated migration
  revision 034 into a linear chain
  (033 -> 034_canonical_run_effect_claim -> 034 -> 035 -> ...).

Test deltas: adopted develop's test_agent_delegate_remote_review.py (new,
473 lines) and its _child_run.py variant; dropped this branch's two tests that
pinned the superseded effect_key claim mechanism (retry-reuse and concurrent
claim coverage for delegation child Runs is provided by the adopted review
suite's delegation_key tests). The 1169-canonical-cancellation.md note now
carries the union of both sides' deltas.

Executed evidence at the committed head: suites enumerated in
auto-42-verification.md's addendum; the only red gate is the debt ledger,
blocked on a reviewed grant for the live create_a2a_task route.
