---
inventory-delta:
  packages/maistro-core/tests: +3
---

# auto-1114 attempt-evidence repair

Three net new collected nodes in `tests/tasks/test_admission.py`, closing the
verifier finding from the #1114 repair pass at head `54defd05ad`:
`TaskQueue._terminalize_stranded_claims` skipped terminalization whenever any
NodeRun existed, without checking for an Attempt, so a task Run left RUNNING
with one NodeRun and zero Attempts survived `recover()` as an immortal RUNNING
Run — the residue of a worker that died between `create_node_run` and its
first `create_attempt` (the non-claiming dispatch window, or a legacy worker
during a rolling upgrade).

The repair makes the scan's evidence test the Attempt, not the NodeRun: an
Attempt — active or terminal — is physical evidence (the lease sweep #232 owns
the active ones, the reconciler the terminal ones), while a NodeRun with no
Attempt under it is an execution record that is incomplete rather than absent,
and is now failed visibly like the no-NodeRun case.

- `test_recovery_terminalizes_a_running_claim_whose_node_run_has_no_attempt` —
  the finding's exact reproduction: RUNNING + NodeRun + zero Attempts becomes
  FAILED with the "stranded dispatch" evidence, the incomplete NodeRun is kept
  as canonical history, and the disposition is idempotent across a second
  restart.
- `test_recovery_leaves_attempt_evidence_to_its_owner_even_when_terminal` — the
  boundary in the other direction: a terminal Attempt is evidence the
  reconciler re-derives from, so the scan must not fail the Run out from under
  it.
- `test_postgres_lone_node_run_is_not_stranded_claim_evidence` — the durable
  store proves the same disposition on PostgreSQL
  (`MAISTRO_TEST_PG_DSN`), mirroring the existing no-NodeRunner PG case.
