# auto-42 develop merge reconciliation (L42 repair)

## Inventory: the reconciliation moved no count against the shared ledger

Measured collected node IDs, merge base ba2f1f077 vs HEAD: core tests
10556 → 10562 (+6), server tests 362 → 363 (+1), conductor backend tests
2482 → 2482 (0). The base tree is exactly ledger-green, and every surviving
addition is already recorded by the surviving branch-side notes (guard +1,
effect-scope +1, #1194 contract +4 core +1 server). This round therefore
records no `inventory-delta:` of its own: an earlier draft of this block
claimed +897/+12/+212, but those were 00cdd9ab5→HEAD line-stat pairs that
double-counted develop-side tests the shared ledger already reflects, and the
original `+473 -76` line was unreadable to the gate.

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
